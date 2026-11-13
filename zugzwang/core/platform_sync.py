"""
Qt-free platform-sync fetch layer.

Downloads a player's recent rated games from external chess platforms and
returns them as ``ParsedGame`` objects (sharing the import parser so colour
detection, opening tagging and dedup ids all work the same as manual import).

Only the network fetch + parse lives here. Deciding which games are new,
running/queuing analysis and emitting progress is the caller's job (the sidecar
SyncRunner / PyQt worker), keeping this module free of threading and DB code.
"""

from __future__ import annotations

import functools
import ssl
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

import zugzwang.config as C
from zugzwang.core.import_pgn import ParsedGame, parse_pgn_games

if TYPE_CHECKING:
    from zugzwang.core.openings import OpeningsBook

logger = logging.getLogger(__name__)

_LICHESS_GAMES_URL = "https://lichess.org/api/games/user/{username}"
_CHESSCOM_ARCHIVES_URL = "https://api.chess.com/pub/player/{username}/games/archives"

# Standard chess starting position. Chess.com sets ``initial_setup`` to this for
# normal games; odds / custom-position games (which carry rules == "chess" but
# can't be replayed by our standard-chess board/opening/classification code)
# differ, so we exclude any game whose setup isn't the standard start.
_CHESSCOM_STANDARD_SETUP = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class SyncError(Exception):
    """Raised when a platform fetch fails irrecoverably."""


@functools.lru_cache(maxsize=1)
def _tls_context() -> ssl.SSLContext | None:
    """Certificates from `certifi` when it is installed (BETA, M12).

    A Python's OpenSSL looks for CA certificates where it was built to: Homebrew's points
    at `/opt/homebrew/etc/openssl@…/cert.pem`. A frozen copy on a Mac without Homebrew has
    no CA bundle at all, and every fetch would fail certificate verification. The packaged
    app ships `certifi`; None leaves urllib's default, which a checkout always had."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _http_get(
    url: str,
    headers: dict[str, str],
    *,
    timeout: int = 60,
    max_retries: int = 3,
) -> str:
    """GET *url* and return the decoded body. Retries on HTTP 429 with the
    server's Retry-After (or exponential backoff). Raises SyncError on
    persistent failure."""
    backoff = 2.0
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            ctx = _tls_context()
            extra = {"context": ctx} if ctx is not None else {}
            with urllib.request.urlopen(req, timeout=timeout, **extra) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries - 1:
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                logger.warning("Rate limited (429); waiting %.1fs", wait)
                time.sleep(wait)
                backoff *= 2
                continue
            if exc.code == 404:
                raise SyncError(
                    f"User not found (HTTP 404) for {url} — check the username is "
                    "correct and on the right platform."
                ) from exc
            raise SyncError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise SyncError(f"Network error fetching {url}: {exc.reason}") from exc
    raise SyncError(f"Gave up fetching {url} after {max_retries} attempts")


def fetch_lichess_pgn(username: str, *, max_games: int | None = C.SYNC_MAX_GAMES) -> str:
    """Return the raw multi-game PGN for *username*'s last *max_games* standard
    games (rated and casual), with embedded ``[%eval]`` annotations and opening
    tags requested. ``max_games=None`` fetches the player's entire history.

    ``perfType`` restricts to standard time-control play; this excludes variants
    (Crazyhouse, Chess960, Atomic, …) which our board/opening/classification
    code can't handle, mirroring the chess.com ``rules == "chess"`` filter."""
    username = username.strip()
    if not username:
        raise SyncError("No Lichess username configured.")
    params = {
        "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence",
        "evals": "true",
        "opening": "true",
        "clocks": "false",
        "moves": "true",
    }
    if max_games is not None:
        params["max"] = max_games  # omitted ⇒ Lichess streams the full history
    query = urllib.parse.urlencode(params)
    url = f"{_LICHESS_GAMES_URL.format(username=urllib.parse.quote(username))}?{query}"
    return _http_get(
        url,
        {
            "Accept": "application/x-chess-pgn",
            "User-Agent": C.SYNC_USER_AGENT,
        },
    )


