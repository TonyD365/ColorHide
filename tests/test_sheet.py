"""Sheet layout used by the print panel, Save as PDF and the preview."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")
from PySide6.QtCore import QSizeF
from PySide6.QtGui import QPageSize

from colorhide.gui import sheet

LETTER = QPageSize(QPageSize.Letter)


def place(w, h, **kw):
    return sheet.place(QSizeF(w, h), LETTER, sheet.SheetSettings(**kw))


def test_actual_size_is_100_percent_and_centred():
    pl = place(6.0, 4.0)
    assert pl.scale == 1.0 and pl.landscape  # a wide page goes landscape on Auto
    r = pl.rects_in[0]
    assert abs(r.center().x() - 5.5) < 1e-9 and abs(r.center().y() - 4.25) < 1e-9


def test_too_big_at_100_percent_is_an_error_not_a_silent_shrink():
    with pytest.raises(ValueError):
        place(12.0, 9.0)


def test_pages_per_sheet():
    assert len(place(3.5, 2.4, per_sheet=2).rects_in) == 2
    pl = place(3.5, 2.4, per_sheet=4)
    assert len(pl.rects_in) == 4 and pl.scale == 1.0
    boxes = [(r.left(), r.top(), r.right(), r.bottom()) for r in pl.rects_in]
    for i, a in enumerate(boxes):  # copies never overlap
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_fit_and_custom_scale():
    pl = place(3.0, 2.0, scale="fit", margins="none")
    assert abs(pl.scale - 11.0 / 3.0) < 1e-9  # landscape Letter is 11 in wide
    assert place(3.0, 2.0, scale="custom", custom_scale=50).scale == 0.5


def test_margins_and_layout():
    assert place(6.0, 4.0, layout="portrait").landscape is False
    assert place(8.0, 5.0, margins="none").rects_in[0].left() > place(8.0, 5.0).rects_in[0].left() - 1


def test_pdf_round_trip(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import numpy as np

    from colorhide import api
    from colorhide.gui import media
    y, x = np.mgrid[0:150, 0:220] / np.array([150, 220])[:, None, None]
    page, _ = api.encode((np.stack([x, y, 1 - x], -1) * 255).astype(np.uint8), width_in=2.5, dpi=600)
    s = sheet.SheetSettings(per_sheet=2)
    sheet.write_pdf(tmp_path / "p.pdf", media.mono(page), 600, LETTER, s, sheet.header_lines("t", "1", "d"))
    assert api.decode(media.read_image(tmp_path / "p.pdf", gray=True), None)[1]["rs_ok"]
