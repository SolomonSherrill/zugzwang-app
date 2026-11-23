"""Puzzles from Lichess (FIX-B6 B, ruling PZ1): the streamed import of the .zst, the swap that keeps
the previous set on a cancel or a failure, an update that keeps the rating, attempts and sessions,
columns by header name, the disk check, and the download through a stand-in for the network."""

from __future__ import annotations

import io
import os
import sqlite3
from pathlib import Path

import pytest

import zugzwang.config as C
from zugzwang.core import puzzle_core as P
from zugzwang.core.database import Database

FIXTURE = Path(__file__).parent / "fixtures" / "puzzles_small.csv.zst"
KEPT = {"zA001", "zA002", "zA003", "zA006"}   # zA004 NbPlays 10, zA005 Popularity -5
HEADER = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags"
FEN = "6k1/5ppp/8/8/7p/8/8/R3R2K b - - 0 1"


def _zst(text: str) -> bytes:
    if P.zstd_backend() == "compression.zstd":
        from compression import zstd
        return zstd.compress(text.encode())
    import zstandard
    return zstandard.ZstdCompressor().compress(text.encode())


def _csv(ids, rating=1500, header=HEADER):
    rows = [f"{i},{FEN},h4h3 a1a8,{rating},80,90,100,mate fork,," for i in ids]
    return header + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "puz.db"
    d = Database(p)
    d.get_puzzle_rating()
    d._conn.close()
    return p


def _q(db_path, sql, *args):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _ids(db_path):
    return {r[0] for r in _q(db_path, "SELECT id FROM puzzles")}


def _meta(db_path):
    return dict(_q(db_path, "SELECT key, value FROM meta WHERE key LIKE 'puzzles%'"))


def _stream(db_path, data: bytes, compressed=True, cancelled=lambda: False, source=None):
    return list(P.import_puzzle_stream(io.BytesIO(data), db_path, total_bytes=len(data),
                                       compressed=compressed, is_cancelled=cancelled,
                                       source=source or {"kind": "lichess", "date": "d", "etag": "e"}))


def test_the_zst_fixture_imports_streamed_with_the_filters(db_path):
    events = list(P.import_puzzles_file(FIXTURE, db_path))
    assert events[-1][0] == "done" and events[-1][1]["count"] == 4
    assert _ids(db_path) == KEPT
    assert ("finishing", 4) in events
    # the theme index was rebuilt over the new set
    hits = _q(db_path, "SELECT p.id FROM puzzles p JOIN puzzle_themes_fts f ON p.rowid = f.rowid"
                       " WHERE puzzle_themes_fts MATCH '\"backRankMate\"'")
    assert hits == [("zA003",)]
    meta = _meta(db_path)
    assert meta["puzzles_imported"] == "1" and meta["puzzles_count"] == "4"
    assert meta["puzzles_source"] == "file"


def test_progress_counts_bytes_of_the_file(db_path, monkeypatch):
    monkeypatch.setattr(C, "PUZZLE_IMPORT_BATCH", 1)
    events = list(P.import_puzzles_file(FIXTURE, db_path))
    prog = [e for e in events if e[0] == "progress"]
    assert prog and all(e[2] == FIXTURE.stat().st_size for e in prog)
    assert prog[-1][1] == FIXTURE.stat().st_size and prog[-1][3] == 4


def test_nothing_but_the_database_is_written(tmp_path, db_path):
    before = set(os.listdir(tmp_path))
    list(P.import_puzzles_file(FIXTURE, db_path))
    assert set(os.listdir(tmp_path)) - before <= {"puz.db-wal", "puz.db-shm"}


def test_columns_are_found_by_header_name(db_path):
    header = "Themes,NbPlays,Popularity,Moves,FEN,PuzzleId,RatingDeviation,Rating,Extra"
    text = header + "\n" + f"fork pin,120,90,h4h3 a1a8,{FEN},zR1,70,1234,x\n"
    events = _stream(db_path, _zst(text))
    assert events[-1][0] == "done"
    row = _q(db_path, "SELECT id, fen, moves_uci, rating, rating_deviation, popularity, nb_plays,"
                      " themes, game_url FROM puzzles")
    assert row == [("zR1", FEN, "h4h3 a1a8", 1234, 70, 90, 120, "fork pin", None)]


