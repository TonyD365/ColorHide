"""Drives the real app window headless (Qt offscreen): feed a photo, simulated print+scan, decode,
export, and open the print panel. Runs on all three OSes in CI."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _wait(app, cond, timeout=120):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, "timed out"
        app.processEvents()
        time.sleep(0.05)


def test_app_cycle(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from colorhide.gui import media
    from colorhide.gui.main import Printer
    from colorhide.gui.printpanel import PrintPanel

    y, x = np.mgrid[0:240, 0:360] / np.array([240, 360])[:, None, None]
    photo = tmp_path / "photo.png"
    cv2.imwrite(str(photo), (np.stack([1 - x, y, x * y], -1) * 255).astype(np.uint8))

    w = Printer()
    w.show()
    w.width_in.setValue(2.5)
    w.feed(str(photo))
    _wait(app, lambda: w.page is not None and not w.busy)
    assert "PAGE READY" in w.lcd.text()

    media.export_pdf(w.page, w.page_dpi, "US Letter", tmp_path / "page.pdf")
    assert media.read_image(tmp_path / "page.pdf", gray=True).shape[0] > 1000

    w.test_cycle()
    _wait(app, lambda: w.color is not None and not w.busy)
    assert "COLOR RESTORED" in w.lcd.text()

    for ext in ("png", "jpg", "pdf"):
        media.save_color(w.color, tmp_path / f"out.{ext}")
        assert (tmp_path / f"out.{ext}").stat().st_size > 1000

    from colorhide.gui.viewer import Viewer
    v = Viewer(w, media.gray_to_qimage(w.page), "page")  # full-resolution zoom view
    v.show()
    v.view.zoom(4.0)
    app.processEvents()
    v.close()

    panel = PrintPanel(w, w.page, w.page_dpi, lambda *_: None)  # lists printers; CI machines may have none
    panel.show()
    app.processEvents()
    panel.close()
    w.close()
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(30000)  # let background jobs (printer queries) finish
