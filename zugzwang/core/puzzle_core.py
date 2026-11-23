"""
Pure puzzle logic — no Qt imports.

Extracted from core/puzzles.py so that both the PyQt PuzzleImporter and the
Tauri sidecar can share it. core/puzzles.py re-exports glicko2_update, so
existing imports keep working.

import_puzzle_stream() is a generator that streams Lichess's puzzle CSV (plain or Zstandard, from a
download or a file) into SQLite on its own connection, beside the current set, and swaps it in at
the end; its events are in its docstring (FIX-B6 B).
"""

from __future__ import annotations

import csv
import io
import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

import chess

import zugzwang.config as C

logger = logging.getLogger(__name__)

_GLICKO_SCALE = 173.7178   # converts between Glicko-2 internal units and Elo-like scale


# ── Glicko-2 rating update ────────────────────────────────────────────────────

def glicko2_update(
    rating: float,
    rd: float,
    volatility: float,
    puzzle_rating: int,
    puzzle_rd: int,
    outcome: float,            # 1.0 = solved clean, 0.0 = failed
    tau: float = C.PUZZLE_TAU,
) -> tuple[float, float, float]:
    """
    Single-game Glicko-2 update (Glickman 2012).
    Returns (new_rating, new_rd, new_volatility).
    Applied per-puzzle rather than per rating period — same approximation
    used by Lichess for puzzle ratings.
    """
    # Step 1: scale to Glicko-2 internal units
    mu    = (rating - 1500.0) / _GLICKO_SCALE
    phi   = rd / _GLICKO_SCALE
    sigma = volatility
    mu_j  = (puzzle_rating - 1500.0) / _GLICKO_SCALE
    phi_j = puzzle_rd / _GLICKO_SCALE

    # Step 2: auxiliary functions
    def g(p: float) -> float:
        return 1.0 / math.sqrt(1.0 + 3.0 * p * p / (math.pi * math.pi))

    def E(m: float, m_j: float, p_j: float) -> float:
        return 1.0 / (1.0 + math.exp(-g(p_j) * (m - m_j)))

    g_j = g(phi_j)
    e_j = E(mu, mu_j, phi_j)

    # Estimated variance
    v = 1.0 / (g_j * g_j * e_j * (1.0 - e_j))

    # Delta (expected improvement)
    delta = v * g_j * (outcome - e_j)

    # Step 4: update volatility via Illinois root-finding algorithm
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex  = math.exp(x)
        phi2 = phi * phi
        d   = phi2 + v + ex
        return (
            ex * (delta * delta - phi2 - v - ex) / (2.0 * d * d)
            - (x - a) / (tau * tau)
        )

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    f_A, f_B = f(A), f(B)
    for _ in range(100):
        C_val  = A + (A - B) * f_A / (f_B - f_A)
        f_C    = f(C_val)
        if f_C * f_B <= 0:
            A, f_A = B, f_B
        else:
            f_A /= 2.0
        B, f_B = C_val, f_C
        if abs(B - A) < 1e-6:
            break

    sigma_new = math.exp(A / 2.0)

    # Step 5-7: update phi and mu
    phi_star = math.sqrt(phi * phi + sigma_new * sigma_new)
    phi_new  = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    mu_new   = mu + phi_new * phi_new * g_j * (outcome - e_j)

    # Step 8: convert back
    new_rating = _GLICKO_SCALE * mu_new + 1500.0
    new_rd     = _GLICKO_SCALE * phi_new

    # Clamp to sensible bounds
    new_rating = max(100.0, min(new_rating, 3500.0))
    new_rd     = max(30.0,  min(new_rd, 350.0))
    return new_rating, new_rd, sigma_new


# ── Import: a stream of Lichess's puzzle CSV, plain or Zstandard (FIX-B6 B, PZ1) ─────────────

# Columns are found by their header names (Lichess's header: PuzzleId, FEN, Moves, Rating,
# RatingDeviation, Popularity, NbPlays, Themes, GameUrl, OpeningTags).
REQUIRED_COLUMNS = ("PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays")
OPTIONAL_COLUMNS = ("Themes", "GameUrl", "OpeningTags")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# The new set is built beside the old one and swapped in at the end, so a cancelled or failed
# import leaves the previous set as it was.
_STAGING = "puzzles_new"
_STAGING_DDL = f"""
    CREATE TABLE {_STAGING} (
        id               TEXT    PRIMARY KEY,
        fen              TEXT    NOT NULL,
        moves_uci        TEXT    NOT NULL,
        rating           INTEGER NOT NULL,
        rating_deviation INTEGER NOT NULL DEFAULT 80,
        popularity       INTEGER NOT NULL DEFAULT 0,
        nb_plays         INTEGER NOT NULL DEFAULT 0,
        themes           TEXT    NOT NULL DEFAULT '',
        game_url         TEXT,
        opening_tags     TEXT,
        imported_at      TEXT    NOT NULL
    )
"""
_INSERT_SQL = f"""
    INSERT OR IGNORE INTO {_STAGING}
        (id, fen, moves_uci, rating, rating_deviation, popularity, nb_plays, themes, game_url,
         opening_tags, imported_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
"""