def test_a_missing_column_is_refused_and_the_previous_set_kept(db_path):
    _stream(db_path, _zst(_csv(["old1", "old2"])))
    bad = _zst(_csv(["new1"], header=HEADER.replace("NbPlays", "Plays")))
    with pytest.raises(P.PuzzleFileError, match="NbPlays"):
        _stream(db_path, bad)
    assert _ids(db_path) == {"old1", "old2"}
    assert _q(db_path, "SELECT name FROM sqlite_master WHERE name = 'puzzles_new'") == []


def test_a_plain_csv_and_a_zst_are_told_apart_by_their_bytes(tmp_path, db_path):
    plain = tmp_path / "p.zst"          # the name lies; the bytes decide
    plain.write_text(_csv(["c1"]))
    assert list(P.import_puzzles_file(plain, db_path))[-1][1]["count"] == 1
    packed = tmp_path / "p.csv"
    packed.write_bytes(_zst(_csv(["z1", "z2"])))
    assert list(P.import_puzzles_file(packed, db_path))[-1][1]["count"] == 2
    assert _ids(db_path) == {"z1", "z2"}


def test_cancel_keeps_the_previous_set(db_path, monkeypatch):
    _stream(db_path, _zst(_csv(["old1", "old2"])))
    monkeypatch.setattr(C, "PUZZLE_IMPORT_BATCH", 1)
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 3

    events = _stream(db_path, _zst(_csv([f"n{i}" for i in range(20)])), cancelled=cancelled)
    assert events[-1] == ("cancelled",)
    assert _ids(db_path) == {"old1", "old2"}
    assert _meta(db_path)["puzzles_count"] == "2"
    assert _q(db_path, "SELECT name FROM sqlite_master WHERE name = 'puzzles_new'") == []


class _Broken(io.RawIOBase):
    """A download that stops part-way (the network drops)."""

    def __init__(self, data: bytes, stop_at: int) -> None:
        self._data, self._at, self._stop = data, 0, stop_at

    def readable(self):
        return True

    def read(self, n=-1):
        if self._at >= self._stop:
            raise OSError("connection reset")
        chunk = self._data[self._at:min(self._stop, self._at + max(1, n))]
        self._at += len(chunk)
        return chunk


