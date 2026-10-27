"""Draw the Inkhue icon: a sheet coming out of a printer slot, covered in one halftone dot
pattern that is black-and-white on one side of the diagonal and full color on the other.

Writes assets/icon.png (1024), icon.icns (macOS, needs iconutil), icon.ico (Windows) and
social-preview.png (1280x640, upload under the repo's Settings > Social preview).
"""
import colorsys
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "assets"
S = 4096  # drawn at 4x, downsampled for clean edges
ACCENT = (238, 107, 51)


def vgrad(w, h, top, bottom):
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        g.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((w, h))


def rounded_mask(size, box, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    return m


def icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    k = S / 1024
    body = (100 * k, 100 * k, 924 * k, 924 * k)
    radius = 185 * k

    # soft drop shadow under the body
    sh = Image.new("L", (S, S), 0)
    ImageDraw.Draw(sh).rounded_rectangle((body[0], body[1] + 18 * k, body[2], body[3] + 18 * k), radius, fill=120)
    img.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(22 * k)))

    # printer shell
    shell = vgrad(S, S, (246, 244, 239), (205, 200, 190))
    img.paste(shell, (0, 0), rounded_mask((S, S), body, radius))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(body, radius, outline=(255, 255, 255, 170), width=int(4 * k))

    # paper
    px0, px1, py0, py1 = 262 * k, 762 * k, 300 * k, 850 * k
    psh = Image.new("L", (S, S), 0)
    ImageDraw.Draw(psh).rectangle((px0 + 6 * k, py0, px1 + 6 * k, py1 + 14 * k), fill=110)
    img.paste((40, 30, 20, 255), (0, 0), psh.filter(ImageFilter.GaussianBlur(14 * k)))
    d.rectangle((px0, py0, px1, py1), fill=(255, 255, 255, 255))

    # halftone dots: one pattern, B/W below the diagonal, color above it
    step = 38 * k
    cols = int((px1 - px0 - 30 * k) // step)
    rows = int((py1 - py0 - 70 * k) // step)
    ox = px0 + (px1 - px0 - (cols - 1) * step) / 2
    oy = py0 + 70 * k
    for j in range(rows):
        for i in range(cols):
            u, v = i / (cols - 1), j / (rows - 1)
            dark = 0.18 + 0.78 * (0.5 + 0.5 * math.cos(math.hypot(u - 0.35, v - 0.4) * 5.2))
            r = 0.5 * step * math.sqrt(dark) * 0.98
            cx, cy = ox + i * step, oy + j * step
            if u > v:  # above the diagonal: color, a full spectrum starting at the brand orange
                t = (u - v + (1 - v) * 0.25) / 1.25
                h = (0.02 + 0.80 * t) % 1
                c = tuple(round(255 * x) for x in colorsys.hsv_to_rgb(h, 0.88, 0.97))
            else:
                c = (28, 28, 30)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c + (255,))

    # output slot across the top of the sheet, with the shell lip over the paper
    d.rectangle((180 * k, 228 * k, 844 * k, 300 * k), fill=None)
    lip = vgrad(int(704 * k), int(92 * k), (246, 244, 239), (222, 218, 210))
    img.paste(lip, (int(160 * k), int(214 * k)), rounded_mask(lip.size, (0, 0, lip.size[0], lip.size[1]), 30 * k))
    d.rounded_rectangle((200 * k, 282 * k, 824 * k, 312 * k), 15 * k, fill=(22, 22, 26, 255))
    # status LED
    d.ellipse((786 * k, 238 * k, 816 * k, 268 * k), fill=ACCENT + (255,))
    return img.resize((1024, 1024), Image.LANCZOS)


def social(icon_img):
    W, H = 1280, 640
    bg = vgrad(W, H, (41, 44, 49), (20, 21, 25)).convert("RGBA")
    bg.alpha_composite(icon_img.resize((440, 440), Image.LANCZOS), (90, 100))
    d = ImageDraw.Draw(bg)
    font = None
    for name in ["/System/Library/Fonts/SFNSRounded.ttf", "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
                 "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans-Bold.ttf"]:
        try:
            font = ImageFont.truetype(name, 96)
            small = ImageFont.truetype(name, 34)
            break
        except OSError:
            continue
    d.text((590, 210), "Ink", font=font, fill=(240, 238, 232))
    d.text((590 + d.textlength("Ink", font=font), 210), "hue", font=font, fill=ACCENT)
    d.text((594, 340), "A black-and-white print\nthat carries its own color.",
           font=small, fill=(170, 172, 178), spacing=12)
    return bg.convert("RGB")


def main():
    OUT.mkdir(exist_ok=True)
    img = icon()
    img.save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    social(img).save(OUT / "social-preview.png")
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            img.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            img.resize((2 * s, 2 * s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
        shutil.rmtree(iconset)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
