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


def encode_bits(q, factor, qbits, capacity):
    """Return a length-`capacity` 0/1 array laid out in cell-bit order."""
    hdr = MAGIC + bytes([VERSION, factor, qbits, 0])
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


def decode_soft(soft, h, w):
    """soft: per cell-bit value, >0 means bit 1. Returns (Cb/Cr small, info dict)."""
    capacity = soft.size
    perm, white = _layout(capacity)
    s = soft[perm] * (1.0 - 2.0 * white[perm])  # stream order, whitening removed
    nh = _hdr_bits() * HDR_REPS
    hdr_soft = s[:nh].reshape(HDR_REPS, -1).sum(0)
    hdr = _hdr_rs.decode(np.packbits(hdr_soft > 0).tobytes())[0]
    if hdr[:2] != MAGIC or hdr[2] != VERSION:
        raise ValueError("no ColorHide header found")
    factor, qbits = hdr[3], hdr[4]
    ch, cw = chroma_shape(h, w, factor)
    count = ch * cw * 2
    nbytes = -(-count * qbits // 8)
    nbody = 8 * (nbytes + BODY_NSYM * -(-nbytes // (255 - BODY_NSYM)))
    reps = (capacity - nh) // nbody
    body_soft = s[nh:nh + reps * nbody].reshape(reps, nbody).sum(0)
    raw = np.packbits(body_soft > 0).tobytes()
    try:
        data, _, errata = _body_rs.decode(raw)
        nfixed = len(errata)
        ok = True
    except ReedSolomonError:
        # fall back to the uncorrected bits: a few wrong chroma samples beats no color at all
        k = 255 - BODY_NSYM
        data = b"".join(raw[blk:min(blk + k, len(raw))] for blk in range(0, len(raw), 255))
        nfixed, ok = -1, False
    q = _unpack(bytes(data), count, qbits).reshape(2, ch, cw)
    info = dict(factor=factor, qbits=qbits, reps=reps, rs_ok=ok, rs_fixed=nfixed)
    return dequantize(q, qbits).transpose(1, 2, 0), info
