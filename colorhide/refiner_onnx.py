"""Run the trained refiner with ONNX Runtime (what the released apps ship instead of PyTorch).

Export from a PyTorch checkpoint:  python -m colorhide.refiner_onnx models/refiner.pt models/refiner.onnx
"""
import sys
from pathlib import Path

import numpy as np

FACTOR = 8


def load(path):
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    def apply(dots, small):
        h, w = dots.shape
        H, W = -(-h // FACTOR) * FACTOR, -(-w // FACTOR) * FACTOR
        d = np.pad(dots, ((0, H - h), (0, W - w)), mode="reflect").astype(np.float32)[None, None]
        s = np.pad(small, ((0, H // FACTOR - small.shape[0]), (0, W // FACTOR - small.shape[1]), (0, 0)),
                   mode="edge").transpose(2, 0, 1)[None].astype(np.float32)
        out = sess.run(None, {"dots": d, "small": s})[0]
        return out[0].transpose(1, 2, 0)[:h, :w].astype(np.float64)

    return apply


def export(src, dst):
    import torch

    from .refiner import Refiner
    net = Refiner()
    net.load_state_dict(torch.load(src, map_location="cpu"))
    net.eval()
    d, s = torch.rand(1, 1, 64, 96), torch.rand(1, 2, 8, 12) - 0.5
    torch.onnx.export(net, (d, s), dst, input_names=["dots", "small"], output_names=["rgb"],
                      dynamic_axes={"dots": {2: "H", 3: "W"}, "small": {2: "h", 3: "w"}, "rgb": {2: "H", 3: "W"}},
                      opset_version=17, dynamo=False)
    # check the ONNX graph against PyTorch on a different size
    d, s = torch.rand(1, 1, 128, 200), torch.rand(1, 2, 16, 25) - 0.5
    ref = net(d, s).detach().numpy()
    import onnxruntime as ort
    got = ort.InferenceSession(str(dst)).run(None, {"dots": d.numpy(), "small": s.numpy()})[0]
    print(f"exported {dst}, max diff vs torch {np.abs(ref - got).max():.2e}")


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]))
