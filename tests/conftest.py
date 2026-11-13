"""Suite-wide isolation from the user's own files.

`~/.zugzwang/settings.json` now holds former handles (`core/handles.py`), which colour
attribution reads whenever a caller passes no alias table — so without this, a test
parsing a PGN would read the real user's settings and could pass or fail depending
on whose machine it ran on. `USER_DIR` is redirected to a per-test temporary
directory; `DB_PATH` is computed at import and is unaffected.

The sidecar's log goes beside the database named by `ZUGZWANG_DB` (`sidecar/main.py`,
`_log_path`), falling back to the real `~/.zugzwang/logs`. A test that started the
sidecar's `main()` without setting it attached a handler to the real log, and every later
test's log lines landed in the file the owner reads (BETA, "Found while building"). So
every test now runs with `ZUGZWANG_DB` and `ZUGZWANG_DATA_DIR` in its own temp directory
(BETA-PUB: the test suite must not write to the real `~/.zugzwang/logs`); a test that
needs them unset or elsewhere sets them itself, as before.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("zugzwang.config.USER_DIR", tmp_path)
    monkeypatch.setenv("ZUGZWANG_DB", str(tmp_path / "zugzwang.db"))
    monkeypatch.setenv("ZUGZWANG_DATA_DIR", str(tmp_path))
