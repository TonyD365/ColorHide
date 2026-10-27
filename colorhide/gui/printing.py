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

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from . import media


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


def _fits(page, dpi, ps):
    w, h = page.shape[1] / dpi, page.shape[0] / dpi
    pw, ph = ps.size(QPageSize.Inch).width(), ps.size(QPageSize.Inch).height()
    return (w <= pw and h <= ph) or (w <= ph and h <= pw)


def page_pdf(page, dpi, ps, path):
    """The page centred at 100% on paper `ps`, rotated to landscape if that is how it fits."""
    img = media.mono(page)
    w = QPdfWriter(str(path))
    w.setResolution(dpi)
    w.setCreator("ColorHide")
    orient = QPageLayout.Landscape if img.width() > img.height() else QPageLayout.Portrait
    w.setPageLayout(QPageLayout(ps, orient, QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    p.setRenderHint(QPainter.LosslessImageRendering)
    p.drawImage(media._centered(w.pageLayout().paintRectPixels(dpi), QSizeF(img.width(), img.height())), img)
    p.end()


# ---- CUPS --------------------------------------------------------------------

class PrinterUnreachable(RuntimeError):
    pass


def _run(*args, timeout=12):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as ex:
        raise PrinterUnreachable("printer not responding (offline or shared from a computer that is asleep)") from ex


class CupsBackend:
    name = "CUPS"

    def printers(self):
        out = []
        for dest in _run("lpstat", "-e").stdout.split():
            info = dict(kv.split("=", 1) for kv in shlex.split(_run("lpoptions", "-p", dest).stdout) if "=" in kv)
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

    def submit(self, printer, page, dpi, values, copies):
        ps = page_size_for(values.get("PageSize", "Letter")) or QPageSize(QPageSize.Letter)
        if not _fits(page, dpi, ps):
            raise ValueError("page is larger than the chosen paper; reduce the print width")
        pdf = Path(tempfile.mkdtemp(prefix="colorhide-print-")) / "ColorHide page.pdf"
        page_pdf(page, dpi, ps, pdf)
        args = ["lp", "-d", printer, "-n", str(copies), "-t", "ColorHide page",
                "-o", "print-scaling=none", "-o", "fit-to-page=false"]
        for k, v in values.items():
            args += ["-o", f"{k}={v}"]
        r = _run(*args, str(pdf))
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "lp failed")
        m = re.search(r"request id is (\S+)", r.stdout)
        return m.group(1) if m else "submitted"


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
            best = "600" if "600" in dict(res) else res[-1][0]
            opts.append(Option("Resolution", "Resolution", res, best))
        dup = [(self.DUPLEX[d].lower().replace(" ", "-"), self.DUPLEX[d]) for d in info.supportedDuplexModes()
               if d in self.DUPLEX]
        if len(dup) > 1:
            opts.append(Option("Duplex", "Two-sided", dup, "off"))
        colors = {QPrinter.GrayScale: ("gray", "Grayscale"), QPrinter.Color: ("color", "Color")}
        cm = [colors[c] for c in info.supportedColorModes() if c in colors]
        if cm:
            opts.append(Option("ColorMode", "Color mode", cm, "gray" if ("gray", "Grayscale") in cm else cm[0][0]))
        opts.append(Option("Collate", "Collate", [("true", "On"), ("false", "Off")], "true"))
        return opts

    def submit(self, printer, page, dpi, values, copies):
        info = QPrinterInfo.printerInfo(printer)
        ps = page_size_for(values.get("PageSize", "Letter")) or QPageSize(QPageSize.Letter)
        if not _fits(page, dpi, ps):
            raise ValueError("page is larger than the chosen paper; reduce the print width")
        pr = QPrinter(info, QPrinter.HighResolution)
        pr.setDocName("ColorHide page")
        img = media.mono(page)
        pr.setPageLayout(QPageLayout(ps, QPageLayout.Landscape if img.width() > img.height() else QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0)))
        if "Resolution" in values:
            pr.setResolution(int(values["Resolution"]))
        inv = {v.lower().replace(" ", "-"): k for k, v in self.DUPLEX.items()}
        pr.setDuplex(inv.get(values.get("Duplex", "off"), QPrinter.DuplexNone))
        pr.setColorMode(QPrinter.Color if values.get("ColorMode") == "color" else QPrinter.GrayScale)
        pr.setCopyCount(copies)
        pr.setCollateCopies(values.get("Collate", "true") == "true")
        res = pr.resolution()
        target = QSizeF(img.width() / dpi * res, img.height() / dpi * res)
        p = QPainter(pr)
        if not p.isActive():
            raise RuntimeError("printer did not accept the job")
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(media._centered(pr.pageLayout().fullRectPixels(res), target), img)
        p.end()
        return "sent"


def backend():
    if sys.platform != "win32" and shutil.which("lp") and shutil.which("lpoptions"):
        return CupsBackend()
    return QtBackend()
