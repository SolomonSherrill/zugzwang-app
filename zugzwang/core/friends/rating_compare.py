"""Lichess → Chess.com rating estimates (FRIENDS.md ruling R2), from the ChessGoals rating-comparison
table kept as a dated copy in `zugzwang/assets/ratings/chessgoals_rating_comparison.json`.

A Lichess-only player's rating in a mode is shown as "≈" the Chess.com rating of that mode (R1):
interpolated linearly between the two table rows around it; Lichess Classical maps to Chess.com Rapid
(Chess.com has no classical rating). Outside the table's range: None, shown blank (R3).
"""
from __future__ import annotations

import bisect
import functools
import json
from pathlib import Path

import zugzwang.config as C

DATA_PATH = C.ASSETS_DIR / "ratings" / "chessgoals_rating_comparison.json"

#: Lichess mode → (the Lichess column, the Chess.com column it converts to)
MODES: dict[str, tuple[str, str]] = {
    "bullet": ("lichess_bullet", "chesscom_bullet"),
    "blitz": ("lichess_blitz", "chesscom_blitz"),
    "rapid": ("lichess_rapid", "chesscom_rapid"),
    "classical": ("lichess_classical", "chesscom_rapid"),
}


@functools.lru_cache(maxsize=1)
def table(path: Path = DATA_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for col in {c for pair in MODES.values() for c in pair}:
        xs = [r[col] for r in data["rows"]]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError(f"{path.name}: column {col} is not increasing")
    return data


def chesscom_mode(lichess_mode: str) -> str | None:
    """The Chess.com mode a Lichess mode's estimate is in."""
    pair = MODES.get(lichess_mode)
    return pair[1].removeprefix("chesscom_") if pair else None


def lichess_to_chesscom(rating: float | int | None, mode: str) -> int | None:
    """The estimated Chess.com rating, rounded, or None (no rating, an unknown mode, off the table)."""
    if rating is None or mode not in MODES:
        return None
    src, dst = MODES[mode]
    rows = table()["rows"]
    xs = [r[src] for r in rows]
    ys = [r[dst] for r in rows]
    if rating < xs[0] or rating > xs[-1]:
        return None
    i = bisect.bisect_left(xs, rating)
    if xs[i] == rating:
        return int(ys[i])
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return int(round(y0 + (y1 - y0) * (rating - x0) / (x1 - x0)))


def credit() -> dict:
    """What the "≈" tooltip and About say about the source."""
    t = table()
    return {"source": t["source"], "url": t["url"], "retrieved": t["retrieved"]}


def speed_of(base_s: int | None, increment_s: int | None) -> str | None:
    """Chess.com's mode for a time control (R1): estimated length base + 40 × increment; under 3 min
    bullet, under 10 blitz, else rapid (there is no classical on Chess.com)."""
    if base_s is None:
        return None
    est = base_s + 40 * (increment_s or 0)
    return "bullet" if est < 180 else "blitz" if est < 600 else "rapid"
