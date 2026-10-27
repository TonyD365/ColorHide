"""Regenerate the README pictures: assets/compare.png and assets/screenshot.png.
Uses scikit-image's CC0 sample photo, the simulated print/scan channel and the shipped refiner.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from skimage import data  # noqa: E402

from colorhide import api, channel  # noqa: E402

ASSETS = ROOT / "assets"


def font(size):
    for name in ["/System/Library/Fonts/SFNSRounded.ttf", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def compare():
    rgb = data.coffee()
    page, _ = api.encode(rgb, width_in=4.0, dpi=600)
    scan = channel.print_scan(page, scale=2.0, seed=11)
    out, info = api.decode(scan, api.load_refiner())
    assert info["rs_ok"]
    H = 420
    fit = lambda a: cv2.resize(a, (round(a.shape[1] * H / a.shape[0]), H), interpolation=cv2.INTER_AREA)
    orig = fit(rgb)
    ys, xs = np.where(page < 128)  # crop to the frame, show it the way the eye sees it
    printed = page[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    printed = cv2.cvtColor(fit(printed), cv2.COLOR_GRAY2RGB)
    # magnifier: the actual dots
    cy, cx = page.shape[0] // 2, page.shape[1] // 2
    zoom = cv2.resize(page[cy - 40:cy + 40, cx - 40:cx + 40], (150, 150), interpolation=cv2.INTER_NEAREST)
    zoom = cv2.copyMakeBorder(cv2.cvtColor(zoom, cv2.COLOR_GRAY2RGB), 3, 3, 3, 3, cv2.BORDER_CONSTANT,
                              value=(238, 107, 51))
    printed[H - zoom.shape[0] - 10:H - 10, printed.shape[1] - zoom.shape[1] - 10:printed.shape[1] - 10] = zoom
    restored = fit(out)

    gap, pad, top = 28, 30, 64
    W = orig.shape[1] + printed.shape[1] + restored.shape[1] + 2 * gap + 2 * pad
    canvas = Image.new("RGB", (W, H + top + pad), (24, 25, 29))
    d = ImageDraw.Draw(canvas)
    x = pad
    panels = [(orig, "ORIGINAL"), (printed, "PRINTED  ·  BLACK & WHITE"), (restored, "SCANNED  ·  COLOR RESTORED")]
    for img, label in panels:
        canvas.paste(Image.fromarray(img), (x, top))
        d.text((x, 22), label, font=font(22), fill=(238, 107, 51) if label.startswith("SCANNED") else (200, 200, 205))
        x += img.shape[1] + gap
    canvas.save(ASSETS / "compare.png", optimize=True)


def screenshot():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from colorhide.gui.main import Printer
    app = QApplication([])
    w = Printer()
    w.resize(1000, 880)
    w.show()
    src = ASSETS / "_coffee.png"
    cv2.imwrite(str(src), cv2.cvtColor(data.coffee(), cv2.COLOR_RGB2BGR))
    steps = iter([lambda: w.feed(str(src))] + [None] * 6 + [lambda: w.test_cycle()] + [None] * 9 +
                 [lambda: (w.grab().save(str(ASSETS / "screenshot.png")), src.unlink(), app.quit())])

    def tick():
        s = next(steps)
        if s:
            s()

    t = QTimer()
    t.timeout.connect(tick)
    t.start(700)
    app.exec()


if __name__ == "__main__":
    compare()
    screenshot()
    print("wrote assets/compare.png, assets/screenshot.png")
