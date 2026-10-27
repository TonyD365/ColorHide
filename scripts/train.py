"""Train the v2 refiner (printer-dot input, 2x output) on the M-series GPU (MPS).

usage: python scripts/train.py [--steps 3000] [--bs 16] [--crop 64]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inkhue.refiner import Refiner2, device  # noqa: E402

K = 4  # printer dots per cell side


def to_gpu(data, idx, dev):
    """Whole split as float16 tensors in (unified) GPU memory: no per-step host copies."""
    floor = data["floor"][idx] if "floor" in data else np.zeros(len(idx), bool)
    return (torch.from_numpy(data["grid"][idx]).to(dev)[:, None],
            torch.from_numpy(data["small"][idx]).to(dev).permute(0, 3, 1, 2),
            torch.from_numpy(data["rgb"][idx]).to(dev).permute(0, 3, 1, 2),
            torch.from_numpy(floor).to(dev))


def floor_correct(net, rgb, floor):
    """Documents print 1..15 dots per cell; the app rescales the refiner's brightness for them
    (codec.decode). Apply the same here so the loss sees what the user sees."""
    if not bool(floor.any()):
        return rgb
    ycc = torch.einsum("ij,bjhw->bihw", torch.linalg.inv(net.mi), rgb)
    y = (1 - (16 * (1 - ycc[:, :1]) - 1) / 14).clamp(0, 1)
    fixed = torch.einsum("ij,bjhw->bihw", net.mi, torch.cat([y, ycc[:, 1:]], 1)).clamp(0, 1)
    return torch.where(floor[:, None, None, None], fixed, rgb)


def batches(gpu, bs, crop, g, factor=8):
    """Random crops of `crop` cells aligned to the chroma blocks, random mirror.
    grid is at K x the cell resolution, the target at 2x."""
    grid, small, rgb, floor = gpu
    n, S = grid.shape[0], grid.shape[-1] // K
    while True:
        b = torch.randint(0, n, (bs,), generator=g)
        y0, x0 = (torch.randint(0, (S - crop) // factor + 1, (2,), generator=g) * factor).tolist()
        c0, c1 = y0 // factor, x0 // factor
        d = grid[b, :, K * y0:K * (y0 + crop), K * x0:K * (x0 + crop)].float() / 255
        s = small[b, :, c0:c0 + crop // factor, c1:c1 + crop // factor].float()
        t = rgb[b, :, 2 * y0:2 * (y0 + crop), 2 * x0:2 * (x0 + crop)].float() / 255
        if torch.rand(1, generator=g).item() < 0.5:
            d, s, t = d.flip(-1), s.flip(-1), t.flip(-1)
        yield d, s, t, floor[b.to(floor.device)]


def psnr(a, b):
    return (10 * torch.log10(1 / F.mse_loss(a, b))).item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/train2.npz")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--crop", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", default="models/refiner.pt")
    ap.add_argument("--init", help="start from this checkpoint (fine-tune) instead of from scratch")
    args = ap.parse_args()

    dev = device()
    data = dict(np.load(args.data))
    n = len(data["grid"])
    rng = np.random.default_rng(0)
    perm = rng.permutation(n)
    nval = min(max(64, n // 20), n // 5)
    val, tr = perm[:nval], perm[nval:]
    print(f"device {dev}, {len(tr)} train / {len(val)} val samples")

    net = Refiner2().to(dev)
    if args.init:
        net.load_state_dict(torch.load(args.init, map_location=dev))
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, args.lr, total_steps=args.steps, pct_start=0.05)
    gtr = to_gpu(data, tr, dev)
    vd, vs, vt, vf = to_gpu(data, val, dev)
    vb = (vd.float() / 255, vs.float(), vt.float() / 255, vf)
    scaler = torch.amp.GradScaler("mps")

    @torch.no_grad()
    def evaluate():
        net.eval()
        out_net, out_base = [], []
        for i in range(0, len(val), 16):
            d, s, f = vb[0][i:i + 16], vb[1][i:i + 16], vb[3][i:i + 16]
            out_net.append(floor_correct(net, net(d, s), f))
            base = torch.einsum("ij,bjhw->bihw", net.mi, net.baseline(d, s)).clamp(0, 1)
            out_base.append(floor_correct(net, base, f))
        net.train()
        return psnr(torch.cat(out_net), vb[2]), psnr(torch.cat(out_base), vb[2])

    Path(args.out).parent.mkdir(exist_ok=True)
    best, t0 = 0, time.time()
    g = torch.Generator().manual_seed(0)
    for step, (d, s, t, f) in enumerate(batches(gtr, args.bs, args.crop, g), 1):
        with torch.autocast("mps", dtype=torch.float16):  # half precision: ~1.5x faster on Apple GPUs
            out = net(d, s)
        loss = F.l1_loss(floor_correct(net, out.float(), f), t)
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
