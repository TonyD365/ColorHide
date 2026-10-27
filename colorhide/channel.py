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