class PuzzleFileError(Exception):
    """The file is not a Lichess puzzle CSV (a column missing, no rows, not Zstandard)."""


class ImportCancelled(Exception):
    pass


def zstd_backend() -> str:
    """Which Zstandard decoder this Python has: the standard library's (3.14+), else the
    `zstandard` package. Raises ImportError when neither is present."""
    try:
        from compression import zstd  # noqa: F401
        return "compression.zstd"
    except ImportError:
        import zstandard  # noqa: F401
        return "zstandard"


def zstd_reader(raw: BinaryIO) -> BinaryIO:
    """A streaming decompressor over *raw* (read only as far as asked; nothing written to
    disk). Every frame is read, as Lichess's file may hold several."""
    if zstd_backend() == "compression.zstd":
        from compression import zstd
        return zstd.ZstdFile(raw, "rb")  # type: ignore[return-value]
    import zstandard
    return zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True)  # type: ignore[return-value]


class CountingReader(io.RawIOBase):
    """Counts the bytes read from *raw* (the progress in MB) and stops the import when
    *is_cancelled* turns True, even while a slow network read is the only thing happening."""

    def __init__(self, raw, is_cancelled: Callable[[], bool] = lambda: False) -> None:
        self._raw = raw
        self._cancelled = is_cancelled
        self.count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        if self._cancelled():
            raise ImportCancelled()
        data = self._raw.read(len(b))
        n = len(data)
        b[:n] = data
        self.count += n
        return n


def _int(v: str) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def import_puzzle_stream(
    raw: BinaryIO,
    db_path: Path,
    *,
    total_bytes: int | None,
    compressed: bool,
    source: dict,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple]:
    """Import Lichess's puzzle CSV from the byte stream *raw* (a download or a file; Zstandard
    when *compressed*) into SQLite, on a connection of its own. Yields:

        ("progress", bytes_read, total_bytes, rows)   after each batch (bytes of *raw*)
        ("finishing", rows)                           the swap and the theme index
        ("done", stats)                               stats: count, added, removed,
                                                      removed_attempted, previous
        ("cancelled",)                                the previous set untouched

    Raises PuzzleFileError for a file that is not the puzzle CSV, and any network or disk
    error as it comes; either way the new set is dropped and the previous one kept. *source*
    is written to meta on success (kind "lichess" or "file", date, etag, bytes).

    The user's rating, attempts and sessions live in other tables and are not touched.
    Puzzles absent from the new file (Lichess removed them) leave the set; an attempt at one
    keeps its row, so history and ratings are unchanged (FIX-B6, decided item)."""
    counter = CountingReader(raw, is_cancelled)
    buffered = io.BufferedReader(counter, buffer_size=1 << 20)
    stream: BinaryIO = zstd_reader(buffered) if compressed else buffered  # type: ignore[assignment]
    text = io.TextIOWrapper(stream, encoding="utf-8", newline="")

    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    def _drop() -> None:
        try:
            conn.rollback()
            conn.execute(f"DROP TABLE IF EXISTS {_STAGING}")
            conn.commit()
        finally:
            conn.close()

    try:
        conn.execute(f"DROP TABLE IF EXISTS {_STAGING}")
        conn.execute(_STAGING_DDL)
        conn.commit()
        reader = csv.reader(text)
        try:
            header = next(reader)
        except StopIteration:
            raise PuzzleFileError("The file is empty.") from None
        except UnicodeDecodeError:
            raise PuzzleFileError("This is not a puzzle CSV (it is not text; a .zst file must end in .zst).") from None
        col = {name.strip().lstrip("\ufeff"): i for i, name in enumerate(header)}
        missing = [c for c in REQUIRED_COLUMNS if c not in col]
        if missing:
            raise PuzzleFileError(
                "This is not the Lichess puzzle CSV: it has no " + ", ".join(missing) + " column"
                + ("s." if len(missing) > 1 else "."))
        ix = [col[c] for c in REQUIRED_COLUMNS]
        opt = [col.get(c) for c in OPTIONAL_COLUMNS]
        width = max(ix + [i for i in opt if i is not None]) + 1

        now = datetime.now(timezone.utc).isoformat()
        rows = 0
        batch: list[tuple] = []
        for row in reader:
            if len(row) < width:
                row = row + [""] * (width - len(row))
            pid, fen, moves, rating, rd, pop, nb = (row[i] for i in ix)
            pop_i, nb_i = _int(pop), _int(nb)
            if pop_i is None or nb_i is None or pop_i < 0 or nb_i < 50:
                continue
            rating_i, rd_i = _int(rating), _int(rd)
            if rating_i is None or rd_i is None or not pid or not fen or not moves.strip():
                continue
            themes, url, tags = ((row[i].strip() if i is not None else "") for i in opt)
            batch.append((pid, fen, moves.strip(), rating_i, rd_i, pop_i, nb_i, themes,
                          url or None, tags or None, now))
            if len(batch) >= C.PUZZLE_IMPORT_BATCH:
                conn.executemany(_INSERT_SQL, batch)
                conn.commit()
                rows += len(batch)
                batch.clear()
                if is_cancelled():
                    raise ImportCancelled()
                yield ("progress", counter.count, total_bytes, rows)
        if batch:
            conn.executemany(_INSERT_SQL, batch)
            conn.commit()
            rows += len(batch)
        if is_cancelled():
            raise ImportCancelled()
        count = conn.execute(f"SELECT count(*) FROM {_STAGING}").fetchone()[0]
        if count == 0:
            raise PuzzleFileError("The file held no puzzles Zugzwang can use.")
        yield ("progress", counter.count, total_bytes, count)
        yield ("finishing", count)
        stats = _swap(conn, count, source)
        conn.close()
        yield ("done", stats)
    except ImportCancelled:
        _drop()
        yield ("cancelled",)
    except BaseException:
        _drop()
        raise


