"""Read-only figures for the redesigned Puzzles lobby (UI-BUILD-2 E2; DESIGN.md "Puzzles", ruling 19).

Everything is read from `puzzle_attempts`, `puzzle_sessions` and `puzzle_rating`; nothing here
writes.

- **Rating** is Home's puzzle row (`home_summary.puzzle_row`), so the lobby and Home's ratings
  card never disagree: the current rating, its 30-day line, the 30-day change (none when the
  first attempt is inside the window, ruling 5 of 2026-11-20, third) and a new peak only on the
  day it was reached (ruling 8).
- **Solved** counts attempts solved **without a miss** (`solved = 1 AND failed = 0`): a puzzle
  finished after a wrong move or a hint was scored as a loss for the rating, so it is not
  counted as solved. **Tries** is every attempt.
- **Rush bests** (per length, `PUZZLE_RUSH_TIMES`) and the **Survival best** are the highest
  score of a finished session (`ended_at` set), as `Database.get_leaderboard` reads them.
- **Recent sessions**, newest first: each stored session, plus the attempts that have no
  session (rated play before E2 did not open one), grouped into one session per run of the
  same mode with no gap over `SESSION_GAP_MIN` minutes. A rated session lists its tries, its
  solved count and its rating change (the last rating after minus the first rating before); a
  Rush or Survival session its score, marked `best` when it equals that board's best.
  A rated session with no attempt, and a Rush or Survival session never finished, are left out.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from .home_summary import parse_time, puzzle_row

SESSION_GAP_MIN = 30
RECENT_SESSIONS = 5
RATED_MODES = ("rated", "theme")


def _clean(solved: object, failed: object) -> bool:
    return bool(solved) and not bool(failed)


def bests(sessions: Sequence[tuple]) -> tuple[dict[str, int | None], int | None]:
    """sessions: (id, mode, started_at, ended_at, time_limit_s, score).
    Returns ({"180": best or None, "300": ...}, survival best or None)."""
    rush: dict[str, int | None] = {}
    survival: int | None = None
    for _id, mode, _start, ended, tl, score in sessions:
        if ended is None or score is None:
            continue
        if mode == "rush" and tl is not None:
            k = str(int(tl))
            rush[k] = max(rush.get(k) or 0, int(score))
        elif mode == "survival":
            survival = max(survival or 0, int(score))
    return rush, survival


def _group_loose(attempts: list[tuple]) -> list[list[tuple]]:
    """Attempts with no session, in time order, split where the mode changes or the gap
    between two attempts exceeds SESSION_GAP_MIN minutes."""
    groups: list[list[tuple]] = []
    prev_t: datetime | None = None
    for a in attempts:
        t = a[3]
        if (groups and prev_t is not None and groups[-1][-1][2] == a[2]
                and t - prev_t <= timedelta(minutes=SESSION_GAP_MIN)):
            groups[-1].append(a)
        else:
            groups.append([a])
        prev_t = t
    return groups


def _rated_change(atts: list[tuple]) -> int | None:
    first = next((a for a in atts if a[6] is not None), None)
    last = next((a for a in reversed(atts) if a[7] is not None), None)
    if first is None or last is None:
        return None
    return round(last[7] - first[6])


def recent_sessions(attempts: Sequence[tuple], sessions: Sequence[tuple],
                    limit: int = RECENT_SESSIONS) -> list[dict]:
    """attempts: (id, session_id, mode, attempted_at, solved, failed, rating_before,
    rating_after); sessions as in `bests`."""
    rush_best, surv_best = bests(sessions)
    parsed = []
    for a in attempts:
        t = parse_time(a[3]) if a[3] else None
        if t is not None:
            parsed.append((a[0], a[1], a[2], t, a[4], a[5], a[6], a[7]))
    parsed.sort(key=lambda a: (a[3], a[0]))
    by_session: dict[int, list[tuple]] = {}
    loose: list[tuple] = []
    for a in parsed:
        if a[1] is None:
            loose.append(a)
        else:
            by_session.setdefault(a[1], []).append(a)

    out: list[dict] = []
    for sid, mode, started, ended, tl, score in sessions:
        atts = by_session.get(sid, [])
        t0 = parse_time(started) if started else None
        if t0 is None:
            continue
        row = {"id": sid, "startedAt": t0.isoformat(), "mode": mode,
               "timeLimit": int(tl) if tl is not None else None,
               "tried": len(atts), "solved": sum(_clean(a[4], a[5]) for a in atts),
               "score": None, "ratingChange": None, "best": False, "inferred": False}
        if mode in RATED_MODES:
            if not atts:
                continue
            row["ratingChange"] = _rated_change(atts)
        else:
            if ended is None:
                continue
            row["score"] = int(score or 0)
            top = rush_best.get(str(int(tl))) if mode == "rush" and tl is not None else (
                surv_best if mode == "survival" else None)
            row["best"] = bool(top) and row["score"] == top
        out.append(row)
    for g in _group_loose(loose):
        mode = g[0][2]
        out.append({"id": None, "startedAt": g[0][3].isoformat(), "mode": mode, "timeLimit": None,
                    "tried": len(g), "solved": sum(_clean(a[4], a[5]) for a in g),
                    "score": None,
                    "ratingChange": _rated_change(g) if mode in RATED_MODES else None,
                    "best": False, "inferred": True})
    out.sort(key=lambda r: r["startedAt"], reverse=True)
    return out[:limit]


def summarize(attempts: Sequence[tuple], sessions: Sequence[tuple],
              current: float | None, now: datetime) -> dict:
    """The lobby's figures. attempts and sessions as in `recent_sessions`; *current* is
    puzzle_rating's stored rating (None before the first rated puzzle)."""
    rush, survival = bests(sessions)
    tries = len(attempts)
    solved = sum(_clean(a[4], a[5]) for a in attempts)
    row = puzzle_row([(a[3], a[6], a[7]) for a in attempts], current, now)
    return {
        "rating": row,
        "tries": tries,
        "solved": solved,
        "rushBest": rush,
        "survivalBest": survival,
        "sessions": recent_sessions(attempts, sessions),
        "sessionGapMin": SESSION_GAP_MIN,
    }
