"""The Games screen's list (UI-BUILD-3 E; DESIGN.md fourth rulings, 7; mockup
`design/mockups/MinimalGames.html`): one page of the user's games under the screen's filters,
with each month's record over **every** game the filters keep (not only the page), and each
listed game's two accuracies from its **standard** run (RUNS-DEPTH: `database.standard_run_sql`,
the depth-14 run first, as `list_games_with_runs` reads it). The stacked list (UI-BUILD-4 B, fifth
rulings 5) shows each player's accuracy on that player's line and no "Your errors" column, so the
page carries no error counts.

Read-only. The filters are the old Games screen's, moved to the backend so the page, the count and
the month records agree:

- **result** `win` / `draw` / `loss` from the user's side (`insights._outcome`, as Home and
  Insights read it); a game whose side is unknown or that is unfinished matches none of them.
- **color**, **source**, **rated** (`[Rated]` or Lichess's Event, `rated_from_pgn`, as the old
  list read it), **analysis** (a complete standard run or not).
- **speeds**: any of bullet, blitz, rapid, classical, daily (chess.com's "1/N" TimeControl,
  `home_summary.bucket`); none selected keeps every game.
- **since** / **until**: ISO instants, since inclusive, until exclusive (the screen turns "Last
  week", a custom range and the like into these).
- **opening**: a substring of the opening's name or ECO.
- **search**: a game id names one game exactly ("#483" the app's id; a bare token either the app's
  or the platform's id; a pasted Chess.com or Lichess game link its platform id, FIX-B8 D), else a
  substring of the opponent, the opening, the ECO or the date.

Months are local calendar months (the sidecar runs on the user's machine).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

from .database import rated_from_pgn, standard_run_sql
from .home_summary import bucket, headers, parse_time
from .insights import _outcome

SPEEDS = ("bullet", "blitz", "rapid", "classical", "daily")
SORTS = ("recent", "oldest", "accuracy_low", "accuracy_high", "opening")
PAGE = 50
PAGE_MAX = 500


@dataclass
class GamesQuery:
    search: str = ""
    result: str = "all"          # all | win | draw | loss
    color: str = "all"           # all | white | black
    speeds: Sequence[str] = field(default_factory=tuple)
    source: str = "all"          # all | local | chesscom | lichess | imported | friends
    rated: str = "all"           # all | rated | casual
    analysis: str = "all"        # all | analyzed | unanalyzed
    opening: str = ""
    since: str | None = None
    until: str | None = None
    sort: str = "recent"
    offset: int = 0
    limit: int = PAGE

    @classmethod
    def from_params(cls, p: dict) -> "GamesQuery":
        q = cls()
        for k in ("search", "result", "color", "source", "rated", "analysis", "opening", "sort"):
            v = p.get(k)
            if isinstance(v, str):
                setattr(q, k, v)
        q.speeds = tuple(s for s in (p.get("speeds") or []) if s in SPEEDS)
        q.since = p.get("since") or None
        q.until = p.get("until") or None
        q.offset = max(0, int(p.get("offset") or 0))
        q.limit = min(PAGE_MAX, max(1, int(p.get("limit") or PAGE)))
        if q.sort not in SORTS:
            q.sort = "recent"
        return q


@dataclass
class Row:
    """One game as the list reads it: the stored columns, the header fields it shows, and its
    standard run (None when it has none)."""
    id: int
    played_at: str
    player_color: str | None
    skill_level: int
    ladder_version: int | None
    result: str
    termination: str
    move_count: int
    opening_eco: str | None
    opening_name: str | None
    source: str
    external_id: str | None
    speed: str | None
    head: str                     # the PGN's header block
    run_id: int | None
    white_accuracy: float | None
    black_accuracy: float | None
    # FRIENDS-2: a friend game's ratings at its start (R1-R3), NULL when unknown
    start_white_rating: int | None = None
    start_white_est: int | None = None
    start_black_rating: int | None = None
    start_black_est: int | None = None
    # derived once
    h: dict = field(default_factory=dict)
    t: datetime | None = None

    def __post_init__(self) -> None:
        self.h = headers(self.head)
        self.t = parse_time(self.played_at)

    @property
    def outcome(self) -> str | None:
        if self.player_color not in ("white", "black"):
            return None
        return _outcome(self.player_color, self.result)

    @property
    def time_control(self) -> str | None:
        tc = (self.h.get("TimeControl") or "").strip()
        return tc if tc and tc not in ("-", "?") else None

    @property
    def speed_bucket(self) -> str | None:
        return bucket(self.speed, self.h.get("TimeControl"))

    @property
    def rated(self) -> bool | None:
        return rated_from_pgn(self.head)

    def name(self, side: str) -> str | None:
        v = (self.h.get("White" if side == "white" else "Black") or "").strip()
        return v or None

    def elo(self, side: str) -> int | None:
        v = (self.h.get("WhiteElo" if side == "white" else "BlackElo") or "").strip()
        return int(v) if v.isdigit() and int(v) > 0 else None

    @property
    def opponent(self) -> str:
        if self.source == "local":
            return "Stockfish"
        side = "white" if self.player_color == "black" else "black"
        return self.name(side) or "Unknown"

    def user_accuracy(self) -> float | None:
        if self.run_id is None or self.player_color not in ("white", "black"):
            return None
        return self.white_accuracy if self.player_color == "white" else self.black_accuracy


def load_rows(conn) -> list[Row]:
    """Every game with its header block and standard run, newest first. The header block only
    (`substr` up to the first blank line), so a 3,620-game library does not move every move."""
    sql = """
        SELECT g.id, g.played_at, g.player_color, g.skill_level, g.ladder_version, g.result,
               g.termination, g.move_count, g.opening_eco, g.opening_name, g.source,
               g.external_id, g.speed,
               CASE WHEN instr(g.pgn, char(10) || char(10)) > 0
                    THEN substr(g.pgn, 1, instr(g.pgn, char(10) || char(10)))
                    ELSE g.pgn END AS head,
               r.id AS run_id, r.white_accuracy, r.black_accuracy,
               g.start_white_rating, g.start_white_est, g.start_black_rating, g.start_black_est
        FROM games g
        LEFT JOIN analysis_runs r ON r.id = (
            SELECT s.id FROM analysis_runs s
            WHERE s.game_id = g.id AND s.completed_at IS NOT NULL
            ORDER BY {standard} DESC, s.id DESC LIMIT 1
        )
        ORDER BY g.played_at DESC, g.id DESC
    """.replace("{standard}", standard_run_sql("s"))
    return [Row(*tuple(r)) for r in conn.execute(sql)]


#: A Chess.com game link: /game/live/<id>, /game/daily/<id>, /live/game/<id>, /daily/game/<id>, /game/<id>, and the
#: same under /analysis/ (FIX-B8 D, owner note 3).
_CHESSCOM_URL = re.compile(r"chess\.com/(?:analysis/)?(?:game/(?:live/|daily/)?|live/(?:game/)?|daily/(?:game/)?)(\d+)")
#: A Lichess game link: lichess.org/<8-character id>, or the 12-character link a player's own view uses (the game's
#: id and 4 more), with /white, /black or a #ply after it.
_LICHESS_URL = re.compile(r"lichess\.org/([a-z0-9]{8})(?:[a-z0-9]{4})?(?=$|[/?#])", re.IGNORECASE)


def id_from_link(query: str) -> str | None:
    """The platform game id in a pasted Chess.com or Lichess game link, else None."""
    q = query.strip()
    m = _CHESSCOM_URL.search(q) or _LICHESS_URL.search(q)
    return m.group(1).lower() if m else None


def matches_id(query: str, game_id: int, external_id: str | None) -> bool:
    """Whether *query* names the game by id: "#483" is the app's id only; a bare token is the
    app's id or the platform's (chess.com numeric, Lichess 8 characters), exactly, never as a
    substring ("483" must not pull in every opponent whose name holds 483); a pasted game link
    names the platform's id it holds (FIX-B8 D)."""
    q = query.strip().lower()
    if not q:
        return False
    if q.startswith("#"):
        return q[1:] == str(game_id)
    link = id_from_link(q)
    if link is not None:
        return external_id is not None and link == external_id.lower()
    return q == str(game_id) or (external_id is not None and q == external_id.lower())


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _search_text(row: Row, tz: tzinfo | None) -> str:
    parts = [row.opponent, row.opening_name or "", row.opening_eco or "", row.played_at]
    if row.t is not None:
        lt = row.t.astimezone(tz)
        parts.append(f"{lt.day} {_MONTHS[lt.month - 1]} {lt.year}")
    return " ".join(parts).lower()


