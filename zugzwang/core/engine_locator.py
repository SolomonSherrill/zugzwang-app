"""
Resolves the Stockfish binary path in priority order:
  1. ZUGZWANG_STOCKFISH env var
  2. Bundled binary in the repo's stockfish/ directory
  3. shutil.which("stockfish") on PATH
  4. Last-used path chosen by the user
  5. Returns None → caller shows file picker
"""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "stockfish_path"


def find_stockfish() -> Path | None:
    """Return the first usable Stockfish path, or None."""

    # 1. Explicit env override
    env = os.environ.get("ZUGZWANG_STOCKFISH")
    if env:
        p = Path(env)
        if _executable(p):
            logger.info("Stockfish from env: %s", p)
            return p
        logger.warning("ZUGZWANG_STOCKFISH set but not executable: %s", env)

    # 2. Bundled binary. Ahead of PATH so that engine strength is reproducible:
    # a stray `stockfish` on PATH is a different build at a different strength,
    # which silently invalidates the skill-level calibration.
    # On x86-64 two builds ship; the faster one is used when the CPU supports it
    # (BETA-PUB Q6, `engine_choice`). Both have the same bench signature.
    from zugzwang import config as C
    from zugzwang.core.engine_choice import choose
    bundled, why = choose(C.BUNDLED_STOCKFISH, C.BUNDLED_FAST_STOCKFISH)
    if bundled:
        logger.info("Stockfish bundled: %s (%s)", bundled, why)
        return bundled

    # 3. PATH
    which = shutil.which("stockfish")
    if which:
        logger.info("Stockfish from PATH: %s", which)
        return Path(which)

    # 4. Last path the user picked in a "locate Stockfish" dialog
    saved = _read_setting(_SETTINGS_KEY)
    if saved:
        p = Path(saved)
        if _executable(p):
            logger.info("Stockfish from settings: %s", p)
            return p

    return None


def popen_args() -> dict:
    """Extra `subprocess` arguments for starting an engine (BETA, M11).

    On Windows a console program started by a process that has no console of its own (the
    packaged sidecar, spawned windowless by Tauri) gets a new console window. One per
    engine, and analysis runs several. `CREATE_NO_WINDOW` suppresses it. Nothing elsewhere."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def popen_engine(path) -> "chess.engine.SimpleEngine":
    """`SimpleEngine.popen_uci` with `popen_args()`: every engine the app starts."""
    import chess.engine
    return chess.engine.SimpleEngine.popen_uci(str(path), **popen_args())


def persist_path(path: Path) -> None:
    """Remember a user-chosen Stockfish path for next launch."""
    _write_setting(_SETTINGS_KEY, str(path))


# ── Qt-free settings file ────────────────────────────────────────────────────
# Stored as JSON next to the database rather than in QSettings, so that core/
# has no Qt import and a packaged sidecar does not drag in PyQt6.

def _settings_path() -> Path:
    from zugzwang.config import USER_DIR
    return USER_DIR / "settings.json"


def _read_setting(key: str) -> str | None:
    try:
        with _settings_path().open(encoding="utf-8") as fh:
            value = json.load(fh).get(key)
        return value if isinstance(value, str) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning("Could not read settings: %s", e)
        return None


def _write_setting(key: str, value: str) -> None:
    path = _settings_path()
    try:
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, ValueError):
            data = {}
        data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError as e:
        logger.warning("Could not persist setting %s: %s", key, e)


def _executable(p: Path) -> bool:
    return p.exists() and os.access(p, os.X_OK)
