"""Reproducible codec benchmark: fixed public-domain photos x fixed print/scan conditions x fixed seeds.

  python scripts/benchmark.py --out bench.json                 # run
  python scripts/benchmark.py --compare base.json bench.json   # markdown diff (for PR comments)

Metrics per condition: decode success rate, raw channel bit error rate, colour error (CIEDE2000 at
cell resolution, lower is better) for the classic and neural decoders, detail (PSNR against the photo
at 2x cell resolution; 1x outputs are upscaled first), and decode time. Per run: print sharpness, the
SSIM between the printed page as the eye sees it and the photo.
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

try:
    from inkhue import api, channel, codec, halftone, layout, payload
except ImportError:  # CI runs this script against the base branch too, which may predate the rename
    from colorhide import api, channel, codec, halftone, layout, payload

# scikit-image sample photos (public domain / CC0), plus a mostly white text document
IMAGES = ["astronaut", "coffee", "chelsea", "rocket", "document"]


def sample_document(w=850, h=1100):
    """A page of notes: white paper, black text, a colored title, a highlighter mark, a colored chart."""
    doc = np.full((h, w, 3), 255, np.uint8)
    cv2.putText(doc, "Meeting notes", (60, 110), cv2.FONT_HERSHEY_DUPLEX, 2.0, (230, 100, 40), 3)
    for i in range(14):
        y = 190 + 40 * i
        cv2.putText(doc, "The quick brown fox jumps over the lazy dog.", (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    (30, 30, 30) if i % 5 else (40, 70, 200), 2)
    cv2.rectangle(doc, (55, 395), (520, 425), (255, 240, 120), -1)  # highlighter, under the text
    cv2.putText(doc, "Remember to bring the color samples!", (60, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (30, 30, 30), 2)
    for i, (hgt, col) in enumerate(((180, (220, 60, 60)), (260, (60, 160, 90)), (120, (60, 110, 220)),
                                    (220, (240, 170, 40)))):
        cv2.rectangle(doc, (90 + i * 150, 1040 - hgt), (190 + i * 150, 1040), col, -1)
    return doc
SEEDS = [1, 2, 3]
WIDTH_IN = 3.0
CONDITIONS = {
    "ideal": dict(scale=2.0, rotate=0.0, persp=0.0, blur=0.4, dot_gain=0.0, noise=0.01, gamma=1.0, jpeg=98),
    "typical": dict(scale=2.0, rotate=1.5, persp=0.004, blur=0.7, dot_gain=0.15, noise=0.03, gamma=1.1, jpeg=90),
    "harsh": dict(scale=1.6, rotate=2.5, persp=0.008, blur=1.0, dot_gain=0.25, noise=0.05, gamma=1.3, jpeg=75),
    "600dpi scan": dict(scale=1.0, rotate=0.5, persp=0.002, blur=0.6, dot_gain=0.1, noise=0.02, gamma=1.0, jpeg=92),
    # typical, plus pen marks: 30 strokes over the image and 4 across the frame / timing track
    "handwriting": dict(scale=2.0, rotate=1.5, persp=0.004, blur=0.7, dot_gain=0.15, noise=0.03, gamma=1.1, jpeg=90,
                        scribble=True),
}


def delta_e(a, b):
    from skimage import color as skcolor  # scikit-image only when actually benchmarking (tests import this file)
    return float(skcolor.deltaE_ciede2000(skcolor.rgb2lab(a / 255.0), skcolor.rgb2lab(b / 255.0)).mean())


def psnr(a, b):
    return float(10 * np.log10(255.0 ** 2 / np.mean((a.astype(float) - b.astype(float)) ** 2)))


def print_sharpness(page, rgb, cw, ch):
    """The page as the eye sees it at reading distance (Gaussian, sigma 1.5 dots at 600 dpi) vs the photo."""
    from skimage.metrics import structural_similarity
    k, off = halftone.K, (layout.QUIET + layout.B) * halftone.K
    ink = (page < 128).astype(float)[off:off + ch * k, off:off + cw * k]
    seen = 1 - cv2.GaussianBlur(ink, (0, 0), 1.5)
    hi = cv2.resize(rgb, (cw * k, ch * k), interpolation=cv2.INTER_CUBIC) / 255.0
    return float(structural_similarity(seen, np.clip(codec.rgb_to_ycbcr(hi)[..., 0], 0, 1), data_range=1))


def _at(img, w, h):
    interp = cv2.INTER_AREA if img.shape[1] > w else cv2.INTER_CUBIC
    return np.clip(cv2.resize(img, (w, h), interpolation=interp), 0, 255)


def run():
    from skimage import data as skdata
    refiner = api.load_refiner()
    rows = []
    for name in IMAGES:
        rgb = sample_document() if name == "document" else getattr(skdata, name)()
        t = time.perf_counter()
        page, info = api.encode(rgb, width_in=WIDTH_IN, dpi=600)
        t_enc = time.perf_counter() - t
        cw, ch = info["cells"]
        ref = cv2.resize(rgb, (cw, ch), interpolation=cv2.INTER_AREA)
        ref2 = cv2.resize(rgb, (2 * cw, 2 * ch), interpolation=cv2.INTER_AREA)
        sharp = print_sharpness(page, rgb, cw, ch)
        ycc = codec.rgb_to_ycbcr(ref / 255.0)
        sh = payload.chroma_shape(ch, cw, 8)
        small = cv2.resize(ycc[..., 1:], (sh[1], sh[0]), interpolation=cv2.INTER_AREA)
        sent, _ = payload.encode_bits(payload.quantize(small.transpose(2, 0, 1), 6), 8, 6, ch * cw * 2)
        for cond, params in CONDITIONS.items():
            params = dict(params)
            marked = page
            if params.pop("scribble", False):
                if not hasattr(channel, "scribble"):
                    continue  # older code under test has no pen-mark simulator
                marked = channel.scribble(page, np.random.default_rng(100 + SEEDS[0]))
            for seed in SEEDS:
                scan = channel.print_scan(marked, seed=seed, **params)
                row = dict(image=name, condition=cond, seed=seed, encode_s=t_enc, ok=False, print_ssim=sharp)
                try:
                    _, soft, h, w = codec.demodulate(scan)
                    if (h, w) == (ch, cw):
                        row["ber"] = float(np.mean((soft > 0) != sent))
                    t = time.perf_counter()
                    out, dinfo = api.decode(scan, None)
                    row["decode_s"] = time.perf_counter() - t
                    row["ok"] = bool(dinfo["rs_ok"])
                    row["de_classic"] = delta_e(ref, _at(out, cw, ch))
                    row["psnr2x_classic"] = psnr(ref2, _at(out, 2 * cw, 2 * ch))
                    if refiner is not None:
                        out_n, _ = api.decode(scan, refiner)
                        row["scale_neural"] = out_n.shape[1] / cw
                        row["de_neural"] = delta_e(ref, _at(out_n, cw, ch))
                        row["psnr2x_neural"] = psnr(ref2, _at(out_n, 2 * cw, 2 * ch))
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
        if not rs:
            out[cond] = dict.fromkeys(["success", "ber", "de_classic", "de_neural", "psnr2x_classic",
                                       "psnr2x_neural", "decode_s"])
            continue
        def mean(k, rs=rs):
            vals = [r[k] for r in rs if k in r]
            return float(np.mean(vals)) if vals else None
        out[cond] = dict(success=sum(r["ok"] for r in rs) / len(rs), ber=mean("ber"),
                         de_classic=mean("de_classic"), de_neural=mean("de_neural"),
                         psnr2x_classic=mean("psnr2x_classic"), psnr2x_neural=mean("psnr2x_neural"),
                         decode_s=mean("decode_s"))
    out["_encode_s"] = float(np.mean([r["encode_s"] for r in result["rows"]]))
    sharp = [r["print_ssim"] for r in result["rows"] if "print_ssim" in r]
    out["_print_ssim"] = float(np.mean(sharp)) if sharp else None
    scales = [r["scale_neural"] for r in result["rows"] if "scale_neural" in r]
    out["_scale"] = round(float(np.mean(scales))) if scales else None
    return out


def fmt(v, kind):
    if v is None:
        return "—"
    return {"pct": f"{v:.0%}", "ber": f"{v:.2%}", "de": f"{v:.2f}", "db": f"{v:.1f}", "s": f"{v:.2f}s",
            "ssim": f"{v:.3f}"}[kind]


COLS = [("success", "Decoded", "pct", +1), ("ber", "Raw BER", "ber", -1), ("de_classic", "ΔE classic", "de", -1),
        ("de_neural", "ΔE neural", "de", -1), ("psnr2x_neural", "Detail (PSNR @2×)", "db", +1),
        ("decode_s", "Decode", "s", -1)]


def headline(summary, base=None):
    def one(key, label, kind, better):
        v = summary.get(key)
        if v is None:
            return f"{label}: —"
        txt = f"{label}: **{fmt(v, kind)}**"
        b = base.get(key) if base else None
        if b is not None and abs(v - b) / abs(b) >= 0.02:
            txt += f" {'🟢' if (v - b) * better > 0 else '🔴'} (was {fmt(b, kind)})"
        return txt

    scale = summary.get("_scale")
    out = one("_print_ssim", "Print sharpness (SSIM, eye model)", "ssim", +1)
    out += f" · Neural output: **{scale}× cell resolution**" if scale else ""
    if base and base.get("_scale") and scale != base.get("_scale"):
        out += f" (was {base['_scale']}×)"
    return out


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
    regressions = [c for c in CONDITIONS if head[c]["success"] is not None and base[c]["success"] is not None
                   and head[c]["success"] < base[c]["success"]]
    md = ["<!-- inkhue-benchmark -->", "## 📊 Codec benchmark", "",
          f"{len(IMAGES)} public-domain photos × {len(SEEDS)} seeds per condition, simulated print + scan. "
          "ΔE is CIEDE2000 colour error at cell resolution (lower is better); Detail compares with the photo at 2× "
          "cell resolution. 🟢/🔴 = better/worse than the base branch.", "",
          headline(head, base), "", table(head, base), ""]
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
    summary = summarize(result)
    md = "## 📊 Codec benchmark\n\n" + headline(summary) + "\n\n" + table(summary)
    print("\n" + md)
    if args.markdown:
        Path(args.markdown).write_text(md + "\n")


if __name__ == "__main__":
    main()