def matches(row: Row, q: GamesQuery, since: datetime | None, until: datetime | None,
            tz: tzinfo | None = None) -> bool:
    if q.result in ("win", "draw", "loss") and row.outcome != q.result:
        return False
    if q.color in ("white", "black") and row.player_color != q.color:
        return False
    if q.source != "all" and row.source != q.source:
        return False
    if q.speeds and row.speed_bucket not in q.speeds:
        return False
    if q.rated == "rated" and row.rated is not True:
        return False
    if q.rated == "casual" and row.rated is not False:
        return False
    if q.analysis == "analyzed" and row.run_id is None:
        return False
    if q.analysis == "unanalyzed" and row.run_id is not None:
        return False
    if since is not None and (row.t is None or row.t < since):
        return False
    if until is not None and (row.t is None or row.t >= until):
        return False
    o = q.opening.strip().lower()
    if o and o not in (row.opening_name or "").lower() and o not in (row.opening_eco or "").lower():
        return False
    s = q.search.strip().lower()
    if s and not matches_id(s, row.id, row.external_id):
        if s.startswith("#") or id_from_link(s) is not None or s not in _search_text(row, tz):
            return False
    return True


def month_key(row: Row, tz: tzinfo | None = None) -> str | None:
    if row.t is None:
        return None
    lt = row.t.astimezone(tz)
    return f"{lt.year:04d}-{lt.month:02d}"


