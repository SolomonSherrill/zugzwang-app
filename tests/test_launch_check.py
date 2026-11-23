"""DF1 (FIX-B6, owner 2026-11-23): the packaged-build launch check runs the app with its home pointed at a temporary
folder, so the app's own path logic (config._user_dir, frozen) picks a temporary data folder, never a real one."""

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import zugzwang.config as C

ROOT = Path(__file__).resolve().parents[1]


def _launch_check():
    spec = importlib.util.spec_from_file_location("launch_check", ROOT / "packaging" / "launch_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_app_finds_a_temporary_data_folder_through_its_own_path_logic(monkeypatch):
    lc = _launch_check()
    home, env = lc.temp_home()
    try:
        assert "ZUGZWANG_DATA_DIR" not in env and "ZUGZWANG_DB" not in env
        real_home = Path(os.path.expanduser("~"))
        for k in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ZUGZWANG_DATA_DIR", "XDG_DATA_HOME"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            if k in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
                monkeypatch.setenv(k, v)
        monkeypatch.setattr(C, "FROZEN", True)
        chosen = C._user_dir()
        assert chosen == lc.data_dir(home)
        assert home in chosen.parents
        assert real_home not in chosen.parents or str(home).startswith(str(real_home))
        assert ".zugzwang" not in chosen.parts
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_the_check_never_names_a_real_folder():
    src = (ROOT / "packaging" / "launch_check.py").read_text()
    assert "Path.home()" not in src and 'os.environ["LOCALAPPDATA"]' not in src
    if sys.platform != "win32":
        assert "HOME" in src
