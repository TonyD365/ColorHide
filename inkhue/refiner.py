"""Scheme D: a small U-Net that turns (scanned dot map, low-res chroma) into a clean
full-resolution color image. It predicts a correction on top of the classical
reconstruction, so an untrained net already gives the baseline result.
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

_M = torch.tensor([[0.299, 0.587, 0.114],
                   [-0.168736, -0.331264, 0.5],
                   [0.5, -0.418688, -0.081312]])
_MI = torch.linalg.inv(_M)


def _gauss(sigma=1.0):
    r = int(3 * sigma)
    x = torch.arange(-r, r + 1, dtype=torch.float32)
    g = torch.exp(-x ** 2 / (2 * sigma ** 2))
    g = g / g.sum()
    return (g[:, None] * g[None, :])[None, None]


def _block(cin, cout):
    return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.GELU(),
                         nn.Conv2d(cout, cout, 3, padding=1), nn.GELU())


class Refiner(nn.Module):
    def __init__(self, ch=32, factor=8):
        super().__init__()
        self.factor = factor
        self.register_buffer("blur", _gauss(1.0))
        self.register_buffer("mi", _MI.clone())
        c1, c2, c3 = ch, ch * 2, ch * 4
        self.e1, self.e2, self.e3 = _block(4, c1), _block(c1, c2), _block(c2, c3)
        self.mid = _block(c3, c3)
        self.u3, self.d3 = nn.ConvTranspose2d(c3, c3, 2, 2), _block(c3 * 2, c2)
        self.u2, self.d2 = nn.ConvTranspose2d(c2, c2, 2, 2), _block(c2 * 2, c1)
        self.u1, self.d1 = nn.ConvTranspose2d(c1, c1, 2, 2), _block(c1 * 2, c1)
        self.out = nn.Conv2d(c1, 3, 1)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)

    def baseline(self, dots, small):
        """dots (B,1,H,W) ink fraction, small (B,2,h,w) chroma -> baseline YCbCr (B,3,H,W)."""
        y = 1 - F.conv2d(F.pad(dots, [3] * 4, mode="replicate"), self.blur)
        cbcr = F.interpolate(small, size=dots.shape[-2:], mode="bicubic", align_corners=False)
        return torch.cat([y, cbcr], 1)

    def forward(self, dots, small):
        base = self.baseline(dots, small)
        x1 = self.e1(torch.cat([dots, base], 1))
        x2 = self.e2(F.avg_pool2d(x1, 2))
        x3 = self.e3(F.avg_pool2d(x2, 2))
        m = self.mid(F.avg_pool2d(x3, 2))
        y = self.d3(torch.cat([self.u3(m), x3], 1))
        y = self.d2(torch.cat([self.u2(y), x2], 1))
        y = self.d1(torch.cat([self.u1(y), x1], 1))
        ycc = base + self.out(y)
        return torch.einsum("ij,bjhw->bihw", self.mi, ycc).clamp(0, 1)


class Refiner2(nn.Module):
    """v2: reads the scan at printer-dot resolution (4x4 dots per cell), where the detail-preserving
    halftone has stored sub-cell image detail, and outputs color at 2x the cell resolution.

    grid  (B,1,4H,4W) ink 0..1 per printer dot      dots (B,1,H,W) ink fraction per cell
    small (B,2,H/8,W/8) decoded chroma              ->  rgb (B,3,2H,2W)
    """

    uses_grid = True
    scale = 2

    def __init__(self, ch=32, factor=8):
        super().__init__()
        self.factor = factor
        self.register_buffer("blur", _gauss(2.0))
        self.register_buffer("mi", _MI.clone())
        c1, c2, c3 = ch, ch * 2, ch * 4
        # 4x -> 2x: learn to read dot placement instead of averaging it away
        self.stem = nn.Sequential(nn.Conv2d(1, 24, 3, padding=1), nn.GELU(),
                                  nn.Conv2d(24, c1, 4, stride=2, padding=1), nn.GELU())
        self.e1, self.e2, self.e3 = _block(c1 + 3, c1), _block(c1, c2), _block(c2, c3)
        self.mid = _block(c3, c3)
        self.u3, self.d3 = nn.ConvTranspose2d(c3, c3, 2, 2), _block(c3 * 2, c2)
        self.u2, self.d2 = nn.ConvTranspose2d(c2, c2, 2, 2), _block(c2 * 2, c1)
        self.u1, self.d1 = nn.ConvTranspose2d(c1, c1, 2, 2), _block(c1 * 2, c1)
        self.out = nn.Conv2d(c1, 3, 1)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)

    def baseline(self, grid, small):
        """Classic reconstruction at 2x: ink averaged over 2x2 dots and low-passed, chroma upsampled."""
        d2 = F.avg_pool2d(grid, 2)
        y = 1 - F.conv2d(F.pad(d2, [6] * 4, mode="replicate"), self.blur)
        cbcr = F.interpolate(small, size=d2.shape[-2:], mode="bicubic", align_corners=False)
        return torch.cat([y, cbcr], 1)

    def forward(self, grid, small):
        base = self.baseline(grid, small)
        x1 = self.e1(torch.cat([self.stem(grid), base], 1))
        x2 = self.e2(F.avg_pool2d(x1, 2))
        x3 = self.e3(F.avg_pool2d(x2, 2))
        m = self.mid(F.avg_pool2d(x3, 2))
        y = self.d3(torch.cat([self.u3(m), x3], 1))
        y = self.d2(torch.cat([self.u2(y), x2], 1))
        y = self.d1(torch.cat([self.u1(y), x1], 1))
        ycc = base + self.out(y)
        return torch.einsum("ij,bjhw->bihw", self.mi, ycc).clamp(0, 1)


def device():
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def load(path):
    dev = device()
    state = torch.load(path, map_location=dev)
    if any(k.startswith("stem.") for k in state):
        return _load_v2(state, dev)
    net = Refiner().to(dev)
    net.load_state_dict(state)
    net.eval()

    @torch.no_grad()
    def apply(dots, small):
        h, w = dots.shape
        f = net.factor
        H, W = -(-h // f) * f, -(-w // f) * f  # pad so chroma cells line up and the U-Net divides evenly
        d = np.pad(dots, ((0, H - h), (0, W - w)), mode="reflect")
        s = np.pad(small, ((0, H // f - small.shape[0]), (0, W // f - small.shape[1]), (0, 0)), mode="edge")
        dt = torch.from_numpy(d).float()[None, None].to(dev)
        st = torch.from_numpy(s.transpose(2, 0, 1).copy()).float()[None].to(dev)
        return net(dt, st)[0].permute(1, 2, 0).cpu().numpy()[:h, :w].astype(np.float64)

    return apply


def _load_v2(state, dev):
    net = Refiner2().to(dev)
    net.load_state_dict(state)
    net.eval()
    f = net.factor

    @torch.no_grad()
    def apply(dots, small, grid):
        h, w = dots.shape
        H, W = -(-h // f) * f, -(-w // f) * f
        g = np.pad(grid, ((0, 4 * (H - h)), (0, 4 * (W - w))), mode="reflect")
        s = np.pad(small, ((0, H // f - small.shape[0]), (0, W // f - small.shape[1]), (0, 0)), mode="edge")
        gt = torch.from_numpy(g).float()[None, None].to(dev)
        st = torch.from_numpy(s.transpose(2, 0, 1).copy()).float()[None].to(dev)
        return net(gt, st)[0].permute(1, 2, 0).cpu().numpy()[:2 * h, :2 * w].astype(np.float64)

    apply.uses_grid = True
    apply.scale = 2
    return apply
