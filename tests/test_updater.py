import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from colorhide import updater


def test_version_order():
    v = updater.parse_version
    assert v("v1.2.10") > v("1.2.9") > v("v1.2") > v("0.0.0-dev")
    assert v("v2.0.0-beta.1") == (2, 0, 0)


def test_asset_names_match_release_workflow():
    name = updater.archive_name("v1.0.0")
    assert name.startswith("ColorHide-v1.0.0-") and name.split("-")[2] in ("macos", "windows", "linux")
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text()
    assert updater.platform_key() in wf
