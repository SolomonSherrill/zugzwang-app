"""Opening ECO loading, transposition, and family-grouping tests
(Phase 2, priority 3).

_load_eco / _board_epd / family_key are tested in isolation with synthetic TSVs;
transposition + book-move detection are verified against the real bundled assets
(loaded once per module).
"""

from pathlib import Path

import chess
import pytest

import zugzwang.config as C
from zugzwang.core.openings import (
    OpeningsBook,
    _load_eco,
    _board_epd,
    family_key,
)

ALIASES = C.TRAINER_FAMILY_ALIASES


# ── _load_eco: last-row-wins per position ────────────────────────────────────

def _write_tsv(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = ["eco\tname\tpgn"]
    lines += ["\t".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_eco_last_row_wins_for_same_position(tmp_path):
    # Two rows reach the identical position (1. e4) but carry different names.
    _write_tsv(tmp_path / "a.tsv", [
        ("A00", "First Name", "1. e4"),
        ("B00", "Second Name", "1. e4"),
    ])
    eco_map, entries = _load_eco(tmp_path)
    board = chess.Board()
    board.push_uci("e2e4")
    assert eco_map[_board_epd(board)] == ("B00", "Second Name")
    # Both distinct (eco, name) pairs survive as entries.
    assert len(entries) == 2


def test_load_eco_skips_incomplete_rows(tmp_path):
    _write_tsv(tmp_path / "a.tsv", [
        ("A00", "", "1. e4"),          # missing name
        ("", "Nameless", "1. d4"),     # missing eco
        ("C00", "Good", "1. c4"),
    ])
    eco_map, entries = _load_eco(tmp_path)
    assert len(entries) == 1
    assert entries[0][:2] == ("C00", "Good")


def test_load_eco_empty_dir(tmp_path):
    eco_map, entries = _load_eco(tmp_path)
    assert eco_map == {}
    assert entries == []


# ── _board_epd: transposition identity ───────────────────────────────────────

def test_board_epd_equal_for_transposition():
    a = chess.Board()
    for uci in ("e2e4", "e7e5", "g1f3", "b8c6"):
        a.push_uci(uci)
    b = chess.Board()
    for uci in ("g1f3", "b8c6", "e2e4", "e7e5"):
        b.push_uci(uci)
    assert _board_epd(a) == _board_epd(b)


def test_board_epd_differs_for_different_positions():
    a = chess.Board()
    a.push_uci("e2e4")
    b = chess.Board()
    b.push_uci("d2d4")
    assert _board_epd(a) != _board_epd(b)


def test_board_epd_ignores_move_counters():
    # epd() drops halfmove/fullmove counters, so same position via different
    # path lengths still matches (here the same position, fresh vs replayed).
    a = chess.Board()
    a.push_uci("g1f3")
    a.push_uci("g8f6")
    a.push_uci("f3g1")
    a.push_uci("f6g8")  # back to start position, counters advanced
    assert _board_epd(a) == _board_epd(chess.Board())


# ── family_key ───────────────────────────────────────────────────────────────

def test_family_key_alias_wins():
    assert family_key("Queen's Pawn Game: London System", ALIASES) == "London System"


def test_family_key_prefix_before_colon():
    assert family_key("Sicilian Defense: Najdorf Variation", ALIASES) == "Sicilian Defense"


def test_family_key_prefix_before_comma():
    assert family_key("Sicilian Defense, Najdorf", ALIASES) == "Sicilian Defense"


def test_family_key_earliest_separator_wins():
    # A comma before a colon -> cut at the comma.
    assert family_key("French Defense, Advance: Main Line", ALIASES) == "French Defense"


def test_family_key_no_separator_returns_whole_name():
    assert family_key("Bongcloud Attack", ALIASES) == "Bongcloud Attack"


# ── graceful degradation when assets absent ──────────────────────────────────

def test_openings_book_missing_assets_degrades(tmp_path):
    book = OpeningsBook(book_path=tmp_path / "nope.bin", eco_dir=tmp_path / "noeco")
    assert book.reader is None
    assert book.book_moves(chess.Board()) == []
    assert book.is_book_move(chess.Board(), chess.Move.from_uci("e2e4")) is False
    assert book.name_after(chess.Board()) is None


# ── real-asset transposition + book detection ────────────────────────────────

@pytest.fixture(scope="module")
def real_book():
    from tests.bookfile import real_book_path
    path = real_book_path()
    if path is None or not C.OPENINGS_ECO_DIR.exists():
        pytest.skip("no opening book installed (BOOK-DL) or no ECO data")
    book = OpeningsBook(book_path=path)
    yield book
    book.close()


def test_real_book_detects_opening_move(real_book):
    assert real_book.is_book_move(chess.Board(), chess.Move.from_uci("e2e4")) is True


def test_real_book_name_after_is_stable_across_transposition(real_book):
    a = chess.Board()
    for uci in ("e2e4", "e7e5", "g1f3", "b8c6"):
        a.push_uci(uci)
    b = chess.Board()
    for uci in ("g1f3", "b8c6", "e2e4", "e7e5"):
        b.push_uci(uci)
    # Same position via different move orders -> identical name lookup.
    assert real_book.name_after(a) == real_book.name_after(b)


# ── UI-BUILD-3 B2: a family's shown moves are the moves every curated line shares ──

def test_shared_prefix_of_lines():
    from zugzwang.core.openings import _shared_prefix
    assert _shared_prefix([]) == []
    assert _shared_prefix([["e2e4", "c7c5", "g1f3"], ["e2e4", "c7c5", "b1c3"]]) == ["e2e4", "c7c5"]
    assert _shared_prefix([["e2e4", "e7e5"]]) == ["e2e4", "e7e5"]
    assert _shared_prefix([["e2e4"], ["d2d4"]]) == []
    # one line of ten by another move order: cut at 1.0, not at 0.9
    lines = [["e2e4", "e7e5", "f1c4"]] * 9 + [["e2e4", "e7e5", "d2d4"]]
    assert _shared_prefix(lines, 1.0) == ["e2e4", "e7e5"]
    assert _shared_prefix(lines, 0.9) == ["e2e4", "e7e5", "f1c4"]
    assert _shared_prefix(lines[:8] + [["e2e4", "e7e5", "d2d4"]] * 2, 0.9) == ["e2e4", "e7e5"]


def test_shared_moves_from_synthetic_family(tmp_path):
    from zugzwang.core.openings import build_family_index
    _write_tsv(tmp_path / "c.tsv", [
        ("C50", "Italian Game", "1. e4 e5 2. Nf3 Nc6 3. Bc4"),
        ("C50", "Italian Game: Anti-Fried Liver Defense", "1. e4 e5 2. Nf3 Nc6 3. Bc4 h6"),
        ("C53", "Italian Game: Classical Variation", "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3"),
    ])
    fams = build_family_index(None, tmp_path, aliases={}, depth_min=1, depth_max=20)
    italian = next(f for f in fams if f.name == "Italian Game")
    # the prefix-dedup keeps the longer lines; both start 1. e4 e5 2. Nf3 Nc6 3. Bc4
    assert italian.shared_moves == "1. e4 e5 2. Nf3 Nc6 3. Bc4"


def _family(book, name):
    return next(f for f in book.family_index() if f.name == name)


def test_real_book_italian_shows_its_shared_moves(real_book):
    # 76 of its 81 curated lines play 3. Bc4; the rest reach it by 3. d4 exd4 4. Bc4
    fam = _family(real_book, "Italian Game")
    assert fam.shared_moves == "1. e4 e5 2. Nf3 Nc6 3. Bc4"
    assert fam.sample_moves.startswith(fam.shared_moves)     # kept for search


def test_real_book_sicilian_shows_its_shared_moves(real_book):
    assert _family(real_book, "Sicilian Defense").shared_moves == "1. e4 c5"
