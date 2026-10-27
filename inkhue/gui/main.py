"""Inkhue desktop app: a printer you feed color photos into and get hidden-color pages out of,
and the reverse."""
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPageSize,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import api, halftone, layout, updater
from .._version import __version__
from . import media, scanner, sheet
from .jobs import Job
from .printpanel import PrintPanel
from .viewer import Viewer

ACCENT = "#ee6b33"
MANY_PAGES = 20  # warn before converting a PDF longer than this

QSS = f"""
#desk {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #292c31, stop:1 #141519); }}
#shell {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #eeebe4, stop:1 #c8c5bc);
          border-radius: 30px; border: 1px solid #f7f5f0; }}
#panel {{ background: #33353a; border-radius: 18px; border: 1px solid #111; }}
#lcd {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9fb578, stop:1 #889e63);
        border: 2px solid #1d2416; border-radius: 6px; color: #1a2814; padding: 4px 10px; }}
#brand {{ font-size: 30px; font-weight: 900; color: #333; }}
#model, .lbl {{ font-size: 9px; font-weight: 700; letter-spacing: 1.2px; color: #666; }}
#slot {{ background: #0f0f12; border-radius: 6px; border: 1px solid #000; }}
QPushButton.key {{ color: #e2e2e2; font-size: 10px; font-weight: 800; letter-spacing: 0.8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555, stop:1 #333);
    border: 1px solid #1a1a1a; border-bottom: 3px solid #111; border-radius: 10px;
    min-width: 88px; max-width: 88px; min-height: 46px; }}
QPushButton.key:pressed {{ border-bottom: 1px solid #111; margin-top: 2px; background: #2c2c2c; }}
QPushButton.key:disabled {{ color: #777; background: #3a3a3a; }}
QPushButton.key[accent="true"] {{ color: white;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {ACCENT}, stop:1 #c4511f); }}
QPushButton.key[accent="true"]:disabled {{ background: #7a4a35; color: #caa; }}
QPushButton.mode {{ color: #999; font-size: 10px; font-weight: 900; letter-spacing: 0.6px; border: none;
    border-radius: 6px; background: transparent; min-height: 26px; }}
QPushButton.mode:checked {{ color: black; background: #d9d9d9; }}
#modebar {{ background: rgba(0,0,0,0.45); border-radius: 8px; }}
#turn {{ color: #ddd; font-size: 26px; font-weight: 700; background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15); border-radius: 22px; padding-bottom: 4px; }}
#turn:hover {{ background: rgba(255,255,255,0.18); }}
#turn:disabled {{ color: #555; background: transparent; }}
#shell QLabel, #shell QCheckBox {{ color: #333; }}
"""


def shadow(widget, radius=24, dy=12, alpha=150):
    e = QGraphicsDropShadowEffect(widget)
    e.setBlurRadius(radius)
    e.setOffset(0, dy)
    e.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(e)


# ---- printer parts ------------------------------------------------------------

class LED(QWidget):
    def __init__(self, label, color):
        super().__init__()
        self.label, self.color, self.on, self.blink, self._phase = label, QColor(color), False, False, False
        self.setFixedSize(46, 26)
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(350)

    def _tick(self):
        self._phase = not self._phase if (self.on and self.blink) else False
        self.update()

    def set(self, on, blink=False):
        self.on, self.blink = on, blink
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lit = self.on and not self._phase
        if lit:
            glow = QColor(self.color)
            glow.setAlpha(90)
            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(self.width() / 2 - 9, 0, 18, 18))
        p.setBrush(self.color if lit else QColor("#262626"))
        p.setPen(QPen(QColor("#111"), 1))
        p.drawEllipse(QRectF(self.width() / 2 - 5, 4, 10, 10))
        p.setPen(QColor("#999"))
        f = QFont()
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 15, self.width(), 11), Qt.AlignCenter, self.label)


