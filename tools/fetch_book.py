#!/usr/bin/env python3
"""Fetch one of the hosted opening books (BOOK-DL's manifest, `zugzwang/core/books.py`) into a
folder, verified against the manifest's size and sha256, through the app's own download path.
For CI (BETA-4 D, FIXPLAN TOOL-GATE-CI): the public repo's CI caches the folder between runs and
runs the packaged smoke test's trainer checks with the book.

    python tools/fetch_book.py [book id, default the manifest's default] <dir>

The book lands at <dir>/books/<file>; its path is printed. A file already there is checked
(size and sha256) and kept when it matches; one that does not match is fetched again.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__, file=sys.stderr)
        return 2
    book_id, folder = (None, argv[0]) if len(argv) == 1 else argv
    folder = Path(folder).resolve()
    # The books folder is <data dir>/books: point the data dir at the target before importing.
    os.environ["ZUGZWANG_DATA_DIR"] = str(folder)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from zugzwang.core import books

    spec = books.spec(book_id or books.DEFAULT_ID)
    dest = books.book_path(spec)
    if dest.exists() and (dest.stat().st_size != spec.bytes or books.file_sha256(dest) != spec.sha256):
        print(f"{dest}: not the manifest's {spec.file}, fetching again", file=sys.stderr)
        dest.unlink()
    elif dest.exists():
        print(f"{dest}: present, {spec.bytes} bytes, sha256 matches the manifest", file=sys.stderr)
    path = books.download(spec)
    assert path.stat().st_size == spec.bytes and books.file_sha256(path) == spec.sha256, path
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
