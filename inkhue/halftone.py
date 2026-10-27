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


def luma_to_levels(y, floor=True):
    """Y in [0,1] -> ink dot count per cell. With `floor`, every cell keeps 1..LEVELS-1 dots: an empty
    (white) or full (black) cell has no corner to lean towards, so it could not carry its 2 bits —
    a mostly white document would then lose most of its data. White paper prints as a 1/16 tint."""
    if floor:
        return error_diffuse((1.0 + (1.0 - y) * (LEVELS - 2)).astype(np.float64), 1, LEVELS - 1)
    return error_diffuse(((1.0 - y) * LEVELS).astype(np.float64), 0, LEVELS)


def floor_to_luma(y):
    """Undo the 1..LEVELS-1 range on a luma estimate made as if 0..LEVELS were used."""
    return np.clip(1.0 - (LEVELS * (1.0 - y) - 1.0) / (LEVELS - 2), 0.0, 1.0)


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


# ---- detail-preserving placement -----------------------------------------------
# The decoder only looks at the sign of each cell's ink centroid (x and y), so the dots don't have to
# grow from the corner: any arrangement whose centroid leans clearly enough towards that corner reads
# the same. render_detail() places the dots where the full-resolution image is darkest, then pulls
# them towards the data corner just as far as needed to keep a safety margin. Old decoders read these
# pages unchanged.

_COORD = np.arange(K) - (K - 1) / 2
_CX = np.tile(_COORD, K)            # x coordinate of each of the K*K dots (row-major)
_CY = np.repeat(_COORD, K)
# centroid of the plain corner pattern for each dot count: the reference the margin is measured against
_REF_X = np.abs((PATTERNS[0].reshape(LEVELS + 1, -1) * _CX).sum(1))
_REF_Y = np.abs((PATTERNS[0].reshape(LEVELS + 1, -1) * _CY).sum(1))
# pull towards each corner: +1 at the corner dot, falling off linearly with distance
_PULL = np.stack([-(np.hypot(_CY - (by - 0.5) * K, _CX - (bx - 0.5) * K)) for by in (0, 1) for bx in (0, 1)])
_PULL = (_PULL - _PULL.min(1, keepdims=True)) / np.ptp(_PULL, 1, keepdims=True)


def render_detail(levels, corners, darkness, margin=0.45, pulls=(0.15, 0.3, 0.5, 0.8, 1.2, 2.0)):
    """levels/corners: (h,w) as for render(); darkness: (h*K, w*K) target ink 0..1 at dot resolution.
    margin: required centroid as a fraction of the plain corner pattern's (decoding robustness)."""
    h, w = levels.shape
    n = levels.ravel()
    c = corners.ravel()
    t = darkness.reshape(h, K, w, K).transpose(0, 2, 1, 3).reshape(-1, LEVELS)
    sx_sign = np.where(c % 2 == 1, 1.0, -1.0)
    sy_sign = np.where(c // 2 == 1, 1.0, -1.0)
    need_x, need_y = margin * _REF_X[n], margin * _REF_Y[n]
    out = PATTERNS[c, n].reshape(-1, LEVELS).copy()  # fallback: the plain corner pattern
    todo = np.flatnonzero((n > 0) & (n < LEVELS))
    jitter = np.random.default_rng(0).random(LEVELS) * 1e-6  # deterministic tie-break
    for lam in pulls:
        if todo.size == 0:
            break
        score = t[todo] + lam * _PULL[c[todo]] + jitter
        rank = np.argsort(np.argsort(-score, axis=1), axis=1)
        sel = (rank < n[todo, None]).astype(np.uint8)
        sx = (sel * _CX).sum(1) * sx_sign[todo]
        sy = (sel * _CY).sum(1) * sy_sign[todo]
        ok = (sx >= need_x[todo] - 1e-9) & (sy >= need_y[todo] - 1e-9)
        out[todo[ok]] = sel[ok]
        todo = todo[~ok]
    return out.reshape(h, w, K, K).transpose(0, 2, 1, 3).reshape(h * K, w * K)
