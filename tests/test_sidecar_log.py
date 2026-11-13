"""W21: the sidecar keeps its own log file, beside the database in use."""

import importlib.util
import logging
import sys
import threading
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "zugzwang_sidecar_main_log", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)


@pytest.fixture
def logged(monkeypatch, tmp_path):
    monkeypatch.setenv("ZUGZWANG_DB", str(tmp_path / "zz.db"))
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    hooks = (sys.excepthook, threading.excepthook)
    path = sidecar._setup_file_logging()
    yield path
    for h in root.handlers[:]:
        if h not in before:
            root.removeHandler(h)
            h.close()
    root.setLevel(level)
    sys.excepthook, threading.excepthook = hooks
    logging.captureWarnings(False)


def _text(path: Path) -> str:
    for h in logging.getLogger().handlers:
        h.flush()
    return path.read_text()


def test_the_log_lives_beside_the_database_in_use(logged, tmp_path):
    assert logged == tmp_path / "logs" / "sidecar.log"
    assert "sidecar starting" in _text(logged)


def test_warnings_from_core_modules_reach_the_file(logged):
    logging.getLogger("zugzwang.core.openings").warning("Opening book not found at /x")
    text = _text(logged)
    assert "WARNING" in text and "Opening book not found at /x" in text


def test_info_reaches_the_file_too(logged):
    # The missing-book notice is logged at INFO (openings.py), and it is exactly the
    # line W21 found missing.
    logging.getLogger("zugzwang.core.openings").info("book classification disabled")
    assert "book classification disabled" in _text(logged)


def test_an_uncaught_worker_exception_is_logged(logged):
    def boom():
        raise RuntimeError("worker died")
    t = threading.Thread(target=boom, name="sync-engine-7")
    t.start()
    t.join()
    text = _text(logged)
    assert "uncaught exception in thread sync-engine-7" in text
    assert "RuntimeError: worker died" in text


def test_an_unwritable_log_is_not_fatal(monkeypatch, tmp_path):
    blocker = tmp_path / "logs"
    blocker.write_text("a file where the directory should be")
    monkeypatch.setenv("ZUGZWANG_DB", str(tmp_path / "zz.db"))
    hooks = (sys.excepthook, threading.excepthook)
    try:
        assert sidecar._setup_file_logging() is None
    finally:
        sys.excepthook, threading.excepthook = hooks
