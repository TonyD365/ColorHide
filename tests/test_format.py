"""Pins the on-paper format. If one of these fails, a format constant was changed and
every page printed so far would no longer decode. Revert the change.
格式指纹测试：失败说明格式常量（如 SEED）被改动，已打印的纸将无法解码。请撤销改动。

run: python -m pytest tests  (or: python tests/test_format.py)
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide import halftone, layout, payload  # noqa: E402


def test_constants():
    assert payload.SEED == 20261027
    assert (payload.MAGIC, payload.VERSION) == (b"CH", 1)
    assert (payload.HDR_NSYM, payload.HDR_REPS, payload.BODY_NSYM) == (8, 48, 32)
    assert (halftone.K, layout.B) == (4, 4)


def test_scatter_fingerprint():
    perm, white = payload._layout(4096)
    h = hashlib.sha256(perm.tobytes() + white.tobytes()).hexdigest()
    assert h == "d12b79e9fb8914d761e9168c73d5beda7639a9992de7f009a2568751b1f7c331"


def test_pattern_fingerprint():
    h = hashlib.sha256(halftone.PATTERNS.tobytes() + layout.frame(10, 12).tobytes()).hexdigest()
    assert h == "c313808d591ca03279e7127c6d625efdef0caf5a53ab1c55c4ef6df9697f312b"


if __name__ == "__main__":
    test_constants()
    test_scatter_fingerprint()
    test_pattern_fingerprint()
    print("format OK")
