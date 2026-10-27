"""Inkhue's print panel: live sheet preview on the left, settings on the right (destination, copies,
layout, color, paper, pages per sheet, margins, scale, two-sided, headers and footers, the driver's
own options). Jobs go straight to the print system (see printing.py), or into a PDF."""
import sys

from PySide6.QtCore import QDateTime, QSizeF, Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor, QPageSize, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .._version import __version__
from . import media, printing, sheet
from .jobs import Job

QSS = """
QDialog { background: white; }
QScrollArea, QScrollArea > QWidget > QWidget#body { background: white; border: none; }
#preview { background: #e8e9ec; }
#side { background: white; border-left: 1px solid #dcdcdf; }
QLabel { color: #202124; font-size: 14px; }
QLabel#title { font-size: 22px; font-weight: 500; }
QLabel#sheets { font-size: 14px; color: #3c4043; }
QLabel#hint { font-size: 12px; color: #5f6368; }
QLabel#warn { font-size: 12px; color: #b3261e; }
QLabel#section { font-size: 12px; font-weight: 700; color: #5f6368; letter-spacing: 0.6px; }
QComboBox, QSpinBox { min-height: 34px; padding: 0 10px; border: 1px solid #dadce0; border-radius: 8px;
                      background: white; color: #202124; font-size: 14px; }
QComboBox:disabled, QSpinBox:disabled { color: #9aa0a6; background: #f6f6f7; }
QCheckBox { color: #202124; font-size: 14px; spacing: 10px; }
QPushButton { min-height: 36px; padding: 0 22px; border-radius: 18px; font-size: 14px; font-weight: 600; }
QPushButton#cancel { color: #ee6b33; background: white; border: 1px solid #f2c1aa; }
QPushButton#go { color: white; background: #ee6b33; border: none; }
QPushButton#go:disabled { background: #f3b597; }
QPushButton#more { text-align: left; border: none; border-radius: 0; background: #f4f4f6; padding: 0 2px;
                   font-weight: 500; color: #202124; min-height: 52px; }
QPushButton#link { text-align: left; border: none; background: transparent; color: #202124; font-weight: 400;
                   padding: 0; min-height: 30px; }
QPushButton#link:hover { color: #ee6b33; }
"""

NICE = {"InputSlot": "Paper source", "MediaType": "Paper type", "cupsPrintQuality": "Quality",
        "OutputMode": "Quality", "Resolution": "Resolution"}
PREFER = {"cupsPrintQuality": ["High", "Best", "Normal"], "OutputMode": ["Best", "High", "Normal"],
          "Resolution": ["600dpi", "600x600dpi", "600"], "MediaType": ["stationery", "Plain", "plain"]}
THUMB_DPI = 150
LABEL_W = 130


def _grid():
    g = QGridLayout()
    g.setContentsMargins(28, 6, 28, 6)
    g.setHorizontalSpacing(16)
    g.setVerticalSpacing(16)
    g.setColumnMinimumWidth(0, LABEL_W)
    g.setColumnStretch(1, 1)
    return g


def _row(g, label, widget):
    r = g.rowCount()
    lab = QLabel(label)
    lab.setFixedWidth(LABEL_W)  # every section lines up on the same column
    g.addWidget(lab, r, 0, Qt.AlignLeft | Qt.AlignVCenter)
    if isinstance(widget, QComboBox):
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    g.addWidget(widget, r, 1)
    return widget