class Paper(QWidget):
    """A sheet: white paper showing an image (or a placeholder) with a caption."""

    def __init__(self, w, h):
        super().__init__()
        self.setFixedSize(w, h)
        self.pix, self.caption, self.placeholder, self.highlight = None, "", "", False
        self.full, self.title = None, ""

    def set_image(self, img: QImage | None, caption="", title=""):
        self.full, self.title = img, title or caption.title() or "Image"
        self.setCursor(Qt.PointingHandCursor if img is not None else Qt.ArrowCursor)
        self.setToolTip("Double-click to view at full resolution" if img is not None else "")
        if img is not None and img.width() > 2 * self.width():
            # area-average big pages down first; drawing a 600 dpi halftone straight to a thumbnail moirés
            img = img.convertToFormat(QImage.Format_Grayscale8 if img.isGrayscale() else QImage.Format_RGB32)
            img = img.scaled(2 * self.width(), 2 * self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.pix = QPixmap.fromImage(img) if img is not None else None
        self.caption = caption
        self.update()

    def mouseDoubleClickEvent(self, _):
        if self.full is not None:
            Viewer(self.window(), self.full, self.title).show()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("white"))
        cap_h = 18 if self.caption else 0
        area = QRectF(12, 12, self.width() - 24, self.height() - 24 - cap_h)
        if self.pix:
            s = self.pix.size().scaled(area.size().toSize(), Qt.KeepAspectRatio)
            p.drawPixmap(QRectF(area.center().x() - s.width() / 2, area.center().y() - s.height() / 2,
                                s.width(), s.height()), self.pix, QRectF(self.pix.rect()))
        elif self.placeholder:
            p.setPen(QColor("#777"))
            f = QFont()
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            p.drawText(area, Qt.AlignCenter, self.placeholder)
        if self.caption:
            p.setPen(QColor("#888"))
            f = QFont()
            f.setPixelSize(9)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
            p.setFont(f)
            p.drawText(QRectF(0, self.height() - cap_h - 6, self.width(), cap_h), Qt.AlignCenter, self.caption)
        if self.highlight:
            p.setPen(QPen(QColor(ACCENT), 3, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self.rect()).adjusted(2, 2, -2, -2))


class InputTray(QWidget):
    """Paper feeder at the top of the printer; accepts dropped files."""

    def __init__(self, on_drop):
        super().__init__()
        self.on_drop = on_drop
        self.setFixedSize(440, 176)
        self.setAcceptDrops(True)
        self.paper = Paper(300, 150)
        self.paper.setParent(self)
        self.paper.move(70, 22)
        e = QGraphicsDropShadowEffect(self.paper)
        e.setBlurRadius(8)
        e.setOffset(0, 2)
        e.setColor(QColor(0, 0, 0, 90))
        self.paper.setGraphicsEffect(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        w, h, inset = self.width(), self.height(), 34
        path.moveTo(inset, 6)
        path.lineTo(w - inset, 6)
        path.lineTo(w, h)
        path.lineTo(0, h)
        path.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#bdb9b0"))
        g.setColorAt(1, QColor("#e9e6df"))
        p.fillPath(path, g)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.paper.highlight = True
            self.paper.update()

    def dragLeaveEvent(self, _):
        self.paper.highlight = False
        self.paper.update()

    def dropEvent(self, e):
        self.paper.highlight = False
        self.paper.update()
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.on_drop(urls[0])


class OutputTray(QWidget):
    """The area under the output slot; the sheet slides out of the top edge. ‹ › turn the pages."""

    def __init__(self, on_turn):
        super().__init__()
        self.setFixedSize(900, 350)
        self.paper = Paper(560, 330)
        self.paper.setParent(self)
        self.paper.hide()
        self.anim = QPropertyAnimation(self.paper, b"pos", self)
        self.anim.setDuration(1100)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.turn = []
        for x, step, text in [(100, -1, "‹"), (756, 1, "›")]:
            b = QPushButton(text, self, objectName="turn")
            b.setFixedSize(44, 44)
            b.move(x, 150)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, step=step: on_turn(step))
            b.hide()
            self.turn.append(b)

    def nav(self, count, at):
        for b, show, on in zip(self.turn, (count > 1, count > 1), (at > 0, at < count - 1)):
            b.setVisible(show)
            b.setEnabled(on)

    def eject(self, img, caption):
        self.paper.set_image(img, caption)
        x = (self.width() - self.paper.width()) // 2
        self.paper.move(x, -self.paper.height())
        self.paper.show()
        self.anim.stop()
        self.anim.setStartValue(QPoint(x, -self.paper.height()))
        self.anim.setEndValue(QPoint(x, 6))
        self.anim.start()

    def clear(self):
        self.anim.stop()
        self.paper.hide()
        self.nav(0, 0)


