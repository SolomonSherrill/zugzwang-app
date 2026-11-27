"""Opening books: the manifest, a verified download, the book in use, and the book relabel
(BOOK-DL, owner ruling D, 2026-11-19; BETA.md "BOOKS-DL", OPENING_DATA.md "Owner rulings on
B1–B6, and D").

No book ships with the app. Three books, built from the Lichess dumps of 2026-08 and 2026-09
(all bands, weight = games, positions first seen at ply <= 24), are release assets of the public
repo's `books-v1` release, which is never marked latest, so the update feed is untouched.

- **The manifest** (`MANIFEST`) is each book's URL, size and sha256. A download streams to
  `<file>.part` in `<data dir>/books/`, hashing as it goes, and becomes the book's file
  (`os.replace`) only when its size and sha256 equal the manifest's. Anything else (a short
  read, a corrupt byte, a dropped connection, a cancel) deletes the part and leaves every file
  that was there, the book in use included, as it was.
- **The book in use** is `<data dir>/books/active.json`: `{"id", "file", "sha256",
  "relabelled"}`. `relabelled` is false from the moment a switch starts until its relabel has
  finished, so an interrupted switch resumes on the next open. No file means no book.
- **The book relabel** (`relabel_for_book`) is W20's backfill, from stored rows, no engine:
  every ply's `is_book` is set from the book (`OpeningsBook.is_book_move`'s rule: the move has
  an entry in the position), and a run whose flags change is relabelled by `labelling.label_game`
  (which applies the `book` rule: a book move is `book` when unscored or its loss is at most
  `WPL_INACCURACY`; brilliant, the only legal move and a mate keep their own labels; and book is
  a prefix, BOOK-PREFIX, version 8: no ply after the first that fails the rule is `book`), its
  summary recomputed. A run at an older classifier version gets its flags only (its labels are the hand
  procedure's or the relabel on update's business). The pattern facts of every run whose labels
  changed are deleted, so the refill recomputes them (R6-REFILL).

The dev run and the packaged app use the same code, each in its own data directory
(`config.USER_DIR`).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import chess
import chess.polyglot

import zugzwang.config as C

RELEASE_BASE = "https://github.com/SolomonSherrill/zugzwang-app/releases/download/books-v1/"


@dataclass(frozen=True)
class BookSpec:
    id: str
    label: str
    min_games: int
    file: str
    bytes: int
    sha256: str
    default: bool = False

    @property
    def url(self) -> str:
        return RELEASE_BASE + self.file


#: The hosted books (books-v1, uploaded 2026-11-19; sizes and digests measured from the files
#: uploaded, OPENING_DATA.md "Books hosted"). The default first.
MANIFEST: tuple[BookSpec, ...] = (
    BookSpec("all-20", "Standard", 20, "zugzwang-book-all-20-games.bin", 151_320_480,
             "d2ab4795e227435450c55ef742dc1d634fa8323bf3535f92533eb54aaadf600a", default=True),
    BookSpec("all-6", "Large", 6, "zugzwang-book-all-6-games.bin", 572_067_472,
             "4d322851fc46bbbe996596333ba7070d5b81415178bca9dfb5299323463e1b4f"),
    BookSpec("all-3", "Largest", 3, "zugzwang-book-all-3-games.bin", 1_323_905_200,
             "13ed897fe6a64896aed5dd7433d73afe171bd8f28be11c78cb2d7694cc86c80f"),
)
DEFAULT_ID = next(b.id for b in MANIFEST if b.default)
CHUNK = 1 << 20


class BookError(RuntimeError):
    pass


class DownloadFailed(BookError):
    pass


class Cancelled(BookError):
    pass


def spec(book_id: str) -> BookSpec:
    for b in MANIFEST:
        if b.id == book_id:
            return b
    raise BookError(f"unknown opening book: {book_id!r}")


def books_dir() -> Path:
    return C.USER_DIR / "books"


def book_path(b: BookSpec) -> Path:
    return books_dir() / b.file


def _active_file() -> Path:
    return books_dir() / "active.json"


def active_state() -> dict | None:
    """The book in use as recorded, or None. A record whose file is gone or the wrong size
    reads as no book (the file is checked by size here; its sha256 was checked when it was
    installed)."""
    try:
        st = json.loads(_active_file().read_text())
        b = spec(st["id"])
    except (OSError, ValueError, KeyError, BookError):
        return None
    p = book_path(b)
    try:
        if p.stat().st_size != b.bytes:
            return None
    except OSError:
        return None
    return {**st, "file": b.file, "sha256": b.sha256, "path": str(p)}


def active_spec() -> BookSpec | None:
    st = active_state()
    return spec(st["id"]) if st else None


def active_book_path() -> Path | None:
    st = active_state()
    return Path(st["path"]) if st else None


def active_stamp() -> dict | None:
    """The run provenance's `book` field: the file and its sha256 from the manifest (verified
    at install; not re-hashed per run)."""
    st = active_state()
    return {"file": st["file"], "sha256": st["sha256"]} if st else None


def set_active(book_id: str | None, *, relabelled: bool) -> None:
    """Record the book in use (None: no book), atomically."""
    f = _active_file()
    if book_id is None:
        f.unlink(missing_ok=True)
        return
    b = spec(book_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"id": b.id, "file": b.file, "sha256": b.sha256,
                               "relabelled": relabelled}))
    os.replace(tmp, f)


def installed(b: BookSpec) -> bool:
    """The file is present at the manifest's size (its hash was checked when it landed)."""
    try:
        return book_path(b).stat().st_size == b.bytes
    except OSError:
        return False


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_open(url: str, timeout: float):
    import urllib.request

    from zugzwang.core.platform_sync import _tls_context
    req = urllib.request.Request(url, headers={"User-Agent": "zugzwang-app"})
    ctx = _tls_context()
    return urllib.request.urlopen(req, timeout=timeout, **({"context": ctx} if ctx else {}))


