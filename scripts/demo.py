"""Encode sample photos, run them through the simulated print+scan, decode, report quality.

usage: python scripts/demo.py [--size 384] [--factor 8] [--scale 2.0] [--images a.jpg b.png]
                              [--refiner models/refiner.pt]
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from skimage import color as skcolor
from skimage import data as skdata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inkhue import channel, codec, payload  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"


def load(args):
    if args.images:
        for p in args.images:
            yield Path(p).stem, cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
    else:
        for name in ["astronaut", "coffee", "chelsea", "rocket"]:
            yield name, getattr(skdata, name)()


def fit(rgb, size):
    h, w = rgb.shape[:2]
    s = size / max(h, w)
    return cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA).astype(np.float64) / 255


def psnr(a, b):
    return 10 * np.log10(1 / np.mean((a - b) ** 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--factor", type=int, default=8)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--images", nargs="*")
    ap.add_argument("--refiner", help="path to a trained refiner, e.g. models/refiner.pt")
    args = ap.parse_args()
    ref = None
    if args.refiner:
        from inkhue.refiner import load as load_refiner
        ref = load_refiner(args.refiner)
    OUT.mkdir(exist_ok=True)

    for name, img in load(args):
        rgb = fit(img, args.size)
        t = time.time()
        page, einfo = codec.encode(rgb, factor=args.factor)
        scan = channel.print_scan(page, scale=args.scale, seed=1)
        t1 = time.time()
        out, info = codec.decode(scan, refiner=ref)
        t2 = time.time()

        # raw channel bit error rate (before repetition + RS)
        h, w = rgb.shape[:2]
        ycc = codec.rgb_to_ycbcr(rgb)
        ch, cw = payload.chroma_shape(h, w, args.factor)
        q = payload.quantize(cv2.resize(ycc[..., 1:], (cw, ch), interpolation=cv2.INTER_AREA).transpose(2, 0, 1), 6)
        sent, _ = payload.encode_bits(q, args.factor, 6, h * w * 2)
        _, soft, _, _ = codec.demodulate(scan)
        ber = np.mean((soft > 0) != sent)

        de = skcolor.deltaE_ciede2000(skcolor.rgb2lab(rgb), skcolor.rgb2lab(out)).mean()
        gray = np.dstack([codec.rgb_to_ycbcr(out)[..., :1]] * 3)
        de_gray = skcolor.deltaE_ciede2000(skcolor.rgb2lab(rgb), skcolor.rgb2lab(np.clip(gray, 0, 1))).mean()
        print(f"{name:10s} {w}x{h}  raw BER {ber:.3%}  reps {info['reps']}  "
              f"RS ok={info['rs_ok']} fixed={info['rs_fixed']}  "
              f"PSNR {psnr(rgb, out):.1f} dB  ΔE00 {de:.2f} (gray-only {de_gray:.2f})  "
              f"enc+scan {t1 - t:.1f}s dec {t2 - t1:.1f}s")

        cv2.imwrite(str(OUT / f"{name}_page.png"), page)
        cv2.imwrite(str(OUT / f"{name}_scan.png"), scan)
        tile = lambda a: cv2.cvtColor((np.clip(a, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        small_scan = cv2.cvtColor(cv2.resize(scan, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
        cv2.imwrite(str(OUT / f"{name}_compare.png"), np.hstack([tile(rgb), small_scan, tile(out)]))


if __name__ == "__main__":
    main()
