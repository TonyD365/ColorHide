"""ColorHide's own print panel: pick a printer and its driver options, then the job goes straight
to the print system (see printing.py). No operating-system print dialog."""
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import printing
from .jobs import Job

QSS = """
QDialog { background: #2b2d31; }
QLabel { color: #d8d8d8; }
QLabel#title { color: #ee6b33; font-size: 13px; font-weight: 900; letter-spacing: 2px; }
QLabel#status { color: #9a9a9a; font-size: 11px; }
QLabel.optlabel { color: #a8a8a8; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QFrame#card { background: #35373c; border: 1px solid #1c1c1f; border-radius: 12px; }
QPushButton { color: #e2e2e2; font-weight: 800; letter-spacing: 0.8px; padding: 8px 18px; border-radius: 8px;
              background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555, stop:1 #3a3a3a);
              border: 1px solid #1a1a1a; border-bottom: 3px solid #111; }
QPushButton:pressed { border-bottom: 1px solid #111; margin-top: 2px; }
QPushButton#go { color: white; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ee6b33, stop:1 #c4511f); }
QPushButton#go:disabled { background: #6a4535; color: #bba; }
"""

# Friendlier names for common CUPS/PPD option keys; anything else shows the driver's own label.
NICE = {"PageSize": "Paper size", "InputSlot": "Paper source", "MediaType": "Paper type", "Duplex": "Two-sided",
        "ColorModel": "Color mode", "cupsPrintQuality": "Quality", "Resolution": "Resolution",
        "OutputMode": "Quality", "Collate": "Collate", "ColorMode": "Color mode"}
# Choices that make a hidden-color page print best, used when the driver offers them.
PREFER = {"cupsPrintQuality": ["High", "Best", "Normal"], "ColorModel": ["Gray", "DeviceGray"],
          "Resolution": ["600dpi", "600x600dpi", "600"], "OutputMode": ["Best", "High", "Normal"],
          "MediaType": ["stationery", "Plain", "plain"]}


class PrintPanel(QDialog):
    def __init__(self, parent, page, dpi, on_sent):
        super().__init__(parent)
        self.page, self.dpi, self.on_sent = page, dpi, on_sent
        self.backend = printing.backend()
        self.combos = {}
        self.setWindowTitle("Print")
        self.setStyleSheet(QSS)
        self.resize(500, 560)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        v.addWidget(QLabel("PRINT  ·  HIDDEN-COLOR PAGE", objectName="title"))
        size = QLabel(f"{page.shape[1] / dpi:.2f} × {page.shape[0] / dpi:.2f} in at 100 % scale · {dpi} dpi")
        size.setObjectName("status")
        v.addWidget(size)

        card = QFrame(objectName="card")
        cv = QFormLayout(card)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setVerticalSpacing(10)
        self.printer = QComboBox()
        for pid, label in self.backend.printers():
            self.printer.addItem(label, pid)
        default = self.backend.default()
        if default is not None and self.printer.findData(default) >= 0:
            self.printer.setCurrentIndex(self.printer.findData(default))
        self.copies = QSpinBox(minimum=1, maximum=999, value=1)
        cv.addRow(self._label("PRINTER"), self.printer)
        cv.addRow(self._label("COPIES"), self.copies)
        v.addWidget(card)

        self.opts_host = QScrollArea()
        self.opts_host.setWidgetResizable(True)
        v.addWidget(self.opts_host, 1)

        self.status = QLabel(objectName="status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton("PRINT", objectName="go")
        self.go.clicked.connect(self.submit)
        self.go.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(self.go)
        v.addLayout(row)

        self.printer.currentIndexChanged.connect(self.load_options)
        if self.printer.count() == 0:
            self.status.setText("No printers found. Add one in your system settings, or use EXPORT PDF.")
            self.go.setEnabled(False)
        else:
            self.load_options()

    def _label(self, text):
        lab = QLabel(text)
        lab.setProperty("class", "optlabel")
        return lab

    def load_options(self):
        pid = self.printer.currentData()
        self.go.setEnabled(False)
        self.status.setText("Reading printer options…")
        self.opts_host.setWidget(QWidget())
        job = Job(self.backend.options, pid, quiet=True)
        job.sig.done.connect(lambda opts, pid=pid: self.show_options(pid, opts, None))
        job.sig.failed.connect(lambda msg, pid=pid: self.show_options(pid, self.backend.fallback_options(), msg))
        QThreadPool.globalInstance().start(job)

    def show_options(self, pid, opts, problem):
        if pid != self.printer.currentData():
            return  # the user already picked another printer
        if not opts:
            opts, problem = self.backend.fallback_options(), problem or "The driver reported no options."
        card = QFrame(objectName="card")
        form = QFormLayout(card)
        form.setContentsMargins(16, 14, 16, 14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        self.combos = {}
        for o in opts:
            combo = QComboBox()
            for value, label in o.choices:
                combo.addItem(label, value)
            pick = next((p for p in PREFER.get(o.key, []) if combo.findData(p) >= 0), o.default)
            combo.setCurrentIndex(max(0, combo.findData(pick)))
            form.addRow(self._label(NICE.get(o.key, o.label).upper()), combo)
            self.combos[o.key] = combo
        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.addWidget(card)
        hv.addStretch(1)
        self.opts_host.setWidget(host)
        tip = "Scaling is fixed at 100 %. For the cleanest dots use a laser printer and plain paper."
        self.status.setText(f"⚠ {problem} Basic options shown; the job can still be queued.  {tip}"
                            if problem else f"{len(opts)} driver options.  {tip}")
        self.go.setEnabled(True)

    def submit(self):
        pid = self.printer.currentData()
        values = {k: c.currentData() for k, c in self.combos.items()}
        self.go.setEnabled(False)
        self.status.setText("Sending to printer…")
        if self.backend.name == "Qt":  # QPrinter painting belongs on the UI thread
            try:
                jid = self.backend.submit(pid, self.page, self.dpi, values, self.copies.value())
            except Exception as ex:
                self.status.setText(f"⚠ {ex}")
                self.go.setEnabled(True)
                return
            self.accept()
            self.on_sent(self.printer.currentText(), jid)
            return
        job = Job(self.backend.submit, pid, self.page, self.dpi, values, self.copies.value(), quiet=True)
        job.sig.done.connect(lambda jid: (self.accept(), self.on_sent(self.printer.currentText(), jid)))
        job.sig.failed.connect(lambda msg: (self.status.setText(f"⚠ {msg}"), self.go.setEnabled(True)))
        QThreadPool.globalInstance().start(job)
