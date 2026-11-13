"""
Qt-free PGN import helpers.

Parses a PGN string that may contain *many* games (Gap A) and, for each game,
determines which colour the user played by matching their saved username(s)
against the White/Black headers (Gap B). Both front-ends and the platform-sync
layer use this so imported games carry the correct per-side metadata.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

import chess
import chess.pgn

if TYPE_CHECKING:
    from zugzwang.core.openings import OpeningsBook


@dataclass
class ParsedGame:
    played_at: str
    player_color: str | None   # 'white' | 'black', or None when it cannot be attributed
    result: str
    termination: str
    move_count: int
    pgn: str
    final_fen: str
    opening_eco: str | None
    opening_name: str | None
    external_id: str | None = None   # source platform game id (sync dedup)
    not_owner: bool = False          # handles were configured and neither side matched


@dataclass
class GameIssue:
    """One game in the file that did not import cleanly.

    `imported` distinguishes the two outcomes, which is the whole point: a game
    with no moves is dropped, but a game python-chess gave up partway through is
    still stored — truncated, and previously without a word to the user.
    """
    index: int         # 1-based position in the file, so it can be found again
    label: str         # from the headers only; never move text
    reason: str
    imported: bool


@dataclass
class ImportReport:
    games: list[ParsedGame]
    issues: list[GameIssue]


def _label(headers: chess.pgn.Headers) -> str:
    white = headers.get("White", "?") or "?"
    black = headers.get("Black", "?") or "?"
    date = headers.get("Date", "") or headers.get("UTCDate", "")
    date = "" if not date or "?" in date else f", {date}"
    return f"{white} vs {black}{date}"


def _parse_played_at(headers: chess.pgn.Headers) -> str:
    """Best-effort ISO timestamp from the PGN date+time headers, falling back to
    now. Lichess and Chess.com both pair a date header with a UTC clock time
    (``UTCTime``/``StartTime``); capturing it is what makes the time-of-day
    breakdown meaningful — without it every game collapses to midnight."""
    for date_key, time_key in (("UTCDate", "UTCTime"), ("Date", "StartTime"), ("Date", "Time")):
        date_str = headers.get(date_key, "")
        if not date_str or "?" in date_str:
            continue
        for dfmt in ("%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                day = datetime.strptime(date_str, dfmt)
            except ValueError:
                continue
            time_str = headers.get(time_key, "").strip()
            if time_str and "?" not in time_str:
                for tfmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t = datetime.strptime(time_str, tfmt)
                    except ValueError:
                        continue
                    day = day.replace(hour=t.hour, minute=t.minute, second=t.second)
                    break
            return day.replace(tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _match_color(headers: chess.pgn.Headers, usernames: list[str]) -> str | None:
    """The side a saved username plays in these headers, or None if none does.

    Case-insensitive, whitespace-trimmed. None is a real answer, not an error: it
    means the headers say nothing about which side is the user's.
    """
    wanted = {u.strip().lower() for u in usernames if u and u.strip()}
    white = headers.get("White", "").strip().lower()
    black = headers.get("Black", "").strip().lower()
    if white in wanted:
        return "white"
    if black in wanted:
        return "black"
    return None


@dataclass(frozen=True)
class Attribution:
    """Whose side the user played, and why that is or is not known (FIXPLAN O5).

    `status` is one of:
      * ``matched``    — exactly one side is a handle of the user's;
      * ``ambiguous``  — both sides are (one of the user's names against another);
      * ``no_handles`` — nothing was configured, so nothing can be known;
      * ``not_owner``  — handles were configured and **neither** side matched: this
        is not the user's game, and it is excluded from Insights, accuracy and every
        corpus baseline. Game 41 was one (`BabyMagnus30` vs `frostypenguin97`).

    There is **no default colour.** Defaulting a miss to White is what put 826
    games on the wrong side (W11).
    """

    color: str | None
    status: str

    @property
    def not_owner(self) -> bool:
        return self.status == "not_owner"


def attribute(headers: chess.pgn.Headers, usernames: list[str],
              aliases: dict[str, list[str]] | None = None) -> Attribution:
    """Attribute a game's side from its headers, recognising former handles.

    *usernames* are the configured handles; each is expanded with its former handles
    (`handles.former_handles()`, or *aliases* in tests) before matching, so a game
    played under a former handle, before a rename, is still the user's.
    """
    from .handles import expand

    wanted = set(expand(usernames, aliases))
    if not wanted:
        return Attribution(None, "no_handles")
    white = headers.get("White", "").strip().lower()
    black = headers.get("Black", "").strip().lower()
    if white in wanted and black in wanted:
        return Attribution(None, "ambiguous")
    if white in wanted:
        return Attribution("white", "matched")
    if black in wanted:
        return Attribution("black", "matched")
    return Attribution(None, "not_owner")


_CHESSCOM_GAME_ID = re.compile(r"/(\d{6,})(?=[/?#]|$)")


def _external_id(headers: chess.pgn.Headers) -> str | None:
    """Extract the source platform's game id from the Site (Lichess) or Link
    (Chess.com) header.

    chess.com: the numeric game id, wherever it sits. A file export's Link can be
    `.../game/live/<id>?move=0` or `.../analysis/game/live/<id>/analysis`,
    and taking the last path segment returned the literal `'analysis'` for the
    second, so such an import never deduplicated against the synced game (REPULL
    step 0 found three duplicates). Lichess: the last path segment, as before.
    """
    for key in ("Site", "Link"):
        url = headers.get(key, "").strip()
        if "chess.com/" in url:
            found = _CHESSCOM_GAME_ID.findall(url.split("#")[0])
            if found:
                return found[-1]
        elif "lichess.org/" in url:
            seg = url.rstrip("/").rsplit("/", 1)[-1]
            # Lichess game ids are 8 chars; a study/embed adds a colour suffix.
            seg = seg.split("#")[0].split("?")[0]
            if seg:
                return seg
    return None


def _termination_from_board(board: chess.Board) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient material"
    return "imported"


# Keyword → normalized termination. Order matters (first match wins). Draw-type
# keywords precede "time" so "drawn by timeout vs insufficient material" reads as
# the draw reason, while a decisive "won on time" still falls through to timeout.
_TERMINATION_KEYWORDS = [
    ("checkmate", "checkmate"),
    ("resign", "resignation"),
    ("stalemate", "stalemate"),
    ("insufficient", "insufficient material"),
    ("repetition", "repetition"),
    ("agree", "agreement"),
    ("50", "fifty-move rule"),
    ("fifty", "fifty-move rule"),
    ("abandon", "abandonment"),
    ("time", "timeout"),               # "won on time", "Time forfeit"
]


def _termination(headers: chess.pgn.Headers, board: chess.Board) -> str:
    """Prefer the platform's [Termination] header (Chess.com is descriptive,
    e.g. 'X won by resignation'); fall back to board state. Lichess uses a
    generic 'Normal', which we resolve from the board instead."""
    raw = headers.get("Termination", "").strip().lower()
    # Chess.com opens with the winner's handle ("<handle> won by resignation"), and a
    # handle can hold a keyword: "…checkmate… won by resignation" read as checkmate, and
    # "…50… won on time" as the fifty-move rule (W13; owner ruling AUDIT-K4, 2026-11-11).
    # Only the words after the handle may decide.
    for side in ("White", "Black"):
        name = headers.get(side, "").strip().lower()
        if name and name not in ("?", "") and raw.startswith(name + " "):
            raw = raw[len(name) + 1:]
            break
    if raw and raw not in ("normal", "?", "unterminated"):
        for keyword, label in _TERMINATION_KEYWORDS:
            if keyword in raw:
                return label
        if "draw" in raw:
            return "draw"
    return _termination_from_board(board)


def parse_pgn_games(
    pgn_text: str,
    *,
    usernames: list[str] | None = None,
    openings: "OpeningsBook | None" = None,
    keep_comments: bool = False,
) -> Iterator[ParsedGame]:
    """Yield a ParsedGame for every game in *pgn_text*.

    Reads the stream game-by-game (Gap A); games with no moves are skipped.
    Set *keep_comments* to preserve move annotations (e.g. Lichess ``[%eval]``)
    in the stored PGN — platform sync needs them for eval-based classification.

    Silent about anything that went wrong. Use `parse_pgn_report` where a person
    is watching the result.
    """
    for item in _parse(pgn_text, usernames=usernames, openings=openings,
                       keep_comments=keep_comments):
        if isinstance(item, ParsedGame):
            yield item


def parse_pgn_report(
    pgn_text: str,
    *,
    usernames: list[str] | None = None,
    openings: "OpeningsBook | None" = None,
    keep_comments: bool = False,
) -> ImportReport:
    """`parse_pgn_games`, keeping the per-game problems instead of discarding them.

    **What this cannot see.** The issues come from python-chess's own `game.errors`,
    and that list is not complete: a token which is not valid SAN *syntax* is
    dropped by the tokeniser without being recorded at all. In `1. e4 e5 2. Qh9 Nf6`
    the `Qh9` vanishes silently and the reported error is against `Nf6`, which was
    only illegal because the move before it was skipped. So an issue means something
    is certainly wrong, while no issue does not prove the game is whole. Detecting
    the dropped-token case would mean re-implementing the tokeniser, which is not
    worth it; it is recorded here so the guarantee is not overstated.
    """
    games: list[ParsedGame] = []
    issues: list[GameIssue] = []
    for item in _parse(pgn_text, usernames=usernames, openings=openings,
                       keep_comments=keep_comments):
        (games if isinstance(item, ParsedGame) else issues).append(item)
    return ImportReport(games=games, issues=issues)


def _parse(
    pgn_text: str,
    *,
    usernames: list[str] | None = None,
    openings: "OpeningsBook | None" = None,
    keep_comments: bool = False,
) -> Iterator[ParsedGame | GameIssue]:
    """The single parse loop behind both entry points, yielding games and problems
    interleaved in file order so neither caller has to parse twice."""
    usernames = usernames or []
    stream = io.StringIO(pgn_text)

    index = 0
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        index += 1
        moves = list(game.mainline_moves())
        if not moves:
            yield GameIssue(
                index=index,
                label=_label(game.headers),
                reason="no moves",
                imported=False,
            )
            continue
        if game.errors:
            # python-chess stops the mainline at the first move it cannot play and
            # records why. The game is still imported — a truncated game is likely
            # more use than none — but silently storing it as if it were complete
            # is how a five-move game became a two-move one with no trace.
            yield GameIssue(
                index=index,
                label=_label(game.headers),
                reason=(
                    f"stopped after {len(moves)} plies: {game.errors[0]}"
                ),
                imported=True,
            )

        # A fresh exporter per game — StringExporter accumulates state, so a
        # shared instance would prepend earlier games to each game's PGN.
        exporter = chess.pgn.StringExporter(
            headers=True, variations=False, comments=keep_comments
        )

        headers = game.headers
        board = game.board()
        last_opening: tuple[str, str] | None = None
        for move in moves:
            board.push(move)
            if openings is not None:
                found = openings.name_after(board)
                if found is not None:
                    last_opening = found

        side = attribute(headers, usernames)
        yield ParsedGame(
            played_at=_parse_played_at(headers),
            player_color=side.color,
            not_owner=side.not_owner,
            result=headers.get("Result", "*"),
            termination=_termination(headers, board),
            move_count=board.ply(),
            pgn=game.accept(exporter),
            final_fen=board.fen(),
            opening_eco=last_opening[0] if last_opening else None,
            opening_name=last_opening[1] if last_opening else None,
            external_id=_external_id(headers),
        )
