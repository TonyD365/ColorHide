"""Direct printing, no system dialog.

macOS / Linux: CUPS. Printers come from `lpstat`, every option of the printer's driver from
`lpoptions -l` (media size, tray, duplex, quality, media type and any vendor-specific setting), and
the job goes straight to `lp` as a PDF sized exactly to the chosen paper, with scaling off.
Windows: Qt's printer API (QPrinterInfo/QPrinter) with the options the driver reports.

Each backend exposes printers() -> [(id, label)], default(), options(id) -> [Option], and
submit(id, page, dpi, values, copies) -> job description.
"""
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from . import media, sheet
from .sheet import SheetSettings

# options the panel shows as its own controls; the driver's duplicates are left out of "Printer options"
STANDARD_KEYS = {"PageSize", "ColorModel", "Duplex", "ColorMode", "Collate"}


@dataclass
class Option:
    key: str
    label: str
    choices: list = field(default_factory=list)  # [(value, label)]
    default: str = ""


# ---- paper sizes -------------------------------------------------------------

def _qt_page_keys():
    keys = {}
    for v in vars(QPageSize.PageSizeId).values():
        if isinstance(v, QPageSize.PageSizeId) and v != QPageSize.Custom:
            ps = QPageSize(v)
            keys.setdefault(ps.key().lower(), ps)
    return keys


_PAGE_KEYS = None


def page_size_for(name):
    """CUPS/PPD media name ('A4', 'Letter', 'Env10', '4x6', '100x150mm', 'na_letter_8.5x11in') -> QPageSize."""
    global _PAGE_KEYS
    if _PAGE_KEYS is None:
        _PAGE_KEYS = _qt_page_keys()
    n = name.split(".")[0]
    if n.lower() in _PAGE_KEYS:
        return _PAGE_KEYS[n.lower()]
    m = re.search(r"([\d.]+)x([\d.]+)(mm|in)?$", n)
    if m:
        w, h, unit = float(m.group(1)), float(m.group(2)), m.group(3) or "in"
        return QPageSize(QSizeF(w, h), QPageSize.Millimeter if unit == "mm" else QPageSize.Inch, name,
                         QPageSize.ExactMatch)
    return None


# ---- CUPS --------------------------------------------------------------------

class PrinterUnreachable(RuntimeError):
    pass


def _run(*args, timeout=12):
    try:
        # printer names/descriptions are not always UTF-8 (e.g. a shared printer "Willis’s" in MacRoman)
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired as ex:
        raise PrinterUnreachable("printer not responding (offline or shared from a computer that is asleep)") from ex


class CupsBackend:
    name = "CUPS"

    def printers(self):
        out = []
        for dest in _run("lpstat", "-e").stdout.split():
            try:
                info = dict(kv.split("=", 1) for kv in shlex.split(_run("lpoptions", "-p", dest).stdout) if "=" in kv)
            except (PrinterUnreachable, ValueError):  # still list it; options are read (and may fail) later
                info = {}
            label = info.get("printer-info") or dest.replace("_", " ")
            loc = info.get("printer-location")
            out.append((dest, f"{label}  —  {loc}" if loc else label))
        return out

    def default(self):
        m = re.search(r":\s*(\S+)", _run("lpstat", "-d").stdout)
        return m.group(1) if m else None

    def options(self, printer):
        """Every option of the printer's driver. Shared/network printers that don't answer raise
        PrinterUnreachable; fallback_options() then still lets the user queue a job."""
        opts = []
        for line in _run("lpoptions", "-p", printer, "-l").stdout.splitlines():
            if ":" not in line:
                continue
            head, values = line.split(":", 1)
            key, _, label = head.partition("/")
            choices, default = [], ""
            for v in values.split():
                if v.startswith("Custom."):
                    continue  # free-form sizes: not offered
                if v.startswith("*"):
                    v = v[1:]
                    default = v
                choices.append((v, v.replace("_", " ")))
            if key == "PageSize":
                choices = [(v, lbl) for v, lbl in choices if page_size_for(v) is not None]
            if choices:
                opts.append(Option(key, label or key, choices, default or choices[0][0]))
        return opts

    @staticmethod
    def fallback_options():
        sizes = ["Letter", "A4", "Legal", "A5", "4x6", "5x7"]
        return [Option("PageSize", "Media Size", [(s, s) for s in sizes], "Letter")]

    def submit(self, printer, page, dpi, s: SheetSettings, driver, header=None):
        """driver: -o values for the driver's own options, incl. its color/duplex keys (see describe())."""
        ps = page_size_for(s.paper) or QPageSize(QPageSize.Letter)
        pdf = Path(tempfile.mkdtemp(prefix="inkhue-print-")) / "Inkhue page.pdf"
        sheet.write_pdf(pdf, media.mono(page), dpi, ps, s, header)
        args = ["lp", "-d", printer, "-n", str(s.copies), "-t", "Inkhue page",
                "-o", "print-scaling=none", "-o", "fit-to-page=false", "-o", f"PageSize={s.paper}",
                "-o", f"print-color-mode={'color' if s.color else 'monochrome'}",
                "-o", f"sides={'two-sided-long-edge' if s.duplex else 'one-sided'}"]
        for k, v in driver.items():
            args += ["-o", f"{k}={v}"]
        r = _run(*args, str(pdf))
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "lp failed")
        m = re.search(r"request id is (\S+)", r.stdout)
        job = m.group(1) if m else "submitted"
        return job, self.job_note(printer, job)

    @staticmethod
    def job_note(printer, job):
        """Does the job need the user? Secure-print queues hold jobs for a sign-in or a release at the printer."""
        import time
        time.sleep(2.0)  # give CUPS a moment to talk to the printer / print server
        try:
            out = _run("lpstat", "-l", "-o", job).stdout.lower()
            info = _run("lpoptions", "-p", printer).stdout.lower()
        except PrinterUnreachable:
            return None
        if "authentication" in out or "auth-info-required" in out:
            return {"kind": "auth", "queue": printer}
        if any(k in info for k in ("pc-printer-discovery", "papercut", "release jobs", "secure print", "follow")):
            return {"kind": "release", "queue": printer}
        return None


