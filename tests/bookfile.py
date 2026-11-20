"""Shared by the book tests: a tiny Polyglot book written from moves, and a BookSpec for it."""
import hashlib
import struct

import chess
import chess.polyglot

from zugzwang.core import books


def _encode(board: chess.Board, move: chess.Move) -> int:
    return (chess.square_file(move.to_square) | chess.square_rank(move.to_square) << 3
            | chess.square_file(move.from_square) << 6 | chess.square_rank(move.from_square) << 9
            | ((move.promotion - 1) << 12 if move.promotion else 0))


def write_book(path, pairs, weight=10):
    """A Polyglot file holding (board, move) pairs; castling moves are skipped (their Polyglot
    encoding differs and no test needs them)."""
    entries = sorted({(chess.polyglot.zobrist_hash(b), _encode(b, m))
                      for b, m in pairs if not b.is_castling(m)})
    path.write_bytes(b"".join(struct.pack(">QHHI", k, mv, weight, 0) for k, mv in entries))
    return path


def spec_for(path, book_id="test", default=True, label="Test"):
    data = path.read_bytes()
    return books.BookSpec(book_id, label, 1, path.name, len(data),
                          hashlib.sha256(data).hexdigest(), default=default)


def real_book_path():
    """A real opening book for the tests that need one (BOOK-DL): `$ZUGZWANG_TEST_BOOK`, else
    the book the dev run has in use (`~/.zugzwang/books/active.json`, read only; the suite's
    own data directory is a temp one). None when neither exists: then the three tests that
    report the missing asset fail and the four that need it skip, as before (W20)."""
    import json
    import os
    from pathlib import Path
    env = os.environ.get("ZUGZWANG_TEST_BOOK")
    if env:
        return Path(env) if Path(env).exists() else None
    d = Path.home() / ".zugzwang" / "books"
    try:
        st = json.loads((d / "active.json").read_text())
        b = books.spec(st["id"])
    except (OSError, ValueError, KeyError, books.BookError):
        return None
    p = d / b.file
    return p if p.exists() and p.stat().st_size == b.bytes else None