def month_records(rows: Sequence[Row], tz: tzinfo | None = None) -> list[dict]:
    """Won, lost and drawn per local month over *rows* (every game the filters keep), newest
    month first; `games` counts every game of the month, unfinished and unattributed ones too."""
    by: dict[str, dict] = {}
    for r in rows:
        k = month_key(r, tz)
        if k is None:
            continue
        m = by.setdefault(k, {"month": k, "games": 0, "won": 0, "lost": 0, "drawn": 0})
        m["games"] += 1
        o = r.outcome
        if o == "win":
            m["won"] += 1
        elif o == "loss":
            m["lost"] += 1
        elif o == "draw":
            m["drawn"] += 1
    return [by[k] for k in sorted(by, reverse=True)]


def _sorted(rows: list[Row], sort: str) -> list[Row]:
    if sort == "oldest":
        return list(reversed(rows))
    if sort in ("accuracy_low", "accuracy_high"):
        have = [r for r in rows if r.user_accuracy() is not None]
        rest = [r for r in rows if r.user_accuracy() is None]   # unanalysed sink, newest first
        have.sort(key=lambda r: r.user_accuracy(), reverse=(sort == "accuracy_high"))
        return have + rest
    if sort == "opening":
        return sorted(rows, key=lambda r: ((r.opening_name or "~").lower(),))
    return rows                                                      # recent: as loaded


def start_ratings(w: int | None, w_est: int | None, b: int | None, b_est: int | None) -> dict | None:
    """A friend game's ratings at its start (FRIENDS-2), or None when neither is known."""
    if w is None and b is None:
        return None
    return {"white": {"rating": w, "estimated": bool(w_est)} if w is not None else None,
            "black": {"rating": b, "estimated": bool(b_est)} if b is not None else None}


def game_item(r: Row) -> dict:
    """One listed game, in `list_games`'s field names plus `timeControl` and `outcome`."""
    return {
        "id": r.id, "playedAt": r.played_at, "playerColor": r.player_color,
        "skillLevel": r.skill_level, "ladderVersion": r.ladder_version,
        "result": r.result, "termination": r.termination, "moveCount": r.move_count,
        "openingEco": r.opening_eco, "openingName": r.opening_name, "source": r.source,
        "externalId": r.external_id, "speed": r.speed, "speedBucket": r.speed_bucket,
        "rated": r.rated, "timeControl": r.time_control,
        "white": r.name("white"), "black": r.name("black"),
        "whiteElo": r.elo("white"), "blackElo": r.elo("black"),
        # FRIENDS-2 (R1-R3): stored apart from the real ratings; "≈" when estimated
        "startRatings": start_ratings(r.start_white_rating, r.start_white_est,
                                      r.start_black_rating, r.start_black_est),
        "whiteAccuracy": r.white_accuracy if r.run_id is not None else None,
        "blackAccuracy": r.black_accuracy if r.run_id is not None else None,
        "analyzed": r.run_id is not None,
        "outcome": r.outcome,
    }


def games_page(conn, q: GamesQuery, tz: tzinfo | None = None) -> dict:
    """One page under *q*: `games` (the page), `total` (games the filters keep), `all`
    (every stored game), `months` (each month's record over the kept games)."""
    rows = load_rows(conn)
    since = parse_time(q.since) if q.since else None
    until = parse_time(q.until) if q.until else None
    kept = [r for r in rows if matches(r, q, since, until, tz)]
    ordered = _sorted(kept, q.sort)
    page = ordered[q.offset:q.offset + q.limit]
    return {
        "games": [game_item(r) for r in page],
        "total": len(kept),
        "all": len(rows),
        "offset": q.offset,
        "months": month_records(kept, tz),
    }
