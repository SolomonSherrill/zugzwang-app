"""Friends' public games from the Chess.com and Lichess public APIs (FRIENDS.md rulings G3, G5).

- **One request at a time** (a process-wide lock and a short gap between requests), **backing off when
  a site asks**: HTTP 429 waits for its Retry-After (or 2, 4, 8 … s, at most 60) and tries again.
- **The last 12 months first** (G3): Chess.com's twelve newest monthly archives, Lichess's games since
  365 days ago. **Older on request**: the twelve months before the oldest fetched, each time.
- Standard chess only, as sync (platform_sync): Chess.com `rules == "chess"` from the standard start;
  Lichess perfType bullet … classical and correspondence; aborted Lichess games are dropped.

Rows are plain dicts for `Database.save_friend_games`. The opening is named the app's own way (the
ECO table of `OpeningsBook`, last named position of the mainline), so scouting groups like Insights.
The API bases can be pointed elsewhere for the headless end-to-end run (ZUGZWANG_CHESSCOM_API,
ZUGZWANG_LICHESS_API); nothing else reads them.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chess
import chess.pgn

import zugzwang.config as C
from zugzwang.core.import_pgn import _termination

logger = logging.getLogger(__name__)

SITES = ("chesscom", "lichess")
WINDOW_MONTHS = 12
_STANDARD = chess.STARTING_FEN
_LOCK = threading.Lock()
_last_request = [0.0]
#: the gap between two requests to the sites, seconds
GAP_S = 0.25
MAX_WAIT_S = 60.0


class FetchError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def chesscom_api() -> str:
    return os.environ.get("ZUGZWANG_CHESSCOM_API", "https://api.chess.com").rstrip("/")


def lichess_api() -> str:
    return os.environ.get("ZUGZWANG_LICHESS_API", "https://lichess.org").rstrip("/")


def _get(url: str, accept: str, *, tries: int = 5) -> str:
    """GET one URL, one request at a time across the process, waiting when a site asks."""
    sleep = time.sleep
    wait = 2.0
    for attempt in range(tries):
        with _LOCK:
            gap = GAP_S - (time.monotonic() - _last_request[0])
            if gap > 0:
                sleep(gap)
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": C.SYNC_USER_AGENT})
            try:
                from zugzwang.core.platform_sync import _tls_context
                ctx = _tls_context() if url.startswith("https:") else None
                extra = {"context": ctx} if ctx is not None else {}
                with urllib.request.urlopen(req, timeout=60, **extra) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < tries - 1:
                    ra = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = min(MAX_WAIT_S, float(ra)) if ra else wait
                    except ValueError:
                        delay = wait
                    logger.info("friends fetch: the site asked to wait (429); %.1f s", delay)
                    sleep(delay)
                    wait = min(MAX_WAIT_S, wait * 2)
                    continue
                if exc.code >= 500 and attempt < 2:
                    sleep(wait)
                    continue
                raise FetchError(f"HTTP {exc.code}", exc.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise FetchError(f"network error: {getattr(exc, 'reason', exc)}") from None
            finally:
                _last_request[0] = time.monotonic()
    raise FetchError("gave up after repeated waits")


def _name_opening(game: chess.pgn.Game, eco_book) -> tuple[str | None, str | None]:
    if eco_book is None:
        return None, None
    board = game.board()
    named = None
    for i, mv in enumerate(game.mainline_moves()):
        board.push(mv)
        hit = eco_book.name_after(board)
        if hit:
            named = hit
        if i > 40:
            break
    return named if named else (None, None)


def _parse_pgn(pgn: str) -> chess.pgn.Game | None:
    try:
        g = chess.pgn.read_game(io.StringIO(pgn))
    except Exception:
        return None
    if g is None or not list(g.mainline_moves()):
        return None
    return g


def _first(g: chess.pgn.Game) -> str | None:
    mv = next(iter(g.mainline_moves()), None)
    return mv.uci() if mv else None


def _final_board(g: chess.pgn.Game) -> chess.Board:
    b = g.board()
    for mv in g.mainline_moves():
        b.push(mv)
    return b


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tc(tc: str | None) -> tuple[int | None, int | None]:
    if not tc or tc == "-" or "/" in tc:
        return None, None
    base, _, inc = tc.partition("+")
    try:
        return int(base), int(inc or 0)
    except ValueError:
        return None, None


# ── Chess.com ───────────────────────────────────────────────────────────────

def chesscom_archives(username: str) -> list[str]:
    url = f"{chesscom_api()}/pub/player/{urllib.parse.quote(username.lower(), safe='')}/games/archives"
    try:
        return list(json.loads(_get(url, "application/json")).get("archives", []))
    except FetchError as exc:
        if exc.status in (404, 410):
            return []
        raise


def _month_of(archive_url: str) -> tuple[int, int]:
    parts = archive_url.rstrip("/").split("/")
    return int(parts[-2]), int(parts[-1])


def _month_start(y: int, m: int) -> datetime:
    return datetime(y, m, 1, tzinfo=timezone.utc)


def months_back(now: datetime, n: int) -> tuple[int, int]:
    """The (year, month) n-1 months before now's month: the oldest month of an n-month window."""
    y, m = now.year, now.month - (n - 1)
    while m <= 0:
        m += 12
        y -= 1
    return y, m


