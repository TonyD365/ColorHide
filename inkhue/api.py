"""In-process API used by the GUI: numpy arrays in, numpy arrays out."""
import sys
from pathlib import Path

import cv2
import numpy as np

from . import codec, halftone, layout

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(getattr(sys, "_MEIPASS", ROOT))  # PyInstaller unpacks data under _MEIPASS
MODELS = BASE / "models"
ICON = BASE / "assets" / "icon.png"


def find_refiner():
    for name in ("refiner.onnx", "refiner.pt"):
        if (MODELS / name).exists():
            return MODELS / name
    return None


def load_refiner(path=None):
    """ONNX model (shipped in releases) preferred; PyTorch checkpoint as a developer fallback."""
    p = Path(path) if path else find_refiner()
    if p is None or not p.exists():
        return None
    if p.suffix == ".onnx":
        from .refiner_onnx import load
    else:
        from .refiner import load
    return load(p)


def encode(rgb_u8, width_in=6.0, dpi=600, factor=8, detail=True):
    """Color photo (h,w,3 uint8) -> bilevel page (uint8, 0 ink / 255 paper) at `dpi`, and info.
    detail: place dots from the photo at full printer resolution (sharper print, same decoder)."""
    cells_w = int(width_in * dpi / halftone.K) - 2 * (layout.B + layout.QUIET)
    if cells_w < 64:
        raise ValueError("print width too small")
    h, w = rgb_u8.shape[:2]
    cells_h = max(64, round(h * cells_w / w))
    img = cv2.resize(rgb_u8, (cells_w, cells_h), interpolation=cv2.INTER_AREA).astype(np.float64) / 255
    luma = None
    if detail:
        k = halftone.K
        interp = cv2.INTER_AREA if w >= cells_w * k else cv2.INTER_CUBIC
        hi = cv2.resize(rgb_u8, (cells_w * k, cells_h * k), interpolation=interp).astype(np.float64) / 255
        luma = np.clip(codec.rgb_to_ycbcr(hi)[..., 0], 0, 1)
    page, info = codec.encode(img, factor=factor, luma_detail=luma)
    return page, dict(dpi=dpi, width_in=page.shape[1] / dpi, height_in=page.shape[0] / dpi,
                      cells=(cells_w, cells_h), reps=info["reps"])


class NoHiddenColor(ValueError):
    """The scan carries no Inkhue data: not a page printed by Inkhue, or its frame is cut off or damaged."""


NO_COLOR = ("No hidden color found on this page. Only pages made with Inkhue carry their color: load the "
            "original in HIDE COLOR, print the black-and-white page it makes, then scan that at 600 dpi "
            "(at least 400). "
            "If it is such a page, keep its whole black frame inside the scan and print it at 100 %.")


def decode(gray_u8, refiner=None):
    """Scanned page (uint8 gray) -> color image (h,w,3 uint8) and info. Raises NoHiddenColor."""
    try:
        rgb, info = codec.decode(gray_u8, refiner=refiner)
    except layout.ScanTooCoarse as ex:
        raise NoHiddenColor(f"{NO_COLOR} (This scan looks like only about {ex.dpi} dpi.)") from ex
    except (ValueError, cv2.error) as ex:
        raise NoHiddenColor(NO_COLOR) from ex
    info = {k: (int(v) if isinstance(v, np.integer) else v) for k, v in info.items()}
    info["cells"] = tuple(int(x) for x in info["cells"])
    return (rgb * 255).round().astype(np.uint8), info
