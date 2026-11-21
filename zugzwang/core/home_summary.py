"""Read-only figures for the redesigned Home (UI-BUILD C; DESIGN.md "Home", rulings 8, 10, 12).

- **Games** is every stored game; **analysed** those with a complete run (VAL-DEATH).
- **Average accuracy** is the mean of the user's own accuracy over analysed games whose
  side is known.
- **Win rate** uses Insights' own definitions (`insights._outcome`, `_wdl_record`): wins over
  decided-or-drawn games whose side is known, **leaving out games against Stockfish** (source
  `local`; ruling 4 of 2026-11-20, third).
- **Ratings** (ruling 10, 12): per platform and time control, the user's rating from the PGN
  headers of their own games (WhiteElo / BlackElo for their side, at the time of the game).
  A time control is listed only if played in the last `WINDOW_DAYS` days; its change is the
  latest rating minus the last one before the window (none when the window holds its first
  game). Daily is chess.com's "1/N" TimeControl; other unbucketed games ("-", "?") get no row.
  The puzzle rating is Zugzwang's own (puzzle_attempts), labelled so; a new peak only on the
  day it was reached (ruling 8); no change when its first attempt is inside the window (ruling
  5 of 2026-11-20, third), else the current rating minus the last rating before the window.
- **Recent games**: the five latest, with the opponent, opening, time control and the user's
  accuracy.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone

from .insights import _outcome, _wdl_record

WINDOW_DAYS = 30
RECENT = 5
SPEEDS = ("bullet", "blitz", "rapid", "classical")
_HDR = re.compile(r'^\[(\w+) "([^"]*)"\]', re.M)
PLATFORM = {"chesscom": "chess.com", "lichess": "Lichess"}


def headers(pgn: str) -> dict[str, str]:
    head = pgn.split("\n\n", 1)[0]
    return dict(_HDR.findall(head))


def parse_time(iso: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def bucket(speed: str | None, time_control: str | None) -> str | None:
    if speed in SPEEDS:
        return speed
    if time_control and re.fullmatch(r"1/\d+", time_control.strip()):
        return "daily"
    return None


def own_rating(h: dict[str, str], color: str | None) -> int | None:
    if color not in ("white", "black"):
        return None
    v = h.get("WhiteElo" if color == "white" else "BlackElo", "")
    return int(v) if v.isdigit() and int(v) > 0 else None


def rating_rows(games: Iterable[tuple], now: datetime) -> list[dict]:
    """games: (played_at, source, speed, time_control, rating) for the user's rated games."""
    start = now - timedelta(days=WINDOW_DAYS)
    by: dict[tuple[str, str], list[tuple[datetime, int]]] = {}
    for played_at, source, speed, tc, rating in games:
        t = parse_time(played_at)
        b = bucket(speed, tc)
        if t is None or b is None or rating is None or source not in PLATFORM:
            continue
        by.setdefault((source, b), []).append((t, rating))
    out = []
    for (source, b), pts in by.items():
        pts.sort()
        last_t, last_r = pts[-1]
        if last_t < start:
            continue                      # ruling 12: only if played recently
        before = [r for t, r in pts if t < start]
        window = [(t, r) for t, r in pts if t >= start]
        series = ([{"t": start.isoformat(), "rating": before[-1]}] if before else []) + \
            [{"t": t.isoformat(), "rating": r} for t, r in window]
        out.append({"platform": PLATFORM[source], "speed": b, "rating": last_r,
                    "change": (last_r - before[-1]) if before else None,
                    "games": len(window), "lastPlayed": last_t.isoformat(), "series": series})
    order = {s: i for i, s in enumerate((*SPEEDS, "daily"))}
    out.sort(key=lambda r: (-r["games"], order[r["speed"]]))
    return out


def puzzle_row(attempts: Sequence[tuple], current: float | None, now: datetime) -> dict | None:
    """attempts: (attempted_at, rating_before, rating_after), any order."""
    pts = []
    for at, before, after in attempts:
        t = parse_time(at)
        if t is not None and after is not None:
            pts.append((t, before, after))
    if not pts or current is None:
        return None
    pts.sort()
    start = now - timedelta(days=WINDOW_DAYS)
    window = [p for p in pts if p[0] >= start]
    if not window:
        return None
    before = [p for p in pts if p[0] < start]
    change = round(current - before[-1][2]) if before else None     # ruling 5 (2026-11-20)
    peak = max(p[2] for p in pts)
    peak_at = next(p[0] for p in pts if p[2] == peak)
    new_peak = round(peak) == round(current) and peak_at.astimezone().date() == now.astimezone().date()
    return {"platform": "Zugzwang", "speed": "puzzles", "rating": round(current),
            "change": change,
            "games": len(window), "lastPlayed": window[-1][0].isoformat(), "newPeak": new_peak,
            "series": [{"t": t.isoformat(), "rating": round(a)} for t, _b, a in window]}


def summarize(rows: Sequence[tuple], now: datetime) -> dict:
    """rows: (id, played_at, player_color, result, termination, source, speed, pgn,
    opening_eco, opening_name, white_accuracy, black_accuracy, analysed), any order."""
    wdl = {"win": 0, "draw": 0, "loss": 0}
    accs: list[float] = []
    rated = []
    analysed = 0
    for (_id, played_at, color, result, _term, source, speed, pgn, _eco, _name,
         wa, ba, done) in rows:
        if done:
            analysed += 1
            a = wa if color == "white" else ba if color == "black" else None
            if a is not None:
                accs.append(a)
        if color in ("white", "black") and source != "local":    # ruling 4: not vs Stockfish
            o = _outcome(color, result)
            if o:
                wdl[o] += 1
        h = headers(pgn)
        rated.append((played_at, source, speed, h.get("TimeControl"), own_rating(h, color)))
    latest = sorted(rows, key=lambda r: r[1], reverse=True)[:RECENT]
    recent = []
    for (gid, played_at, color, result, term, source, _speed, pgn, eco, name,
         wa, ba, done) in latest:
        h = headers(pgn)
        opp_side = "black" if color == "white" else "white" if color == "black" else None
        opponent = "Stockfish" if source == "local" else (h.get("Black" if color == "white" else "White") if opp_side else None)
        recent.append({
            "id": gid, "playedAt": played_at, "playerColor": color,
            "outcome": _outcome(color, result) if color in ("white", "black") else None,
            "result": result, "termination": term, "source": source, "opponent": opponent,
            "openingEco": eco, "openingName": name, "timeControl": h.get("TimeControl"),
            "accuracy": (wa if color == "white" else ba if color == "black" else None) if done else None,
            "opponentAccuracy": (ba if color == "white" else wa if color == "black" else None) if done else None,
        })
    record = _wdl_record(wdl)
    return {
        "games": len(rows), "analysed": analysed,
        "avgAccuracy": round(sum(accs) / len(accs), 1) if accs else None,
        "winRate": record["winRate"] if record["total"] else None,
        "ratings": rating_rows(rated, now), "recent": recent,
    }
