# PyInstaller spec for the Zugzwang sidecar (BETA, packaging).
#   pyinstaller --noconfirm --distpath build/sidecar-dist --workpath build/sidecar-work packaging/sidecar.spec
# One-dir by default; ZUGZWANG_ONEFILE=1 builds the one-file variant (measured in BETA.md).
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ONEFILE = os.environ.get("ZUGZWANG_ONEFILE") == "1"

datas = [(str(ROOT / "zugzwang/assets/openings/eco"), "zugzwang/assets/openings/eco"),
         # the ChessGoals rating table Friends reads (FRIENDS-1 R2); missing until BETA-5 C, when Friends
         # first ran in a packaged build (friends_status failed without it)
         (str(ROOT / "zugzwang/assets/ratings"), "zugzwang/assets/ratings")]
version_file = ROOT / "build" / "build_info.json"
if version_file.exists():
    datas.append((str(version_file), "zugzwang"))
try:
    import certifi
    datas.append((certifi.where(), "certifi"))
except ImportError:
    pass

# Windows: cryptography's Rust extension (_rust.pyd, an abi3t wheel on Python 3.15) imports
# python3t.dll, the stable-ABI DLL beside python.exe, which PyInstaller 6.22.3 does not collect; without it
# the frozen sidecar dies at import ("DLL load failed while importing _rust", BETA-5 D, the third beta.5 CI run).
binaries = []
if sys.platform == "win32":
    py3t = Path(sys.base_prefix) / "python3t.dll"
    if not py3t.exists():
        raise SystemExit(f"error: {py3t} not found; the frozen sidecar could not load cryptography")
    binaries.append((str(py3t), "."))

a = Analysis(
    [str(ROOT / "sidecar" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=collect_submodules("zugzwang") + collect_submodules("chess"),
    excludes=["tkinter", "test", "unittest", "pydoc_data", "pytest", "mypy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# UTF-8 mode: on Windows the locale code page is not UTF-8, and stdin carries JSON the
# webview wrote as UTF-8.
opts = [("X utf8_mode=1", None, "OPTION")]
if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, opts, name="zugzwang-sidecar",
              console=True, upx=False, strip=False)
else:
    exe = EXE(pyz, a.scripts, opts, exclude_binaries=True, name="zugzwang-sidecar",
              console=True, upx=False, strip=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="zugzwang-sidecar", upx=False, strip=False)
