"""
Pure helpers for the Opening Trainer. No Qt imports.

All functions accept a reader that may be None (graceful no-op when book is absent).
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field

import chess
import chess.pgn
import chess.polyglot

import zugzwang.config as C


@dataclass
class TrainingConfig:
    eco: str
    name: str
    color: str              # 'white' | 'black'
    mode: str               # 'varied' | 'pinned'
    starting_fen: str       # board FEN at the ECO endpoint
    allow_off_book: bool = False
    threshold_fraction: float = C.TRAINER_WEIGHT_THRESHOLD
    start_from_move1: bool = False
    starting_pgn: str = ""  # PGN move text leading to the ECO endpoint; used when start_from_move1=True


def parse_pgn_moves(pgn_text: str) -> list[chess.Move]:
    """Parse a PGN string into the sequence of chess.Move objects from the initial position."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return []
        return list(game.mainline_moves())
    except Exception:
        return []


def accepted_book_moves(
    reader: chess.polyglot.MemoryMappedReader | None,
    board: chess.Board,
    threshold_fraction: float = C.TRAINER_WEIGHT_THRESHOLD,
) -> list[chess.Move]:
    """Moves in the Polyglot book above the weight threshold, sorted desc by weight.

    Uses the Zobrist hash of `board` internally, so transpositions are accepted
    automatically — no move-sequence tracking required.
    """
    if reader is None:
        return []
    try:
        entries = sorted(reader.find_all(board), key=lambda e: e.weight, reverse=True)
    except Exception:
        return []
    if not entries:
        return []
    threshold = max(1, int(entries[0].weight * threshold_fraction))
    return [e.move for e in entries if e.weight >= threshold]


def weighted_random_reply(
    reader: chess.polyglot.MemoryMappedReader | None,
    board: chess.Board,
) -> chess.Move | None:
    """Weighted-random book reply for varied mode."""
    if reader is None:
        return None
    try:
        entries = list(reader.find_all(board))
    except Exception:
        return None
    if not entries:
        return None
    total = sum(e.weight for e in entries)
    if total == 0:
        return random.choice(entries).move
    r = random.randint(0, total - 1)
    cumulative = 0
    for e in entries:
        cumulative += e.weight
        if r < cumulative:
            return e.move
    return entries[-1].move


def uniform_random_reply(
    reader: chess.polyglot.MemoryMappedReader | None,
    board: chess.Board,
) -> chess.Move | None:
    """Uniform-random book reply: every book move is equally likely regardless of weight.

    Same candidate pool as weighted_random_reply (find_all with no weight filter),
    but probability is flat so rare/offbeat lines appear as often as mainlines.
    """
    if reader is None:
        return None
    try:
        entries = list(reader.find_all(board))
    except Exception:
        return None
    if not entries:
        return None
    return random.choice(entries).move


def top_book_reply(
    reader: chess.polyglot.MemoryMappedReader | None,
    board: chess.Board,
) -> chess.Move | None:
    """Highest-weight book reply for pinned mode."""
    if reader is None:
        return None
    try:
        entries = sorted(reader.find_all(board), key=lambda e: e.weight, reverse=True)
        return entries[0].move if entries else None
    except Exception:
        return None


def has_coverage(
    reader: chess.polyglot.MemoryMappedReader | None,
    board: chess.Board,
    training_color: chess.Color,
) -> bool:
    """True if the trainer can run for this color from this board position.

    If it's the player's turn: check for accepted book moves directly.
    If it's the opponent's turn: play the top opponent reply, then check.
    """
    if reader is None:
        return False
    if board.turn == training_color:
        return bool(accepted_book_moves(reader, board))
    else:
        opp_move = top_book_reply(reader, board)
        if opp_move is None:
            return False
        try:
            b2 = board.copy()
            b2.push(opp_move)
            return bool(accepted_book_moves(reader, b2))
        except Exception:
            return False