def fetch_lichess_games(
    username: str,
    *,
    usernames: list[str] | None = None,
    openings: "OpeningsBook | None" = None,
    max_games: int | None = C.SYNC_MAX_GAMES,
) -> list[ParsedGame]:
    """Fetch and parse *username*'s recent rated Lichess games. The PGN keeps
    move comments so embedded evals survive for later classification."""
    pgn = fetch_lichess_pgn(username, max_games=max_games)
    return list(
        parse_pgn_games(
            pgn,
            usernames=usernames or [username],
            openings=openings,
            keep_comments=True,
        )
    )


# ── Chess.com ─────────────────────────────────────────────────────────────────

def _http_get_json(url: str) -> dict:
    body = _http_get(
        url,
        {"Accept": "application/json", "User-Agent": C.SYNC_USER_AGENT},
    )
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SyncError(f"Bad JSON from {url}: {exc}") from exc


def _tag_rated(pgn: str, rated: object) -> str:
    """Prepend a ``[Rated "true"|"false"]`` header to a Chess.com game PGN.

    Chess.com PGNs carry no rated/casual indicator (unlike Lichess, whose Event
    header reads "Rated …"/"Casual …"); the flag lives only in the JSON. We fold
    it into the stored PGN so display code can derive rated vs. casual without a
    schema or ``source`` change. python-chess re-exports headers in canonical
    order, so prepending is safe even though Event conventionally comes first."""
    return f'[Rated "{str(bool(rated)).lower()}"]\n{pgn}'


def fetch_chesscom_pgn(
    username: str, *, max_games: int | None = C.SYNC_MAX_GAMES
) -> str:
    """Return a concatenated PGN of *username*'s last *max_games* standard games.
    ``max_games=None`` collects the player's entire archive history.

    Chess.com publishes games in monthly archives (oldest→newest). We walk the
    archives newest-first, collecting standard-chess games (rated or casual)
    until we have enough, then return them in chronological order.

    Two filters keep this to games our board/opening/classification code can
    replay: (1) ``rules == "chess"`` drops every named variant (chess960,
    bughouse, crazyhouse, threecheck, king-of-the-hill, …); (2) the starting
    position must be the standard one, dropping odds / custom-position games that
    carry ``rules == "chess"`` but begin from a non-standard ``initial_setup``.
    Both rated and unrated games are kept by design. Chess.com PGNs carry no
    ``[%eval]``, so these games are later analysed with local Stockfish."""
    username = username.strip().lower()
    if not username:
        raise SyncError("No Chess.com username configured.")
    archives_url = _CHESSCOM_ARCHIVES_URL.format(
        username=urllib.parse.quote(username)
    )
    archives = _http_get_json(archives_url).get("archives", [])

    collected: list[str] = []
    for archive_url in reversed(archives):
        if max_games is not None and len(collected) >= max_games:
            break
        games = _http_get_json(archive_url).get("games", [])
        for g in reversed(games):  # newest-first within the month
            if max_games is not None and len(collected) >= max_games:
                break
            if g.get("rules") != "chess":  # exclude 960/bughouse/etc.
                continue
            setup = g.get("initial_setup")
            if setup and setup != _CHESSCOM_STANDARD_SETUP:
                continue  # odds / custom-position game — not standard chess
            pgn = g.get("pgn")
            if pgn:
                collected.append(_tag_rated(pgn, g.get("rated")))

    collected.reverse()  # back to chronological order
    return "\n\n".join(collected)


def fetch_chesscom_games(
    username: str,
    *,
    usernames: list[str] | None = None,
    openings: "OpeningsBook | None" = None,
    max_games: int | None = C.SYNC_MAX_GAMES,
) -> list[ParsedGame]:
    """Fetch and parse *username*'s recent standard Chess.com games (rated and
    casual; variants and custom-position games excluded by fetch_chesscom_pgn)."""
    pgn = fetch_chesscom_pgn(username, max_games=max_games)
    return list(
        parse_pgn_games(
            pgn,
            usernames=usernames or [username],
            openings=openings,
            keep_comments=True,
        )
    )
