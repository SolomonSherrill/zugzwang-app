"""The test suite never writes to the real `~/.zugzwang/logs` (BETA-PUB, owner 2026-11-12).

`tests/conftest.py` gives every test its own `ZUGZWANG_DB` and `ZUGZWANG_DATA_DIR`. Before
it did, `test_main_skips_bad_json_and_blank_lines` ran the sidecar's `main()` with neither
set, which attached a file handler on the owner's real `sidecar.log`; every later test's log
lines then went there (the engine-death tests' "exit code -9" among them). These fail on that
conftest."""

import logging
import logging.handlers
from pathlib import Path

from tests.test_sidecar_rpc import _RecordingServer, sidecar

REAL_LOG_DIR = Path.home() / ".zugzwang" / "logs"


def _under_real_log_dir(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(REAL_LOG_DIR.resolve())
        return True
    except ValueError:
        return False


def test_the_sidecar_log_path_is_never_the_real_one_in_a_test():
    assert not _under_real_log_dir(sidecar._log_path()), sidecar._log_path()


def test_running_the_sidecar_main_attaches_no_handler_to_the_real_log(monkeypatch):
    import io
    rec = _RecordingServer()
    monkeypatch.setattr(sidecar, "Server", lambda: rec)
    monkeypatch.setattr(sidecar.sys, "stdin", io.StringIO('{"id": 1, "method": "ping"}\n'))
    root = logging.getLogger()
    before = set(root.handlers)
    try:
        sidecar.main()
        added = [h for h in root.handlers if h not in before]
        files = [h.baseFilename for h in added if isinstance(h, logging.FileHandler)]
        assert files, "main() should have opened its log file"
        assert not any(_under_real_log_dir(Path(f)) for f in files), files
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
