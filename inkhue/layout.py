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


def _ring_end(profile):
    """Inner edge of the ring along a line entering from the frame's edge (skipping paper at the very edge)."""
    ink = profile > 0.5
    start = int(np.argmax(ink))
    return start + int(np.argmax(~ink[start:]))


def _cell_size(profile):
    """Cell size in px along a line through the timing track (alternating 1-cell runs).
    Robust to pen strokes: runs of the wrong length are dropped and the size comes from a
    least-squares fit of the remaining run centres, not from counting runs."""
    ink = profile > 0.5
    on = np.flatnonzero(ink)
    if len(on) < 2:
        return None
    ink = ink[on[0]:on[-1] + 1]  # the outermost pixels can sample paper just outside the frame
    edges = np.flatnonzero(np.diff(ink.astype(np.int8))) + 1
    starts = np.concatenate([[0], edges])[1:-1]  # drop the runs merged with the ring on both ends
    ends = np.concatenate([edges, [len(ink)]])[1:-1]
    if len(starts) < 8:
        return None
    lengths = ends - starts
    cell0 = float(np.median(lengths))
    good = np.abs(lengths - cell0) < 0.35 * cell0
    centres = ((starts + ends) / 2.0)[good]
    if len(centres) < 8:
        return None
    k = np.concatenate([[0], np.cumsum(np.round(np.diff(centres) / cell0))])  # cell index of each run
    for _ in range(2):  # fit, drop outliers, refit
        cell, c0 = np.polyfit(k, centres, 1)
        keep = np.abs(centres - (c0 + cell * k)) < 0.3 * cell
        k, centres = k[keep], centres[keep]
    return float(cell)


def _grid_count(rough, axis, cell_px, length):
    """Cells across the frame along `axis`, from several lines through the timing track."""
    sizes = []
    for f in (2.3, 2.5, 2.7):
        i = int(round(f * cell_px))
        size = _cell_size(rough[i, :] if axis == 1 else rough[:, i])
        if size:
            sizes.append(size)
    if not sizes:
        raise ValueError("timing track not found")
    return int(round(length / float(np.median(sizes))))


def _find_quad(contour):
    """Four rough corners of the frame. Pen strokes stuck to the frame make the outline ragged,
    so simplify harder until a quadrilateral appears; the minimum-area box is the last resort."""
    peri = cv2.arcLength(contour, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        quad = cv2.approxPolyDP(contour, eps * peri, True)
        if len(quad) == 4:
            return quad.reshape(4, 2).astype(np.float64)
    return cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float64)


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


class ScanTooCoarse(ValueError):
    """The frame was found, but the scan has fewer pixels than the page has printer dots."""

    def __init__(self, dpi):
        super().__init__(f"scan resolution too low (about {dpi} dpi)")
        self.dpi = dpi


class Frame:
    """The page found in a scan: refined corners and the estimated grid size in cells."""

    def __init__(self, src, W, H):
        self.src, self.W, self.H = src, W, H

    def candidates(self, radius=2):
        """(W, H) to try, the estimate first, then its neighbours by distance."""
        near = [(self.W + dw, self.H + dh) for dw in range(-radius, radius + 1) for dh in range(-radius, radius + 1)]
        return sorted(near, key=lambda c: abs(c[0] - self.W) + abs(c[1] - self.H))


def _box(W, H):
    # pixel centres sit at integer coords, so the frame's outer edge is at -0.5
    return np.array([[-0.5, -0.5], [W - 0.5, -0.5], [W - 0.5, H - 0.5], [-0.5, H - 0.5]], np.float32)


def find_frame(gray):
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        raise ValueError("page frame not found")
    c = max(cnts, key=cv2.contourArea)
    src = _refine_corners(c, _order(_find_quad(c)))
    wo = int(round(max(np.linalg.norm(src[1] - src[0]), np.linalg.norm(src[2] - src[3]))))
    ho = int(round(max(np.linalg.norm(src[3] - src[0]), np.linalg.norm(src[2] - src[1]))))
    warped = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, _box(wo, ho)), (wo, ho),
                                 flags=cv2.INTER_LINEAR, borderValue=255).astype(np.float64)
    # rough levels for reading the timing track
    ink0 = np.median(warped[: max(1, ho // 400), :])
    paper0 = np.percentile(warped, 99)
    rough = (paper0 - warped) / max(paper0 - ink0, 1)
    # ring thickness (2 cells); the timing track lengthens it on half the columns, so take a low percentile
    cols = np.linspace(wo * 0.2, wo * 0.8, 64).astype(int)
    cell_px = np.percentile([_ring_end(rough[:, x]) for x in cols], 10) / 2.0
    if cell_px / K < 0.75:  # under ~450 dpi for a 600 dpi print: single printer dots can't be told apart
        raise ScanTooCoarse(round(cell_px / K * 600))
    return Frame(src, _grid_count(rough, 1, cell_px, wo), _grid_count(rough, 0, cell_px, ho))


def sample(gray, frame, W, H, oversample=2):
    """The image area resampled to exactly 1 px per printer dot for a W x H cell grid, as float
    darkness (0 = paper, 1 = ink), plus (h, w)."""
    s = oversample
    fine = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(frame.src, _box(W * K * s, H * K * s)),
                               (W * K * s, H * K * s), flags=cv2.INTER_LINEAR, borderValue=255)
    grid = cv2.resize(fine.astype(np.float32), (W * K, H * K), interpolation=cv2.INTER_AREA).astype(np.float64)
    ink = np.median(grid[: 2 * K, 2 * K:-2 * K])
    paper = np.median(np.concatenate([grid[3 * K:4 * K, 4 * K:-4 * K].ravel(),
                                      grid[-4 * K:-3 * K, 4 * K:-4 * K].ravel()]))
    dark = np.clip((paper - grid) / max(paper - ink, 1), 0, 1)
    h, w = H - 2 * B, W - 2 * B
    return dark[B * K:(B + h) * K, B * K:(B + w) * K], h, w


def locate(gray, oversample=2):
    """Find the page in a scan; return the image area at 1 px per printer dot, plus (h, w).
    Uses the estimated grid size; codec.demodulate_full also tries neighbouring sizes."""
    f = find_frame(gray)
    return sample(gray, f, f.W, f.H, oversample)
