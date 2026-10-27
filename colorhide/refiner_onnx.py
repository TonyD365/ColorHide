"""Run the trained refiner with ONNX Runtime (what the released apps ship instead of PyTorch).

Export from a PyTorch checkpoint:  python -m colorhide.refiner_onnx models/refiner.pt models/refiner.onnx
Both model generations load: v1 (inputs dots, small -> 1x) and v2 (inputs grid, small -> 2x).
"""
import sys
from pathlib import Path

import numpy as np

FACTOR = 8


def _pad(a, H, W):
    return np.pad(a, ((0, H - a.shape[0]), (0, W - a.shape[1])), mode="reflect")


def _pad_small(small, H, W):
    s = np.pad(small, ((0, H // FACTOR - small.shape[0]), (0, W // FACTOR - small.shape[1]), (0, 0)), mode="edge")
    return s.transpose(2, 0, 1)[None].astype(np.float32)


def load(path):
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inputs = {i.name for i in sess.get_inputs()}

    if "grid" in inputs:
        def apply(dots, small, grid):
            h, w = dots.shape
            H, W = -(-h // FACTOR) * FACTOR, -(-w // FACTOR) * FACTOR
            g = _pad(grid, 4 * H, 4 * W).astype(np.float32)[None, None]
            out = sess.run(None, {"grid": g, "small": _pad_small(small, H, W)})[0]
            return out[0].transpose(1, 2, 0)[:2 * h, :2 * w].astype(np.float64)

        apply.uses_grid = True
        apply.scale = 2
        return apply

    def apply_v1(dots, small):
        h, w = dots.shape
        H, W = -(-h // FACTOR) * FACTOR, -(-w // FACTOR) * FACTOR
        out = sess.run(None, {"dots": _pad(dots, H, W).astype(np.float32)[None, None],
                              "small": _pad_small(small, H, W)})[0]
        return out[0].transpose(1, 2, 0)[:h, :w].astype(np.float64)

    apply_v1.scale = 1
    return apply_v1


def export(src, dst):
    import onnxruntime as ort
    import torch

    from .refiner import Refiner, Refiner2
    state = torch.load(src, map_location="cpu")
    v2 = any(k.startswith("stem.") for k in state)
    net = Refiner2() if v2 else Refiner()
    net.load_state_dict(state)
    net.eval()
    first = "grid" if v2 else "dots"
    k = 4 if v2 else 1  # input pixels per cell
    s_out = 2 if v2 else 1
    d, s = torch.rand(1, 1, 64 * k, 96 * k), torch.rand(1, 2, 8, 12) - 0.5
    torch.onnx.export(net, (d, s), dst, input_names=[first, "small"], output_names=["rgb"],
                      dynamic_axes={first: {2: "H", 3: "W"}, "small": {2: "h", 3: "w"}, "rgb": {2: "Ho", 3: "Wo"}},
                      opset_version=17, dynamo=False)
    # check the ONNX graph against PyTorch on a different size
    d, s = torch.rand(1, 1, 128 * k, 200 * k), torch.rand(1, 2, 16, 25) - 0.5
    ref = net(d, s).detach().numpy()
    got = ort.InferenceSession(str(dst)).run(None, {first: d.numpy(), "small": s.numpy()})[0]
    assert got.shape[-1] == 200 * s_out
    print(f"exported {'v2' if v2 else 'v1'} {dst}, max diff vs torch {np.abs(ref - got).max():.2e}")


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]))
