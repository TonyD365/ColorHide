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
    from inkhue.gui import media
    from inkhue.gui.main import Printer
    from inkhue.gui.printpanel import PrintPanel

    y, x = np.mgrid[0:240, 0:360] / np.array([240, 360])[:, None, None]
    photo = tmp_path / "photo.png"
    cv2.imwrite(str(photo), (np.stack([1 - x, y, x * y], -1) * 255).astype(np.uint8))

    w = Printer()
    w.show()
    w.fill.setChecked(False)  # a small page keeps the test fast; "fill the paper" would print it Letter-sized
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

    from inkhue.gui.viewer import Viewer
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


def test_multipage_pdf(tmp_path, monkeypatch):
    """Every page of a PDF is converted, printed to PDF and revealed; long PDFs ask first."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from inkhue.gui import main, media
    from inkhue.gui.main import Printer

    y, x = np.mgrid[0:240, 0:360] / np.array([240, 360])[:, None, None]
    photos = [(np.stack([1 - x, y, x * y], -1) * 255).astype(np.uint8),
              (np.stack([x, 1 - y, y], -1) * 255).astype(np.uint8)]
    src = tmp_path / "two.pdf"
    media.save_color(photos, src)
    assert media.page_count(src) == 2

    w = Printer()
    w.fill.setChecked(False)
    w.width_in.setValue(2.5)
    w.feed(str(src))
    _wait(app, lambda: len(w.pages) == 2 and not w.busy)
    assert "2 PAGES" in w.lcd.text()
    media.export_pdf(w.pages, w.page_dpi, "US Letter", tmp_path / "pages.pdf")
    assert media.page_count(tmp_path / "pages.pdf") == 2

    w.test_cycle()
    _wait(app, lambda: len(w.colors) == 2 and not w.busy)
    assert "ALL 2 PAGES" in w.lcd.text()
    w.turn(1)
    assert w.at == 1 and "2 OF 2" in w.tray_out.paper.caption
    media.save_color(w.colors, tmp_path / "out.png")
    assert (tmp_path / "out-1.png").exists() and (tmp_path / "out-2.png").exists()

    monkeypatch.setattr(main, "MANY_PAGES", 1)  # pretend two pages is a lot, and say Cancel
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda box: asked.append(box.text()))
    assert w.count_pages(str(src)) is None and "2 pages" in asked[0]
    w.close()
