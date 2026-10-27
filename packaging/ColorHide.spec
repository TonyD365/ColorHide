# PyInstaller spec for the desktop app (macOS .app, Windows/Linux folder).
#   pyinstaller packaging/ColorHide.spec --noconfirm
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'"(.+?)"', (ROOT / "colorhide" / "_version.py").read_text()).group(1)

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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ColorHide", console=False,
          target_arch=None, codesign_identity=None, icon=str(ROOT / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="ColorHide")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ColorHide.app",
        icon=str(ROOT / "assets" / "icon.icns"),
        bundle_identifier="io.github.tonyd365.colorhide",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        },
    )
