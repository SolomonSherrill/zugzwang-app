"""The live-database guard (BETA-PUB, owner 2026-11-12).

A packaged (frozen) sidecar started by a test or a script must refuse to open the default
user database; only an explicit path (or the app's own launch flag) lets it open one. The
subprocess tests run the real `sidecar/main.py` with `sys.frozen` set — what PyInstaller
does — and a throwaway HOME, so "the default database" is a file under a temp folder and
the user's own is never at risk. On the code before the guard the frozen run opens the
default database (creating it, running the migrations, opening the log beside it) and
waits on stdin: these tests fail.

CI runs the same check against the real frozen build (`packaging/guard_check.py`)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Pretend to be PyInstaller's bootloader: set sys.frozen, then run the sidecar as __main__.
_FROZEN_RUNNER = (
    "import runpy, sys; sys.frozen = True; "
    f"sys.path.insert(0, {str(REPO)!r}); "
    "sys.argv = ['zugzwang-sidecar'] + sys.argv[1:]; "
    f"runpy.run_path({str(REPO / 'sidecar' / 'main.py')!r}, run_name='__main__')"
)


def _env(home: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ZUGZWANG_DB", "ZUGZWANG_DATA_DIR", "ZUGZWANG_STOCKFISH")}
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / "AppData" / "Local"),
               ZUGZWANG_STOCKFISH=str(home / "no-such-engine"), **extra)
    return env


def _default_data_dir(home: Path) -> Path:
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "dev.zugzwang.desktop"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Zugzwang"
    return home / ".local" / "share" / "zugzwang"


def _run_frozen(home: Path, *args: str, timeout: float = 30, **env: str):
    return subprocess.run(
        [sys.executable, "-c", _FROZEN_RUNNER, *args],
        input="", capture_output=True, text=True, timeout=timeout, env=_env(home, **env),
    )


@pytest.mark.parametrize("args", [(), ("--help",)])
def test_frozen_sidecar_started_by_a_script_refuses_the_default_database(tmp_path, args):
    home = tmp_path / "home"
    home.mkdir()
    proc = _run_frozen(home, *args)
    assert proc.returncode == 2, (proc.returncode, proc.stderr[-2000:])
    assert "refusing to open the default user database" in proc.stderr
    data = _default_data_dir(home)
    # Nothing written: no database, no log, not even the folder.
    assert not data.exists(), sorted(str(p) for p in data.rglob("*"))
    assert not (home / ".zugzwang").exists()


def test_frozen_sidecar_with_an_explicit_database_opens_it(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    db = tmp_path / "explicit" / "z.db"
    db.parent.mkdir()
    proc = _run_frozen(home, ZUGZWANG_DB=str(db), ZUGZWANG_DATA_DIR=str(db.parent))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert db.exists()
    assert not _default_data_dir(home).exists()


def test_frozen_sidecar_launched_by_the_app_opens_the_default_database(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = _run_frozen(home, "--app")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert (_default_data_dir(home) / "zugzwang.db").exists()


def test_guard_decision():
    from tests.test_sidecar_rpc import sidecar      # the module, loaded once by that file
    refuse = sidecar.refuse_default_db
    assert refuse(False, ["main.py"], {}) is None                   # a checkout: unchanged
    assert refuse(True, ["zugzwang-sidecar"], {}) is not None
    assert refuse(True, ["zugzwang-sidecar", "--help"], {}) is not None
    assert refuse(True, ["zugzwang-sidecar", "--app"], {}) is None
    assert refuse(True, ["zugzwang-sidecar"], {"ZUGZWANG_DB": "/x/z.db"}) is None
    assert refuse(True, ["zugzwang-sidecar"], {"ZUGZWANG_DATA_DIR": "/x"}) is None
    assert refuse(True, ["zugzwang-sidecar"], {"ZUGZWANG_DB": ""}) is not None
    # argv[0] is the program, never the flag.
    assert refuse(True, ["--app"], {}) is not None
