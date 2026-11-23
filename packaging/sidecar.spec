# PyInstaller spec for the Zugzwang sidecar (BETA, packaging).
#   pyinstaller --noconfirm --distpath build/sidecar-dist --workpath build/sidecar-work packaging/sidecar.spec
# One-dir by default; ZUGZWANG_ONEFILE=1 builds the one-file variant (measured in BETA.md).
import os
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

a = Analysis(
    [str(ROOT / "sidecar" / "main.py")],
    pathex=[str(ROOT)],
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
