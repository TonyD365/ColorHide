"""Lay out a Inkhue page on a sheet of paper and paint it. One code path for the printer, for
"Save as PDF" and for the live preview, so the preview is exactly what comes out."""
from dataclasses import dataclass, field

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

MARGINS_IN = {"default": 0.4, "minimum": 0.25, "none": 0.0}
GRIDS = {1: [(1, 1)], 2: [(2, 1), (1, 2)], 4: [(2, 2)]}  # (columns, rows) to try


@dataclass
class SheetSettings:
    paper: str = "Letter"        # media name, as CUPS / the driver calls it
    layout: str = "auto"         # auto | portrait | landscape
    margins: str = "default"     # default | minimum | none
    scale: str = "actual"        # actual | fit | custom
    custom_scale: int = 100      # percent, for scale == "custom"
    per_sheet: int = 1           # 1, 2 or 4 copies of the page on one sheet
    headers: bool = True         # title/date and a scanning hint in the margins
    color: bool = False
    duplex: bool = False
    copies: int = 1


@dataclass
class Placement:
    paper_in: QSizeF                              # oriented sheet size, inches
    landscape: bool
    scale: float                                  # 1.0 = the printer dots land 1:1
    rects_in: list = field(default_factory=list)  # where each copy of the page goes, inches
    margin_in: float = 0.0


def place(page_in: QSizeF, ps: QPageSize, s: SheetSettings) -> Placement:
    """Find where the page(s) go. Raises ValueError if they don't fit at the requested scale."""
    size = ps.size(QPageSize.Inch)
    short, long_ = min(size.width(), size.height()), max(size.width(), size.height())
    m = MARGINS_IN[s.margins]
    if s.layout == "auto":
        wide = page_in.width() > page_in.height()
        if s.per_sheet == 2:
            wide = not wide  # two copies sit side by side best on the other orientation
        orients = [wide, not wide]
    else:
        orients = [s.layout == "landscape"]
    best = None
    for landscape in orients:
        W, H = (long_, short) if landscape else (short, long_)
        aw, ah = W - 2 * m, H - 2 * m
        for cols, rows in GRIDS[s.per_sheet]:
            cw, ch = aw / cols, ah / rows
            fit = min(cw / page_in.width(), ch / page_in.height())
            k = {"actual": 1.0, "fit": fit, "custom": s.custom_scale / 100}[s.scale]
            if k > fit + 1e-6:
                continue
            pw, ph = page_in.width() * k, page_in.height() * k
            rects = [QRectF(m + c * cw + (cw - pw) / 2, m + r * ch + (ch - ph) / 2, pw, ph)
                     for r in range(rows) for c in range(cols)]
            cand = Placement(QSizeF(W, H), landscape, k, rects, m)
            if s.scale != "fit":
                return cand  # first orientation / arrangement that fits, in order of preference
            if best is None or k > best.scale:
                best = cand
    if best is None:
        raise ValueError("doesn't fit on this paper at this scale — use a smaller print width, "
                         "fewer pages per sheet, smaller margins or bigger paper")
    return best


def header_lines(title, version, date):
    return (date, title), (f"Scan in grayscale at 1200 dpi to reveal the color · Inkhue v{version}", "1/1")


def paint(p: QPainter, res, img: QImage, img_dpi, pl: Placement, s: SheetSettings, header=None, smooth=False):
    """Paint the sheet at `res` device pixels per inch. img is the page at img_dpi."""
    p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
    p.setRenderHint(QPainter.LosslessImageRendering)
    for r in pl.rects_in:
        p.drawImage(QRectF(r.x() * res, r.y() * res, r.width() * res, r.height() * res), img)
    if s.headers and header and pl.margin_in >= 0.2:
        (tl, tc), (bl, br) = header
        f = QFont()
        f.setPixelSize(max(1, round(0.09 * res)))
        p.setFont(f)
        p.setPen(Qt.black)
        band = pl.margin_in * res
        W, H = pl.paper_in.width() * res, pl.paper_in.height() * res
        pad = 0.25 * res
        top = QRectF(pad, 0, W - 2 * pad, band)
        bottom = QRectF(pad, H - band, W - 2 * pad, band)
        p.drawText(top, Qt.AlignLeft | Qt.AlignVCenter, tl)
        p.drawText(top, Qt.AlignHCenter | Qt.AlignVCenter, tc)
        p.drawText(bottom, Qt.AlignLeft | Qt.AlignVCenter, bl)
        p.drawText(bottom, Qt.AlignRight | Qt.AlignVCenter, br)


def page_layout(ps: QPageSize, pl: Placement):
    return QPageLayout(ps, QPageLayout.Landscape if pl.landscape else QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))


def write_pdf(path, img: QImage, dpi, ps: QPageSize, s: SheetSettings, header=None):
    """The sheet as a PDF (lossless 1-bit page image). Returns the placement used."""
    pl = place(QSizeF(img.width() / dpi, img.height() / dpi), ps, s)
    w = QPdfWriter(str(path))
    w.setResolution(dpi)
    w.setCreator("Inkhue")
    w.setTitle("Inkhue page")
    w.setPageLayout(page_layout(ps, pl))
    p = QPainter(w)
    paint(p, dpi, img, dpi, pl, s, header)
    p.end()
    return pl


def preview(img_thumb: QImage, thumb_dpi, page_in: QSizeF, ps: QPageSize, s: SheetSettings, res, header=None):
    """The sheet as an image at `res` pixels per inch (for the on-screen preview)."""
    pl = place(page_in, ps, s)
    out = QImage(round(pl.paper_in.width() * res), round(pl.paper_in.height() * res), QImage.Format_RGB32)
    out.fill(Qt.white)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    paint(p, res, img_thumb, thumb_dpi, pl, s, header, smooth=True)
    p.end()
    return out, pl



def fill_width(aspect, ps: QPageSize, dpi, margins="default"):
    """Largest print width (inches, frame included) at which a photo of `aspect` (height / width)
    fits on `ps` at 100 % within the margins, choosing portrait or landscape, whichever is bigger."""
    from ..halftone import K
    from ..layout import QUIET, B
    frame = 2 * (B + QUIET) * K / dpi  # frame + quiet zone, inches, both sides together
    size = ps.size(QPageSize.Inch)
    m = 2 * MARGINS_IN[margins]
    best = 0.0
    for aw, ah in ((size.width() - m, size.height() - m), (size.height() - m, size.width() - m)):
        w = min(aw, (ah - frame) / aspect + frame)
        if (w - frame) * aspect * w > (best - frame) * aspect * best:
            best = w
    step = 0.05  # round down so rounding of cells never pushes the page over the edge
    return max(2.0, int((best - 0.01) / step) * step)
