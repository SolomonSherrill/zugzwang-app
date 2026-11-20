"""BOOK-DL (owner ruling D, 2026-11-19): the manifest, the verified download (a corrupt and a
partial file included), the book in use, and the no-book state. Constructed data only."""
import io
import json
import types

import chess
import pytest

import sidecar.main as sidecar
from tests.bookfile import spec_for, write_book
from zugzwang.core import books
from zugzwang.core.database import Database
from zugzwang.core.openings import OpeningsBook


def _start_book(tmp_path, name="src.bin"):
    b = chess.Board()
    pairs = [(b.copy(), chess.Move.from_uci(u)) for u in ("e2e4", "d2d4", "c2c4")]
    return write_book(tmp_path / name, pairs)


class _Resp(io.BytesIO):
    """A response that serves *data*, optionally raising after *fail_after* bytes."""
    def __init__(self, data, fail_after=None):
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, n=-1):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise ConnectionResetError("connection reset by peer")
        return super().read(n if self.fail_after is None else min(n, self.fail_after))


def _opener(data, **kw):
    return lambda url, timeout: _Resp(data, **kw)


# ── the manifest ─────────────────────────────────────────────────────────────

def test_manifest_is_the_three_hosted_books_default_first():
    assert [b.id for b in books.MANIFEST] == ["all-20", "all-6", "all-3"]
    assert [b.min_games for b in books.MANIFEST] == [20, 6, 3]
    assert books.DEFAULT_ID == "all-20" and sum(b.default for b in books.MANIFEST) == 1
    for b in books.MANIFEST:
        assert b.url == ("https://github.com/SolomonSherrill/zugzwang-app/releases/download/"
                         f"books-v1/{b.file}")
        assert len(b.sha256) == 64 and b.bytes % 16 == 0      # whole Polyglot entries
    # never the update feed's release
    assert all("/latest/" not in b.url for b in books.MANIFEST)


# ── the verified download ────────────────────────────────────────────────────

def test_download_verifies_and_installs(tmp_path):
    src = _start_book(tmp_path)
    b = spec_for(src)
    seen = []
    got = books.download(b, opener=_opener(src.read_bytes()), progress=lambda d, t: seen.append(d))
    assert got == books.book_path(b) and got.read_bytes() == src.read_bytes()
    assert seen[-1] == b.bytes
    assert not got.with_name(got.name + ".part").exists()
    assert books.installed(b)
    assert books.active_state() is None          # downloading is not switching


def test_corrupt_download_is_refused_and_leaves_nothing(tmp_path):
    src = _start_book(tmp_path)
    b = spec_for(src)
    bad = bytearray(src.read_bytes())
    bad[5] ^= 0xFF                                # same size, one byte wrong
    with pytest.raises(books.DownloadFailed, match="sha256"):
        books.download(b, opener=_opener(bytes(bad)))
    assert list(books.books_dir().iterdir()) == []


def test_partial_download_is_refused_and_leaves_nothing(tmp_path):
    src = _start_book(tmp_path)
    b = spec_for(src)
    with pytest.raises(books.DownloadFailed, match="incomplete"):
        books.download(b, opener=_opener(src.read_bytes()[:-16]))
    assert list(books.books_dir().iterdir()) == []


def test_dropped_connection_is_refused_and_leaves_nothing(tmp_path):
    src = _start_book(tmp_path)
    b = spec_for(src)
    with pytest.raises(books.DownloadFailed, match="reset"):
        books.download(b, opener=_opener(src.read_bytes(), fail_after=16))
    assert list(books.books_dir().iterdir()) == []


def test_oversized_download_is_refused(tmp_path):
    src = _start_book(tmp_path)
    b = spec_for(src)
    with pytest.raises(books.DownloadFailed, match="more than"):
        books.download(b, opener=_opener(src.read_bytes() + b"x" * 16))
    assert list(books.books_dir().iterdir()) == []


def test_a_failed_download_leaves_the_book_in_use(tmp_path, monkeypatch):
    a_src = _start_book(tmp_path, "a.bin")
    b_src = write_book(tmp_path / "b.bin", [(chess.Board(), chess.Move.from_uci("g1f3"))])
    a, b = spec_for(a_src, "a"), spec_for(b_src, "b", default=False)
    monkeypatch.setattr(books, "MANIFEST", (a, b))
    books.download(a, opener=_opener(a_src.read_bytes()))
    books.set_active("a", relabelled=True)
    before = (books.book_path(a).read_bytes(), (books.books_dir() / "active.json").read_text())
    with pytest.raises(books.DownloadFailed):
        books.download(b, opener=_opener(b_src.read_bytes()[:8]))
    with pytest.raises(books.Cancelled):
        books.download(b, opener=_opener(b_src.read_bytes()), cancelled=lambda: True)
    assert (books.book_path(a).read_bytes(),
            (books.books_dir() / "active.json").read_text()) == before
    assert books.active_spec() == a and not books.installed(b)
    ob = OpeningsBook(eco_dir=tmp_path)
    assert ob.is_book_move(chess.Board(), chess.Move.from_uci("e2e4"))
    ob.close()