def _swap(conn: sqlite3.Connection, count: int, source: dict) -> dict:
    """In one transaction: count what leaves, drop the old set, rename the new one in, index
    it, rebuild the theme index, write meta. Readers see the old set until the commit."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = conn.execute("SELECT count(*) FROM puzzles").fetchone()[0]
        removed = conn.execute(
            f"SELECT count(*) FROM puzzles WHERE id NOT IN (SELECT id FROM {_STAGING})").fetchone()[0]
        removed_attempted = conn.execute(
            f"""SELECT count(DISTINCT a.puzzle_id) FROM puzzle_attempts a
                WHERE a.puzzle_id IN (SELECT id FROM puzzles)
                  AND a.puzzle_id NOT IN (SELECT id FROM {_STAGING})""").fetchone()[0]
        conn.execute("DROP TABLE puzzles")
        conn.execute(f"ALTER TABLE {_STAGING} RENAME TO puzzles")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_puzzles_rating ON puzzles(rating)")
        conn.execute("INSERT INTO puzzle_themes_fts(puzzle_themes_fts) VALUES('rebuild')")
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "puzzles_imported": "1",
            "puzzles_imported_at": now,
            "puzzles_count": str(count),
            "puzzles_source": str(source.get("kind") or ""),
            "puzzles_source_date": str(source.get("date") or ""),
            "puzzles_source_etag": str(source.get("etag") or ""),
            "puzzles_source_bytes": str(source.get("bytes") or ""),
        }
        conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", list(meta.items()))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"count": count, "previous": previous, "removed": removed,
            "removed_attempted": removed_attempted, "added": count - (previous - removed)}


def import_puzzles_file(path: Path, db_path: Path,
                        is_cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple]:
    """Import a puzzle file the user picked: the CSV, or Lichess's .zst as downloaded (told
    apart by its first bytes, not its name)."""
    if not path.exists():
        yield ("error", f"No such file: {path}")
        return
    with open(path, "rb") as fh:
        compressed = fh.read(4) == ZSTD_MAGIC
        fh.seek(0)
        source = {"kind": "file", "date": "", "etag": "", "bytes": path.stat().st_size}
        short = disk_shortfall(db_path, path.stat().st_size, compressed)
        if short:
            yield ("error", short)
            return
        yield from import_puzzle_stream(fh, db_path, total_bytes=path.stat().st_size,
                                        compressed=compressed, source=source,
                                        is_cancelled=is_cancelled)


def _default_open(url: str, timeout: float, method: str = "GET"):
    import urllib.request

    from zugzwang.core.platform_sync import _tls_context
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "zugzwang-app"})
    ctx = _tls_context()
    return urllib.request.urlopen(req, timeout=timeout, **({"context": ctx} if ctx else {}))


def _http_date(value: str | None) -> str:
    """Last-Modified as an ISO date-time (UTC), or "" when absent or unreadable."""
    if not value:
        return ""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _source_from_headers(headers) -> dict:
    length = headers.get("Content-Length")
    return {"kind": "lichess", "date": _http_date(headers.get("Last-Modified")),
            "etag": (headers.get("ETag") or "").strip('"'),
            "bytes": int(length) if length and length.isdigit() else None}


def lichess_file_info(open_fn=None, url: str | None = None) -> dict:
    """What Lichess serves now (a HEAD request, nothing downloaded): {date, etag, bytes}."""
    opener = open_fn or _default_open
    with opener(url or C.PUZZLE_LICHESS_URL, C.PUZZLE_DOWNLOAD_TIMEOUT_S, "HEAD") as resp:
        return _source_from_headers(resp.headers)


def disk_needed(nbytes: int | None, compressed: bool) -> int:
    """The free space an import of a file of *nbytes* needs: the new set is built beside the
    old one, plus the write-ahead log (factors measured on a real download, config.py)."""
    if not nbytes:
        nbytes = C.PUZZLE_ZST_BYTES_FALLBACK
        compressed = True
    per = C.PUZZLE_DISK_PER_ZST_BYTE if compressed else C.PUZZLE_DISK_PER_CSV_BYTE
    return int(nbytes * per)


def disk_shortfall(db_path: Path, nbytes: int | None, compressed: bool) -> str | None:
    """A sentence for the user when the disk that holds the database has too little room."""
    import shutil
    need = disk_needed(nbytes, compressed)
    free = shutil.disk_usage(db_path.parent).free
    if free >= need:
        return None
    gb = lambda n: f"{n / 1e9:.1f} GB"  # noqa: E731
    return (f"Not enough free disk space: the puzzles need about {gb(need)} free on the disk that "
            f"holds Zugzwang's data, and it has {gb(free)}. Free some space, then try again.")


def download_lichess_puzzles(db_path: Path, is_cancelled: Callable[[], bool] = lambda: False,
                             open_fn=None, url: str | None = None) -> Iterator[tuple]:
    """Download Lichess's puzzle file and import it as it arrives: the bytes go from the
    network through the Zstandard decoder into SQLite, the decompressed CSV never touches the
    disk. Events as import_puzzle_stream's (bytes counted are the compressed bytes received);
    ("error", message) when the disk has too little room."""
    opener = open_fn or _default_open
    with opener(url or C.PUZZLE_LICHESS_URL, C.PUZZLE_DOWNLOAD_TIMEOUT_S) as resp:
        source = _source_from_headers(resp.headers)
        short = disk_shortfall(db_path, source["bytes"], True)
        if short:
            yield ("error", short)
            return
        yield ("progress", 0, source["bytes"], 0)
        yield from import_puzzle_stream(resp, db_path, total_bytes=source["bytes"],
                                        compressed=True, source=source, is_cancelled=is_cancelled)


def import_puzzles_csv(csv_path: Path, db_path: Path,
                       is_cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple]:
    """The old name: a file import, its events as before ("progress", rows, total) and
    ("done", rows), for callers and tests that use it."""
    for ev in import_puzzles_file(csv_path, db_path, is_cancelled):
        if ev[0] == "progress":
            yield ("progress", ev[3], ev[2])
        elif ev[0] == "done":
            yield ("done", ev[1]["count"])
        elif ev[0] == "finishing":
            continue
        else:
            yield ev


# ── Alternate mating moves (F7) ──────────────────────────────────────────────

def alternate_final_mates(fen: str, moves_uci: list[str]) -> list[str]:
    """Every move that delivers mate in place of a puzzle's final solution move.

    Lichess accepts any mate on the last move of a puzzle: if the point is
    "find the mate" and two mates exist, both are correct. The stored solution
    names only one, so matching it exactly rejects answers Lichess would accept.

    Returns the full set of mating moves (including the stored one) when the
    intended final move is itself mate, and [] otherwise — the mate rule applies
    only to the final move, and only when that move actually mates. UCIs are
    returned in full, so a promotion appears as e.g. 'e7e8q' and callers compare
    exactly rather than by from/to.
    """
    if len(moves_uci) < 2:
        return []

    board = chess.Board(fen)
    try:
        for uci in moves_uci[:-1]:
            board.push(chess.Move.from_uci(uci))
        final = chess.Move.from_uci(moves_uci[-1])
    except (ValueError, AssertionError):
        logger.warning("unplayable puzzle line for fen %s", fen)
        return []

    if final not in board.legal_moves:
        return []

    # Only the *final* move gets the alternate-mate rule, and only if the
    # intended move is a mate. A non-mating last move means the puzzle is about
    # something else (winning material, a defensive resource), where a different
    # move is not interchangeable.
    board.push(final)
    intended_is_mate = board.is_checkmate()
    board.pop()
    if not intended_is_mate:
        return []

    mates = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            mates.append(move.uci())
        board.pop()
    return sorted(mates)
