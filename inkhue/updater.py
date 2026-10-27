"""Self-update from GitHub Releases, using the same installers people download.

The release marked "Latest" on GitHub is the update channel; its tag (v1.2.3) is the version.
Flow: check -> download this platform's installer -> verify against SHA256SUMS.txt -> after the app
exits, a small helper installs it and relaunches the app:
  macOS    .pkg  The installer made the app the user's own, so the helper unpacks the .pkg and swaps
                 the bundle in place: no password. If that isn't possible it runs the .pkg with the
                 system's administrator prompt.
  Windows  .exe  The Inno Setup installer runs silently (/UPDATE relaunches the app afterwards).
  Linux    .deb  Installed with `pkexec dpkg -i` (the desktop's password prompt).
Installers are fetched by the app itself (not a browser), so macOS adds no quarantine flag and the
user approves Gatekeeper only once, on first install.
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from ._version import __version__

REPO = "TonyD365/Inkhue"
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


def installer_name(tag):
    """Must match what .github/workflows/release.yml uploads."""
    key = platform_key()
    if sys.platform == "darwin":
        return f"Inkhue-{tag}-{key}.pkg"
    if sys.platform == "win32":
        return f"Inkhue-{tag}-{key}-setup.exe"
    return f"Inkhue-{tag}-{key}.deb"


def frozen():
    return getattr(sys, "frozen", False)


def install_path():
    """What gets replaced: the .app bundle on macOS, the program folder elsewhere."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        return exe.parents[2]  # Inkhue.app/Contents/MacOS/Inkhue
    return exe.parent


def _ssl_context():
    import ssl
    try:  # bundled CA list: frozen apps on Windows/Linux can't always find the system store
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"Inkhue/{__version__}"})
    return urllib.request.urlopen(req, timeout=30, context=_ssl_context())


def check():
    """Return the newer Latest release as {tag, notes, url, sums_url}, or None."""
    with _get(API) as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if rel.get("draft") or rel.get("prerelease") or parse_version(tag) <= parse_version(__version__):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    name = installer_name(tag)
    # SHA256SUMS.txt is uploaded last by CI, so its presence means the build is complete
    if name not in assets or "SHA256SUMS.txt" not in assets:
        return None
    return dict(tag=tag, notes=rel.get("body") or "", url=assets[name], sums_url=assets["SHA256SUMS.txt"], name=name)


def download(info, progress=None):
    """Download and verify the installer; return its path (ready for apply())."""
    work = Path(tempfile.mkdtemp(prefix="inkhue-update-"))
    installer = work / info["name"]
    with _get(info["url"], "application/octet-stream") as r, open(installer, "wb") as f:
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
    return installer


def _q(path):
    """Single-quote for /bin/sh."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def helper_script(installer, pid, target):
    """The script that runs after the app has quit. Separate so it can be tested."""
    if sys.platform == "win32":
        return f"""@echo off
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)
"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /UPDATE
"""
    wait = f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
    if sys.platform == "darwin":
        t, pkg = _q(target), _q(installer)
        admin = (f"/usr/bin/osascript -e 'do shell script \"/usr/sbin/installer -pkg \" & quoted form of "
                 f"\"{installer}\" & \" -target /\" with administrator privileges'")
        return wait + f"""T={t}
OK=
if [ -O "$T" ] && [ -w "$(dirname "$T")" ]; then
    X=$(mktemp -d)
    if /usr/sbin/pkgutil --expand-full {pkg} "$X/pkg" && [ -d "$X/pkg/Inkhue.pkg/Payload/Inkhue.app" ]; then
        rm -rf "$T.old"
        if mv "$T" "$T.old"; then  # only touch the old app once it is safely set aside
            if /usr/bin/ditto "$X/pkg/Inkhue.pkg/Payload/Inkhue.app" "$T"; then
                OK=1
                rm -rf "$T.old"
            else
                rm -rf "$T"
                mv "$T.old" "$T"
            fi
        fi
    fi
    rm -rf "$X"
fi
if [ -z "$OK" ]; then
    {admin} && T=/Applications/Inkhue.app
fi
/usr/bin/open "$T"
"""
    return wait + f"""if command -v pkexec >/dev/null 2>&1 && pkexec dpkg -i {_q(installer)}; then
    nohup /opt/Inkhue/Inkhue >/dev/null 2>&1 &
else
    xdg-open https://github.com/{REPO}/releases/latest
fi
"""


def apply(installer):
    """Start a detached helper that waits for this process to exit, installs and relaunches."""
    script = Path(tempfile.mkdtemp()) / ("update.bat" if sys.platform == "win32" else "update.sh")
    script.write_text(helper_script(installer, os.getpid(), install_path()))
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000 | 0x00000008)  # no window, detached
    else:
        script.chmod(0o755)
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True)


def discard(installer):
    shutil.rmtree(Path(installer).parent, ignore_errors=True)
