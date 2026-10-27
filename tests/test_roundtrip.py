"""End-to-end: encode a synthetic photo, simulated print+scan, decode. Runs in CI before packaging."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide import api, channel  # noqa: E402


def _photo(h=200, w=300):
    y, x = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    rgb = np.stack([x, y, 1 - x * y], -1)
    rgb[60:140, 100:200] = [0.9, 0.2, 0.1]
    return (rgb * 255).astype(np.uint8)


def _roundtrip(refiner):
    rgb = _photo()
    page, _ = api.encode(rgb, width_in=2.5, dpi=600)
    scan = channel.print_scan(page, scale=2.0, seed=7)
    out, info = api.decode(scan, refiner)
    assert info["rs_ok"]
    small = lambda a: a.reshape(a.shape[0] // 10, 10, a.shape[1] // 10, 10, 3).mean((1, 3))
    import cv2
    ref = cv2.resize(rgb, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_AREA).astype(float)
    h, w = (out.shape[0] // 10) * 10, (out.shape[1] // 10) * 10
    err = np.abs(small(out[:h, :w].astype(float)) - small(ref[:h, :w])).mean()
    assert err < 25, err


def test_roundtrip_classic():
    _roundtrip(None)


def test_roundtrip_refiner():
    ref = api.load_refiner()
    if ref is not None:
        _roundtrip(ref)


if __name__ == "__main__":
    test_roundtrip_classic()
    test_roundtrip_refiner()
    print("roundtrip OK")


def test_pen_marks_on_image_and_frame():
    """Handwriting over the photo and strokes across the frame / timing track still decode."""
    rgb = _photo(300, 450)
    page, _ = api.encode(rgb, width_in=4.0, dpi=600)
    for seed in (0, 1):
        marked = channel.scribble(page, np.random.default_rng(seed))
        _, info = api.decode(channel.print_scan(marked, seed=seed), None)
        assert info["rs_ok"]
