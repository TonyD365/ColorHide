"""Color image <-> black-and-white page that hides its own color."""
import cv2
import numpy as np

from . import halftone, layout, payload
from .color import rgb_to_ycbcr, ycbcr_to_rgb

FLOOR_ABOVE = 0.2  # share of empty/full cells above which every cell keeps 1..15 dots


def encode(rgb, factor=4, qbits=6, luma_detail=None, margin=0.45):
    """rgb: float (h,w,3) in [0,1], one image pixel per halftone cell.
    luma_detail: optional (h*K, w*K) luma at printer-dot resolution; dots are then placed to show
    detail inside each cell (see halftone.render_detail). Returns the bilevel page
    (uint8, 0 = ink, 255 = paper) and info."""
    h, w, _ = rgb.shape
    ycc = rgb_to_ycbcr(rgb)
    ch, cw = payload.chroma_shape(h, w, factor)
    small = cv2.resize(ycc[..., 1:], (cw, ch), interpolation=cv2.INTER_AREA)
    q = payload.quantize(small.transpose(2, 0, 1), qbits)
    # Cells with 0 or 16 dots carry no data. Photos have few, so they keep the full 0..16 range (best
    # contrast); documents (mostly white paper) and very dark images switch to 1..15 dots per cell.
    plain = halftone.luma_to_levels(ycc[..., 0], floor=False)
    floor = np.mean((plain == 0) | (plain == halftone.LEVELS)) > FLOOR_ABOVE
    flags = payload.FLAG_INK_FLOOR if floor else 0
    bits, reps = payload.encode_bits(q, factor, qbits, h * w * 2, flags=flags)
    xbit, ybit = bits[0::2].reshape(h, w), bits[1::2].reshape(h, w)
    levels = halftone.luma_to_levels(ycc[..., 0], floor=True) if floor else plain
    if luma_detail is None:
        ink = halftone.render(levels, ybit * 2 + xbit)
    else:
        ink = halftone.render_detail(levels, ybit * 2 + xbit, 1.0 - luma_detail, margin=margin)
    page = layout.compose(ink, h, w)
    return (255 - page * 255).astype(np.uint8), dict(reps=reps, chroma=(ch, cw), ink_floor=bool(floor))


def baseline_luma(dots):
    """Per-cell ink fraction -> luma: the eye's own low-pass, done explicitly."""
    return np.clip(1.0 - cv2.GaussianBlur(dots, (0, 0), 1.0), 0, 1)


def demodulate(gray):
    """Scan -> (ink fraction per cell (h,w), soft bits (h*w*2,), h, w)."""
    _, dots, soft, h, w = demodulate_full(gray)
    return dots, soft, h, w


def _soft_bits(dark, h, w):
    n, sx, sy = halftone.measure(dark, h, w)
    # remove slowly varying centroid bias left by sub-dot misregistration
    sx = sx - cv2.GaussianBlur(sx, (0, 0), 6)
    sy = sy - cv2.GaussianBlur(sy, (0, 0), 6)
    soft = np.empty(h * w * 2)
    soft[0::2], soft[1::2] = sx.ravel(), sy.ravel()
    return n, soft


def demodulate_full(gray):
    """Like demodulate(), plus the ink map at printer-dot resolution (h*K, w*K) for refiners that
    read detail inside the cells. If the estimated grid size does not yield a valid header (a pen
    stroke across the frame can fool the count), neighbouring sizes are tried; if the page still
    reads as nothing, the scan is tried turned by 90, 180 and 270 degrees (paper put in sideways or
    upside down)."""
    first, err = None, None
    for turns in range(4):
        img = np.rot90(gray, turns) if turns else gray
        try:
            frame = layout.find_frame(np.ascontiguousarray(img))
        except ValueError as ex:
            err = err or ex
            continue
        for W, H in frame.candidates():
            dark, h, w = layout.sample(img, frame, W, H)
            n, soft = _soft_bits(dark, h, w)
            if first is None:
                first = (dark, n, soft, h, w)
            if payload.has_header(soft):
                return dark, n / halftone.LEVELS, soft, h, w
    if first is None:
        raise err
    dark, n, soft, h, w = first  # nothing verified: hand back the best guess, decoding reports the error
    return dark, n / halftone.LEVELS, soft, h, w


def _clean_paper(rgb):
    """Paper is white: fade the color out over the last few percent of brightness, so tiny chroma noise
    doesn't tint blank paper. Light colors (a yellow highlighter is ~0.9) are untouched."""
    ycc = rgb_to_ycbcr(rgb)
    ycc[..., 1:] *= np.clip((1.0 - ycc[..., :1]) / 0.05, 0.0, 1.0)
    return ycbcr_to_rgb(ycc)


def decode(gray, refiner=None):
    """gray: uint8 scan. refiner: optional callable (dots, small chroma[, grid]) -> rgb; refiners
    with `uses_grid` also get the dot-resolution ink map and may return a larger image.
    Returns rgb float (h,w,3) or (s*h, s*w, 3) and info."""
    grid, dots, soft, h, w = demodulate_full(gray)
    small, info = payload.decode_soft(soft, h, w)
    info["cells"] = (w, h)
    floor = bool(info.get("flags", 0) & payload.FLAG_INK_FLOOR)
    if refiner is not None:
        rgb = refiner(dots, small, grid) if getattr(refiner, "uses_grid", False) else refiner(dots, small)
        if floor:  # the refiner reads brightness as 0..16 dots; rescale to the 1..15 range actually printed
            ycc = rgb_to_ycbcr(rgb)
            ycc[..., 0] = halftone.floor_to_luma(ycc[..., 0])
            rgb = ycbcr_to_rgb(ycc)
        return _clean_paper(rgb), info
    y = baseline_luma(dots)
    cbcr = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return _clean_paper(ycbcr_to_rgb(np.dstack([halftone.floor_to_luma(y) if floor else y, cbcr]))), info
