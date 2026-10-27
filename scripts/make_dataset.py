"""Build refiner training data: random photo crops -> encode (detail-preserving halftone) ->
simulated print+scan with randomized printer/scanner settings -> the scan's ink map at printer-dot
resolution, the decoded chroma, and the photo at 2x cell resolution as the target.

usage: python scripts/make_dataset.py data/div2k/DIV2K_valid_HR --crops 20 --size 128
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide import channel, codec, halftone, payload

FACTOR, QBITS, K = 8, 6, halftone.K
ARGS = None


def work(job):
    idx, path = job
    rng = np.random.default_rng(idx)
    img = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    S = ARGS.size
    out = []
    for k in range(ARGS.crops):
        # a region of 2S..4S photo pixels becomes S cells: photos are printed at many sizes
        r = int(rng.uniform(2 * S, min(4 * S, *img.shape[:2])))
        y0, x0 = rng.integers(0, img.shape[0] - r + 1), rng.integers(0, img.shape[1] - r + 1)
        region = img[y0:y0 + r, x0:x0 + r]
        cells = cv2.resize(region, (S, S), interpolation=cv2.INTER_AREA).astype(np.float64) / 255
        hi = cv2.resize(region, (K * S, K * S), interpolation=cv2.INTER_AREA if r >= K * S else cv2.INTER_CUBIC)
        luma = np.clip(codec.rgb_to_ycbcr(hi.astype(np.float64) / 255)[..., 0], 0, 1)
        target = cv2.resize(region, (2 * S, 2 * S), interpolation=cv2.INTER_AREA)
        page, _ = codec.encode(cells, factor=FACTOR, qbits=QBITS, luma_detail=luma)
        scan = channel.print_scan(page, seed=idx * 100 + k,
                                  scale=rng.uniform(1.0, 3.0), rotate=2.0,
                                  blur=rng.uniform(0.4, 1.0), dot_gain=rng.uniform(0.0, 0.25),
                                  noise=rng.uniform(0.01, 0.05), gamma=rng.uniform(0.8, 1.3),
                                  jpeg=int(rng.integers(75, 96)))
        try:
            grid, _, _, h, w = codec.demodulate_full(scan)
        except Exception:
            continue
        if (h, w) != (S, S):
            continue
        ycc = codec.rgb_to_ycbcr(cells)
        small = cv2.resize(ycc[..., 1:], (S // FACTOR, S // FACTOR), interpolation=cv2.INTER_AREA)
        small = payload.dequantize(payload.quantize(small, QBITS), QBITS)  # exactly what the decoder receives
        out.append(((grid * 255).round().astype(np.uint8), small.astype(np.float16), target))
    return out


def init(args):
    global ARGS
    ARGS = args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--crops", type=int, default=20)
    ap.add_argument("--size", type=int, default=128, help="crop size in cells")
    ap.add_argument("--out", default="data/train2.npz")
    args = ap.parse_args()
    files = sorted(Path(args.src).glob("*.png")) + sorted(Path(args.src).glob("*.jpg"))
    with Pool(10, initializer=init, initargs=(args,)) as pool:
        res = []
        for i, r in enumerate(pool.imap_unordered(work, list(enumerate(files)), chunksize=2)):
            res += r
            if i % 20 == 0:
                print(f"{i}/{len(files)} images, {len(res)} samples", flush=True)
    grid, small, rgb = map(np.stack, zip(*res))
    np.savez(args.out, grid=grid, small=small, rgb=rgb)
    print("saved", args.out, grid.shape)


if __name__ == "__main__":
    main()