def download(b: BookSpec, *, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             opener: Callable[[str, float], object] | None = None,
             url: str | None = None) -> Path:
    """Fetch *b* into the books folder and verify it against the manifest; return its path.

    Already installed: nothing is fetched. Otherwise the bytes go to `<file>.part`; only a
    part of exactly `b.bytes` bytes whose sha256 is `b.sha256` is renamed into place. On
    any failure the part is deleted and `DownloadFailed` (or `Cancelled`) raised; no other
    file is touched."""
    dest = book_path(b)
    if installed(b):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    got = 0
    try:
        with (opener or _default_open)(url or b.url, 60) as resp, open(part, "wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled("download cancelled")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                got += len(chunk)
                if got > b.bytes:
                    raise DownloadFailed(f"{b.file}: more than the expected {b.bytes} bytes")
                h.update(chunk)
                out.write(chunk)
                if progress is not None:
                    progress(got, b.bytes)
        if got != b.bytes:
            raise DownloadFailed(f"{b.file}: incomplete, {got} of {b.bytes} bytes")
        if h.hexdigest() != b.sha256:
            raise DownloadFailed(f"{b.file}: sha256 {h.hexdigest()} is not the manifest's")
        os.replace(part, dest)
    except BookError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:          # network, disk: the same outcome, nothing installed
        part.unlink(missing_ok=True)
        raise DownloadFailed(f"{b.file}: {exc}") from exc
    return dest


def remove(b: BookSpec) -> None:
    """Delete a downloaded book that is not in use."""
    st = active_state()
    if st and st["id"] == b.id:
        raise BookError("the book in use cannot be removed")
    book_path(b).unlink(missing_ok=True)


# ── the book relabel (W20) ───────────────────────────────────────────────────

def _flags(reader, rows: Iterable[tuple]) -> list[bool]:
    """`OpeningsBook.is_book_move`'s rule per row (fen_before, played_uci at [2], [3])."""
    out = []
    for r in rows:
        if reader is None:
            out.append(False)
            continue
        m = chess.Move.from_uci(r[3])
        out.append(any(e.move == m for e in reader.find_all(chess.Board(r[2]))))
    return out


def relabel_for_book(db_path: Path, new_book: Path | None, *, write: bool,
                     progress: Callable[[int, int], None] | None = None,
                     cancelled: Callable[[], bool] | None = None,
                     detail: Callable[[int, list[tuple]], None] | None = None) -> dict:
    """Set every complete run's `is_book` from *new_book* (None: no book) and relabel the runs
    whose flags change; `write=False` is the dry run (nothing written).

    Returns {"runs", "runsChanged", "runsFlagsOnly", "pliesFlagged", "pliesUnflagged",
    "labelsChanged", "transitions": {"old>new": n}, "factsDeleted", "relabelledRuns": [run ids
    whose labels changed]} (and "integrity" when written). *detail*, if given, gets
    (run_id, [(ply, old_label, new_label, old_is_book, new_is_book, open), ...]) for every run
    with a change, the dry run's exact set; *open* is whether the game's book prefix was still
    open at that ply under the new flags (None for a run at an older classifier, whose labels
    are not recomputed). One transaction per run."""
    from zugzwang.core import labelling
    from zugzwang.core.classification import CLASSIFIER_VERSION
    from zugzwang.core.relabel import _COLS, _to_ma

    reader = chess.polyglot.open_reader(str(new_book)) if new_book is not None else None
    con = sqlite3.connect(str(db_path) if write else f"file:{db_path}?mode=ro",
                          uri=not write, isolation_level=None)
    con.execute("PRAGMA busy_timeout = 5000")
    stats = Counter()
    trans: Counter = Counter()
    relabelled_runs: list[int] = []
    try:
        runs = con.execute(
            "SELECT r.id, r.classifier_version, r.final_lines_json, g.source, g.pgn "
            "FROM analysis_runs r JOIN games g ON g.id = r.game_id "
            "WHERE r.completed_at IS NOT NULL ORDER BY r.id").fetchall()
        for k, (rid, ver, fl, source, pgn) in enumerate(runs, 1):
            if cancelled is not None and cancelled():
                raise Cancelled("book relabel cancelled")
            rows = con.execute(f"SELECT {_COLS} FROM move_analyses WHERE run_id=? ORDER BY ply",
                               (rid,)).fetchall()
            flags = _flags(reader, rows)
            old = [bool(r[14]) for r in rows]
            if flags != old:
                stats["runsChanged"] += 1
                stats["pliesFlagged"] += sum(1 for a, b in zip(old, flags) if b and not a)
                stats["pliesUnflagged"] += sum(1 for a, b in zip(old, flags) if a and not b)
                current = ver == CLASSIFIER_VERSION
                if current:
                    plies = [replace(_to_ma(r), is_book=f) for r, f in zip(rows, flags)]
                    new = labelling.label_game(plies, json.loads(fl) if fl else [],
                                               ratings=labelling.game_ratings(source, pgn))
                    labels = [m.classification for m in new]
                    opens: list[bool | None] = []
                    still = True
                    for m in new:
                        opens.append(still)
                        still = still and labelling.in_book(m)
                else:
                    stats["runsFlagsOnly"] += 1
                    labels = [r[13] for r in rows]
                    new = None
                    opens = [None] * len(rows)
                changes = [(r[1], r[13], lab, a, f, o) for r, lab, a, f, o
                           in zip(rows, labels, old, flags, opens) if r[13] != lab or a != f]
                n_lab = sum(1 for c in changes if c[1] != c[2])
                stats["labelsChanged"] += n_lab
                if n_lab:
                    relabelled_runs.append(rid)
                trans.update(f"{c[1]}>{c[2]}" for c in changes if c[1] != c[2])
                if detail is not None:
                    detail(rid, changes)
                if write:
                    con.execute("BEGIN IMMEDIATE")
                    try:
                        con.executemany(
                            "UPDATE move_analyses SET is_book=?, classification=? WHERE id=?",
                            [(int(f), lab, r[0]) for r, f, lab in zip(rows, flags, labels)])
                        if new is not None:
                            summ = labelling.summary(new)
                            con.execute(
                                "UPDATE analysis_runs SET payload_json=?, white_accuracy=?, "
                                "black_accuracy=? WHERE id=?",
                                (json.dumps(summ), summ["white"]["accuracy"],
                                 summ["black"]["accuracy"], rid))
                        if n_lab:
                            stats["factsDeleted"] += con.execute(
                                "DELETE FROM pattern_facts WHERE run_id=?", (rid,)).rowcount
                        con.execute("COMMIT")
                    except BaseException:
                        con.execute("ROLLBACK")
                        raise
            if progress is not None:
                progress(k, len(runs))
        out = {"runs": len(runs), "runsChanged": 0, "runsFlagsOnly": 0, "pliesFlagged": 0,
               "pliesUnflagged": 0, "labelsChanged": 0, "factsDeleted": 0, **stats,
               "transitions": dict(trans.most_common()), "relabelledRuns": relabelled_runs}
        if write:
            out["integrity"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        return out
    finally:
        con.close()
        if reader is not None:
            reader.close()


def outside_w20(change: tuple, row_scores: tuple | None = None) -> bool:
    """Whether one change (ply, old, new, old_is_book, new_is_book[, open]) is outside W20's
    rule with the book prefix (BOOK-PREFIX): a label may only become `book` on a ply the book
    now holds inside the game's book prefix, and only leave `book` on a ply the book no longer
    holds or one past the prefix. *open* (`relabel_for_book`'s detail) is whether the prefix
    was still open at the ply; absent or None reads as open."""
    _ply, old, new, _ob, nb = change[:5]
    open_ = change[5] if len(change) > 5 and change[5] is not None else True
    if old == new:
        return False
    if new == "book":
        return not (nb and open_)
    if old == "book":
        return nb and open_
    return True
