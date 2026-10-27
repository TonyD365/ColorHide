"""Page frame: a thin black ring (for locating the page in a scan) plus a timing
track of alternating cells (so the decoder can count the grid size).

Grid in cells, B = 4 border cells on each side of the image:
  rows 0-1   black ring
  row  2     timing track (black on odd columns)
  row  3     white gap (gives a clean paper-white reference)
  then the image, then the mirror of the above without the timing track.
The same holds for columns. A QUIET-cell white margin surrounds everything.
"""
import cv2
import numpy as np

from .halftone import K

B = 4
QUIET = 6


def frame(h, w):
    """Return (H, W) ink map of the full page in cells (1 = ink) with the image area zero."""
    H, W = h + 2 * B, w + 2 * B
    f = np.zeros((H, W), np.uint8)
    f[:2, :] = f[-2:, :] = 1
    f[:, :2] = f[:, -2:] = 1
    f[2, 3:W - 2:2] = 1
    f[3:H - 2:2, 2] = 1
    return f


def compose(img_ink, h, w):
    """Put the image ink map inside the frame, add quiet zone. Everything in printer dots."""
    page = np.kron(frame(h, w), np.ones((K, K), np.uint8))
    page[B * K:(B + h) * K, B * K:(B + w) * K] = img_ink
    return np.pad(page, QUIET * K)


def _order(pts):
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32)


def _count_cells(profile, length):
    """Count grid cells along a line through the timing track."""
    ink = profile > 0.5
    edges = np.flatnonzero(np.diff(ink.astype(np.int8))) + 1
    runs = np.split(np.arange(len(ink)), edges)
    runs = runs[1:-1]  # drop the runs merged with the ring on both ends
    if len(runs) < 4:
        raise ValueError("timing track not found")
    span = runs[-1][-1] + 1 - runs[0][0]
    cell = span / len(runs)
    return int(round(length / cell))


def _refine_corners(contour, rough):
    """Fit a line to each side of the ring's outer contour and intersect them (sub-pixel corners).
    Lines are pushed 0.5 px outward: contour points are centres of the outermost ink pixels."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    centre = rough.mean(0)
    lines = []
    for i in range(4):
        a, b = rough[i], rough[(i + 1) % 4]
        d = (b - a) / np.linalg.norm(b - a)
        t = (pts - a) @ d
        off = np.abs((pts - a) @ np.array([-d[1], d[0]]))
        L = np.linalg.norm(b - a)
        sel = pts[(t > 0.1 * L) & (t < 0.9 * L) & (off < 0.02 * L + 3)]
        vx, vy, x0, y0 = cv2.fitLine(sel.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        n = np.array([-vy, vx])
        if (np.array([x0, y0]) - centre) @ n < 0:
            n = -n
        p = np.array([x0, y0]) + 0.5 * n
        lines.append((p, np.array([vx, vy])))
    corners = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        s = np.linalg.solve(np.column_stack([d1, -d2]), p2 - p1)
        corners.append(p1 + s[0] * d1)
    return np.array(corners, np.float32)


def locate(gray, oversample=2):
    """Find the page in a scan; return the image area resampled to exactly 1 px per printer dot,
    as float darkness (0 = paper, 1 = ink), plus (h, w)."""
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)
    quad = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(quad) != 4:
        raise ValueError("page frame not found")
    src = _refine_corners(c, _order(quad.reshape(4, 2).astype(np.float64)))
    wo = int(round(max(np.linalg.norm(src[1] - src[0]), np.linalg.norm(src[2] - src[3]))))
    ho = int(round(max(np.linalg.norm(src[3] - src[0]), np.linalg.norm(src[2] - src[1]))))
    # pixel centres sit at integer coords, so the frame's outer edge is at -0.5
    box = lambda W, H: np.array([[-0.5, -0.5], [W - 0.5, -0.5], [W - 0.5, H - 0.5], [-0.5, H - 0.5]], np.float32)
    warped = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, box(wo, ho)), (wo, ho),
                                 flags=cv2.INTER_LINEAR, borderValue=255).astype(np.float64)

    # rough levels for reading the timing track
    ink0 = np.median(warped[: max(1, ho // 400), :])
    paper0 = np.percentile(warped, 99)
    rough = (paper0 - warped) / max(paper0 - ink0, 1)
    # ring thickness (2 cells); the timing track lengthens it on half the columns, so take a low percentile
    cols = np.linspace(wo * 0.2, wo * 0.8, 64).astype(int)
    cell_px = np.percentile([np.argmax(rough[:, x] < 0.5) for x in cols], 10) / 2.0
    row = rough[int(round(2.5 * cell_px)), :]
    col = rough[:, int(round(2.5 * cell_px))]
    W = _count_cells(row, wo)
    H = _count_cells(col, ho)

    s = oversample
    fine = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, box(W * K * s, H * K * s)),
                               (W * K * s, H * K * s), flags=cv2.INTER_LINEAR, borderValue=255)
    grid = cv2.resize(fine.astype(np.float32), (W * K, H * K), interpolation=cv2.INTER_AREA).astype(np.float64)
    ink = np.median(grid[: 2 * K, 2 * K:-2 * K])
    paper = np.median(np.concatenate([grid[3 * K:4 * K, 4 * K:-4 * K].ravel(),
                                      grid[-4 * K:-3 * K, 4 * K:-4 * K].ravel()]))
    dark = np.clip((paper - grid) / max(paper - ink, 1), 0, 1)
    h, w = H - 2 * B, W - 2 * B
    return dark[B * K:(B + h) * K, B * K:(B + w) * K], h, w