# ── the book in use ──────────────────────────────────────────────────────────

def test_active_book_is_read_at_call_time(tmp_path, monkeypatch):
    src = _start_book(tmp_path)
    b = spec_for(src)
    monkeypatch.setattr(books, "MANIFEST", (b,))
    assert OpeningsBook(eco_dir=tmp_path).has_book is False
    books.download(b, opener=_opener(src.read_bytes()))
    books.set_active(b.id, relabelled=True)
    ob = OpeningsBook(eco_dir=tmp_path)
    assert ob.has_book and ob.is_book_move(chess.Board(), chess.Move.from_uci("d2d4"))
    assert not ob.is_book_move(chess.Board(), chess.Move.from_uci("g1f3"))
    ob.close()
    assert books.active_stamp() == {"file": b.file, "sha256": b.sha256}


def test_a_truncated_book_file_reads_as_no_book(tmp_path, monkeypatch):
    src = _start_book(tmp_path)
    b = spec_for(src)
    monkeypatch.setattr(books, "MANIFEST", (b,))
    books.download(b, opener=_opener(src.read_bytes()))
    books.set_active(b.id, relabelled=True)
    books.book_path(b).write_bytes(src.read_bytes()[:16])
    assert books.active_state() is None and OpeningsBook(eco_dir=tmp_path).has_book is False


def test_provenance_names_the_book_in_use_without_hashing_it(tmp_path, monkeypatch):
    from zugzwang.core import provenance
    src = _start_book(tmp_path)
    b = spec_for(src)
    monkeypatch.setattr(books, "MANIFEST", (b,))
    books.download(b, opener=_opener(src.read_bytes()))
    books.set_active(b.id, relabelled=True)
    monkeypatch.setattr(provenance, "file_sha256", lambda p: pytest.fail("hashed per run"))
    assert provenance.book_state(True) == {"file": b.file, "sha256": b.sha256}
    assert provenance.book_state(False) is None


# ── the no-book state ────────────────────────────────────────────────────────

@pytest.fixture
def server():
    return object.__new__(sidecar.Server)


@pytest.fixture
def sent(monkeypatch):
    frames = []
    monkeypatch.setattr(sidecar, "_send", lambda obj: frames.append(obj))
    return frames


def test_no_book_state(server, sent, tmp_path):
    server._books = sidecar.BookRunner(lambda fn: fn())
    server._openings = OpeningsBook()
    server._db = Database(tmp_path / "t.db")
    server._coverage = types.SimpleNamespace(running=lambda: False)
    server._handle_request({"id": 1, "method": "books_status"})
    st = sent[-1]["result"]
    assert st["active"] is None and st["defaultId"] == "all-20" and st["job"] is None
    assert [(b["id"], b["installed"], b["active"]) for b in st["books"]] == [
        ("all-20", False, False), ("all-6", False, False), ("all-3", False, False)]
    assert [b["bytes"] for b in st["books"]] == [151_320_480, 572_067_472, 1_323_905_200]
    server._handle_request({"id": 2, "method": "trainer_lobby"})
    lobby = sent[-1]["result"]
    assert lobby["bookAvailable"] is False and lobby["bookId"] is None
    assert lobby["bookPath"] == str(books.books_dir())
    server._handle_request({"id": 3, "method": "trainer_index_coverage"})
    assert "No opening book installed" in sent[-1]["error"]["message"]
    server._db.close()


def test_book_use_refuses_while_games_are_analysed(server, sent):
    server._sync = types.SimpleNamespace(running=lambda: False)
    server._analysis = types.SimpleNamespace(games_pending=1)
    server._relabel = types.SimpleNamespace(state="idle")
    server._handle_request({"id": 1, "method": "book_use", "params": {"id": "all-20"}})
    assert "being analysed" in sent[-1]["error"]["message"]


def test_analysis_refuses_during_a_book_relabel(server, sent):
    server._books = types.SimpleNamespace(relabelling=lambda: True)
    server._sync = types.SimpleNamespace(running=lambda: False)
    server._handle_request({"id": 1, "method": "analyze_game", "params": {"game_id": 1}})
    assert "being switched" in sent[-1]["error"]["message"]
    server._handle_request({"id": 2, "method": "analyze_pending", "params": {}})
    assert "being switched" in sent[-1]["error"]["message"]
