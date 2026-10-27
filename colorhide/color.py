"""RGB <-> YCbCr (BT.601 full range). Y in [0,1], Cb/Cr in [-0.5,0.5]."""
import numpy as np

_M = np.array([[0.299, 0.587, 0.114],
               [-0.168736, -0.331264, 0.5],
               [0.5, -0.418688, -0.081312]])
_MI = np.linalg.inv(_M)


def rgb_to_ycbcr(rgb):
    return rgb @ _M.T


def ycbcr_to_rgb(ycc):
    return np.clip(ycc @ _MI.T, 0.0, 1.0)
