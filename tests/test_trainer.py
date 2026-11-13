"""Opening-trainer pure-function tests (Phase 2, priority 3 — R3).

trainer.py talks to a Polyglot reader only through .find_all(board) -> entries
with .move and .weight, so a small stub reader exercises every branch without
the 88 MB book. R3 (weighted_random_reply distribution) is verified statistically
with a seeded RNG so the assertion is reproducible.
"""

import random

import chess
import pytest

from zugzwang.core import trainer
from zugzwang.core.trainer import (
    accepted_book_moves,
    weighted_random_reply,
    uniform_random_reply,
    top_book_reply,
    has_coverage,
)


class FakeEntry:
    def __init__(self, uci: str, weight: int):
        self.move = chess.Move.from_uci(uci)
        self.weight = weight


class FakeReader:
    """Returns a fixed entry list from find_all, ignoring the board."""

    def __init__(self, entries):
        self._entries = entries

    def find_all(self, board):
        return list(self._entries)


class RaisingReader:
    def find_all(self, board):
        raise RuntimeError("corrupt book")


WHITE_ENTRIES = [
    FakeEntry("e2e4", 100),
    FakeEntry("d2d4", 30),
    FakeEntry("g1f3", 5),
]


# ── accepted_book_moves: threshold = max(1, int(top_weight * fraction)) ───────

def test_accepted_strict_fraction_keeps_only_heavy_moves():
    reader = FakeReader(WHITE_ENTRIES)
    # frac 0.30 -> threshold 30 -> weights >= 30 -> e2e4, d2d4 (5 excluded).
    moves = accepted_book_moves(reader, chess.Board(), threshold_fraction=0.30)
    assert [m.uci() for m in moves] == ["e2e4", "d2d4"]


def test_accepted_normal_fraction():
    reader = FakeReader(WHITE_ENTRIES)
    # frac 0.10 -> threshold 10 -> e2e4, d2d4 (5 < 10 excluded).
    moves = accepted_book_moves(reader, chess.Board(), threshold_fraction=0.10)
    assert [m.uci() for m in moves] == ["e2e4", "d2d4"]


def test_accepted_loose_fraction_keeps_all():
    reader = FakeReader(WHITE_ENTRIES)
    # frac 0.02 -> threshold max(1, int(2)) = 2 -> all three kept.
    moves = accepted_book_moves(reader, chess.Board(), threshold_fraction=0.02)
    assert [m.uci() for m in moves] == ["e2e4", "d2d4", "g1f3"]


def test_accepted_threshold_floor_is_one():
    # Tiny top weight: int(3 * 0.02) == 0, but threshold floors at 1, so a
    # weight-0 padding move would still be excluded while weight>=1 is kept.
    reader = FakeReader([FakeEntry("e2e4", 3), FakeEntry("d2d4", 0)])
    moves = accepted_book_moves(reader, chess.Board(), threshold_fraction=0.02)
    assert [m.uci() for m in moves] == ["e2e4"]


def test_accepted_sorted_descending_by_weight():
    reader = FakeReader([FakeEntry("g1f3", 5), FakeEntry("e2e4", 100), FakeEntry("d2d4", 30)])
    moves = accepted_book_moves(reader, chess.Board(), threshold_fraction=0.02)
    assert [m.uci() for m in moves] == ["e2e4", "d2d4", "g1f3"]


def test_accepted_none_reader_returns_empty():
    assert accepted_book_moves(None, chess.Board()) == []


def test_accepted_empty_book_returns_empty():
    assert accepted_book_moves(FakeReader([]), chess.Board()) == []


def test_accepted_swallows_reader_errors():
    assert accepted_book_moves(RaisingReader(), chess.Board()) == []


# ── top_book_reply / uniform_random_reply ────────────────────────────────────

def test_top_book_reply_returns_heaviest():
    reader = FakeReader([FakeEntry("g1f3", 5), FakeEntry("e2e4", 100)])
    assert top_book_reply(reader, chess.Board()).uci() == "e2e4"


def test_top_book_reply_none_when_empty():
    assert top_book_reply(FakeReader([]), chess.Board()) is None


def test_top_book_reply_none_reader():
    assert top_book_reply(None, chess.Board()) is None


def test_uniform_reply_always_a_candidate():
    reader = FakeReader(WHITE_ENTRIES)
    seen = {uniform_random_reply(reader, chess.Board()).uci() for _ in range(200)}
    assert seen <= {"e2e4", "d2d4", "g1f3"}
    assert len(seen) > 1  # actually varies


def test_uniform_reply_none_reader():
    assert uniform_random_reply(None, chess.Board()) is None


# ── weighted_random_reply (R3) ───────────────────────────────────────────────

def test_weighted_reply_single_entry():
    reader = FakeReader([FakeEntry("e2e4", 100)])
    assert weighted_random_reply(reader, chess.Board()).uci() == "e2e4"


def test_weighted_reply_all_zero_weights_falls_back_to_choice():
    reader = FakeReader([FakeEntry("e2e4", 0), FakeEntry("d2d4", 0)])
    move = weighted_random_reply(reader, chess.Board())
    assert move.uci() in ("e2e4", "d2d4")


def test_weighted_reply_none_reader():
    assert weighted_random_reply(None, chess.Board()) is None


def test_weighted_reply_empty_book():
    assert weighted_random_reply(FakeReader([]), chess.Board()) is None


def test_weighted_reply_swallows_reader_errors():
    assert weighted_random_reply(RaisingReader(), chess.Board()) is None


def test_weighted_reply_distribution_matches_weights():
    """Empirical selection frequency must track the Polyglot weights.

    Weights 70/20/10 -> expected 0.70/0.20/0.10. Seeded for reproducibility;
    N=20000 keeps the seeded sample comfortably within +/-0.02 absolute.
    """
    reader = FakeReader([
        FakeEntry("e2e4", 70),
        FakeEntry("d2d4", 20),
        FakeEntry("g1f3", 10),
    ])
    random.seed(20260616)
    n = 20000
    counts = {"e2e4": 0, "d2d4": 0, "g1f3": 0}
    board = chess.Board()
    for _ in range(n):
        counts[weighted_random_reply(reader, board).uci()] += 1

    assert counts["e2e4"] / n == pytest.approx(0.70, abs=0.02)
    assert counts["d2d4"] / n == pytest.approx(0.20, abs=0.02)
    assert counts["g1f3"] / n == pytest.approx(0.10, abs=0.02)


# ── has_coverage: player-turn vs opponent-turn branches ──────────────────────

def test_has_coverage_player_turn_true():
    reader = FakeReader(WHITE_ENTRIES)
    assert has_coverage(reader, chess.Board(), chess.WHITE) is True


def test_has_coverage_none_reader_false():
    assert has_coverage(None, chess.Board(), chess.WHITE) is False


def test_has_coverage_opponent_turn_plays_reply_then_checks():
    # Board after 1.e4: Black to move; we train as White, so the opponent (Black)
    # must have a book reply that leads to a position with White book moves.
    board = chess.Board()
    board.push_uci("e2e4")
    reader = FakeReader([FakeEntry("e7e5", 50), FakeEntry("c7c5", 40)])
    assert has_coverage(reader, board, chess.WHITE) is True


def test_has_coverage_opponent_no_reply_false():
    board = chess.Board()
    board.push_uci("e2e4")
    assert has_coverage(FakeReader([]), board, chess.WHITE) is False
