<div align="center">

<img src="assets/icon.png" width="132" alt="ColorHide icon">

# ColorHide

**Print a color photo as a plain-looking black-and-white page. Scan it, and the color comes back.**

[![Release](https://img.shields.io/github/v/release/TonyD365/ColorHide?color=ee6b33&label=release)](https://github.com/TonyD365/ColorHide/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/TonyD365/ColorHide/release.yml?label=build)](https://github.com/TonyD365/ColorHide/actions/workflows/release.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-3a7bd5)](LICENSE)
![Platforms](https://img.shields.io/badge/macOS%20·%20Windows%20·%20Linux-555)

[Download](#download) · [How it works](#how-it-works) · [Printing tips](#printing-and-scanning-tips) · [Build from source](#build-from-source) · [中文说明](README.zh-CN.md)

<img src="assets/compare.png" alt="Original photo, the black-and-white printout, and the color recovered from a scan">

<sub>Left: original. Middle: what gets printed (any black-and-white laser printer). Right: color recovered from the scan.</sub>

</div>

---

## Why

Black-and-white printing is cheap and everywhere. Color is not. ColorHide stores a photo's color **inside the
microscopic arrangement of the printer dots**: to the eye the page is an ordinary grayscale halftone, but a scanner
can read the color back out. No secret key, nothing encrypted — the format is open and anyone can decode it.

<div align="center"><img src="assets/screenshot.png" width="760" alt="The ColorHide app"></div>

## Features

- 🖨️ **Printer-style desktop app** for macOS, Windows and Linux
- 🎨 **Hide color** in a black-and-white page, **reveal color** from a scan
- 📄 Print with your **system print dialog** (all of its options), or export a lossless **PDF**
- 🔍 Scan straight from your **scanner or multifunction printer** (ImageKit on macOS, WIA on Windows, SANE on Linux), or import a PDF / image
- 💾 Export the recovered photo as **PDF, PNG, JPEG, TIFF, WebP, HEIC, JPEG 2000, BMP**…
- 🧠 Optional **neural refiner** (small U-Net, runs on CPU via ONNX Runtime) removes grain and sharpens color
- 🛡️ Reed-Solomon error correction + redundancy survive smudges, skew and scanner noise
- 🔄 **Auto-updates** from the latest GitHub release, verified by SHA-256

## Download

| Platform | File |
|---|---|
| macOS (Apple silicon) | `ColorHide-vX.Y.Z-macos-arm64.zip` |
| macOS (Intel) | `ColorHide-vX.Y.Z-macos-x64.zip` |
| Windows 10/11 (64-bit) | `ColorHide-vX.Y.Z-windows-x64.zip` |
| Linux (x86-64) | `ColorHide-vX.Y.Z-linux-x64.tar.gz` |

Get them from the [latest release](https://github.com/TonyD365/ColorHide/releases/latest). Every file has a
SHA-256 in `SHA256SUMS.txt` and a [build provenance attestation](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations)
(`gh attestation verify <file> -R TonyD365/ColorHide`).

<details>
<summary><b>First launch: the apps are not code-signed by a paid certificate</b></summary>

**macOS** — unzip, move `ColorHide.app` to Applications and open it. macOS will refuse the first time.
Open **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. You only do this once;
later updates install without asking. (Terminal alternative: `xattr -dr com.apple.quarantine /Applications/ColorHide.app`.)

**Windows** — unzip anywhere and run `ColorHide.exe`. If SmartScreen appears, click **More info → Run anyway**.

**Linux** — `tar xzf ColorHide-*.tar.gz && ./ColorHide/ColorHide`. Needs a desktop with X11 or Wayland;
on minimal systems install `libxcb-cursor0`. Scanning uses SANE (`sudo apt install sane-utils`).
</details>

## How it works

```mermaid
flowchart LR
    A[Color photo] --> Y[Luminance Y]
    A --> C[Color Cb/Cr<br/>1/8 resolution, 6 bit]
    C --> RS[Reed-Solomon<br/>+ repetition + scatter]
    Y --> H{{4×4-dot halftone cell}}
    RS --> H
    H -->|dot count = gray<br/>growth corner = 2 bits| P[B/W page]
    P --> S[Scan]
    S --> D[Locate frame,<br/>read cells]
    D --> N[Neural refiner]
    N --> O[Color photo]
```

| Layer | What it does |
|---|---|
| **Data halftone** | Every pixel becomes a 4×4 cell of printer dots (1/150 inch at 600 dpi). *How many* dots are inked sets the gray level; *which corner* they grow from carries 2 bits. The eye only sees gray. |
| **Color payload** | Cb/Cr at 1/8 resolution, 6-bit, protected by Reed-Solomon and repeated across the page. A fixed, public permutation spreads every byte over the whole sheet so local damage never destroys a region. |
| **Neural refiner** | A small U-Net trained on [DIV2K](https://data.vision.ee.ethz.ch/cvl/DIV2K/) through a simulated print/scan channel. It removes halftone grain, corrects toner spread and sharpens the low-resolution color along luminance edges. |
| **Frame** | A thin border to find the page in a scan and a timing track to count the grid. |

## Printing and scanning tips

- Print at the printer's **native resolution (600 dpi)** and **100 % scale** — turn off *Fit to page* and any photo enhancement.
  Laser printers work best.
- Scan in **grayscale at 1200 dpi** (at least 900), with sharpening and descreening off.
- Keep the black frame fully inside the scan.

## Build from source

```bash
git clone https://github.com/TonyD365/ColorHide && cd ColorHide
python3 -m venv .venv && .venv/bin/pip install -r requirements-app.txt
.venv/bin/python -m colorhide            # the app
```

Command line:

```bash
python -m colorhide.cli encode photo.jpg page.png --width-in 6      # hide
python -m colorhide.cli simulate page.png scan.png                  # software print + scan
python -m colorhide.cli decode scan.png color.png                   # reveal
```

Train the refiner (uses Apple GPU / CUDA if available):

```bash
pip install -r requirements.txt
python scripts/make_dataset.py data/div2k/DIV2K_valid_HR --crops 20
python scripts/train.py --steps 3000
python -m colorhide.refiner_onnx models/refiner.pt models/refiner.onnx
```

Package the app: `pyinstaller packaging/ColorHide.spec`. Releases are built by
[GitHub Actions](.github/workflows/release.yml) whenever a release is published; the tag (`v1.2.3`) is the version.

## Format stability

Pages printed today must still decode in ten years. The constants in
[`colorhide/payload.py`](colorhide/payload.py) — above all `SEED` — are frozen and pinned by
[`tests/test_format.py`](tests/test_format.py). Any change to the on-paper format needs a new `VERSION` and a decoder
that still reads the old one.

## Related work

- R. L. de Queiroz, K. M. Braun. *Color to Gray and Back: Color Embedding Into Textured Gray Images.* IEEE TIP, 2006.
- M. Xia, X. Liu, T.-T. Wong. *Invertible Grayscale.* ACM TOG (SIGGRAPH Asia), 2018.
- M. Tancik, B. Mildenhall, R. Ng. *StegaStamp: Invisible Hyperlinks in Physical Photographs.* CVPR, 2020.
- E. Agustsson, R. Timofte. *NTIRE 2017 Challenge on Single Image Super-Resolution: Dataset and Study* (DIV2K).

## Contributing

Issues and pull requests are welcome — especially **real-world print/scan results** (printer and scanner model,
settings, and whether it decoded). They are the best way to make the simulator and the refiner better.

## License

[Apache-2.0](LICENSE). Free to use, modify and ship, including commercially. Published openly so that the method stays
free for everyone.
