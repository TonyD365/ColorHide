import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inkhue import updater


def test_version_order():
    v = updater.parse_version
    assert v("v1.2.10") > v("1.2.9") > v("v1.2") > v("0.0.0-dev")
    assert v("v2.0.0-beta.1") == (2, 0, 0)


def test_asset_names_match_release_workflow():
    name = updater.installer_name("v1.0.0")
    assert name.startswith("Inkhue-v1.0.0-") and name.split("-")[2] in ("macos", "windows", "linux")
    root = Path(__file__).resolve().parents[1]
    wf = (root / ".github/workflows/release.yml").read_text()
    assert updater.platform_key() in wf
    # the updater downloads exactly the installers the release workflow and packaging scripts produce
    assert name.endswith((".pkg", "-setup.exe", ".deb"))
    assert "build_pkg.sh" in wf and "build_deb.sh" in wf and "Inkhue-$TAG-windows-x64-setup.exe" in wf
    assert 'OUT="Inkhue-$TAG-macos-$ARCH.pkg"' in (root / "packaging/macos/build_pkg.sh").read_text()
    assert 'OUT="Inkhue-$TAG-linux-x64.deb"' in (root / "packaging/linux/build_deb.sh").read_text()
    iss = (root / "packaging/windows/Inkhue.iss").read_text()
    assert "OutputBaseFilename=Inkhue-{#Tag}-windows-x64-setup" in iss
