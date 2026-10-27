# PyInstaller spec for the desktop app (macOS .app, Windows/Linux folder).
#   pyinstaller packaging/Inkhue.spec --noconfirm
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'"(.+?)"', (ROOT / "inkhue" / "_version.py").read_text()).group(1)

hidden = []
if sys.platform == "darwin":
    hidden += ["Quartz", "ImageCaptureCore", "AppKit", "Foundation", "objc"]
elif sys.platform == "win32":
    hidden += ["win32com.client", "pythoncom", "pywintypes"]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "models" / "refiner.onnx"), "models"), (str(ROOT / "assets" / "icon.png"), "assets")],
    hiddenimports=hidden,
    # training-only and unused heavy packages stay out of the app
    excludes=["torch", "numba", "llvmlite", "skimage", "scipy", "matplotlib", "onnx", "onnxscript",
              "PIL", "tkinter", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Inkhue", console=False,
          target_arch=None, codesign_identity=None, icon=str(ROOT / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="Inkhue")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Inkhue.app",
        icon=str(ROOT / "assets" / "icon.icns"),
        bundle_identifier="io.github.tonyd365.inkhue",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            # network printers and scanners (AirPrint / AirScan) are local-network devices
            "NSLocalNetworkUsageDescription": "Inkhue finds and uses printers and scanners on your network.",
            "NSBonjourServices": ["_ipp._tcp", "_ipps._tcp", "_uscan._tcp", "_uscans._tcp", "_scanner._tcp",
                                  "_pdl-datastream._tcp", "_printer._tcp"],
        },
    )
