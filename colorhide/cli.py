"""Command line interface. Prints one JSON line.

  python -m colorhide.cli encode photo.jpg page.png --width-in 6 [--dpi 600]
  python -m colorhide.cli decode scan.png color.png [--refiner models/refiner.pt | --no-refiner]
  python -m colorhide.cli simulate page.png scan.png   # software print+scan, for testing without hardware
"""
import argparse
import json
import sys
import time

import cv2
import numpy as np
from PIL import Image

from . import api, channel
from .api import load_refiner


def _read_rgb(path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def encode(args):
    page, info = api.encode(_read_rgb(args.input), args.width_in, args.dpi, args.factor)
    Image.fromarray(page).convert("1").save(args.output, dpi=(args.dpi, args.dpi))
    return dict(output=str(args.output), pixels=[page.shape[1], page.shape[0]], **info)


def decode(args):
    gray = cv2.imread(str(args.input), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"cannot read image {args.input}")
    refiner = None if args.no_refiner else load_refiner(args.refiner)
    rgb, info = api.decode(gray, refiner)
    cv2.imwrite(str(args.output), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return dict(output=str(args.output), pixels=[rgb.shape[1], rgb.shape[0]], refiner=refiner is not None, **info)


def simulate(args):
    page = cv2.imread(str(args.input), cv2.IMREAD_GRAYSCALE)
    if page is None:
        raise ValueError(f"cannot read image {args.input}")
    scan = channel.print_scan(page, scale=args.scale, seed=args.seed)
    cv2.imwrite(str(args.output), scan)
    return dict(output=str(args.output), pixels=[scan.shape[1], scan.shape[0]])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="colorhide")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode", help="color image -> black-and-white page hiding the color")
    e.add_argument("input")
    e.add_argument("output")
    e.add_argument("--width-in", type=float, default=6.0, help="printed width in inches")
    e.add_argument("--dpi", type=int, default=600, help="printer's native resolution")
    e.add_argument("--factor", type=int, default=8, help="chroma downscale factor")
    d = sub.add_parser("decode", help="scan -> color image")
    d.add_argument("input")
    d.add_argument("output")
    d.add_argument("--refiner")
    d.add_argument("--no-refiner", action="store_true")
    s = sub.add_parser("simulate", help="software print+scan of a page")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--scale", type=float, default=2.0, help="scan px per printer dot")
    s.add_argument("--seed", type=int)
    args = ap.parse_args(argv)
    t = time.time()
    try:
        res = dict(encode=encode, decode=decode, simulate=simulate)[args.cmd](args)
        res.update(ok=True, seconds=round(time.time() - t, 2))
    except Exception as ex:  # report to the app instead of a traceback
        res = dict(ok=False, error=f"{type(ex).__name__}: {ex}")
    print(json.dumps(res), flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
