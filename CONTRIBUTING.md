# Contributing to Inkhue

Thanks for helping! Inkhue is small, so every contribution matters.

## The most useful thing you can do

**Print a page and scan it.** Open an issue with the
[🖨️ Print / scan report](https://github.com/TonyD365/Inkhue/issues/new?template=print-scan-report.yml)
template. Real printers and scanners are how the simulator, the benchmark and the neural refiner get better.

## Development setup

```bash
git clone https://github.com/TonyD365/Inkhue && cd Inkhue
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # app + training + tools
.venv/bin/python -m inkhue                         # run the app
.venv/bin/python -m pytest tests                      # tests (the app test runs headless)
.venv/bin/ruff check .                                # lint
.venv/bin/python scripts/benchmark.py                 # codec benchmark (~2 min): photos + a document, 6 conditions
```

## Pull requests

- Keep a PR to one change. CI runs lint, tests on macOS / Windows / Linux, a packaged-app self-test and the
  **codec benchmark**, which posts a before/after table on your PR. A drop in decode success fails the check.
- **Do not change the on-paper format** (`inkhue/payload.py` constants — above all `SEED` —,
  `halftone.py` patterns, `layout.py` frame) unless the PR also bumps `VERSION` and keeps decoding old pages.
  `tests/test_format.py` guards this.
- New model weights: include how they were trained and the benchmark result.

## Releases

Maintainers publish a GitHub release with a tag like `v1.2.3`. The release workflow builds all platforms,
attaches them with `SHA256SUMS.txt`, and installed apps update themselves once the release is marked *Latest*.
Use a **pre-release** to test builds without updating anyone.
