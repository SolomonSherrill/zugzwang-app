"""Ratings at a friend game's start (FRIENDS.md rulings R1-R3, FRIENDS-2 C).

R1: the rating shown is the Chess.com rating for the game's mode (bullet, blitz, rapid as
`rating_compare.speed_of` reads the time control). R2: a player with no Chess.com rating in that mode but a
Lichess one gets the "≈" estimate from the ChessGoals table (`rating_compare`). R3: taken at the game's start,
stored apart from the real rating fields, blank (None) when unknown.

Read from the players' proven linked accounts, which the server sends with the game; the requests go to
Chess.com's and Lichess's public APIs one at a time (`platform_games._get`, which backs off on HTTP 429).
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from zugzwang.core.friends import platform_games as PG
from zugzwang.core.friends import rating_compare

logger = logging.getLogger(__name__)


def lichess_speed(base_s: int, inc_s: int) -> str:
    """Lichess's own mode for a time control (its estimate base + 40 x increment)."""
    est = base_s + 40 * inc_s
    return "bullet" if est < 179 else "blitz" if est < 479 else "rapid" if est < 1499 else "classical"


def parse_tc(tc: str) -> tuple[int, int]:
    m, s = tc.split("+")
    return int(m) * 60, int(s)


def chesscom_rating(username: str, speed: str) -> int | None:
    try:
        data = json.loads(PG._get(f"{PG.chesscom_api()}/pub/player/{urllib.parse.quote(username.lower(), safe='')}/stats",
                                  "application/json"))
    except PG.FetchError as exc:
        logger.info("start ratings: Chess.com stats: %s", exc)
        return None
    except (OSError, ValueError) as exc:
        logger.info("start ratings: Chess.com stats unreadable: %s", exc)
        return None
    r = ((data.get(f"chess_{speed}") or {}).get("last") or {}).get("rating")
    return int(r) if isinstance(r, (int, float)) and r > 0 else None


def lichess_rating(username: str, mode: str) -> int | None:
    try:
        data = json.loads(PG._get(f"{PG.lichess_api()}/api/user/{urllib.parse.quote(username, safe='')}",
                                  "application/json"))
    except PG.FetchError as exc:
        logger.info("start ratings: Lichess user: %s", exc)
        return None
    except (OSError, ValueError) as exc:
        logger.info("start ratings: Lichess user unreadable: %s", exc)
        return None
    r = ((data.get("perfs") or {}).get(mode) or {}).get("rating")
    return int(r) if isinstance(r, (int, float)) and r > 0 else None


def rating_for(linked: list[dict], tc: str) -> dict:
    """{"rating": int | None, "estimated": bool, "site": "chesscom" | "lichess" | None} for one player."""
    base, inc = parse_tc(tc)
    speed = rating_compare.speed_of(base, inc) or "rapid"
    sites = {l.get("site"): l.get("username") for l in linked or [] if l.get("username")}
    if sites.get("chesscom"):
        r = chesscom_rating(sites["chesscom"], speed)
        if r is not None:
            return {"rating": r, "estimated": False, "site": "chesscom", "speed": speed}
    if sites.get("lichess"):
        mode = lichess_speed(base, inc)
        est = rating_compare.lichess_to_chesscom(lichess_rating(sites["lichess"], mode), mode)
        if est is not None:
            return {"rating": est, "estimated": True, "site": "lichess", "speed": rating_compare.chesscom_mode(mode)}
    return {"rating": None, "estimated": False, "site": None, "speed": speed}


def at_start(state: dict) -> dict:
    """Both players' ratings for a game state from the server (`white`/`black` with `linked`, `tc`)."""
    return {side: rating_for((state.get(side) or {}).get("linked") or [], state["tc"]) for side in ("white", "black")}
