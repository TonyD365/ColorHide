"""Color image <-> black-and-white page that hides its own color."""
import cv2
import numpy as np

from . import halftone, layout, payload
from .color import rgb_to_ycbcr, ycbcr_to_rgb


def encode(rgb, factor=4, qbits=6):
    """rgb: float (h,w,3) in [0,1], one image pixel per halftone cell.
    Returns the bilevel page (uint8, 0 = ink, 255 = paper) and info."""
    h, w, _ = rgb.shape
    ycc = rgb_to_ycbcr(rgb)
    ch, cw = payload.chroma_shape(h, w, factor)
    small = cv2.resize(ycc[..., 1:], (cw, ch), interpolation=cv2.INTER_AREA)
    q = payload.quantize(small.transpose(2, 0, 1), qbits)
    bits, reps = payload.encode_bits(q, factor, qbits, h * w * 2)
    xbit, ybit = bits[0::2].reshape(h, w), bits[1::2].reshape(h, w)
    levels = halftone.luma_to_levels(ycc[..., 0])
    ink = halftone.render(levels, ybit * 2 + xbit)
    page = layout.compose(ink, h, w)
    return (255 - page * 255).astype(np.uint8), dict(reps=reps, chroma=(ch, cw))


def baseline_luma(dots):
    """Per-cell ink fraction -> luma: the eye's own low-pass, done explicitly."""
    return np.clip(1.0 - cv2.GaussianBlur(dots, (0, 0), 1.0), 0, 1)


def demodulate(gray):
    """Scan -> (ink fraction per cell (h,w), soft bits (h*w*2,), h, w)."""
    dark, h, w = layout.locate(gray)
    n, sx, sy = halftone.measure(dark, h, w)
    # remove slowly varying centroid bias left by sub-dot misregistration
    sx = sx - cv2.GaussianBlur(sx, (0, 0), 6)
    sy = sy - cv2.GaussianBlur(sy, (0, 0), 6)
    soft = np.empty(h * w * 2)
    soft[0::2], soft[1::2] = sx.ravel(), sy.ravel()
    return n / halftone.LEVELS, soft, h, w


def decode(gray, refiner=None):
    """gray: uint8 scan. refiner: optional callable (dots, small chroma) -> rgb.
    Returns rgb float (h,w,3) and info."""
    dots, soft, h, w = demodulate(gray)
    small, info = payload.decode_soft(soft, h, w)
    if refiner is not None:
        return refiner(dots, small), info
    cbcr = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return ycbcr_to_rgb(np.dstack([baseline_luma(dots), cbcr])), info
