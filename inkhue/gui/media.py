"""Paper in and out: PDF export, PDF/image import, colour export. Qt only, so it is the same
code on macOS, Windows and Linux. Printing lives in printing.py."""
import cv2
import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

PAPERS = {"Actual size": None, "US Letter": QPageSize.Letter, "A4": QPageSize.A4}


# ---- numpy <-> QImage -------------------------------------------------------

def gray_to_qimage(a):
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_Grayscale8).copy()


def rgb_to_qimage(a):
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_RGB888).copy()


def qimage_to_array(img, gray):
    img = img.convertToFormat(QImage.Format_Grayscale8 if gray else QImage.Format_RGB888)
    ch = 1 if gray else 3
    ptr = img.constBits()
    a = np.frombuffer(ptr, np.uint8, img.bytesPerLine() * img.height()).reshape(img.height(), img.bytesPerLine())
    return a[:, : img.width() * ch].reshape(img.height(), img.width(), *(() if gray else (3,))).copy()


def mono(page):
    """1-bit image: PDF writers and print spoolers keep it lossless (no JPEG over the dots)."""
    return gray_to_qimage(page).convertToFormat(QImage.Format_Mono, Qt.ThresholdDither | Qt.MonoOnly)


# ---- reading ----------------------------------------------------------------

def read_image(path, gray):
    if str(path).lower().endswith(".pdf"):
        return render_pdf(path, dpi=1200 if gray else 300, gray=gray)
    data = np.fromfile(str(path), np.uint8)  # np.fromfile + imdecode handles non-ASCII paths on Windows
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot read this image")
    return img if gray else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def render_pdf(path, dpi, gray, max_pixels=250e6):
    """Rasterize page 1 in horizontal strips so a 1200 dpi page never needs a giant RGBA buffer."""
    doc = QPdfDocument()
    if doc.load(str(path)) != QPdfDocument.Error.None_ or doc.pageCount() < 1:
        raise ValueError("cannot open PDF")
    pts = doc.pagePointSize(0)
    scale = dpi / 72
    if pts.width() * pts.height() * scale * scale > max_pixels:
        scale = (max_pixels / (pts.width() * pts.height())) ** 0.5
    W, H = int(pts.width() * scale), int(pts.height() * scale)
    out = np.empty((H, W) if gray else (H, W, 3), np.uint8)
    strip = 1024
    for y in range(0, H, strip):
        h = min(strip, H - y)
        opts = QPdfDocumentRenderOptions()
        opts.setScaledSize(QSize(W, H))
        opts.setScaledClipRect(QRect(0, y, W, h))
        img = doc.render(0, QSize(W, h), opts)
        # transparent page areas render as black; paint onto white first
        bg = QImage(img.size(), QImage.Format_RGB32)
        bg.fill(0xFFFFFFFF)
        p = QPainter(bg)
        p.drawImage(0, 0, img)
        p.end()
        out[y:y + h] = qimage_to_array(bg, gray)
    doc.close()
    return out


# ---- writing ----------------------------------------------------------------

def _centered(area, size):
    return QRectF(QPointF((area.width() - size.width()) / 2, (area.height() - size.height()) / 2), size)


def _place(page_px, dpi, target_dpi):
    return QSizeF(page_px.width() / dpi * target_dpi, page_px.height() / dpi * target_dpi)


def export_pdf(page, dpi, paper, path):
    """Page at its exact physical size, centred on the chosen paper."""
    img = mono(page)
    size_in = QSizeF(img.width() / dpi, img.height() / dpi)
    w = QPdfWriter(str(path))
    w.setResolution(dpi)
    w.setCreator("Inkhue")
    w.setTitle("Inkhue page")
    if PAPERS[paper] is None:
        ps = QPageSize(size_in, QPageSize.Inch, "Inkhue", QPageSize.ExactMatch)
        orient = QPageLayout.Portrait
    else:
        ps = QPageSize(PAPERS[paper])
        paper_in = ps.size(QPageSize.Inch)
        orient = QPageLayout.Landscape if size_in.width() > size_in.height() else QPageLayout.Portrait
        long_, short = max(paper_in.width(), paper_in.height()), min(paper_in.width(), paper_in.height())
        fit = (size_in.width() <= (long_ if orient == QPageLayout.Landscape else short) and
               size_in.height() <= (short if orient == QPageLayout.Landscape else long_))
        if not fit:
            raise ValueError(f"page is larger than {paper}; reduce the print width")
    w.setPageLayout(QPageLayout(ps, orient, QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    p.setRenderHint(QPainter.LosslessImageRendering)  # PDF output (export, Linux/CUPS printing): no JPEG
    area = w.pageLayout().paintRectPixels(dpi)
    target = _place(img.size(), dpi, dpi)
    p.drawImage(_centered(area, target), img)
    p.end()


# ---- saving the recovered color image -----------------------------------------

# (label, extensions) in menu order; only formats this platform's Qt can write are offered
COLOR_FORMATS = [("PDF document", ["pdf"]), ("PNG image", ["png"]), ("JPEG image", ["jpg", "jpeg"]),
                 ("TIFF image", ["tif", "tiff"]), ("WebP image", ["webp"]), ("HEIC image", ["heic"]),
                 ("JPEG 2000 image", ["jp2"]), ("BMP image", ["bmp"]), ("PPM image", ["ppm"])]


def color_save_filters():
    from PySide6.QtGui import QImageWriter
    can = {bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()} | {"pdf"}
    return [f"{label} ({' '.join('*.' + e for e in exts)})" for label, exts in COLOR_FORMATS if exts[0] in can]


def save_color(rgb, path, paper="Actual size", ppi=150):
    """Save the decoded photo. ppi=150 is one cell per pixel at 600 dpi, i.e. the original printed size."""
    ext = str(path).rsplit(".", 1)[-1].lower()
    img = rgb_to_qimage(rgb)
    if ext != "pdf":
        if not img.save(str(path), None, 95):
            raise ValueError(f"cannot save .{ext} on this system")
        return
    size_in = QSizeF(img.width() / ppi, img.height() / ppi)
    w = QPdfWriter(str(path))
    w.setResolution(ppi)
    w.setCreator("Inkhue")
    w.setTitle("Inkhue recovered color")
    if PAPERS[paper] is None:
        w.setPageLayout(QPageLayout(QPageSize(size_in, QPageSize.Inch, "Inkhue", QPageSize.ExactMatch),
                                    QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    else:
        orient = QPageLayout.Landscape if img.width() > img.height() else QPageLayout.Portrait
        w.setPageLayout(QPageLayout(QPageSize(PAPERS[paper]), orient, QMarginsF(36, 36, 36, 36)))
    area = w.pageLayout().paintRectPixels(ppi)
    target = QSizeF(img.width(), img.height())
    s = min(1.0, area.width() / target.width(), area.height() / target.height())  # shrink only if it must
    target *= s
    p = QPainter(w)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.LosslessImageRendering)
    p.drawImage(_centered(area, target), img)
    p.end()
