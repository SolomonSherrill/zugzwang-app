"""Stockfish resolution order.

The order is a correctness concern, not a preference: if a stray `stockfish` on
PATH can outrank the binary shipped with the app, engine strength is not
reproducible across machines — and the skill-level calibration (F5) is measured
against whichever binary happened to win.
"""

import ast
import json
import stat
import sys
from pathlib import Path

import pytest

from zugzwang.core import engine_locator


@pytest.fixture
def fake_engine(tmp_path):
    """Factory for executable dummy files standing in for a Stockfish binary."""

    def _make(name: str):
        p = tmp_path / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return p

    return _make


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No env var, nothing on PATH, no bundled binary unless a test says so."""
    monkeypatch.delenv("ZUGZWANG_STOCKFISH", raising=False)
    monkeypatch.setattr(engine_locator.shutil, "which", lambda _: None)
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", None)
    monkeypatch.setattr("zugzwang.config.BUNDLED_FAST_STOCKFISH", None)


def test_env_var_outranks_everything(monkeypatch, fake_engine):
    env = fake_engine("env-sf")
    bundled = fake_engine("bundled-sf")
    on_path = fake_engine("path-sf")
    monkeypatch.setenv("ZUGZWANG_STOCKFISH", str(env))
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", bundled)
    monkeypatch.setattr(engine_locator.shutil, "which", lambda _: str(on_path))

    assert engine_locator.find_stockfish() == env


def test_bundled_outranks_path(monkeypatch, fake_engine):
    """P4: the binary we ship and calibrate against must beat a stray PATH one."""
    bundled = fake_engine("bundled-sf")
    on_path = fake_engine("path-sf")
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", bundled)
    monkeypatch.setattr(engine_locator.shutil, "which", lambda _: str(on_path))

    assert engine_locator.find_stockfish() == bundled


def test_path_used_when_nothing_bundled(monkeypatch, fake_engine):
    on_path = fake_engine("path-sf")
    monkeypatch.setattr(engine_locator.shutil, "which", lambda _: str(on_path))

    assert engine_locator.find_stockfish() == on_path


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows has no executable bit: os.access(X_OK) is true for any file")
def test_non_executable_env_var_falls_through(monkeypatch, tmp_path, fake_engine):
    """A set-but-unusable override must not shadow a working binary."""
    dud = tmp_path / "not-executable"
    dud.write_text("")
    dud.chmod(dud.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    bundled = fake_engine("bundled-sf")
    monkeypatch.setenv("ZUGZWANG_STOCKFISH", str(dud))
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", bundled)

    assert engine_locator.find_stockfish() == bundled


def test_returns_none_when_nothing_available():
    assert engine_locator.find_stockfish() is None


# ── saved path (P3/D19: Qt-free settings file, was QSettings) ────────────────


@pytest.fixture
def settings_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("zugzwang.config.USER_DIR", tmp_path)
    return tmp_path


def test_saved_path_used_as_last_resort(settings_dir, fake_engine):
    saved = fake_engine("saved-sf")
    engine_locator.persist_path(saved)

    assert engine_locator.find_stockfish() == saved


def test_saved_path_ranks_below_bundled(monkeypatch, settings_dir, fake_engine):
    bundled = fake_engine("bundled-sf")
    engine_locator.persist_path(fake_engine("saved-sf"))
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", bundled)

    assert engine_locator.find_stockfish() == bundled


def test_persist_path_round_trips_without_qt(settings_dir, fake_engine):
    saved = fake_engine("saved-sf")
    engine_locator.persist_path(saved)

    assert json.loads((settings_dir / "settings.json").read_text()) == {
        "stockfish_path": str(saved)
    }


def test_persist_path_preserves_unrelated_keys(settings_dir, fake_engine):
    (settings_dir / "settings.json").write_text(json.dumps({"theme": "dark"}))

    engine_locator.persist_path(fake_engine("saved-sf"))

    assert json.loads((settings_dir / "settings.json").read_text())["theme"] == "dark"


def test_corrupt_settings_file_does_not_crash(settings_dir, fake_engine):
    """A hand-edited or truncated settings file must degrade, not brick startup."""
    (settings_dir / "settings.json").write_text("{not json")
    bundled = fake_engine("bundled-sf")

    assert engine_locator.find_stockfish() is None

    engine_locator.persist_path(bundled)
    assert json.loads((settings_dir / "settings.json").read_text()) == {
        "stockfish_path": str(bundled)
    }


def test_saved_path_ignored_when_no_longer_executable(settings_dir, tmp_path):
    """The user's binary can be moved or uninstalled between launches."""
    gone = tmp_path / "deleted-sf"
    gone.write_text("")
    engine_locator.persist_path(gone)
    gone.unlink()

    assert engine_locator.find_stockfish() is None


def test_core_does_not_import_qt():
    """D19 golden rule: no Qt import in zugzwang/core/, at module or call time.

    Walks the AST rather than grepping the source, so that deferred imports
    inside a function body — which is exactly how the QSettings import hid here
    — are caught, and prose mentioning Qt is not.
    """
    tree = ast.parse(Path(engine_locator.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not {"PyQt6", "PyQt5", "PySide6"} & imported


def test_source_names_where_each_binary_came_from(monkeypatch, fake_engine):
    """Settings' Engine row says how the binary was found (bundled, chosen, …), in
    find_stockfish's own terms."""
    env = fake_engine("env-sf")
    bundled = fake_engine("bundled-sf")
    on_path = fake_engine("path-sf")
    picked = fake_engine("picked-sf")
    monkeypatch.setattr("zugzwang.config.BUNDLED_STOCKFISH", bundled)
    monkeypatch.setattr(engine_locator.shutil, "which", lambda _: str(on_path))
    assert engine_locator.stockfish_source(bundled) == "bundled"
    assert engine_locator.stockfish_source(on_path) == "path"
    assert engine_locator.stockfish_source(picked) == "chosen"
    assert engine_locator.stockfish_source(None) is None
    monkeypatch.setenv("ZUGZWANG_STOCKFISH", str(env))
    assert engine_locator.stockfish_source(env) == "env"
    # what find_stockfish returns is always named
    assert engine_locator.stockfish_source(engine_locator.find_stockfish()) == "env"
