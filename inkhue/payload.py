"""Chroma payload (scheme C): quantize low-res Cb/Cr, protect with Reed-Solomon,
repeat to fill the page, and scatter over the cells with a fixed permutation.

The scatter + whitening use a public, fixed seed. They are not for secrecy; they
spread local damage (a smudge, a fold) across the whole codeword and keep the
dot texture statistically uniform so no pattern becomes visible.
"""
import numpy as np
from reedsolo import ReedSolomonError, RSCodec

# ============================================================================
# FORMAT CONSTANTS - DO NOT MODIFY / 格式常量，禁止修改
# Every page ever printed was laid out with these exact values. Changing any of
# them (SEED above all) makes every existing printout undecodable.
# tests/test_format.py pins them; a format change needs a new VERSION and a
# decoder that still reads the old one.
# 已经打印出来的每一张纸都依赖这些值。改动任何一个（尤其是 SEED），
# 之前所有的打印件都将无法解码。tests/test_format.py 会校验它们。
# ============================================================================
MAGIC = b"CH"
VERSION = 1
SEED = 20261027  # DO NOT MODIFY / 禁止修改
HDR_NSYM = 8
# header byte 5 holds flags (always 0 before Inkhue 1.2, so old pages read as "no flags")
FLAG_INK_FLOOR = 1  # every cell has 1..15 dots: the decoder rescales brightness
HDR_REPS = 48
BODY_NSYM = 32

_hdr_rs = RSCodec(HDR_NSYM)
_body_rs = RSCodec(BODY_NSYM)


def _bits(b):
    return np.unpackbits(np.frombuffer(bytes(b), np.uint8))


def chroma_shape(h, w, factor):
    return -(-h // factor), -(-w // factor)


def quantize(cbcr, qbits):
    m = (1 << qbits) - 1
    return np.clip(np.round((cbcr + 0.5) * m), 0, m).astype(np.uint16)


def dequantize(q, qbits):
    return q.astype(np.float64) / ((1 << qbits) - 1) - 0.5


def _pack(q, qbits):
    planes = ((q.ravel()[:, None] >> np.arange(qbits)[::-1]) & 1).astype(np.uint8)
    return np.packbits(planes.ravel()).tobytes()


def _unpack(data, count, qbits):
    bits = np.unpackbits(np.frombuffer(data, np.uint8))[: count * qbits].reshape(count, qbits)
    return (bits.astype(np.uint16) << np.arange(qbits)[::-1].astype(np.uint16)).sum(1).astype(np.uint16)


def _layout(capacity):
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(capacity)
    white = rng.integers(0, 2, capacity, dtype=np.uint8)
    return perm, white


def _hdr_bits():
    return 8 * (6 + HDR_NSYM)


def encode_bits(q, factor, qbits, capacity, flags=0):
    """Return a length-`capacity` 0/1 array laid out in cell-bit order."""
    hdr = MAGIC + bytes([VERSION, factor, qbits, flags])
    hb = _bits(_hdr_rs.encode(hdr))
    bb = _bits(_body_rs.encode(_pack(q, qbits)))
    nh = len(hb) * HDR_REPS
    reps = (capacity - nh) // len(bb)
    if reps < 1:
        raise ValueError(f"payload {len(bb)} bits does not fit capacity {capacity - nh}; use a larger chroma factor")
    stream = np.zeros(capacity, np.uint8)
    stream[:nh] = np.tile(hb, HDR_REPS)
    stream[nh:nh + reps * len(bb)] = np.tile(bb, reps)
    rng = np.random.default_rng(SEED + 1)
    stream[nh + reps * len(bb):] = rng.integers(0, 2, capacity - nh - reps * len(bb))
    perm, white = _layout(capacity)
    out = np.empty(capacity, np.uint8)
    out[perm] = stream ^ white[perm]
    return out, reps


def _header(s, nh):
    """(factor, qbits) from the header copies at the start of the stream, or None."""
    hdr_soft = s[:nh].reshape(HDR_REPS, -1).sum(0)
    try:
        hdr = _hdr_rs.decode(np.packbits(hdr_soft > 0).tobytes())[0]
    except ReedSolomonError:
        return None
    if hdr[:2] != MAGIC or hdr[2] != VERSION:
        return None
    return hdr[3], hdr[4], hdr[5]


def has_header(soft):
    """True if these soft bits carry a valid Inkhue header: confirms the grid was read right."""
    perm, white = _layout(soft.size)
    nh = _hdr_bits() * HDR_REPS
    if soft.size < nh:
        return False
    s = soft[perm[:nh]] * (1.0 - 2.0 * white[perm[:nh]])  # only the header's share of the stream
    return _header(s, nh) is not None


def decode_soft(soft, h, w):
    """soft: per cell-bit value, >0 means bit 1. Returns (Cb/Cr small, info dict)."""
    capacity = soft.size
    perm, white = _layout(capacity)
    s = soft[perm] * (1.0 - 2.0 * white[perm])  # stream order, whitening removed
    nh = _hdr_bits() * HDR_REPS
    hdr = _header(s, nh)
    if hdr is None:
        raise ValueError("no Inkhue header found")
    factor, qbits, flags = hdr
    ch, cw = chroma_shape(h, w, factor)
    count = ch * cw * 2
    nbytes = -(-count * qbits // 8)
    nbody = 8 * (nbytes + BODY_NSYM * -(-nbytes // (255 - BODY_NSYM)))
    reps = (capacity - nh) // nbody
    body_soft = s[nh:nh + reps * nbody].reshape(reps, nbody).sum(0)
    raw = np.packbits(body_soft > 0).tobytes()
    # Reed-Solomon block by block: a block that can't be corrected leaves its samples neutral (no color
    # there) instead of filling the photo with random colors
    k = 255 - BODY_NSYM
    data, bad, nfixed = bytearray(), [], 0
    for i, start in enumerate(range(0, len(raw), 255)):
        chunk = raw[start:start + 255]
        try:
            msg, _, errata = _body_rs.decode(chunk)
            data += msg
            nfixed += len(errata)
        except ReedSolomonError:
            data += chunk[:max(0, len(chunk) - BODY_NSYM)]
            bad.append(i)
    q = _unpack(bytes(data), count, qbits)
    for i in bad:  # bytes [i*k, (i+1)*k) -> the samples whose bits fall inside
        lo, hi = i * k * 8 // qbits, min(count, -(-(i + 1) * k * 8 // qbits))
        q[lo:hi] = round(0.5 * ((1 << qbits) - 1))
    q = q.reshape(2, ch, cw)
    nblocks = -(-len(raw) // 255)
    info = dict(factor=factor, qbits=qbits, flags=flags, reps=reps, rs_ok=not bad, rs_fixed=nfixed,
                damaged=len(bad) / nblocks)
    return dequantize(q, qbits).transpose(1, 2, 0), info
