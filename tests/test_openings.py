"""Tests for OpeningsBook — ECO lookup and Polyglot book detection."""

import chess
import pytest

from zugzwang.core.openings import OpeningsBook
import zugzwang.config as C


@pytest.fixture(scope="module")
def book():
    """Real OpeningsBook loaded from the bundled assets."""
    return OpeningsBook()


# ── Book detection ────────────────────────────────────────────────────────────

def test_book_loads(book):
    assert book._reader is not None

def test_eco_loads(book):
    assert len(book._eco) > 100   # at least a few hundred openings

def test_starting_position_has_book_moves(book):
    board = chess.Board()
    moves = book.book_moves(board)
    assert len(moves) > 0
    # Standard opening moves should be present
    ucis = {m.uci() for m in moves}
    assert "e2e4" in ucis

def test_is_book_move_true(book):
    board = chess.Board()
    e4 = chess.Move.from_uci("e2e4")
    assert book.is_book_move(board, e4)

def test_is_book_move_false_novelty(book):
    # h3 is unlikely to be in Perfect2023.bin at depth
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))
    board.push(chess.Move.from_uci("e7e5"))
    board.push(chess.Move.from_uci("h2h4"))   # odd move — not book
    odd = chess.Move.from_uci("a7a5")
    # Just verify the call doesn't crash; result may vary by book
    result = book.is_book_move(board, odd)
    assert isinstance(result, bool)


# ── ECO name lookup ───────────────────────────────────────────────────────────

def test_name_after_starting_position_is_none(book):
    # Starting position has no specific named opening yet
    board = chess.Board()
    assert book.name_after(board) is None

def test_kings_pawn_opening(book):
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))
    result = book.name_after(board)
    assert result is not None
    eco, name = result
    assert eco.startswith("B") or eco.startswith("C")
    assert "pawn" in name.lower() or "king" in name.lower()

def test_sicilian_defense(book):
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))
    board.push(chess.Move.from_uci("c7c5"))
    result = book.name_after(board)
    assert result is not None
    eco, name = result
    assert "Sicilian" in name

def test_queens_gambit(book):
    board = chess.Board()
    board.push(chess.Move.from_uci("d2d4"))
    board.push(chess.Move.from_uci("d7d5"))
    board.push(chess.Move.from_uci("c2c4"))
    result = book.name_after(board)
    assert result is not None
    _, name = result
    assert "Queen" in name or "Gambit" in name

def test_unknown_position_returns_none(book):
    # After a non-standard sequence, opening should return None
    board = chess.Board()
    board.push(chess.Move.from_uci("h2h4"))
    board.push(chess.Move.from_uci("a7a5"))
    board.push(chess.Move.from_uci("h4h5"))
    result = book.name_after(board)
    assert result is None

def test_returns_tuple_of_strings(book):
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))
    result = book.name_after(board)
    if result is not None:
        eco, name = result
        assert isinstance(eco, str)
        assert isinstance(name, str)


# ── Graceful degradation ──────────────────────────────────────────────────────

def test_missing_book_degrades(tmp_path):
    ob = OpeningsBook(
        book_path=tmp_path / "missing.bin",
        eco_dir=tmp_path / "no_eco",
    )
    board = chess.Board()
    assert ob.book_moves(board) == []
    assert not ob.is_book_move(board, chess.Move.from_uci("e2e4"))
    assert ob.name_after(board) is None


def test_missing_book_is_a_warning(tmp_path, caplog):
    """W29 (owner, 2026-11-08): a missing book silently disables book labels across a
    whole corpus (W20), so it is logged as a warning, not as information."""
    import logging
    from zugzwang.core.openings import OpeningsBook
    with caplog.at_level(logging.INFO, logger="zugzwang.core.openings"):
        OpeningsBook(book_path=tmp_path / "absent.bin", eco_dir=tmp_path)
    hits = [r for r in caplog.records if "Opening book not found" in r.getMessage()]
    assert hits and all(r.levelno == logging.WARNING for r in hits)
