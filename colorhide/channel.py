"""Software stand-in for print + scan, so the codec can be tested without paper.

Models: toner spread (dot gain) and paper noise on the print side; rotation,
perspective, optical blur, tone curve, sensor noise and JPEG on the scan side.
"""
import cv2
import numpy as np


def print_scan(page, scale=2.0, rotate=1.5, persp=0.004, blur=0.7, dot_gain=0.15,
               noise=0.03, gamma=1.1, jpeg=90, seed=None):
    rng = np.random.default_rng(seed)
    ink = (page < 128).astype(np.float32)

    # print: toner spreads past the dot edge, coverage is a bit uneven
    spread = cv2.GaussianBlur(ink, (0, 0), 0.6)
    ink = (spread > 0.5 - dot_gain).astype(np.float32)
    ink *= 1 - 0.08 * rng.random(ink.shape, dtype=np.float32)
    paper = 1 - 0.92 * ink
    # the scanner bed is bigger than the sheet: room for the rotated corners
    m = int(0.04 * max(paper.shape))
    paper = np.pad(paper, m, constant_values=1.0)

    # scan geometry: resample at `scale` px per printer dot, small rotation + keystone
    h, w = paper.shape
    Ho, Wo = int(h * scale), int(w * scale)
    a = np.deg2rad(rng.uniform(-rotate, rotate))
    cx, cy = Wo / 2, Ho / 2
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    dst = corners * scale - [cx, cy]
    dst = dst @ np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]).T
    dst = dst * (1 + rng.uniform(-persp, persp, (4, 1))) + [cx, cy]
    M = cv2.getPerspectiveTransform(corners, dst.astype(np.float32))
    img = cv2.warpPerspective(paper, M, (Wo, Ho), flags=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
                              borderValue=1.0)

    img = cv2.GaussianBlur(img, (0, 0), blur * scale)
    img = 0.04 + 0.9 * np.clip(img, 0, 1) ** gamma
    img += rng.normal(0, noise, img.shape).astype(np.float32)
    img = np.clip(img * 255, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def scribble(page, rng, inside=30, across=4, ink=25, width=6):
    """Pen marks on a printed page (in printer dots): `inside` wobbly strokes over the image and
    `across` strokes that cross the frame and timing track. ink 0 = black pen, ~120 = blue/pencil."""
    from .halftone import K
    from .layout import QUIET, B
    out = page.copy()
    off = QUIET * K
    h, w = page.shape
    img = (off + B * K, off + B * K, w - off - B * K, h - off - B * K)  # x0, y0, x1, y1

    def stroke(x, y, dx, dy):
        pts = [(x, y)]
        for _ in range(12):
            x += rng.integers(-dx, dx + 1)
            y += rng.integers(-dy, dy + 1)
            pts.append((x, y))
        return np.array(pts, np.int32)

    lines = [stroke(rng.integers(img[0] + 60, img[2] - 60), rng.integers(img[1] + 60, img[3] - 60), 40, 20)
             for _ in range(inside)]
    for i in range(across):  # start in the margin, run over the frame into the page
        x = rng.integers(off, w - off)
        y = rng.integers(off // 2, off + B * K) if i % 2 == 0 else rng.integers(h - off - B * K, h - off // 2)
        lines.append(np.array([(x, y), (x + rng.integers(-200, 200), y + (300 if i % 2 == 0 else -300))], np.int32))
    clip = np.zeros_like(page)  # strokes inside the image stay inside it
    cv2.rectangle(clip, img[:2], (img[2] - 1, img[3] - 1), 255, -1)
    for i, pts in enumerate(lines):
        layer = np.full_like(page, 255)
        cv2.polylines(layer, [pts], False, int(ink), width, cv2.LINE_AA)
        if i < inside:
            layer[clip == 0] = 255
        out = np.minimum(out, layer)
    return out
