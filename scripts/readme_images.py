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

from inkhue import api, channel  # noqa: E402

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


def screenshot(version=None):
    """assets/screenshot.png: the app right after revealing the color (waits for the work to finish,
    not for a fixed time). `version` sets the version shown on the printer, e.g. the latest release."""
    import time

    from PySide6.QtWidgets import QApplication

    from inkhue import _version
    if version:
        _version.__version__ = version
    from inkhue.gui import main as gui_main
    gui_main.__version__ = _version.__version__
    app = QApplication.instance() or QApplication([])
    w = gui_main.Printer()
    w.resize(1000, 900)
    w.show()

    def wait(cond, timeout=300):
        end = time.time() + timeout
        while not cond():
            if time.time() > end:
                raise TimeoutError("app did not finish")
            app.processEvents()
            time.sleep(0.05)

    src = ASSETS / "_coffee.png"
    cv2.imwrite(str(src), cv2.cvtColor(data.coffee(), cv2.COLOR_RGB2BGR))
    try:
        w.fill.setChecked(False)  # a moderate page keeps this quick; the picture looks the same
        w.width_in.setValue(6.0)
        w.feed(str(src))
        wait(lambda: w.page is not None and not w.busy)
        w.test_cycle()
        wait(lambda: w.color is not None and not w.busy)
        assert "COLOR RESTORED" in w.lcd.text(), w.lcd.text()
        for _ in range(40):  # let the sheet finish sliding out of the printer
            app.processEvents()
            time.sleep(0.05)
        w.width_in.clearFocus()
        app.processEvents()
        w.grab().save(str(ASSETS / "screenshot.png"))
    finally:
        src.unlink(missing_ok=True)
        w.close()


def reveal_gif(width=540, frames=16):
    """assets/reveal.gif: the black-and-white print, wiped into the recovered color, and back."""
    rgb = data.coffee()
    page, _ = api.encode(rgb, width_in=5.0, dpi=600)
    out, info = api.decode(channel.print_scan(page, seed=5), api.load_refiner())
    assert info["rs_ok"]
    ys, xs = np.where(page < 128)
    bw = page[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h = round(out.shape[0] * width / out.shape[1])
    color = cv2.resize(out, (width, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(cv2.resize(bw, (width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2RGB)
    imgs = []
    pos = [0] * 6 + [round(width * (i / frames) ** 1.5) for i in range(frames + 1)] + [width] * 10
    for p in pos + pos[::-1][10:]:
        f = gray.copy()
        f[:, :p] = color[:, :p]
        if 0 < p < width:
            f[:, max(0, p - 2):p + 2] = (238, 107, 51)  # the scan line
        imgs.append(Image.fromarray(f).quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    imgs[0].save(ASSETS / "reveal.gif", save_all=True, append_images=imgs[1:], duration=90, loop=0, optimize=True)


def gallery(height=230):
    """assets/gallery.png: more photos, plus one with handwriting on the printout."""
    rows = []
    for name, marks in (("astronaut", False), ("rocket", False), ("chelsea", True)):
        rgb = getattr(data, name)()
        page, _ = api.encode(rgb, width_in=4.0, dpi=600)
        if marks:
            page = channel.scribble(page, np.random.default_rng(4), inside=14, across=2)
        out, info = api.decode(channel.print_scan(page, seed=3), api.load_refiner())
        assert info["rs_ok"]
        ys, xs = np.where(page < 128)
        bw = cv2.cvtColor(page[ys.min():ys.max() + 1, xs.min():xs.max() + 1], cv2.COLOR_GRAY2RGB)
        fit = lambda a: cv2.resize(a, (round(a.shape[1] * height / a.shape[0]), height), interpolation=cv2.INTER_AREA)
        rows.append(np.hstack([fit(rgb), np.full((height, 16, 3), 24, np.uint8), fit(bw),
                               np.full((height, 16, 3), 24, np.uint8), fit(out)]))
    w = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=24) for r in rows]
    sheet = np.vstack([np.vstack([r, np.full((16, w, 3), 24, np.uint8)]) for r in rows])
    Image.fromarray(np.pad(sheet, ((16, 0), (16, 16), (0, 0)), constant_values=24)).save(ASSETS / "gallery.png",
                                                                                         optimize=True)


def document_demo(height=520):
    """assets/document.png: a mostly white page of notes (text, highlighter, chart), printed and recovered."""
    W, H = 1275, 1650  # US Letter at 150 dpi
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    big, mid, small = font(64), font(34), font(28)
    d.text((90, 90), "Field trip notes", font=big, fill=(232, 98, 40))
    d.text((92, 175), "Thursday · Science museum", font=small, fill=(120, 120, 130))
    lines = ["Meet at the main entrance at 9:00.", "Bring a notebook and a pencil.",
             "Lunch is at the café on the second floor.", "We will visit the color and light exhibit.",
             "Write down three things that surprised you.", "Bus leaves at 3:30 — don't be late!"]
    y = 270
    for i, t in enumerate(lines):
        if i == 3:
            d.rectangle((84, y - 4, 92 + d.textlength(t, font=mid), y + 42), fill=(255, 236, 110))
        d.text((90, y), t, font=mid, fill=(40, 40, 45) if i != 5 else (200, 40, 40))
        y += 62
    d.text((90, y + 20), "learn more: museum.example/kids", font=mid, fill=(30, 90, 210))
    d.text((90, 760), "Votes for the next trip", font=mid, fill=(40, 40, 45))
    for i, (v, c, n) in enumerate(((210, (231, 76, 60), "Zoo"), (320, (46, 160, 90), "Park"),
                                   (150, (52, 120, 220), "Aquarium"), (260, (243, 166, 35), "Space center"))):
        x = 110 + i * 270
        d.rectangle((x, 1160 - v, x + 170, 1160), fill=c)
        d.text((x, 1180), n, font=small, fill=(60, 60, 70))
    d.ellipse((900, 1300, 1150, 1550), fill=(52, 120, 220))
    d.pieslice((900, 1300, 1150, 1550), -90, 40, fill=(243, 166, 35))
    d.pieslice((900, 1300, 1150, 1550), 40, 140, fill=(46, 160, 90))
    d.text((90, 1400), "Signed: Ms. Rivera", font=mid, fill=(30, 30, 35))
    rgb = np.asarray(img)
    page, info = api.encode(rgb, width_in=6.0, dpi=600)
    out, dinfo = api.decode(channel.print_scan(page, seed=7), api.load_refiner())
    assert dinfo["rs_ok"]
    ys, xs = np.where(page < 128)
    bw = cv2.cvtColor(page[ys.min():ys.max() + 1, xs.min():xs.max() + 1], cv2.COLOR_GRAY2RGB)
    fit = lambda a: cv2.resize(a, (round(a.shape[1] * height / a.shape[0]), height), interpolation=cv2.INTER_AREA)
    gap = np.full((height, 24, 3), 24, np.uint8)
    strip = np.hstack([fit(rgb), gap, fit(bw), gap, fit(out)])
    Image.fromarray(np.pad(strip, ((24, 24), (24, 24), (0, 0)), constant_values=24)).save(ASSETS / "document.png",
                                                                                          optimize=True)


if __name__ == "__main__":
    compare()
    reveal_gif()
    gallery()
    document_demo()
    import subprocess
    tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True).stdout.strip()
    screenshot(tag.lstrip("v") or None)  # show the released version, not 0.0.0-dev
    print("wrote assets/compare.png, reveal.gif, gallery.png, screenshot.png")