# ---- Qt (Windows) ------------------------------------------------------------

class QtBackend:
    name = "Qt"

    @staticmethod
    def fallback_options():
        return CupsBackend.fallback_options()
    DUPLEX = {QPrinter.DuplexNone: "Off", QPrinter.DuplexAuto: "Auto", QPrinter.DuplexLongSide: "Long edge",
              QPrinter.DuplexShortSide: "Short edge"}

    def printers(self):
        return [(p.printerName(), p.description() or p.printerName()) for p in QPrinterInfo.availablePrinters()]

    def default(self):
        return QPrinterInfo.defaultPrinter().printerName() or None

    def options(self, printer):
        info = QPrinterInfo.printerInfo(printer)
        sizes = [(ps.key(), ps.name()) for ps in info.supportedPageSizes()] or [("Letter", "Letter"), ("A4", "A4")]
        opts = [Option("PageSize", "Paper size", sizes, info.defaultPageSize().key() or sizes[0][0])]
        res = [(str(r), f"{r} dpi") for r in sorted(set(info.supportedResolutions()))]
        if res:
            opts.append(Option("Resolution", "Resolution", res, "600" if "600" in dict(res) else res[-1][0]))
        if len(info.supportedDuplexModes()) > 1:
            opts.append(Option("Duplex", "Two-sided", [("None", "Off"), ("DuplexNoTumble", "Long edge")], "None"))
        if QPrinter.Color in info.supportedColorModes():
            opts.append(Option("ColorModel", "Color", [("Gray", "Gray"), ("RGB", "Color")], "Gray"))
        return opts

    def submit(self, printer, page, dpi, s: SheetSettings, driver, header=None):
        """Must run on the UI thread (QPrinter painting)."""
        info = QPrinterInfo.printerInfo(printer)
        ps = page_size_for(s.paper) or QPageSize(QPageSize.Letter)
        img = media.mono(page)
        pl = sheet.place(QSizeF(img.width() / dpi, img.height() / dpi), ps, s)
        pr = QPrinter(info, QPrinter.HighResolution)
        pr.setDocName("Inkhue page")
        pr.setFullPage(True)
        pr.setPageLayout(sheet.page_layout(ps, pl))
        if "Resolution" in driver:
            pr.setResolution(int(driver["Resolution"]))
        pr.setDuplex(QPrinter.DuplexLongSide if s.duplex else QPrinter.DuplexNone)
        pr.setColorMode(QPrinter.Color if s.color else QPrinter.GrayScale)
        pr.setCopyCount(s.copies)
        pr.setCollateCopies(True)
        p = QPainter(pr)
        if not p.isActive():
            raise RuntimeError("printer did not accept the job")
        sheet.paint(p, pr.resolution(), img, dpi, pl, s, header)
        p.end()
        return "sent"