def thumb(img, side=1600):
    """A copy small enough to keep for every page of a long PDF (the trays and the zoom view)."""
    if max(img.width(), img.height()) <= side:
        return img
    if img.format() == QImage.Format_Mono:
        img = img.convertToFormat(QImage.Format_Grayscale8)
    return img.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def key(text, accent=False):
    b = QPushButton(text)
    b.setProperty("class", "key")
    b.setProperty("accent", "true" if accent else "false")
    b.setCursor(Qt.PointingHandCursor)
    return b


def small_label(text):
    lab = QLabel(text)
    lab.setProperty("class", "lbl")
    return lab


# ---- main window --------------------------------------------------------------

class Printer(QMainWindow):
    HIDE, REVEAL = "HIDE COLOR", "REVEAL COLOR"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inkhue")
        self.pool = QThreadPool.globalInstance()
        self.mode = self.HIDE
        self.pages, self.colors, self.sources = [], [], []  # 1-bit pages; decoded photos; input-tray previews
        self.at, self.out = 0, None  # page shown, and what the output tray holds: "pages" or "colors"
        self.page_dpi = None
        self.source_name = "photo"
        self.busy = False
        self.refiner = None
        self.pending_update = None
        self._build()
        self.set_mode(self.HIDE)
        QTimer.singleShot(3000, self.check_updates)
        t = QTimer(self)
        t.timeout.connect(self.check_updates)
        t.start(6 * 3600 * 1000)

    # -- layout --
    def _build(self):
        desk = QWidget(objectName="desk")
        col = QVBoxLayout(desk)
        col.setContentsMargins(0, 16, 0, 0)
        col.setSpacing(0)
        self.tray_in = InputTray(self.handle_file)
        col.addWidget(self.tray_in, 0, Qt.AlignHCenter)

        shell = QFrame(objectName="shell")
        shell.setFixedSize(900, 300)
        shadow(shell)
        sv = QVBoxLayout(shell)
        sv.setContentsMargins(30, 22, 30, 14)
        row = QHBoxLayout()
        row.addLayout(self._brand_and_settings())
        row.addStretch(1)
        row.addWidget(self._control_panel(), 0, Qt.AlignTop)
        sv.addLayout(row)
        sv.addStretch(1)
        slot = QFrame(objectName="slot")
        slot.setFixedSize(600, 12)
        sv.addWidget(slot, 0, Qt.AlignHCenter)
        col.addWidget(shell, 0, Qt.AlignHCenter)

        self.tray_out = OutputTray(self.turn)
        col.addWidget(self.tray_out, 0, Qt.AlignHCenter)
        col.addStretch(1)
        self.setCentralWidget(desk)
        self.setStyleSheet(QSS)
        self.setMinimumSize(980, 860)

    def _brand_and_settings(self):
        v = QVBoxLayout()
        v.setSpacing(6)
        brand = QLabel(f'Ink<span style="color:{ACCENT}">hue</span>', objectName="brand")
        v.addWidget(brand)
        v.addWidget(QLabel(f"LP-600  ·  HIDDEN-COLOR PRINTER  ·  v{__version__}", objectName="model"))
        v.addSpacing(10)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.width_in = QDoubleSpinBox(suffix=" in", minimum=2, maximum=16, singleStep=0.5, value=6.0, decimals=2)
        self.dpi = QComboBox()
        self.dpi.addItems(["300", "600", "1200"])
        self.dpi.setCurrentText("600")
        self.paper = QComboBox()
        self.paper.addItems(list(media.PAPERS))
        self.paper.setCurrentText("US Letter")
        self.use_net = QCheckBox("Neural refiner")
        has_model = api.find_refiner() is not None
        self.use_net.setChecked(has_model)
        self.use_net.setEnabled(has_model)
        self.use_net.setToolTip("Clean up the decoded color with the trained network" if has_model
                                else "No trained model found (models/refiner.onnx)")
        for r, (name, w) in enumerate([("PRINT WIDTH", self.width_in), ("PRINTER DPI", self.dpi),
                                       ("PAPER", self.paper), ("DECODER", self.use_net)]):
            g.addWidget(small_label(name), r, 0)
            g.addWidget(w, r, 1)
        # what the width means: on paper, and how many pixels the color comes back with
        self.fill = QCheckBox("Fill the paper")
        self.fill.setChecked(True)
        self.fill.setToolTip("Print as large as fits on the PDF paper at 100 % (bigger = sharper color)")
        self.fill.toggled.connect(lambda on: self.width_in.setEnabled(not on))
        self.width_in.setEnabled(False)
        g.addWidget(self.fill, 4, 1)
        self.width_info = QLabel()
        self.width_info.setStyleSheet("color: #666; font-size: 10px;")
        g.addWidget(self.width_info, 0, 2)
        self.width_in.valueChanged.connect(self._width_info)
        self.dpi.currentTextChanged.connect(self._width_info)
        self._width_info()
        v.addLayout(g)
        v.addStretch(1)
        return v

    def _width_info(self):
        w = self.width_in.value()
        cells = int(w * int(self.dpi.currentText()) / halftone.K) - 2 * (layout.B + layout.QUIET)
        self.width_info.setText(f"{w * 2.54:.1f} cm · color back at ~{2 * cells} px")

    def _control_panel(self):
        panel = QFrame(objectName="panel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        top = QHBoxLayout()
        self.lcd = QLabel(objectName="lcd")
        self.lcd.setFixedSize(320, 58)
        top.addWidget(self.lcd)
        leds = QVBoxLayout()
        leds.setSpacing(0)
        self.led_power = LED("POWER", "#3ddc57")
        self.led_data = LED("DATA", "#ffa31a")
        self.led_err = LED("ERROR", "#ff3b30")
        self.led_power.set(True)
        for led in (self.led_power, self.led_data, self.led_err):
            leds.addWidget(led)
        top.addLayout(leds)
        v.addLayout(top)

        bar = QFrame(objectName="modebar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(3, 3, 3, 3)
        self.mode_group = QButtonGroup(self)
        for m in (self.HIDE, self.REVEAL):
            b = QPushButton(m)
            b.setProperty("class", "mode")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            self.mode_group.addButton(b)
            bl.addWidget(b)
        v.addWidget(bar)

        self.keys = QHBoxLayout()
        self.keys.setSpacing(10)
        self.k_load = key("LOAD\nPHOTO")
        self.k_print = key("PRINT", accent=True)
        self.k_pdf = key("EXPORT\nPDF")
        self.k_test = key("TEST\nCYCLE")
        self.k_import = key("IMPORT\nPAGE")
        self.k_scan = key("SCAN", accent=True)
        self.k_save = key("EXPORT\nCOLOR")
        for b, fn in [(self.k_load, self.open_file), (self.k_print, self.print_page), (self.k_pdf, self.export_pdf),
                      (self.k_test, self.test_cycle), (self.k_import, self.open_file), (self.k_scan, self.scan),
                      (self.k_save, self.save_color)]:
            b.clicked.connect(fn)
            self.keys.addWidget(b)
        v.addLayout(self.keys)
        return panel

    # -- state --
    def say(self, a, b="", fault=False):
        self.lcd.setText(f'<div style="font-family:Menlo,Consolas,monospace; font-size:17px; font-weight:800">'
                         f'{a.upper()}</div><div style="font-family:Menlo,Consolas,monospace; font-size:12px">'
                         f'{(b or "&nbsp;").upper()}</div>')
        self.led_err.set(fault)

    def refresh_keys(self):
        hide = self.mode == self.HIDE
        for b in (self.k_load, self.k_print, self.k_pdf, self.k_test):
            b.setVisible(hide)
        for b in (self.k_import, self.k_scan, self.k_save):
            b.setVisible(not hide)
        idle = not self.busy
        self.k_load.setEnabled(idle)
        self.k_import.setEnabled(idle)
        self.k_scan.setEnabled(idle)
        for b in (self.k_print, self.k_pdf, self.k_test):
            b.setEnabled(idle and bool(self.pages))
        self.k_save.setEnabled(idle and any(c is not None for c in self.colors))
        self.led_data.set(self.busy, blink=True)

    def set_mode(self, m, keep=False):
        self.mode = m
        for b in self.mode_group.buttons():
            b.setChecked(b.text() == m)
        if not keep:
            self.tray_out.clear()
            self.tray_in.paper.set_image(None)
            self.say("READY", "FEED A COLOR PHOTO" if m == self.HIDE else "IMPORT OR SCAN A PAGE")
        self.tray_in.paper.placeholder = ("DROP A COLOR PHOTO\nimage or PDF" if m == self.HIDE
                                          else "DROP A SCANNED PAGE\nimage or PDF")
        self.tray_in.paper.update()
        self.refresh_keys()

    def run(self, title, fn, *args, done, progress=None):
        if self.busy:
            return
        self.busy = True
        self.say(title, "PLEASE WAIT")
        self.refresh_keys()
        job = Job(fn, *args, progress=progress is not None)

        def finish(result):
            self.busy = False
            self.refresh_keys()
            try:
                done(result)
            except Exception as ex:
                self.fail(str(ex))

        job.sig.done.connect(finish)
        job.sig.failed.connect(lambda msg: (setattr(self, "busy", False), self.refresh_keys(), self.fail(msg)))
        if progress:
            job.sig.progress.connect(progress)
        self.pool.start(job)

    @property
    def page(self):
        """The page on show, as an array (0 ink / 255 paper)."""
        return media.qimage_to_array(self.pages[self.at], gray=True) if self.pages else None

    @property
    def color(self):
        return self.colors[self.at] if self.colors else None

    def count_pages(self, path):
        """Pages to convert, after asking when there are many; None to stop."""
        try:
            n = media.page_count(path)
        except Exception as ex:
            self.fail(str(ex))
            return None
        if n > MANY_PAGES:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("Many pages")
            box.setText(f"This PDF has {n} pages.")
            box.setInformativeText("That's quite a lot: converting every page will take a while. Continue?")
            go = box.addButton("Convert All", QMessageBox.AcceptRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                self.say("READY", "CANCELLED")
                return None
        return n

    def page_progress(self, title, n):
        return lambda f: n > 1 and self.say(title, f"PAGE {round(f * n) + 1} OF {n}")

    def turn(self, step):
        n = len(self.pages if self.out == "pages" else self.colors)
        self.at = max(0, min(n - 1, self.at + step))
        self.show_output()

    def show_output(self, eject=False):
        n = len(self.pages if self.out == "pages" else self.colors)
        of = f" {self.at + 1} OF {n}" if n > 1 else ""
        if self.out == "pages":
            img, caption = self.pages[self.at], f"HIDDEN-COLOR PAGE{of}  ·  DOUBLE-CLICK TO SEE THE DOTS"
        elif self.colors[self.at] is None:  # this page of a longer scan carried no color
            img, caption = None, f"PAGE{of}"
        else:
            rgb = self.colors[self.at]
            img = media.rgb_to_qimage(rgb)
            caption = f"RECOVERED COLOR{of}  ·  {rgb.shape[1]} × {rgb.shape[0]} PX  ·  DOUBLE-CLICK TO ZOOM"
        self.tray_out.paper.placeholder = "NO HIDDEN COLOR ON THIS PAGE" if img is None else ""
        (self.tray_out.eject if eject else self.tray_out.paper.set_image)(img, caption)
        self.tray_out.nav(n, self.at)
        if self.at < len(self.sources):
            self.tray_in.paper.set_image(self.sources[self.at])

    def fail(self, msg):
        if msg.startswith(api.NO_COLOR[:30]):
            self.say("NO HIDDEN COLOR", "MAKE IT WITH HIDE COLOR FIRST", fault=True)
            self.statusBar().showMessage(msg, 30000)
            return
        self.say("ERROR", msg[:40], fault=True)
        self.statusBar().showMessage(msg, 15000)

    # -- hide color --
    def handle_file(self, path):
        (self.feed if self.mode == self.HIDE else self.import_page)(path)

    def open_file(self):
        hide = self.mode == self.HIDE
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a color photo" if hide else "Choose a scanned page", "",
            "Images and PDF (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.pdf);;All files (*)")
        if path:
            self.handle_file(path)

    def feed(self, path):
        n = self.count_pages(path)
        if n is None:
            return
        self.source_name = Path(path).stem
        width, dpi = self.width_in.value(), int(self.dpi.currentText())
        paper = media.PAPERS.get(self.paper.currentText())
        fill = self.fill.isChecked() and paper is not None

        def work(progress):
            pages, sources, first = [], [], None
            for i in range(n):
                progress(i / n)
                rgb = media.read_image(path, gray=False, page=i)
                w = sheet.fill_width(rgb.shape[0] / rgb.shape[1], QPageSize(paper), dpi) if fill else width
                page, info = api.encode(rgb, w, dpi)
                pages.append(media.mono(page))
                sources.append(thumb(media.rgb_to_qimage(rgb)))
                first = first or (info, w)
            return pages, sources, first

        def done(r):
            pages, sources, (info, w) = r
            if fill:
                self.width_in.setValue(w)
            self.pages, self.sources, self.colors, self.page_dpi = pages, sources, [], dpi
            self.at, self.out = 0, "pages"
            self.show_output(eject=True)
            if len(pages) == 1:
                self.say("PAGE READY", f"{info['width_in']:.2f} x {info['height_in']:.2f} IN @ {dpi} DPI")
            else:
                self.say("PAGES READY", f"{len(pages)} PAGES @ {dpi} DPI")
            self.refresh_keys()

        self.run("ENCODING", work, done=done, progress=self.page_progress("ENCODING", n))

    def print_page(self):
        if not self.pages:
            return
        self.say("PRINT SETUP", "CHOOSE PRINTER + OPTIONS")
        paper = {"US Letter": "Letter", "A4": "A4"}.get(self.paper.currentText())
        panel = PrintPanel(self, self.pages, self.page_dpi, self.printed, title=f"Inkhue · {self.source_name}",
                           paper=paper)
        panel.rejected.connect(lambda: self.say("PAGE READY", "PRINT CANCELLED"))
        panel.open()

    def printed(self, printer, job, note=None):
        kind = (note or {}).get("kind")
        if kind == "release":
            self.say("SENT TO PRINT SERVER", "RELEASE IT AT THE PRINTER")
            self.statusBar().showMessage(f"{printer}: the job waits on the print server until you sign in at a "
                                         "printer and release it.", 30000)
            return
        if kind == "auth":
            self.say("SIGN IN TO PRINT", "JOB IS WAITING FOR YOU")
            box = QMessageBox(self)
            box.setWindowTitle("Sign in to print")
            box.setText(f"{printer} needs you to sign in before it prints.\n"
                        "Open the print queue and enter your account to release the job.")
            open_q = box.addButton("Open Print Queue", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_q:
                from .printing import open_queue
                open_queue(note.get("queue"))
            return
        self.say("PRINTING", f"{job} · {printer}"[:34])
        msg = f"Sent to {printer} ({job}). Scan it in grayscale at 600 dpi to reveal the color."
        self.statusBar().showMessage(msg, 20000)

    def export_pdf(self):
        if not self.pages:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", f"{self.source_name}-inkhue.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            media.export_pdf(self.pages, self.page_dpi, self.paper.currentText(), path)
            self.say("PDF SAVED", Path(path).name)
        except Exception as ex:
            self.fail(str(ex))

    def test_cycle(self):
        """Software print + scan, then decode: tries the whole loop without hardware."""
        if not self.pages:
            return
        from .. import channel
        pages = list(self.pages)
        self.set_mode(self.REVEAL, keep=True)
        self.reveal(lambda i: channel.print_scan(media.qimage_to_array(pages[i], gray=True), scale=2.0),
                    len(pages), "SIMULATING")

    # -- reveal color --
    def import_page(self, path):
        n = self.count_pages(path)
        if n is None:
            return
        self.source_name = Path(path).stem
        self.reveal(lambda i: media.read_image(path, gray=True, page=i), n)

    def scan(self):
        self.say("SCANNER", "CHOOSE A DEVICE")
        scanner.scan(self, on_done=self.import_page, on_error=self.fail)

    def reveal(self, read, n, title="DECODING"):
        """read(i) gives scanned page i (gray array); runs in the background."""
        use_net = self.use_net.isChecked()

        def work(progress):
            if use_net and self.refiner is None:
                self.refiner = api.load_refiner()
            colors, scans, infos, first_error = [], [], [], None
            for i in range(n):
                progress(i / n)
                gray = read(i)
                scans.append(thumb(media.gray_to_qimage(gray)))
                try:
                    rgb, info = api.decode(gray, self.refiner if use_net else None)
                except ValueError as ex:
                    if n == 1:
                        raise
                    rgb, info, first_error = None, None, first_error or str(ex)  # keep going with the rest
                colors.append(rgb)
                infos.append(info)
            if all(c is None for c in colors):
                raise ValueError(first_error)
            return colors, scans, infos

        def done(r):
            colors, scans, infos = r
            self.colors, self.sources, self.at, self.out = colors, scans, 0, "colors"
            self.show_output(eject=True)
            if n == 1:
                info = infos[0]
                scale = round(colors[0].shape[1] / info["cells"][0])
                how = f"NEURAL {scale}X" if use_net and self.refiner else "CLASSIC"
                if info["rs_ok"]:
                    self.say("COLOR RESTORED", f"{how} · {info['reps']}X REDUNDANCY")
                else:  # damaged parts stay gray instead of random colors
                    self.say("PARTLY RESTORED", f"{info['damaged']:.0%} LEFT GRAY · DAMAGED", fault=True)
            else:
                ok = sum(i is not None and i["rs_ok"] for i in infos)
                if ok == n:
                    self.say("COLOR RESTORED", f"ALL {n} PAGES")
                else:
                    missing = sum(i is None for i in infos)
                    self.say("PARTLY RESTORED", f"{ok} OF {n} PAGES OK · {missing} WITHOUT COLOR", fault=True)
            self.refresh_keys()

        self.run(title, work, done=done, progress=self.page_progress(title, n))

    def save_color(self):
        colors = [c for c in self.colors if c is not None]
        if not colors:
            return
        filters = media.color_save_filters()
        path, chosen = QFileDialog.getSaveFileName(self, "Export color image", f"{self.source_name}-color.png",
                                                   ";;".join(filters), filters[1])
        if not path:
            return
        if "." not in Path(path).name:  # some platforms don't append the extension of the chosen filter
            path += "." + chosen.split("*.")[1].split()[0].rstrip(")")
        try:
            media.save_color(colors, path, self.paper.currentText())
            self.say("EXPORTED", Path(path).name if len(colors) == 1 or path.lower().endswith(".pdf")
                     else f"{len(colors)} FILES")
        except Exception as ex:
            self.fail(str(ex))

    # -- updates --
    def check_updates(self):
        if not updater.frozen() or self.pending_update:
            return  # running from source: nothing to replace
        job = Job(updater.check, quiet=True)  # offline or no release yet: try again later, silently
        job.sig.done.connect(lambda info: info and self.download_update(info))
        self.pool.start(job)

    def download_update(self, info):
        job = Job(updater.download, info, progress=True)
        job.sig.progress.connect(lambda f: self.statusBar().showMessage(f"Downloading {info['tag']}… {f:.0%}"))
        job.sig.done.connect(lambda new: self.update_ready(info, new))
        job.sig.failed.connect(lambda msg: self.statusBar().showMessage(f"Update failed: {msg}", 15000))
        self.pool.start(job)

    def update_ready(self, info, new_app):
        self.pending_update = new_app
        self.statusBar().showMessage(f"Inkhue {info['tag']} is ready; it installs when you quit.")
        box = QMessageBox(self)
        box.setWindowTitle("Update ready")
        extra = "\nYou'll be asked for your password to install it." if sys.platform.startswith("linux") else ""
        box.setText(f"Inkhue {info['tag']} has been downloaded and verified.\n"
                    f"You have v{__version__}.{extra}")
        box.setDetailedText(info["notes"] or "")
        now = box.addButton("Restart Now", QMessageBox.AcceptRole)
        box.addButton("Install When I Quit", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is now:
            self.close()

    def closeEvent(self, e):
        if self.pending_update:
            updater.apply(self.pending_update)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Inkhue")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(api.ICON)))
    w = Printer()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
