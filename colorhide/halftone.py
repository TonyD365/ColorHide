"""Data-carrying halftone (scheme B).

Every image pixel becomes a K x K cell of printer dots.
- How many dots are inked (0..K*K) sets the cell's gray level  -> luminance.
- Which corner the dots grow from carries 2 bits (x bit, y bit) -> hidden data.
At 600 dpi a cell is 1/150 inch, so the corner choice is far below what the eye
resolves: the page just looks like an ordinary black-and-white halftone.
"""
import numpy as np

try:  # numba makes error diffusion ~100x faster; the app bundles run fine without it
    from numba import njit
except ImportError:
    def njit(**_):
        return lambda f: f

K = 4
LEVELS = K * K


def _patterns():
    yy, xx = np.mgrid[0:K, 0:K] + 0.5
    pats = np.zeros((4, LEVELS + 1, K, K), np.uint8)  # 1 = ink
    # corner index c = ybit * 2 + xbit
    for c, (cy, cx) in enumerate([(0, 0), (0, K), (K, 0), (K, K)]):
        order = np.argsort(((yy - cy) ** 2 + (xx - cx) ** 2).ravel(), kind="stable")
        for n in range(LEVELS + 1):
            p = np.zeros(K * K, np.uint8)
            p[order[:n]] = 1
            pats[c, n] = p.reshape(K, K)
    return pats


PATTERNS = _patterns()


@njit(cache=True)
def error_diffuse(target, lo, hi):
    """Serpentine Floyd-Steinberg on cell levels; target is float darkness in [lo, hi]."""
    h, w = target.shape
    t = target.copy()
    out = np.zeros((h, w), np.int64)
    for y in range(h):
        rev = y % 2 == 1
        dx = -1 if rev else 1
        for i in range(w):
            x = w - 1 - i if rev else i
            v = t[y, x]
            q = min(max(int(np.floor(v + 0.5)), lo), hi)
            out[y, x] = q
            e = v - q
            if 0 <= x + dx < w:
                t[y, x + dx] += e * 7 / 16
            if y + 1 < h:
                if 0 <= x - dx < w:
                    t[y + 1, x - dx] += e * 3 / 16
                t[y + 1, x] += e * 5 / 16
                if 0 <= x + dx < w:
                    t[y + 1, x + dx] += e * 1 / 16
    return out


def luma_to_levels(y):
    """Y in [0,1] -> ink dot count per cell."""
    return error_diffuse(((1.0 - y) * LEVELS).astype(np.float64), 0, LEVELS)


def render(levels, corners):
    """(h,w) dot counts + (h,w) corner ids -> (h*K, w*K) ink map."""
    h, w = levels.shape
    tiles = PATTERNS[corners, levels]
    return tiles.transpose(0, 2, 1, 3).reshape(h * K, w * K)


def measure(dark, h, w):
    """Ink map (float darkness 0..1, aligned to the cell grid) -> dot count and soft x/y bits."""
    cells = dark.reshape(h, K, w, K).transpose(0, 2, 1, 3)
    coord = np.arange(K) - (K - 1) / 2
    n = cells.sum((2, 3))
    sx = (cells * coord[None, None, None, :]).sum((2, 3))
    sy = (cells * coord[None, None, :, None]).sum((2, 3))
    return n, sx, sy
