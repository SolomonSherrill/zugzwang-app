"""BETA item 1: nothing assumes the owner's machine (BETA.md, stage 1, M4–M14)."""

from __future__ import annotations

import json
import re
import ssl
import sys
from pathlib import Path

import pytest

import zugzwang.config as C
from zugzwang import build_info
from zugzwang.core import engine_locator, platform_sync, provenance


@pytest.mark.parametrize("system,machine,want", [
    ("Darwin", "arm64", ("darwin", "arm64")),
    ("Darwin", "x86_64", ("darwin", "x86_64")),
    ("Windows", "AMD64", ("windows", "x86_64")),
    ("Linux", "aarch64", ("linux", "arm64")),
])
def test_host_target(monkeypatch, system, machine, want):
    monkeypatch.setattr(C.platform, "system", lambda: system)
    monkeypatch.setattr(C.platform, "machine", lambda: machine)
    assert C.host_target() == want


def test_every_shipped_target_has_an_asset():
    for target in [("darwin", "arm64"), ("darwin", "x86_64"), ("windows", "x86_64")]:
        spec = C.STOCKFISH_ASSETS[target]
        assert re.fullmatch(r"[0-9a-f]{64}", spec["asset_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", spec["binary_sha256"])
    # the binary every measurement ran on (CLAUDE.md)
    assert C.STOCKFISH_ASSETS[("darwin", "arm64")]["binary_sha256"].startswith("bc0cac905ecdf214")


def test_user_dir_dev_is_unchanged(monkeypatch):
    monkeypatch.delenv("ZUGZWANG_DATA_DIR", raising=False)
    monkeypatch.setattr(C, "FROZEN", False)
    assert C._user_dir() == Path.home() / ".zugzwang"


def test_user_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("ZUGZWANG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(C, "FROZEN", True)
    assert C._user_dir() == tmp_path


def test_user_dir_packaged_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("ZUGZWANG_DATA_DIR", raising=False)
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert C._user_dir() == tmp_path / "dev.zugzwang.desktop"


def test_user_dir_packaged_macos(monkeypatch):
    monkeypatch.delenv("ZUGZWANG_DATA_DIR", raising=False)
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "platform", "darwin")
    assert C._user_dir() == Path.home() / "Library" / "Application Support" / "Zugzwang"


def test_packaged_engine_is_beside_the_sidecar(monkeypatch, tmp_path):
    exe = tmp_path / "zugzwang-sidecar"
    exe.write_text("")
    name = "stockfish.exe" if sys.platform == "win32" else "stockfish"
    sf = tmp_path / name
    sf.write_text("")
    sf.chmod(0o755)
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "executable", str(exe))
    assert C._bundled_stockfish() == sf


@pytest.mark.parametrize("layout", ["macos", "windows"])
def test_packaged_engine_found_from_the_resource_folder(monkeypatch, tmp_path, layout):
    """The sidecar runs from the `sidecar/` resource folder; Stockfish is the externalBin."""
    if layout == "macos":
        exe = tmp_path / "Z.app/Contents/Resources/sidecar/zugzwang-sidecar"
        sf = tmp_path / "Z.app/Contents/MacOS/stockfish"
        monkeypatch.setattr(C.sys, "platform", "darwin")
    else:
        exe = tmp_path / "Zugzwang/sidecar/zugzwang-sidecar.exe"
        sf = tmp_path / "Zugzwang/stockfish.exe"
        monkeypatch.setattr(C.sys, "platform", "win32")
    exe.parent.mkdir(parents=True)
    sf.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    sf.write_text("")
    sf.chmod(0o755)
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "executable", str(exe))
    assert C._bundled_stockfish() == sf


def test_packaged_engine_missing_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "executable", str(tmp_path / "zugzwang-sidecar"))
    assert C._bundled_stockfish() is None


def test_engine_popen_args_hide_the_console_on_windows(monkeypatch):
    monkeypatch.setattr(engine_locator.sys, "platform", "win32")
    assert engine_locator.popen_args() == {"creationflags": 0x08000000}
    monkeypatch.setattr(engine_locator.sys, "platform", "darwin")
    assert engine_locator.popen_args() == {}


def test_performance_cores_never_calls_sysctl_off_macos(monkeypatch):
    calls = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setattr(C.os, "cpu_count", lambda: 8)
    assert C._performance_cores() == 4
    assert calls == []


def test_settings_are_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr("zugzwang.config.USER_DIR", tmp_path)
    engine_locator._write_setting("stockfish_path", "C:/Users/Jürgen/sf.exe")
    raw = (tmp_path / "settings.json").read_bytes()
    raw.decode("utf-8")
    assert engine_locator._read_setting("stockfish_path") == "C:/Users/Jürgen/sf.exe"


def test_frozen_provenance_never_calls_git(monkeypatch):
    provenance.code_commit.cache_clear()
    build_info.info.cache_clear()
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(build_info, "info", lambda: {"commit": "abc123", "version": "0.1.0-beta.1",
                                                     "beta": True, "built_at": None, "target": None})
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("git was called"))
    try:
        assert provenance.code_commit() == {"commit": "abc123", "dirty": False}
    finally:
        provenance.code_commit.cache_clear()


def test_build_info_reads_the_baked_file(monkeypatch, tmp_path):
    f = tmp_path / "build_info.json"
    f.write_text(json.dumps({"version": "0.1.0-beta.2", "commit": "def", "beta": True}))
    monkeypatch.setattr(build_info, "_FILE", f)
    build_info.info.cache_clear()
    try:
        assert build_info.info()["version"] == "0.1.0-beta.2"
        assert build_info.info()["beta"] is True
    finally:
        build_info.info.cache_clear()


def test_build_info_dev_default(monkeypatch, tmp_path):
    monkeypatch.setattr(build_info, "_FILE", tmp_path / "absent.json")
    build_info.info.cache_clear()
    try:
        assert build_info.info()["version"] == "dev"
        assert build_info.info()["beta"] is False
    finally:
        build_info.info.cache_clear()


def test_tls_context_uses_certifi():
    certifi = pytest.importorskip("certifi")
    platform_sync._tls_context.cache_clear()
    ctx = platform_sync._tls_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert Path(certifi.where()).exists()


@pytest.mark.parametrize("cores,logical,want", [
    (4, 10, 8),    # the owner's M4: unchanged by BETA item 3
    (2, 4, 2),     # a 4-thread laptop: two CPUs left free
    (4, 8, 6),     # 4 cores / 8 threads
    (8, 16, 8),    # capped at 8 as ruled (ENGINE-BUDGET-M4B)
    (2, None, 6),  # cpu_count unknown
])
def test_idle_ceiling_leaves_two_cpus(cores, logical, want):
    assert C._idle_ceiling(cores, logical) == want


def test_windows_data_folder_is_the_tauri_identifier():
    import json
    conf = json.loads((Path(C.REPO_ROOT) / "desktop/src-tauri/tauri.conf.json").read_text())
    assert C.WINDOWS_DATA_DIR_NAME == conf["identifier"]
