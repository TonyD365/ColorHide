"""Train the refiner on the M-series GPU (MPS).

usage: python scripts/train.py [--steps 3000] [--bs 32] [--crop 128]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide.refiner import Refiner, device  # noqa: E402


def to_gpu(data, idx, dev):
    """Whole split as float16 tensors in (unified) GPU memory: no per-step host copies."""
    return (torch.from_numpy(data["dots"][idx]).to(dev)[:, None],
            torch.from_numpy(data["small"][idx]).to(dev).permute(0, 3, 1, 2),
            torch.from_numpy(data["rgb"][idx]).to(dev).permute(0, 3, 1, 2))


def batches(gpu, bs, crop, g, factor=8):
    """Random crops aligned to the chroma cells, random mirror."""
    dots, small, rgb = gpu
    n, S = dots.shape[0], dots.shape[-1]
    while True:
        b = torch.randint(0, n, (bs,), generator=g)
        y0, x0 = (torch.randint(0, (S - crop) // factor + 1, (2,), generator=g) * factor).tolist()
        c0, c1 = y0 // factor, x0 // factor
        d = dots[b, :, y0:y0 + crop, x0:x0 + crop].float()
        s = small[b, :, c0:c0 + crop // factor, c1:c1 + crop // factor].float()
        t = rgb[b, :, y0:y0 + crop, x0:x0 + crop].float() / 255
        if torch.rand(1, generator=g).item() < 0.5:
            d, s, t = d.flip(-1), s.flip(-1), t.flip(-1)
        yield d, s, t


def psnr(a, b):
    return (10 * torch.log10(1 / F.mse_loss(a, b))).item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/train.npz")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--crop", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", default="models/refiner.pt")
    args = ap.parse_args()

    dev = device()
    data = dict(np.load(args.data))
    n = len(data["dots"])
    rng = np.random.default_rng(0)
    perm = rng.permutation(n)
    nval = min(max(64, n // 20), n // 5)
    val, tr = perm[:nval], perm[nval:]
    print(f"device {dev}, {len(tr)} train / {len(val)} val samples")

    net = Refiner().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, args.lr, total_steps=args.steps, pct_start=0.05)
    gtr = to_gpu(data, tr, dev)
    vd, vs, vt = to_gpu(data, val, dev)
    vb = (vd.float(), vs.float(), vt.float() / 255)
    scaler = torch.amp.GradScaler("mps")

    @torch.no_grad()
    def evaluate():
        net.eval()
        out_net, out_base = [], []
        for i in range(0, len(val), 16):
            d, s = vb[0][i:i + 16], vb[1][i:i + 16]
            out_net.append(net(d, s))
            out_base.append(torch.einsum("ij,bjhw->bihw", net.mi, net.baseline(d, s)).clamp(0, 1))
        net.train()
        return psnr(torch.cat(out_net), vb[2]), psnr(torch.cat(out_base), vb[2])

    Path(args.out).parent.mkdir(exist_ok=True)
    best, t0 = 0, time.time()
    g = torch.Generator().manual_seed(0)
    for step, (d, s, t) in enumerate(batches(gtr, args.bs, args.crop, g), 1):
        with torch.autocast("mps", dtype=torch.float16):  # half precision: ~1.5x faster on Apple GPUs
            out = net(d, s)
        loss = F.l1_loss(out.float(), t)
        opt.zero_grad()
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        if step % 500 == 0 or step == args.steps:
            pn, pb = evaluate()
            if pn > best:
                best = pn
                torch.save(net.state_dict(), args.out)
            print(f"step {step:5d}  loss {loss.item():.4f}  val PSNR {pn:.2f} dB (baseline {pb:.2f})  "
                  f"{time.time() - t0:.0f}s", flush=True)
        if step == args.steps:
            break
    print("best val PSNR", best, "saved", args.out)


if __name__ == "__main__":
    main()