PDF = "__pdf__"  # the "Save as PDF" destination
PDF_PAPERS = ["Letter", "A4", "Legal", "A5", "A3", "Tabloid", "4x6", "5x7", "8x10"]


@dataclass
class Capabilities:
    papers: list                      # [(value, label)]
    paper_default: str
    color: dict | None = None         # {"key": ..., False: bw value, True: color value} or None
    duplex: dict | None = None        # {"key": ..., False: off value, True: long-edge value} or None
    driver: list = field(default_factory=list)  # remaining driver options (Option)


def _pick(choices, *prefer):
    vals = [v for v, _ in choices]
    return next((p for p in prefer if p in vals), None)


def describe(options):
    """Turn a printer's option list into the panel's standard controls plus leftover driver options."""
    by = {o.key: o for o in options}
    page = by.get("PageSize") or Option("PageSize", "Paper", [(p, p) for p in PDF_PAPERS], "Letter")
    caps = Capabilities(page.choices, page.default)
    cm = by.get("ColorModel") or by.get("ColorMode")
    if cm:
        bw = _pick(cm.choices, "Gray", "DeviceGray", "Grayscale", "gray", "Mono", "Black")
        col = _pick(cm.choices, "RGB", "DeviceRGB", "CMYK", "Color", "color")
        if bw and col:
            caps.color = {"key": cm.key, False: bw, True: col}
    dp = by.get("Duplex")
    if dp:
        off = _pick(dp.choices, "None", "Off", "off")
        on = _pick(dp.choices, "DuplexNoTumble", "LongEdge", "long-edge")
        if off and on:
            caps.duplex = {"key": dp.key, False: off, True: on}
    caps.driver = [o for o in options if o.key not in STANDARD_KEYS]
    return caps


def pdf_capabilities():
    return Capabilities([(p, p) for p in PDF_PAPERS], "Letter", color=None, duplex=None)


def backend():
    if sys.platform != "win32" and shutil.which("lp") and shutil.which("lpoptions"):
        return CupsBackend()
    return QtBackend()


def system_dialog(parent, page, dpi, s: SheetSettings, header=None):
    """Secondary path: the operating system's own print dialog, with the page laid out the same way."""
    from dataclasses import replace

    from PySide6.QtGui import QPageLayout
    from PySide6.QtPrintSupport import QPrintDialog
    img = media.mono(page)
    page_in = QSizeF(img.width() / dpi, img.height() / dpi)
    ps = page_size_for(s.paper) or QPageSize(QPageSize.Letter)
    pr = QPrinter(QPrinter.HighResolution)
    pr.setDocName("Inkhue page")
    pr.setFullPage(True)
    pr.setPageLayout(sheet.page_layout(ps, sheet.place(page_in, ps, s)))
    pr.setCopyCount(s.copies)
    if QPrintDialog(pr, parent).exec() != QPrintDialog.Accepted:
        return False
    # the user may have picked other paper or orientation in the dialog: lay out again for that
    chosen = pr.pageLayout()
    s2 = replace(s, layout="landscape" if chosen.orientation() == QPageLayout.Landscape else "portrait")
    pl = sheet.place(page_in, chosen.pageSize(), s2)
    p = QPainter(pr)
    sheet.paint(p, pr.resolution(), img, dpi, pl, s2, header)
    p.end()
    return True


def open_pdf(page, dpi, s: SheetSettings, header=None):
    """Write the sheet as a PDF and open it in the system viewer (Preview on macOS)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    path = Path(tempfile.mkdtemp(prefix="inkhue-print-")) / "Inkhue page.pdf"
    sheet.write_pdf(path, media.mono(page), dpi, page_size_for(s.paper) or QPageSize(QPageSize.Letter), s, header)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    return path


def open_queue(printer):
    """Show the system print queue for `printer`, where the OS asks for the sign-in."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if sys.platform == "darwin":
        app = Path.home() / "Library" / "Printers" / f"{printer}.app"
        if app.exists():
            subprocess.Popen(["open", str(app)])
            return
        QDesktopServices.openUrl(QUrl("x-apple.systempreferences:com.apple.Print-Scan-Settings.extension"))
    elif sys.platform == "win32":
        subprocess.Popen(["rundll32", "printui.dll,PrintUIEntry", "/o", "/n", printer])
    else:
        QDesktopServices.openUrl(QUrl("http://localhost:631/jobs/"))
