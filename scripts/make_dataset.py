"""Build refiner training data: random photo crops -> encode -> simulated print+scan
(with randomized printer/scanner settings) -> demodulate.

usage: python scripts/make_dataset.py data/div2k/DIV2K_train_HR --crops 5 --size 256
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide import channel, codec, payload  # noqa: E402

FACTOR, QBITS = 8, 6
ARGS = None


def work(job):
    idx, path = job
    rng = np.random.default_rng(idx)
    img = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    S = ARGS.size
    out = []
    for k in range(ARGS.crops):
        # photos get printed at many sizes: shrink by a random amount before cropping
        lo = S / min(img.shape[:2]) * 1.05
        s = rng.uniform(lo, max(lo, 0.6))
        im = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        y0, x0 = rng.integers(0, im.shape[0] - S + 1), rng.integers(0, im.shape[1] - S + 1)
        rgb = im[y0:y0 + S, x0:x0 + S].astype(np.float64) / 255
        page, _ = codec.encode(rgb, factor=FACTOR, qbits=QBITS)
        scan = channel.print_scan(page, seed=idx * 100 + k,
                                  scale=rng.uniform(1.5, 3.0), rotate=2.0,
                                  blur=rng.uniform(0.4, 1.0), dot_gain=rng.uniform(0.0, 0.25),
                                  noise=rng.uniform(0.01, 0.05), gamma=rng.uniform(0.8, 1.3),
                                  jpeg=int(rng.integers(75, 96)))
        try:
            dots, _, h, w = codec.demodulate(scan)
        except Exception:
            continue
        if (h, w) != (S, S):
            continue
        ycc = codec.rgb_to_ycbcr(rgb)
        small = cv2.resize(ycc[..., 1:], (S // FACTOR, S // FACTOR), interpolation=cv2.INTER_AREA)
        small = payload.dequantize(payload.quantize(small, QBITS), QBITS)  # exactly what the decoder receives
        out.append((dots.astype(np.float16), small.astype(np.float16), (rgb * 255).round().astype(np.uint8)))
    return out


def init(args):
    global ARGS
    ARGS = args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--crops", type=int, default=5)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--out", default="data/train.npz")
    args = ap.parse_args()
    files = sorted(Path(args.src).glob("*.png")) + sorted(Path(args.src).glob("*.jpg"))
    with Pool(10, initializer=init, initargs=(args,)) as pool:
        res = []
        for i, r in enumerate(pool.imap_unordered(work, list(enumerate(files)), chunksize=4)):
            res += r
            if i % 50 == 0:
                print(f"{i}/{len(files)} images, {len(res)} samples", flush=True)
    dots, small, rgb = map(np.stack, zip(*res))
    np.savez(args.out, dots=dots, small=small, rgb=rgb)
    print("saved", args.out, dots.shape)


if __name__ == "__main__":
    main()