def chesscom_rows(username: str, games: list[dict], eco_book) -> list[dict]:
    rows = []
    for g in games:
        if g.get("rules") != "chess":
            continue
        setup = g.get("initial_setup")
        if setup and setup != _STANDARD:
            continue
        pgn = g.get("pgn") or ""
        game = _parse_pgn(pgn)
        if game is None:
            continue
        w, b = g.get("white") or {}, g.get("black") or {}
        base, inc = _tc(g.get("time_control"))
        eco, name = _name_opening(game, eco_book)
        result = game.headers.get("Result", "*")
        rows.append({
            "site": "chesscom",
            "platform_id": str(g.get("url", "")).rstrip("/").split("/")[-1] or str(g.get("uuid", "")),
            "player": username.lower(),
            "white": w.get("username"), "black": b.get("username"),
            "white_elo": w.get("rating"), "black_elo": b.get("rating"),
            "result": result,
            "time_control": g.get("time_control"), "base_s": base, "inc_s": inc,
            "speed": g.get("time_class"),
            "rated": 1 if g.get("rated") else 0,
            "termination": _termination(game.headers, _final_board(game)),
            "ended_at": _iso(g["end_time"]) if g.get("end_time") else None,
            "eco": eco or game.headers.get("ECO"), "opening": name,
            "first_move": _first(game),
            "pgn": pgn,
        })
    return rows


def fetch_chesscom(username: str, *, now: datetime, older_than: tuple[int, int] | None = None,
                   newer_than: tuple[int, int] | None = None, eco_book=None) -> dict:
    """One window of a player's games: the twelve months before *older_than* (exclusive), or the
    twelve newest (*older_than* None), or every month from *newer_than* on (a refresh).
    Returns {"rows", "oldest": (y, m) fetched or None, "complete": no older archive remains}."""
    archives = chesscom_archives(username)
    months = sorted((_month_of(a), a) for a in archives)
    if newer_than is not None:
        pick = [(ym, a) for ym, a in months if ym >= newer_than]
    elif older_than is not None:
        older = [(ym, a) for ym, a in months if ym < older_than]
        pick = older[-WINDOW_MONTHS:]
    else:
        lo = months_back(now, WINDOW_MONTHS)
        pick = [(ym, a) for ym, a in months if ym >= lo]
    rows: list[dict] = []
    for _ym, a in pick:
        games = json.loads(_get(a, "application/json")).get("games", [])
        rows += chesscom_rows(username, games, eco_book)
    oldest = pick[0][0] if pick else (older_than if older_than else months_back(now, WINDOW_MONTHS))
    complete = not any(ym < oldest for ym, _a in months)
    return {"rows": rows, "oldest": oldest, "complete": complete}


# ── Lichess ─────────────────────────────────────────────────────────────────

_LICHESS_TERMINATION = {
    "mate": "checkmate", "resign": "resignation", "outoftime": "timeout", "timeout": "abandonment",
    "draw": "draw", "stalemate": "stalemate",
}


def lichess_rows(username: str, games: list[dict], eco_book) -> list[dict]:
    rows = []
    for g in games:
        if g.get("variant", "standard") != "standard" or g.get("status") in ("aborted", "noStart", "created", "started"):
            continue
        pgn = g.get("pgn") or ""
        game = _parse_pgn(pgn)
        if game is None:
            continue
        pw = (g.get("players") or {}).get("white") or {}
        pb = (g.get("players") or {}).get("black") or {}
        clock = g.get("clock") or {}
        base, inc = clock.get("initial"), clock.get("increment")
        winner = g.get("winner")
        result = "1-0" if winner == "white" else "0-1" if winner == "black" else "1/2-1/2"
        eco, name = _name_opening(game, eco_book)
        speed = g.get("speed")
        speed = {"ultraBullet": "bullet", "correspondence": "daily"}.get(speed, speed)
        rows.append({
            "site": "lichess",
            "platform_id": str(g.get("id")),
            "player": username.lower(),
            "white": (pw.get("user") or {}).get("name"), "black": (pb.get("user") or {}).get("name"),
            "white_elo": pw.get("rating"), "black_elo": pb.get("rating"),
            "result": result,
            "time_control": f"{base}+{inc}" if base is not None else None, "base_s": base, "inc_s": inc,
            "speed": speed,
            "rated": 1 if g.get("rated") else 0,
            "termination": _LICHESS_TERMINATION.get(g.get("status"), _termination(game.headers, _final_board(game))),
            "ended_at": _iso(g["lastMoveAt"] / 1000) if g.get("lastMoveAt") else None,
            "eco": eco or (g.get("opening") or {}).get("eco"), "opening": name,
            "first_move": _first(game),
            "pgn": pgn,
        })
    return rows


def lichess_created(username: str) -> float | None:
    try:
        u = json.loads(_get(f"{lichess_api()}/api/user/{urllib.parse.quote(username, safe='')}",
                            "application/json"))
    except FetchError as exc:
        if exc.status in (404, 410):
            return None
        raise
    return u.get("createdAt") / 1000 if u.get("createdAt") else None


def fetch_lichess(username: str, *, since: datetime, until: datetime | None = None,
                  eco_book=None) -> list[dict]:
    params = {"since": int(since.timestamp() * 1000), "pgnInJson": "true", "opening": "true",
              "moves": "true", "clocks": "false", "evals": "false",
              "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence"}
    if until is not None:
        params["until"] = int(until.timestamp() * 1000)
    url = (f"{lichess_api()}/api/games/user/{urllib.parse.quote(username, safe='')}?"
           + urllib.parse.urlencode(params))
    try:
        body = _get(url, "application/x-ndjson")
    except FetchError as exc:
        if exc.status in (404, 410):
            return []
        raise
    games = [json.loads(line) for line in body.splitlines() if line.strip()]
    return lichess_rows(username, games, eco_book)


def eco_only_book():
    """An OpeningsBook with the ECO names and no Polyglot book, for the fetch thread (the app
    thread's book is not shared across threads)."""
    from zugzwang.core.openings import OpeningsBook
    return OpeningsBook(book_path=Path(os.devnull) / "no-book")


def window_start(now: datetime) -> datetime:
    return now - timedelta(days=365)
