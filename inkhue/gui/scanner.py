"""Scanning through each operating system's own scanner stack.

macOS   ImageKit scanner panel (same UI as Image Capture; every option the device offers)
Windows WIA common dialog (the system "Scan" dialog with its quality/DPI settings)
Linux   SANE: the device's full option list read from `scanimage -A`, shown as a form
Every backend ends with a file path handed to `on_done(path)` or a message to `on_error(msg)`.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

TIP = "Scan in Grayscale at 600 dpi (at least 400), with sharpening and descreening off."
_keep = []  # live native panels/delegates (otherwise garbage collected mid-scan)


def scan(parent, on_done, on_error):
    try:
        if sys.platform == "darwin":
            _scan_macos(on_done, on_error)
        elif sys.platform == "win32":
            _scan_windows(on_done, on_error)
        else:
            SaneDialog(parent, on_done, on_error).open()
    except Exception as ex:  # missing driver stack, no device, user cancel surfaced as COM error...
        on_error(str(ex) or type(ex).__name__)


# ---- macOS -------------------------------------------------------------------

def _scan_macos(on_done, on_error):
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSMakeRect,
        NSPanel,
        NSTextField,
        NSView,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSURL, NSObject
    from Quartz import (
        IKDeviceBrowserView,
        IKDeviceBrowserViewDisplayModeTable,
        IKScannerDeviceView,
        IKScannerDeviceViewDisplayModeAdvanced,
        IKScannerDeviceViewTransferModeFileBased,
    )

    out_dir = Path(tempfile.mkdtemp(prefix="inkhue-scan-"))

    class Delegate(NSObject):
        def deviceBrowserView_selectionDidChange_(self, browser, device):
            from ImageCaptureCore import ICScannerDevice
            scanner = device if isinstance(device, ICScannerDevice) else None
            self.scanner.setScannerDevice_(scanner)
            self.tip.setStringValue_(TIP)
            if scanner is not None:  # an empty panel means the session never opened: say why, don't stay blank
                self.performSelector_withObject_afterDelay_("checkSession:", scanner, 12.0)

        def checkSession_(self, device):
            if self.scanner.scannerDevice() is device and not device.hasOpenSession():
                self.tip.setStringValue_(
                    f"Couldn't connect to {device.name()}. It may be asleep, busy (close HP Smart, Image Capture "
                    "or other scanning apps) or on another network. Wake it up, then select it again.")
                self.tip.setTextColor_(NSColor.systemRedColor())

        def deviceBrowserView_didEncounterError_(self, browser, error):
            on_error(str(error.localizedDescription()))

        def scannerDeviceView_didScanToURL_error_(self, view, url, error):
            if error is not None:
                on_error(str(error.localizedDescription()))
                return
            self.panel.close()
            on_done(str(url.path()))

        def scannerDeviceView_didEncounterError_(self, view, error):
            on_error(str(error.localizedDescription()))

    W, H, side = 900, 600, 230
    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0, 0, W, H), style,
                                                                         NSBackingStoreBuffered, False)
    panel.setTitle_("Scan from Scanner")
    content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
    tip = NSTextField.labelWithString_(TIP)
    tip.setFrame_(NSMakeRect(12, H - 26, W - 24, 18))
    tip.setAutoresizingMask_(2 | 8)  # width sizable | min-y margin
    browser = IKDeviceBrowserView.alloc().initWithFrame_(NSMakeRect(0, 0, side, H - 32))
    browser.setAutoresizingMask_(16)  # height sizable
    browser.setDisplaysLocalScanners_(True)
    browser.setDisplaysNetworkScanners_(True)
    browser.setDisplaysLocalCameras_(False)
    browser.setDisplaysNetworkCameras_(False)
    browser.setMode_(IKDeviceBrowserViewDisplayModeTable)
    view = IKScannerDeviceView.alloc().initWithFrame_(NSMakeRect(side, 0, W - side, H - 32))
    view.setAutoresizingMask_(2 | 16)
    view.setTransferMode_(IKScannerDeviceViewTransferModeFileBased)
    view.setDownloadsDirectory_(NSURL.fileURLWithPath_(str(out_dir)))
    view.setDocumentName_("inkhue-scan")
    view.setDisplaysDownloadsDirectoryControl_(False)
    view.setDisplaysPostProcessApplicationControl_(False)
    view.setHasDisplayModeSimple_(True)
    view.setHasDisplayModeAdvanced_(True)
    view.setMode_(IKScannerDeviceViewDisplayModeAdvanced)
    for v in (tip, browser, view):
        content.addSubview_(v)
    panel.setContentView_(content)

    d = Delegate.alloc().init()
    d.scanner, d.panel, d.tip = view, panel, tip
    browser.setDelegate_(d)
    view.setDelegate_(d)
    _keep[:] = [panel, d, browser, view]
    panel.center()
    panel.makeKeyAndOrderFront_(None)


# ---- Windows -----------------------------------------------------------------

def _scan_windows(on_done, on_error):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    WIA_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
    dlg = win32com.client.Dispatch("WIA.CommonDialog")
    # DeviceType 1 = scanner, Intent 2 = grayscale; the common UI lets the user change everything
    img = dlg.ShowAcquireImage(1, 2, 0, WIA_PNG, False, True, False)
    if img is None:
        return  # cancelled
    path = Path(tempfile.mkdtemp(prefix="inkhue-scan-")) / "scan.png"
    img.SaveFile(str(path))
    on_done(str(path))


# ---- Linux (SANE) ------------------------------------------------------------

_OPT = re.compile(r"^\s+(--?[\w-]+)(?:\[=\(([^)]*)\)\])?\s*(.*?)\s*\[(.*?)\]\s*$")


def parse_sane_options(text):
    """Parse `scanimage -A` into [(flag, kind, choices_or_range, default, unit)]."""
    opts = []
    for line in text.splitlines():
        m = _OPT.match(line)
        if not m:
            continue
        flag, _, spec, default = m.groups()
        if default == "inactive" or not spec:
            continue
        unit = re.search(r"(dpi|mm|%|us|bit)$", spec)
        unit = unit.group(1) if unit else ""
        spec = spec[: -len(unit)] if unit else spec
        if ".." in spec:
            lo, hi = re.findall(r"-?[\d.]+", spec)[:2]
            opts.append((flag, "range", (float(lo), float(hi)), default, unit))
        elif "|" in spec:
            opts.append((flag, "choice", spec.split("|"), default, unit))
        else:
            opts.append((flag, "text", spec, default, unit))
    return opts


class SaneDialog(QDialog):
    def __init__(self, parent, on_done, on_error):
        super().__init__(parent)
        self.on_done, self.on_error = on_done, on_error
        self.setWindowTitle("Scan from Scanner")
        self.resize(560, 620)
        if not shutil.which("scanimage"):
            QMessageBox.warning(parent, "SANE not found",
                                "Scanning on Linux uses SANE. Install it, e.g.\n  sudo apt install sane-utils")
            raise RuntimeError("scanimage not installed")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(TIP))
        self.device = QComboBox()
        lay.addWidget(self.device)
        self.form_host = QScrollArea()
        self.form_host.setWidgetResizable(True)
        lay.addWidget(self.form_host, 1)
        self.status = QLabel("Looking for scanners…")
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.scan_btn = self.buttons.addButton("Scan", QDialogButtonBox.AcceptRole)
        self.scan_btn.setEnabled(False)
        self.buttons.rejected.connect(self.reject)
        self.scan_btn.clicked.connect(self.start_scan)
        lay.addWidget(self.buttons)
        self.fields = {}
        self.device.currentIndexChanged.connect(self.load_options)
        out = subprocess.run(["scanimage", "-f", "%d\t%v %m%n"], capture_output=True, text=True, timeout=60).stdout
        for line in out.splitlines():
            if "\t" in line:
                dev, name = line.split("\t", 1)
                self.device.addItem(f"{name}  ({dev})", dev)
        if self.device.count() == 0:
            self.status.setText("No scanners found. Check the connection and `scanimage -L`.")

    def load_options(self):
        dev = self.device.currentData()
        text = subprocess.run(["scanimage", "-d", dev, "-A"], capture_output=True, text=True, timeout=60).stdout
        form_w = QWidget()
        form = QFormLayout(form_w)
        self.fields = {}
        for flag, kind, spec, default, unit in parse_sane_options(text):
            if kind == "choice":
                w = QComboBox()
                w.addItems(spec)
                pref = {"--mode": "Gray", "--resolution": "1200"}.get(flag)
                pick = pref if pref in spec else default
                if pick in spec:
                    w.setCurrentText(pick)
            elif kind == "range":
                w = QDoubleSpinBox()
                w.setRange(*spec)
                w.setDecimals(1)
                try:
                    w.setValue(float(re.findall(r"-?[\d.]+", default)[0]))
                except IndexError:
                    pass
                if flag == "--resolution":
                    w.setValue(min(max(1200, spec[0]), spec[1]))
            else:
                w = QLineEdit(default)
            form.addRow(f"{flag.lstrip('-')} {('(' + unit + ')') if unit else ''}", w)
            self.fields[flag] = (kind, w, unit)
        self.form_host.setWidget(form_w)
        self.scan_btn.setEnabled(True)
        self.status.setText(f"{len(self.fields)} options")

    def start_scan(self):
        path = Path(tempfile.mkdtemp(prefix="inkhue-scan-")) / "scan.png"
        args = ["-d", self.device.currentData(), "--format=png", "-o", str(path)]
        for flag, (kind, w, _unit) in self.fields.items():
            val = w.currentText() if kind == "choice" else (f"{w.value():g}" if kind == "range" else w.text())
            args += [f"{flag}={val}"] if flag.startswith("--") else [flag, val]
        self.scan_btn.setEnabled(False)
        self.status.setText("Scanning…")
        self.proc = QProcess(self)
        self.proc.finished.connect(lambda code, _s: self._finished(code, path))
        self.proc.start("scanimage", args)

    def _finished(self, code, path):
        if code == 0 and path.exists():
            self.accept()
            self.on_done(str(path))
        else:
            err = bytes(self.proc.readAllStandardError()).decode(errors="replace").strip()
            self.status.setText(err or "Scan failed")
            self.scan_btn.setEnabled(True)
            self.on_error(err or "scan failed")

