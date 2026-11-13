"""The user's former handles, for colour attribution (FIXPLAN O5, reduced scope).

chess.com serves a renamed account's history under the *current* handle — every game
in a renamed account's archives names the new handle, never the old one (REPULL step
0). So a sync needs no alias. PGNs that predate a rename keep the old name, though:
the stored corpus and any file exported before it. A game played as Black under
the old handle, matched against the new one alone, matches nothing — and the import
default used to make it White.

So each configured handle can carry former handles, used **only to recognise the
user's side**, never to fetch. Stored in `~/.zugzwang/settings.json` beside the
Stockfish path (real settings, not webview storage — owner ruling 2026-10-22), as

    {"former_handles": {"new_handle": ["old_handle"]}}

keys and names compared case-insensitively. Per-account sync jobs and a platform-
scoped account id are deliberately not built (FIXPLAN O5-DEFER).
"""

from __future__ import annotations

import json
import logging

from .engine_locator import _settings_path

logger = logging.getLogger(__name__)

_KEY = "former_handles"


def former_handles() -> dict[str, list[str]]:
    """current handle (lower-case) -> its former handles (lower-case)."""
    try:
        with _settings_path().open(encoding="utf-8") as fh:
            raw = json.load(fh).get(_KEY) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Could not read former handles: %s", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k).strip().lower(): [str(v).strip().lower() for v in vs if str(v).strip()]
        for k, vs in raw.items() if isinstance(vs, list) and str(k).strip()
    }


def set_former_handles(current: str, former: list[str]) -> None:
    """Record *former* as the old names of *current*, replacing any previous list."""
    path = _settings_path()
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, ValueError):
        data = {}
    table = data.get(_KEY) if isinstance(data.get(_KEY), dict) else {}
    table[current.strip().lower()] = [f.strip().lower() for f in former if f.strip()]
    data[_KEY] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def expand(usernames: list[str], aliases: dict[str, list[str]] | None = None) -> list[str]:
    """*usernames* plus the former handles of each, de-duplicated, order kept."""
    table = former_handles() if aliases is None else aliases
    out: list[str] = []
    for u in usernames:
        for name in (u, *table.get((u or "").strip().lower(), [])):
            name = (name or "").strip().lower()
            if name and name not in out:
                out.append(name)
    return out
