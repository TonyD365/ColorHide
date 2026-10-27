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
from inkhue import channel, codec, halftone, payload

FACTOR, QBITS, K = 8, 6, halftone.K
ARGS = None


DOC_COLORS = [(20, 20, 20), (60, 60, 65), (30, 40, 200), (25, 25, 135), (200, 30, 30), (20, 130, 60),
              (120, 40, 160), (230, 110, 20), (0, 120, 180)]
HIGHLIGHTS = [(255, 240, 110), (170, 235, 160), (180, 215, 255), (255, 200, 220)]


def synth_document(rng, r):
    """An r x r patch of a document as printed at full page width: white paper, text lines in black or
    in color (strokes ~1-2 cells wide), highlights, rules, boxes, chart bars."""
    doc = np.full((r, r, 3), 255, np.uint8)
    px_per_cell = r / ARGS.size
    y = int(rng.integers(0, int(12 * px_per_cell)))
    while y < r:
        kind = rng.random()
        if kind < 0.7:  # a line of text
            scale = rng.uniform(0.3, 0.7) * px_per_cell  # 10-14 pt text at full page width, some headings
            thick = max(1, int(round(rng.uniform(0.6, 1.8) * px_per_cell)))  # strokes ~1-2 cells
            col = DOC_COLORS[rng.integers(len(DOC_COLORS))] if rng.random() < 0.6 else (20, 20, 20)
            text = "".join(rng.choice(list("abcdefghijklmnopqrstuvwxyz ABCDEFGHIJK.,0123456789"),
                                      int(rng.integers(20, 60))))
            h = int(30 * scale)
            x0 = int(rng.integers(0, int(6 * px_per_cell)))
            if rng.random() < 0.15:
                cv2.rectangle(doc, (x0, y - int(0.3 * h)), (x0 + int(rng.uniform(0.3, 1.0) * r), y + h + int(0.3 * h)),
                              HIGHLIGHTS[rng.integers(len(HIGHLIGHTS))], -1)
            cv2.putText(doc, text, (x0, y + h), cv2.FONT_HERSHEY_SIMPLEX if rng.random() < 0.7
                        else cv2.FONT_HERSHEY_DUPLEX, scale, col, thick, cv2.LINE_AA)
            y += int(h * rng.uniform(1.6, 2.4))
        elif kind < 0.8:  # rule or box outline
            col = (20, 20, 20) if rng.random() < 0.7 else DOC_COLORS[rng.integers(len(DOC_COLORS))]
            t = max(1, int(round(rng.uniform(0.2, 0.6) * px_per_cell)))
            y2 = y + int(rng.uniform(0.05, 0.5) * r)
            cv2.rectangle(doc, (int(rng.integers(0, r // 4)), y), (int(rng.integers(r // 2, r)), y2), col, t)
            y += int(rng.uniform(4, 10) * px_per_cell)
        else:  # chart bars / solid color blocks
            x = int(rng.integers(0, r // 3))
            base = y + int(rng.uniform(0.2, 0.5) * r)
            for _ in range(int(rng.integers(2, 6))):
                w = int(rng.uniform(4, 14) * px_per_cell)
                hgt = int(rng.uniform(0.1, 0.4) * r)
                cv2.rectangle(doc, (x, base - hgt), (x + w, base), DOC_COLORS[rng.integers(2, len(DOC_COLORS))], -1)
                x += w + int(rng.uniform(2, 6) * px_per_cell)
            y = base + int(rng.uniform(4, 10) * px_per_cell)
    return doc


def make_sample(region, rng, seed):
    """Encode `region` as S x S cells, simulate print + scan, return the training tuple or None."""
    S = ARGS.size
    r = region.shape[0]
    cells = cv2.resize(region, (S, S), interpolation=cv2.INTER_AREA).astype(np.float64) / 255
    hi = cv2.resize(region, (K * S, K * S), interpolation=cv2.INTER_AREA if r >= K * S else cv2.INTER_CUBIC)
    luma = np.clip(codec.rgb_to_ycbcr(hi.astype(np.float64) / 255)[..., 0], 0, 1)
    target = cv2.resize(region, (2 * S, 2 * S), interpolation=cv2.INTER_AREA)
    page, info = codec.encode(cells, factor=FACTOR, qbits=QBITS, luma_detail=luma)
    scan = channel.print_scan(page, seed=seed,
                              scale=rng.uniform(1.0, 3.0), rotate=2.0,
                              blur=rng.uniform(0.4, 1.0), dot_gain=rng.uniform(0.0, 0.25),
                              noise=rng.uniform(0.01, 0.05), gamma=rng.uniform(0.8, 1.3),
                              jpeg=int(rng.integers(75, 96)))
    try:
        grid, _, _, h, w = codec.demodulate_full(scan)
    except Exception:
        return None
    if (h, w) != (S, S):
        return None
    ycc = codec.rgb_to_ycbcr(cells)
    small = cv2.resize(ycc[..., 1:], (S // FACTOR, S // FACTOR), interpolation=cv2.INTER_AREA)
    small = payload.dequantize(payload.quantize(small, QBITS), QBITS)  # exactly what the decoder receives
    return (grid * 255).round().astype(np.uint8), small.astype(np.float16), target, bool(info["ink_floor"])


def work(job):
    idx, path = job
    rng = np.random.default_rng(idx)
    S = ARGS.size
    out = []
    if path is None:  # a synthetic document
        for k in range(ARGS.crops):
            smp = make_sample(synth_document(rng, 4 * S), rng, idx * 100 + k)
            if smp:
                out.append(smp)
        return out
    img = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    for k in range(ARGS.crops):
        # a region of 2S..4S photo pixels becomes S cells: photos are printed at many sizes
        r = int(rng.uniform(2 * S, min(4 * S, *img.shape[:2])))
        y0, x0 = rng.integers(0, img.shape[0] - r + 1), rng.integers(0, img.shape[1] - r + 1)
        smp = make_sample(img[y0:y0 + r, x0:x0 + r], rng, idx * 100 + k)
        if smp:
            out.append(smp)
    return out


def init(args):
    global ARGS
    ARGS = args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--crops", type=int, default=20)
    ap.add_argument("--size", type=int, default=128, help="crop size in cells")
    ap.add_argument("--documents", type=int, default=0, help="also make this many synthetic document jobs")
    ap.add_argument("--out", default="data/train2.npz")
    args = ap.parse_args()
    files = sorted(Path(args.src).glob("*.png")) + sorted(Path(args.src).glob("*.jpg"))
    with Pool(10, initializer=init, initargs=(args,)) as pool:
        res = []
        jobs = list(enumerate(files)) + [(len(files) + i, None) for i in range(args.documents)]
        for i, r in enumerate(pool.imap_unordered(work, jobs, chunksize=2)):
            res += r
            if i % 20 == 0:
                print(f"{i}/{len(files)} images, {len(res)} samples", flush=True)
    grid, small, rgb, floor = map(np.stack, zip(*res))
    np.savez(args.out, grid=grid, small=small, rgb=rgb, floor=floor)
    print(f"{floor.sum()} of {len(floor)} samples use the 1..15-dot document encoding")
    print("saved", args.out, grid.shape)


if __name__ == "__main__":
    main()
