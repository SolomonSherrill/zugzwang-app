"""Position legality, checked before any engine sees a position (FIXPLAN VAL-FEN).

`chess.Board(fen)` rejects a *malformed* FEN and accepts a well-formed *illegal* one:
no kings, two kings of one colour, a pawn on the first rank, the side not to move
already in check. Measured against the bundled Stockfish
(`review/scratch/val_illegal_engine.out`, 2026-10-22):

  * **no kings: Stockfish segfaults** (exit −11) — python-chess raises
    `EngineTerminatedError`, and the engine is gone;
  * the other three are **analysed silently**: confident evaluations (+0.04, +0.35,
    +5.32) of positions that cannot occur, with no error anywhere.

So legality is a precondition, enforced at every boundary where a position enters
from outside — an RPC's FEN, a PGN's `[FEN]` start — with an error that says what is
wrong. `board.is_valid()` is python-chess's full test (`board.status()`).
"""

from __future__ import annotations

import chess

# Plain-language reasons for each `board.status()` flag, in the order they are
# reported. Every flag python-chess defines is listed, so none is ever unexplained.
_REASONS = (
    (chess.STATUS_EMPTY, "the board is empty"),
    (chess.STATUS_NO_WHITE_KING, "White has no king"),
    (chess.STATUS_NO_BLACK_KING, "Black has no king"),
    (chess.STATUS_TOO_MANY_KINGS, "a side has more than one king"),
    (chess.STATUS_TOO_MANY_WHITE_PAWNS, "White has more than eight pawns"),
    (chess.STATUS_TOO_MANY_BLACK_PAWNS, "Black has more than eight pawns"),
    (chess.STATUS_PAWNS_ON_BACKRANK, "a pawn is on the first or last rank"),
    (chess.STATUS_TOO_MANY_WHITE_PIECES, "White has more than sixteen pieces"),
    (chess.STATUS_TOO_MANY_BLACK_PIECES, "Black has more than sixteen pieces"),
    (chess.STATUS_BAD_CASTLING_RIGHTS, "the castling rights do not match the board"),
    (chess.STATUS_INVALID_EP_SQUARE, "the en-passant square is impossible"),
    (chess.STATUS_OPPOSITE_CHECK, "the side not to move is in check"),
    (chess.STATUS_TOO_MANY_CHECKERS, "the side to move is checked by too many pieces"),
    (chess.STATUS_IMPOSSIBLE_CHECK, "the check given could not have arisen"),
    (chess.STATUS_RACE_CHECK, "a racing-kings rule is broken"),
    (chess.STATUS_RACE_OVER, "a racing-kings rule is broken"),
    (chess.STATUS_RACE_MATERIAL, "a racing-kings rule is broken"),
)


class IllegalPosition(ValueError):
    """A FEN that parses but describes a position that cannot occur."""


def reasons(board: chess.Board) -> list[str]:
    status = board.status()
    seen: list[str] = []
    for flag, text in _REASONS:
        if status & flag and text not in seen:
            seen.append(text)
    return seen


def legal_board(fen: str) -> chess.Board:
    """`chess.Board(fen)`, raising `IllegalPosition` — with the reasons — when the
    position is well-formed but illegal. A malformed FEN still raises python-chess's
    own `ValueError`. Use this wherever a position from outside will reach an engine."""
    board = chess.Board(fen)
    require_legal(board, fen)
    return board


def require_legal(board: chess.Board, where: str = "") -> None:
    if not board.is_valid():
        what = "; ".join(reasons(board)) or f"status {board.status()!r}"
        raise IllegalPosition(f"Illegal position{f' ({where})' if where else ''}: {what}.")
