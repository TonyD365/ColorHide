"""End-to-end: encode a synthetic photo, simulated print+scan, decode. Runs in CI before packaging."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inkhue import api, channel  # noqa: E402


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


def test_clear_errors_for_plain_pages_and_coarse_scans():
    import cv2
    import pytest
    plain = np.full((1100, 850), 255, np.uint8)
    cv2.rectangle(plain, (60, 60), (790, 1040), 0, 4)  # an ordinary document with a box on it
    cv2.putText(plain, "Hello", (200, 400), cv2.FONT_HERSHEY_SIMPLEX, 3, 0, 6)
    with pytest.raises(api.NoHiddenColor, match="No hidden color"):
        api.decode(plain, None)
    page, _ = api.encode(_photo(), width_in=2.5, dpi=600)
    coarse = channel.print_scan(page, scale=0.3, seed=1)  # ~180 dpi
    with pytest.raises(api.NoHiddenColor, match="about 1[0-9]{2} dpi"):
        api.decode(coarse, None)


def test_mostly_white_document_decodes():
    """A text document is mostly white paper; every cell must still carry data (1..15 dots)."""
    import cv2
    doc = np.full((600, 450, 3), 255, np.uint8)
    for i in range(12):
        cv2.putText(doc, "The parts of a paragraph", (20, 40 + 45 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
    cv2.rectangle(doc, (20, 300), (200, 330), (120, 230, 120), -1)  # a highlighter mark
    page, _ = api.encode(doc, width_in=3.5, dpi=600)
    out, info = api.decode(channel.print_scan(page, seed=2), None)
    assert info["rs_ok"]
    assert out[5:40, 300:440].mean() > 235  # white paper comes back white, not tinted gray


def test_upside_down_and_sideways_scans():
    page, _ = api.encode(_photo(), width_in=2.5, dpi=600)
    scan = channel.print_scan(page, seed=3)
    for turns in (1, 2, 3):
        _, info = api.decode(np.ascontiguousarray(np.rot90(scan, turns)), None)
        assert info["rs_ok"], turns


def test_photos_keep_full_contrast_documents_get_ink_floor():
    from inkhue import codec
    _, info = codec.encode(_photo() / 255.0, factor=8)
    assert not info["ink_floor"]
    _, info = codec.encode(np.ones((200, 300, 3)), factor=8)
    assert info["ink_floor"]