def test_a_failed_download_keeps_the_previous_set(db_path, monkeypatch):
    _stream(db_path, _zst(_csv(["old1"])))
    monkeypatch.setattr(C, "PUZZLE_IMPORT_BATCH", 1)
    data = _zst(_csv([f"n{i}" for i in range(400)]))
    with pytest.raises(OSError):
        list(P.import_puzzle_stream(_Broken(data, len(data) // 2), db_path, total_bytes=len(data),
                                    compressed=True, source={"kind": "lichess"}))
    assert _ids(db_path) == {"old1"}
    assert _q(db_path, "SELECT name FROM sqlite_master WHERE name = 'puzzles_new'") == []


def test_an_update_keeps_rating_attempts_sessions_and_drops_removed_puzzles(db_path):
    _stream(db_path, _zst(_csv(["keep", "gone", "gone2"])))
    d = Database(db_path)
    d.save_puzzle_rating(1777.0, 90.0, 0.05)
    sid = d.save_puzzle_session(mode="rated", time_limit_s=None)
    for pid in ("keep", "gone"):
        d.save_puzzle_attempt(puzzle_id=pid, session_id=sid, mode="rated", solved=True, failed=False,
                              used_hint=False, gave_up=False, solve_time_s=3.0,
                              rating_before=1700.0, rating_after=1777.0)
    d._conn.close()
    attempts = _q(db_path, "SELECT * FROM puzzle_attempts ORDER BY id")
    sessions = _q(db_path, "SELECT * FROM puzzle_sessions ORDER BY id")

    events = _stream(db_path, _zst(_csv(["keep", "fresh"], rating=1600)))
    stats = events[-1][1]
    assert stats == {"count": 2, "previous": 3, "removed": 2, "removed_attempted": 1, "added": 1}
    assert _ids(db_path) == {"keep", "fresh"}
    assert _q(db_path, "SELECT rating FROM puzzles WHERE id = 'keep'") == [(1600,)]   # Lichess's new figure
    assert _q(db_path, "SELECT rating, rd, volatility FROM puzzle_rating") == [(1777.0, 90.0, 0.05)]
    assert _q(db_path, "SELECT * FROM puzzle_attempts ORDER BY id") == attempts
    assert _q(db_path, "SELECT * FROM puzzle_sessions ORDER BY id") == sessions
    # the rating index and the theme index exist over the new table
    assert _q(db_path, "SELECT name FROM sqlite_master WHERE name = 'idx_puzzles_rating'")
    assert len(_q(db_path, "SELECT rowid FROM puzzle_themes_fts WHERE puzzle_themes_fts MATCH 'fork'")) == 2
    d = Database(db_path)
    assert {p.id for p in d.select_puzzles(user_rating=1600, rating_range=50, exclude_recent=0)} == {"keep", "fresh"}


def test_an_empty_file_is_refused(db_path):
    with pytest.raises(P.PuzzleFileError):
        _stream(db_path, _zst(HEADER + "\n"))
    assert _ids(db_path) == set()


class _Resp(io.BytesIO):
    def __init__(self, data: bytes, headers: dict) -> None:
        super().__init__(data)
        self.headers = headers


def _opener(data: bytes, calls: list | None = None):
    headers = {"Content-Length": str(len(data)), "Last-Modified": "Sun, 01 Nov 2026 07:57:40 GMT",
               "ETag": '"6ae6f0f4-12766d85"'}

    def open_fn(url, timeout, method="GET"):
        if calls is not None:
            calls.append((url, method))
        return _Resp(b"" if method == "HEAD" else data, headers)
    return open_fn


def test_the_download_streams_into_the_database_with_the_files_date(db_path):
    data = FIXTURE.read_bytes()
    calls: list = []
    events = list(P.download_lichess_puzzles(db_path, open_fn=_opener(data, calls)))
    assert calls == [(C.PUZZLE_LICHESS_URL, "GET")]
    assert events[0] == ("progress", 0, len(data), 0)
    assert events[-1][0] == "done" and events[-1][1]["count"] == 4
    meta = _meta(db_path)
    assert meta["puzzles_source"] == "lichess"
    assert meta["puzzles_source_date"] == "2026-11-01T07:57:40+00:00"
    assert meta["puzzles_source_etag"] == "6ae6f0f4-12766d85"
    assert meta["puzzles_source_bytes"] == str(len(data))


def test_the_check_reads_the_headers_only():
    calls: list = []
    info = P.lichess_file_info(open_fn=_opener(b"x" * 10, calls))
    assert calls == [(C.PUZZLE_LICHESS_URL, "HEAD")]
    assert info == {"kind": "lichess", "date": "2026-11-01T07:57:40+00:00",
                    "etag": "6ae6f0f4-12766d85", "bytes": 10}


def test_too_little_disk_is_refused_before_anything_is_read(db_path, monkeypatch):
    import shutil
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**12, 10**12 - 10**6, 10**6))
    events = list(P.download_lichess_puzzles(db_path, open_fn=_opener(b"\0" * 300_000_000)))
    assert len(events) == 1 and events[0][0] == "error"
    assert "Not enough free disk space" in events[0][1] and "GB" in events[0][1]
    assert _ids(db_path) == set()


def test_the_disk_need_follows_the_measured_factors():
    assert P.disk_needed(100, True) == int(100 * C.PUZZLE_DISK_PER_ZST_BYTE)
    assert P.disk_needed(100, False) == int(100 * C.PUZZLE_DISK_PER_CSV_BYTE)
    assert P.disk_needed(None, False) == int(C.PUZZLE_ZST_BYTES_FALLBACK * C.PUZZLE_DISK_PER_ZST_BYTE)


def test_this_python_has_a_zstandard_decoder():
    assert P.zstd_backend() in ("compression.zstd", "zstandard")