class Preview(QWidget):
    """The sheet as it will come out of the printer."""

    def __init__(self):
        super().__init__(objectName="preview")
        self.setAttribute(Qt.WA_StyledBackground)
        self.image, self.error = None, ""
        self.setMinimumSize(460, 560)

    def show_sheet(self, image, error=""):
        self.image, self.error = image, error
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.image is not None:
            s = self.image.size().scaled(self.width() - 60, self.height() - 60, Qt.KeepAspectRatio)
            x, y = (self.width() - s.width()) // 2, (self.height() - s.height()) // 2
            for d, a in ((6, 18), (3, 28)):  # soft paper shadow
                p.fillRect(x - d // 2, y + d // 2, s.width() + d, s.height() + d // 2, QColor(0, 0, 0, a))
            p.drawImage(x, y, self.image.scaled(s, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if self.error:
            p.setPen(QColor("#b3261e"))
            p.drawText(self.rect().adjusted(40, 0, -40, 0), Qt.AlignCenter | Qt.TextWordWrap, self.error)


class PrintPanel(QDialog):
    def __init__(self, parent, page, dpi, on_sent, title="Inkhue page", paper=None):
        super().__init__(parent)
        self.page, self.dpi, self.on_sent = page, dpi, on_sent
        self.wanted_paper = paper  # the paper the page was sized for, preselected when the printer has it
        self.backend = printing.backend()
        self.caps = printing.pdf_capabilities()
        self.driver, self.problem = {}, None
        date = QDateTime.currentDateTime().toString("M/d/yy, h:mm AP")
        self.header = sheet.header_lines(title, __version__, date)
        self.page_in = QSizeF(page.shape[1] / dpi, page.shape[0] / dpi)
        self.thumb = media.gray_to_qimage(page).scaled(
            round(self.page_in.width() * THUMB_DPI), round(self.page_in.height() * THUMB_DPI),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setWindowTitle("Print")
        self.setStyleSheet(QSS)
        self.resize(1080, 760)
        self._refresh = QTimer(self, singleShot=True, interval=40)
        self._refresh.timeout.connect(self.update_preview)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.preview = Preview()
        row.addWidget(self.preview, 1)
        side = QFrame(objectName="side")
        side.setFixedWidth(430)
        row.addWidget(side)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(28, 22, 28, 12)
        head.addWidget(QLabel("Print", objectName="title"))
        head.addStretch(1)
        self.sheets = QLabel(objectName="sheets")
        head.addWidget(self.sheets)
        sv.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="body")
        self.form = QVBoxLayout(body)
        self.form.setContentsMargins(0, 0, 0, 16)
        self.form.setSpacing(0)
        scroll.setWidget(body)
        sv.addWidget(scroll, 1)
        self._build_controls()

        foot = QVBoxLayout()
        foot.setContentsMargins(28, 10, 28, 20)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        foot.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel", objectName="cancel")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton("Print", objectName="go")
        self.go.setDefault(True)
        self.go.clicked.connect(self.submit)
        btns.addWidget(cancel)
        btns.addWidget(self.go)
        foot.addLayout(btns)
        sv.addLayout(foot)

        self.destination_changed()

    # ---- controls ------------------------------------------------------------

    def _combo(self, items, live=True):
        c = QComboBox()
        c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)  # never wider than the column
        c.setMinimumContentsLength(8)
        for value, label in items:
            c.addItem(label, value)
        if live:
            c.currentIndexChanged.connect(self._refresh.start)
        return c

    def _build_controls(self):
        g = _grid()
        self.form.addLayout(g)
        self.dest = QComboBox()
        self.dest.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.dest.setMinimumContentsLength(8)
        for pid, label in self.backend.printers():
            self.dest.addItem(label, pid)
        if self.dest.count():
            self.dest.insertSeparator(self.dest.count())
        self.dest.addItem("Save as PDF", printing.PDF)
        default = self.backend.default()
        i = self.dest.findData(default) if default else -1
        self.dest.setCurrentIndex(i if i >= 0 else self.dest.findData(printing.PDF))
        self.dest.currentIndexChanged.connect(self.destination_changed)
        _row(g, "Destination", self.dest)
        self.copies = _row(g, "Copies", QSpinBox(minimum=1, maximum=999, value=1))
        self.copies.setMaximumWidth(110)
        self.copies.valueChanged.connect(self._refresh.start)
        self.layout_ = _row(g, "Layout", self._combo([("auto", "Auto"), ("portrait", "Portrait"),
                                                      ("landscape", "Landscape")]))
        self.color = _row(g, "Color", self._combo([(False, "Black and white"), (True, "Color")]))

        self.more = QPushButton(objectName="more")
        self.more.setCheckable(True)
        self.more.toggled.connect(self._toggle_more)
        self.form.addSpacing(8)
        self.form.addWidget(self.more)
        self.more_box = QWidget()
        mv = QVBoxLayout(self.more_box)
        mv.setContentsMargins(0, 8, 0, 0)
        self.form.addWidget(self.more_box)

        g = _grid()
        mv.addLayout(g)
        self.paper = _row(g, "Paper size", self._combo([]))
        self.per_sheet = _row(g, "Pages per sheet", self._combo([(1, "1"), (2, "2"), (4, "4")]))
        self.margins = _row(g, "Margins", self._combo([("default", "Default"), ("minimum", "Minimum"),
                                                       ("none", "None")]))
        scale_box = QWidget()
        sb = QHBoxLayout(scale_box)
        sb.setContentsMargins(0, 0, 0, 0)
        self.scale = self._combo([("actual", "Actual size (100%)"), ("fit", "Fit to page"), ("custom", "Custom")])
        self.custom = QSpinBox(minimum=10, maximum=400, value=100, suffix=" %")
        self.custom.setMaximumWidth(100)
        self.custom.valueChanged.connect(self._refresh.start)
        sb.addWidget(self.scale, 1)
        sb.addWidget(self.custom)
        _row(g, "Scale", scale_box)
        self.scale_warn = QLabel(objectName="warn")
        self.scale_warn.setWordWrap(True)
        g.addWidget(self.scale_warn, g.rowCount(), 1)
        self.duplex = _row(g, "Two-sided", QCheckBox("Print on both sides"))
        self.duplex.toggled.connect(self._refresh.start)
        self.headers = _row(g, "Options", QCheckBox("Headers and footers"))
        self.headers.setChecked(True)
        self.headers.toggled.connect(self._refresh.start)

        sec = QLabel("PRINTER OPTIONS", objectName="section")
        sec.setContentsMargins(28, 18, 28, 0)
        mv.addWidget(sec)
        self.driver_host = QVBoxLayout()
        mv.addLayout(self.driver_host)

        self.form.addSpacing(10)
        links = QVBoxLayout()
        links.setContentsMargins(28, 4, 28, 4)
        viewer = "Preview" if sys.platform == "darwin" else "your PDF viewer"
        for text, fn in (("Print using system dialog…   ↗", self.system_dialog),
                         (f"Open PDF in {viewer}   ↗", self.open_pdf)):
            b = QPushButton(text, objectName="link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            links.addWidget(b)
        self.form.addLayout(links)
        self.form.addStretch(1)
        self._toggle_more(False)

    def _toggle_more(self, on):
        self.more_box.setVisible(on)
        self.more.setText(f"    More settings   {'▴' if on else '▾'}")

    # ---- state ---------------------------------------------------------------

    def settings(self):
        return sheet.SheetSettings(
            paper=self.paper.currentData() or self.caps.paper_default,
            layout=self.layout_.currentData(), margins=self.margins.currentData(), scale=self.scale.currentData(),
            custom_scale=self.custom.value(), per_sheet=self.per_sheet.currentData(),
            headers=self.headers.isChecked(), color=bool(self.color.currentData()) and self.color.isEnabled(),
            duplex=self.duplex.isChecked() and self.duplex.isEnabled(), copies=self.copies.value())

    @staticmethod
    def page_size(s):
        return printing.page_size_for(s.paper) or QPageSize(QPageSize.Letter)

    def destination_changed(self):
        pid = self.dest.currentData()
        self.go.setText("Save" if pid == printing.PDF else "Print")
        if pid == printing.PDF:
            self.apply_caps(printing.pdf_capabilities(), None)
            return
        self.go.setEnabled(False)
        self.status.setText("Reading printer options…")
        job = Job(self.backend.options, pid, quiet=True)
        job.sig.done.connect(lambda opts, pid=pid: self._got_options(pid, opts, None))
        job.sig.failed.connect(lambda msg, pid=pid: self._got_options(pid, self.backend.fallback_options(), msg))
        QThreadPool.globalInstance().start(job)

    def _got_options(self, pid, opts, problem):
        if pid != self.dest.currentData():
            return  # the user already picked another destination
        if not opts:
            opts, problem = self.backend.fallback_options(), problem or "The driver reported no options."
        self.apply_caps(printing.describe(opts), problem)

    def apply_caps(self, caps, problem):
        self.caps, self.problem = caps, problem
        keep = self.paper.currentData() or self.wanted_paper
        self.paper.blockSignals(True)
        self.paper.clear()
        for value, label in caps.papers:
            self.paper.addItem(label, value)
        i = self.paper.findData(keep) if keep else -1
        self.paper.setCurrentIndex(i if i >= 0 else max(0, self.paper.findData(caps.paper_default)))
        self.paper.blockSignals(False)
        is_pdf = self.dest.currentData() == printing.PDF
        self.color.setEnabled(is_pdf or caps.color is not None)
        self.duplex.setEnabled(caps.duplex is not None)
        if caps.duplex is None:
            self.duplex.setChecked(False)
        while self.driver_host.count():  # the driver's own options
            w = self.driver_host.takeAt(0).widget()
            if w:
                w.deleteLater()
        box = QWidget()
        g = _grid()
        box.setLayout(g)
        self.driver = {}
        for o in caps.driver:
            c = self._combo(o.choices, live=False)
            pick = next((p for p in PREFER.get(o.key, []) if c.findData(p) >= 0), o.default)
            c.setCurrentIndex(max(0, c.findData(pick)))
            _row(g, NICE.get(o.key, o.label), c)
            self.driver[o.key] = c
        if not caps.driver:
            _row(g, "", QLabel("None" if not is_pdf else "Not used when saving a PDF"))
        self.driver_host.addWidget(box)
        self.go.setEnabled(True)
        self.update_preview()

    def update_preview(self):
        s = self.settings()
        self.custom.setVisible(s.scale == "custom")
        self.sheets.setText(f"{s.copies} sheet{'s' if s.copies != 1 else ''} of paper")
        pl = None
        try:
            img, pl = sheet.preview(self.thumb, THUMB_DPI, self.page_in, self.page_size(s), s, res=110,
                                    header=self.header)
            self.preview.show_sheet(img)
        except ValueError as ex:
            self.preview.show_sheet(None, str(ex).capitalize())
        warn = ""
        if pl is not None and abs(pl.scale - 1) > 1e-6:
            warn = (f"⚠ Printing at {pl.scale:.0%} resamples the printer dots — the color will probably not "
                    "decode. Use Actual size for pages you want to scan back.")
        self.scale_warn.setText(warn)
        self.scale_warn.setVisible(bool(warn))
        tip = "Actual size on plain paper, ideally with a laser printer, decodes best."
        self.status.setText(f"⚠ {self.problem} Basic options shown.  {tip}" if self.problem else tip)
        self.go.setEnabled(pl is not None)

    # ---- output --------------------------------------------------------------

    def driver_values(self, s):
        values = {k: c.currentData() for k, c in self.driver.items()}
        if self.caps.color:
            values[self.caps.color["key"]] = self.caps.color[s.color]
        if self.caps.duplex:
            values[self.caps.duplex["key"]] = self.caps.duplex[s.duplex]
        return values

    def submit(self):
        s = self.settings()
        pid = self.dest.currentData()
        if pid == printing.PDF:
            path, _ = QFileDialog.getSaveFileName(self, "Save as PDF", "Inkhue page.pdf", "PDF (*.pdf)")
            if not path:
                return
            try:
                sheet.write_pdf(path, media.mono(self.page), self.dpi, self.page_size(s), s, self.header)
            except Exception as ex:
                self.status.setText(f"⚠ {ex}")
                return
            self.accept()
            self.on_sent("PDF", path.replace("\\", "/").rsplit("/", 1)[-1])
            return
        self.go.setEnabled(False)
        self.status.setText("Sending to printer…")
        args = (pid, self.page, self.dpi, s, self.driver_values(s), self.header)
        name = self.dest.currentText()
        if self.backend.name == "Qt":  # QPrinter painting belongs on the UI thread
            try:
                jid = self.backend.submit(*args)
            except Exception as ex:
                self.status.setText(f"⚠ {ex}")
                self.go.setEnabled(True)
                return
            self.accept()
            self.on_sent(name, jid)
            return
        job = Job(self.backend.submit, *args, quiet=True)
        job.sig.done.connect(lambda jid: (self.accept(), self.on_sent(name, jid)))
        job.sig.failed.connect(lambda msg: (self.status.setText(f"⚠ {msg}"), self.go.setEnabled(True)))
        QThreadPool.globalInstance().start(job)

    def system_dialog(self):
        try:
            if printing.system_dialog(self, self.page, self.dpi, self.settings(), self.header):
                self.accept()
                self.on_sent("system dialog", "sent")
        except Exception as ex:
            self.status.setText(f"⚠ {ex}")

    def open_pdf(self):
        try:
            printing.open_pdf(self.page, self.dpi, self.settings(), self.header)
        except Exception as ex:
            self.status.setText(f"⚠ {ex}")
