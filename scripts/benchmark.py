"""Reproducible codec benchmark: fixed public-domain photos x fixed print/scan conditions x fixed seeds.

  python scripts/benchmark.py --out bench.json                 # run
  python scripts/benchmark.py --compare base.json bench.json   # markdown diff (for PR comments)

Metrics per condition: decode success rate, raw channel bit error rate, colour error (CIEDE2000,
lower is better) and PSNR for the classic and neural decoders, plus encode/decode time.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
from skimage import color as skcolor
from skimage import data as skdata

from colorhide import api, channel, codec, payload

# scikit-image sample photos: public domain / CC0
IMAGES = ["astronaut", "coffee", "chelsea", "rocket"]
SEEDS = [1, 2, 3]
WIDTH_IN = 3.0
CONDITIONS = {
    "ideal": dict(scale=2.0, rotate=0.0, persp=0.0, blur=0.4, dot_gain=0.0, noise=0.01, gamma=1.0, jpeg=98),
    "typical": dict(scale=2.0, rotate=1.5, persp=0.004, blur=0.7, dot_gain=0.15, noise=0.03, gamma=1.1, jpeg=90),
    "harsh": dict(scale=1.6, rotate=2.5, persp=0.008, blur=1.0, dot_gain=0.25, noise=0.05, gamma=1.3, jpeg=75),
    "600dpi scan": dict(scale=1.0, rotate=0.5, persp=0.002, blur=0.6, dot_gain=0.1, noise=0.02, gamma=1.0, jpeg=92),
}


def delta_e(a, b):
    return float(skcolor.deltaE_ciede2000(skcolor.rgb2lab(a / 255.0), skcolor.rgb2lab(b / 255.0)).mean())


def psnr(a, b):
    return float(10 * np.log10(255.0 ** 2 / np.mean((a.astype(float) - b.astype(float)) ** 2)))


def run():
    refiner = api.load_refiner()
    rows = []
    for name in IMAGES:
        rgb = getattr(skdata, name)()
        t = time.perf_counter()
        page, info = api.encode(rgb, width_in=WIDTH_IN, dpi=600)
        t_enc = time.perf_counter() - t
        cw, ch = info["cells"]
        ref = cv2.resize(rgb, (cw, ch), interpolation=cv2.INTER_AREA)
        ycc = codec.rgb_to_ycbcr(ref / 255.0)
        sh = payload.chroma_shape(ch, cw, 8)
        small = cv2.resize(ycc[..., 1:], (sh[1], sh[0]), interpolation=cv2.INTER_AREA)
        sent, _ = payload.encode_bits(payload.quantize(small.transpose(2, 0, 1), 6), 8, 6, ch * cw * 2)
        for cond, params in CONDITIONS.items():
            for seed in SEEDS:
                scan = channel.print_scan(page, seed=seed, **params)
                row = dict(image=name, condition=cond, seed=seed, encode_s=t_enc, ok=False)
                try:
                    _, soft, h, w = codec.demodulate(scan)
                    if (h, w) == (ch, cw):
                        row["ber"] = float(np.mean((soft > 0) != sent))
                    t = time.perf_counter()
                    out, dinfo = api.decode(scan, None)
                    row["decode_s"] = time.perf_counter() - t
                    row["ok"] = bool(dinfo["rs_ok"])
                    row["de_classic"], row["psnr_classic"] = delta_e(ref, out), psnr(ref, out)
                    if refiner is not None:
                        out_n, _ = api.decode(scan, refiner)
                        row["de_neural"], row["psnr_neural"] = delta_e(ref, out_n), psnr(ref, out_n)
                except Exception as ex:  # a failed decode is a result, not a crash
                    row["error"] = str(ex)
                rows.append(row)
                print(f"{name:10s} {cond:12s} seed {seed}  ok={row['ok']}  "
                      f"ΔE {row.get('de_classic', float('nan')):.2f}/{row.get('de_neural', float('nan')):.2f}",
                      flush=True)
    return dict(meta=dict(python=platform.python_version(), machine=platform.machine(), system=platform.system(),
                          refiner=refiner is not None, images=IMAGES, seeds=SEEDS, width_in=WIDTH_IN), rows=rows)


def summarize(result):
    out = {}
    for cond in CONDITIONS:
        rs = [r for r in result["rows"] if r["condition"] == cond]
        def mean(k, rs=rs):
            vals = [r[k] for r in rs if k in r]
            return float(np.mean(vals)) if vals else None
        out[cond] = dict(success=sum(r["ok"] for r in rs) / len(rs), ber=mean("ber"),
                         de_classic=mean("de_classic"), de_neural=mean("de_neural"),
                         psnr_classic=mean("psnr_classic"), psnr_neural=mean("psnr_neural"),
                         decode_s=mean("decode_s"))
    out["_encode_s"] = float(np.mean([r["encode_s"] for r in result["rows"]]))
    return out


def fmt(v, kind):
    if v is None:
        return "—"
    return {"pct": f"{v:.0%}", "ber": f"{v:.2%}", "de": f"{v:.2f}", "db": f"{v:.1f}", "s": f"{v:.2f}s"}[kind]


COLS = [("success", "Decoded", "pct", +1), ("ber", "Raw BER", "ber", -1), ("de_classic", "ΔE classic", "de", -1),
        ("de_neural", "ΔE neural", "de", -1), ("psnr_neural", "PSNR neural", "db", +1), ("decode_s", "Decode", "s", -1)]


def table(summary, base=None):
    lines = ["| Condition | " + " | ".join(c[1] for c in COLS) + " |", "|---" * (len(COLS) + 1) + "|"]
    for cond in CONDITIONS:
        cells = []
        for key, _, kind, better in COLS:
            v = summary[cond][key]
            cell = fmt(v, kind)
            if base is not None and v is not None and base[cond][key] is not None:
                b = base[cond][key]
                rel = (v - b) / abs(b) if b else 0.0
                if key != "decode_s" and abs(rel) >= 0.02 or key == "decode_s" and abs(rel) >= 0.25:
                    cell += " 🟢" if rel * better > 0 else " 🔴"
                cell += f"<br><sub>was {fmt(b, kind)}</sub>"
            cells.append(cell)
        lines.append(f"| **{cond}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def compare(base_path, head_path):
    base, head = summarize(json.load(open(base_path))), summarize(json.load(open(head_path)))
    regressions = [c for c in CONDITIONS if head[c]["success"] < base[c]["success"]]
    md = ["<!-- colorhide-benchmark -->", "## 📊 Codec benchmark", "",
          f"{len(IMAGES)} public-domain photos × {len(SEEDS)} seeds per condition, simulated print + scan. "
          "ΔE is CIEDE2000 colour error (lower is better). 🟢/🔴 = better/worse than the base branch.", "",
          table(head, base), ""]
    if regressions:
        md.append(f"> [!WARNING]\n> Decode success dropped under: **{', '.join(regressions)}**")
    else:
        md.append("✅ No decode-success regressions.")
    return "\n".join(md), bool(regressions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench.json")
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "HEAD"))
    ap.add_argument("--markdown", help="write the comparison / summary markdown here")
    ap.add_argument("--fail-on-regression", action="store_true")
    args = ap.parse_args()
    if args.compare:
        md, regressed = compare(*args.compare)
        print(md)
        if args.markdown:
            Path(args.markdown).write_text(md + "\n")
        sys.exit(1 if regressed and args.fail_on_regression else 0)
    result = run()
    Path(args.out).write_text(json.dumps(result, indent=1))
    md = "## 📊 Codec benchmark\n\n" + table(summarize(result))
    print("\n" + md)
    if args.markdown:
        Path(args.markdown).write_text(md + "\n")


if __name__ == "__main__":
    main()
