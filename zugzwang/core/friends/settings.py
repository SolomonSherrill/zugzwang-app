"""Friends' local settings, in `settings.json` beside the database (key "friends"), never the key.

handle          your handle once signed up (also the server's; kept to show offline)
share_games     "Share the games you play in Zugzwang": BETA-6 (ruling SG1) hides the switch and sends it nowhere;
                a stored value is kept as it is, unused, until a screen shows shared games
appear_offline  "Appear offline" (also sent to the server, ruling C2)
chat_enabled    "Chat in friend games" (used from FRIENDS-2, ruling H3); on by default
chesscom_link   a pending Chess.com link: username, code, when it expires, the last check (chesscom_link.py)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
KEY = "friends"
DEFAULTS = {"handle": None, "share_games": False, "appear_offline": False, "chat_enabled": True,
            "chesscom_link": None}


def _path() -> Path:
    from zugzwang.config import USER_DIR
    return USER_DIR / "settings.json"


def _read_all() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Could not read settings: %s", e)
        return {}


def load() -> dict:
    raw = _read_all().get(KEY)
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        out.update({k: raw[k] for k in DEFAULTS if k in raw})
    return out


def save(**changes) -> dict:
    data = _read_all()
    cur = load()
    cur.update({k: v for k, v in changes.items() if k in DEFAULTS})
    data[KEY] = cur
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return cur


def clear() -> None:
    data = _read_all()
    if data.pop(KEY, None) is not None:
        _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
