"""Self-update from GitHub Releases.

The release marked "Latest" on GitHub is the update channel; its tag (v1.2.3) is the version.
Flow: check -> download this platform's archive -> verify against SHA256SUMS.txt -> unpack to a
staging folder -> after the app exits, a small helper script swaps the install folder and relaunches.
Archives are fetched by the app itself (not a browser), so macOS adds no quarantine flag and the
user approves Gatekeeper only once, on first install.
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from ._version import __version__

REPO = "TonyD365/ColorHide"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(v):
    """'v1.2.3' -> (1, 2, 3); pre-release/dev suffixes sort lowest."""
    core = v.lstrip("vV").split("-")[0].split("+")[0]
    try:
        return tuple(int(x) for x in core.split("."))
    except ValueError:
        return (0,)


def platform_key():
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    if sys.platform == "win32":
        return f"windows-{arch}"
    return f"linux-{arch}"


def archive_name(tag):
    ext = "tar.gz" if sys.platform.startswith("linux") else "zip"
    return f"ColorHide-{tag}-{platform_key()}.{ext}"


def frozen():
    return getattr(sys, "frozen", False)


def install_path():
    """What gets replaced: the .app bundle on macOS, the program folder elsewhere."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        return exe.parents[2]  # ColorHide.app/Contents/MacOS/ColorHide
    return exe.parent


def _ssl_context():
    import ssl
    try:  # bundled CA list: frozen apps on Windows/Linux can't always find the system store
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"ColorHide/{__version__}"})
    return urllib.request.urlopen(req, timeout=30, context=_ssl_context())


def check():
    """Return the newer Latest release as {tag, notes, url, sums_url}, or None."""
    with _get(API) as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if rel.get("draft") or rel.get("prerelease") or parse_version(tag) <= parse_version(__version__):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    name = archive_name(tag)
    # SHA256SUMS.txt is uploaded last by CI, so its presence means the build is complete
    if name not in assets or "SHA256SUMS.txt" not in assets:
        return None
    return dict(tag=tag, notes=rel.get("body") or "", url=assets[name], sums_url=assets["SHA256SUMS.txt"], name=name)


def download(info, progress=None):
    """Download and verify; return the staged new app path (ready for apply())."""
    work = Path(tempfile.mkdtemp(prefix="colorhide-update-"))
    archive = work / info["name"]
    with _get(info["url"], "application/octet-stream") as r, open(archive, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        h = hashlib.sha256()
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    with _get(info["sums_url"], "application/octet-stream") as r:
        sums = dict(line.split()[::-1] for line in r.read().decode().splitlines() if line.strip())
    if sums.get(info["name"]) != h.hexdigest():
        raise RuntimeError("update failed its SHA-256 check; not installed")

    stage = work / "stage"
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as t:
            t.extractall(stage, filter="data")
    elif sys.platform == "darwin":
        stage.mkdir()
        subprocess.run(["ditto", "-x", "-k", str(archive), str(stage)], check=True)  # keeps symlinks + signature
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(stage)
    new = next(stage.iterdir())
    return new


def apply(new_app):
    """Start a detached helper that waits for this process to exit, swaps in the new version and relaunches."""
    target = install_path()
    pid = os.getpid()
    if sys.platform == "win32":
        script = Path(tempfile.mkdtemp()) / "update.bat"
        script.write_text(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)
rmdir /s /q "{target}.old" 2>nul
move "{target}" "{target}.old" >nul
move "{new_app}" "{target}" >nul
rmdir /s /q "{target}.old" 2>nul
start "" "{target}\\ColorHide.exe"
""")
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000 | 0x00000008)  # no window, detached
    else:
        relaunch = f'open "{target}"' if sys.platform == "darwin" else f'nohup "{target}/ColorHide" >/dev/null 2>&1 &'
        script = Path(tempfile.mkdtemp()) / "update.sh"
        script.write_text(f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
rm -rf "{target}.old"
mv "{target}" "{target}.old" && mv "{new_app}" "{target}" && rm -rf "{target}.old"
{relaunch}
""")
        script.chmod(0o755)
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True)


def discard(new_app):
    shutil.rmtree(Path(new_app).parents[1], ignore_errors=True)
