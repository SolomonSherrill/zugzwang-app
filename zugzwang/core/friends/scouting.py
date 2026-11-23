"""A friend's profile figures, engine-free (FRIENDS.md ruling S3): from the games' headers and moves
alone, as the sites publish them. Nothing here runs an engine or reads the user's own games table.

Input rows are `friend_games` rows (dicts): the friend's games on each linked site, each with
`player` = the friend's username on that site.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from zugzwang.core.friends import rating_compare

SPEED_ORDER = ("blitz", "rapid", "bullet", "classical", "daily")
SITE_LABEL = {"chesscom": "Chess.com", "lichess": "Lichess", "here": "Played here"}


def _when(row: dict) -> datetime | None:
    s = row.get("ended_at")
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def side_of(row: dict, username: str) -> str | None:
    u = username.lower()
    if (row.get("white") or "").lower() == u:
        return "white"
    if (row.get("black") or "").lower() == u:
        return "black"
    return None


def outcome_for(row: dict, color: str | None) -> str | None:
    """'won' | 'drawn' | 'lost' for the player of *color*."""
    r = row.get("result")
    if color is None or r not in ("1-0", "0-1", "1/2-1/2"):
        return None
    if r == "1/2-1/2":
        return "drawn"
    return "won" if (r == "1-0") == (color == "white") else "lost"


def family(name: str | None) -> str | None:
    if not name:
        return None
    return name.split(":")[0].strip() or None


def _wdl(outs: list[str]) -> dict:
    w, d, l = outs.count("won"), outs.count("drawn"), outs.count("lost")
    n = w + d + l
    return {"games": n, "won": w, "drawn": d, "lost": l,
            "score": round(100 * (w + d / 2) / n, 1) if n else None}


def _eco_range(ecos: list[str]) -> str | None:
    ecos = sorted(e for e in ecos if e)
    if not ecos:
        return None
    return ecos[0] if ecos[0] == ecos[-1] else f"{ecos[0]}–{ecos[-1]}"


def opening_table(rows: list[dict], limit: int = 5) -> list[dict]:
    """Opening families by games: [{opening, eco, games, won, drawn, lost, score}] (the friend's side)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        f = family(r.get("opening"))
        if f:
            groups[f].append(r)
    out = []
    for f, rs in groups.items():
        outs = [o for o in (outcome_for(r, side_of(r, r["player"])) for r in rs) if o]
        out.append({"opening": f, "eco": _eco_range([r.get("eco") for r in rs]), **_wdl(outs)})
    out.sort(key=lambda x: (-x["games"], x["opening"]))
    return out[:limit]


def _bucket(termination: str | None) -> str:
    t = (termination or "").lower()
    if t == "checkmate":
        return "mate"
    if t in ("timeout", "abandonment"):
        return "time"
    if t == "resignation":
        return "resigned"
    return "other"


def endings(rows: list[dict]) -> dict:
    """How their games end: draws, and the wins and losses split by mate, resignation and time."""
    won: dict[str, int] = defaultdict(int)
    lost: dict[str, int] = defaultdict(int)
    draws = n = 0
    for r in rows:
        o = outcome_for(r, side_of(r, r["player"]))
        if o is None:
            continue
        n += 1
        if o == "drawn":
            draws += 1
        else:
            (won if o == "won" else lost)[_bucket(r.get("termination"))] += 1

    def split(d: dict) -> dict:
        total = sum(d.values())
        pct = {k: round(100 * d.get(k, 0) / total) if total else 0 for k in ("mate", "resigned", "time", "other")}
        return {"games": total, "pct": round(100 * total / n) if n else 0, "by": pct}

    return {"games": n, "draws": {"games": draws, "pct": round(100 * draws / n) if n else 0},
            "won": split(won), "lost": split(lost)}


def by_speed(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        o = outcome_for(r, side_of(r, r["player"]))
        if o and r.get("speed"):
            groups[r["speed"]].append(o)
    out = [{"speed": s, **_wdl(o)} for s, o in groups.items()]
    out.sort(key=lambda x: (SPEED_ORDER.index(x["speed"]) if x["speed"] in SPEED_ORDER else 9, -x["games"]))
    return out


def ratings(rows: list[dict], now: datetime) -> list[dict]:
    """Their rating per site and mode from their rated games: the latest, and its change over 30 days."""
    per: dict[tuple[str, str], list[tuple[datetime, int]]] = defaultdict(list)
    for r in rows:
        color = side_of(r, r["player"])
        when = _when(r)
        elo = r.get(f"{color}_elo") if color else None
        if not r.get("rated") or when is None or not isinstance(elo, int) or not r.get("speed"):
            continue
        per[(r["site"], r["speed"])].append((when, elo))
    cut = now - timedelta(days=30)
    out = []
    for (site, speed), pts in per.items():
        pts.sort()
        latest = pts[-1][1]
        before = [e for t, e in pts if t <= cut]
        recent = [e for t, e in pts if t > cut]
        base = before[-1] if before else (recent[0] if recent else None)
        out.append({"site": site, "speed": speed, "rating": latest, "games": len(pts),
                    "delta30": (latest - base) if base is not None and recent else None,
                    "spark": spark_series(before[-1:] + recent),
                    "estimate": (rating_compare.lichess_to_chesscom(latest, speed)
                                 if site == "lichess" else None)})
    out.sort(key=lambda x: (x["site"] != "chesscom", -x["games"]))
    return out


#: at most this many points in a rating cell's sparkline (FRIENDS-1B D; the mockup draws 5–7)
SPARK_POINTS = 24


def spark_series(values: list[int], n: int = SPARK_POINTS) -> list[int]:
    """The rating cell's sparkline: the rating after each rated game of the last 30 days, led by the last
    one before them (so the line starts where the 30-day change counts from), in game order; at most *n*
    evenly spaced points, always the first and the last. Empty with fewer than two values (no line)."""
    if len(values) < 2:
        return []
    if len(values) <= n:
        return list(values)
    step = (len(values) - 1) / (n - 1)
    return [values[round(i * step)] for i in range(n)]


def list_ratings(r: list[dict], n: int = 2) -> list[dict]:
    """The friends list's Ratings column: Chess.com ratings, or "≈" ones from Lichess when the friend
    has no Chess.com games (R1, R2). Their two most-played modes."""
    cc = [x for x in r if x["site"] == "chesscom"]
    if cc:
        return [{"speed": x["speed"], "rating": x["rating"], "approx": False} for x in cc[:n]]
    li = [x for x in r if x["site"] == "lichess" and x.get("estimate") is not None]
    return [{"speed": rating_compare.chesscom_mode(x["speed"]) or x["speed"], "rating": x["estimate"],
             "approx": True, "lichess": x["rating"]} for x in li[:n]]


def together(rows: list[dict], mine: dict[str, str]) -> tuple[list[dict], dict]:
    """Games between the friend and you, from your side: on Chess.com and Lichess between the two linked
    accounts (S3). (Games played here come with FRIENDS-2.)"""
    seen = set()
    games = []
    for r in rows:
        me = (mine.get(r["site"]) or "").strip()
        if not me:
            continue
        my_color = side_of(r, me)
        if my_color is None or side_of(r, r["player"]) is None:
            continue
        key = (r["site"], r["platform_id"])
        if key in seen:
            continue
        seen.add(key)
        games.append({"id": r["id"], "site": r["site"], "where": SITE_LABEL.get(r["site"], r["site"]),
                      "result": outcome_for(r, my_color), "color": my_color, "time_control": r.get("time_control"),
                      "opening": r.get("opening"), "eco": r.get("eco"), "ended_at": r.get("ended_at")})
    games.sort(key=lambda g: g["ended_at"] or "", reverse=True)
    rec = _wdl([g["result"] for g in games if g["result"]])
    return games, rec


def recent(rows: list[dict], limit: int, offset: int = 0) -> list[dict]:
    rs = sorted(rows, key=lambda r: r.get("ended_at") or "", reverse=True)[offset:offset + limit]
    return [{"id": r["id"], "site": r["site"], "where": SITE_LABEL.get(r["site"], r["site"]),
             "result": outcome_for(r, side_of(r, r["player"])), "white": r.get("white"),
             "black": r.get("black"), "white_elo": r.get("white_elo"), "black_elo": r.get("black_elo"),
             "player": r["player"], "opening": r.get("opening"), "eco": r.get("eco"),
             "time_control": r.get("time_control"), "ended_at": r.get("ended_at")} for r in rs]


def profile(rows: list[dict], mine: dict[str, str], now: datetime, *, recent_limit: int = 10,
            recent_offset: int = 0) -> dict:
    as_white = [r for r in rows if side_of(r, r["player"]) == "white"]
    as_black = [r for r in rows if side_of(r, r["player"]) == "black"]
    games, rec = together(rows, mine)
    per_site: dict[str, int] = defaultdict(int)
    for r in rows:
        per_site[r["site"]] += 1
    oldest = min((r["ended_at"] for r in rows if r.get("ended_at")), default=None)
    r = ratings(rows, now)
    return {
        "ratings": r,
        "listRatings": list_ratings(r),
        "record": rec,
        "together": games,
        "scouting": {
            "asWhite": opening_table(as_white),
            "vsE4": opening_table([x for x in as_black if x.get("first_move") == "e2e4"]),
            "vsD4": opening_table([x for x in as_black if x.get("first_move") == "d2d4"]),
            "games": len(rows), "sites": dict(per_site), "oldest": oldest,
        },
        "bySpeed": by_speed(rows),
        "endings": endings(rows),
        "recent": recent(rows, recent_limit, recent_offset),
        "recentTotal": len(rows),
    }
