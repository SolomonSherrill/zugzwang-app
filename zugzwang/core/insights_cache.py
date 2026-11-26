"""FIX-B8 D (owner note 11, "Insights takes so long to load"): a cache of the Insights payload.

Before it, every open of Insights rebuilt the whole aggregate (about 5.5 s on the owner's library, measured
2026-11-26 under load: review/scratch/fixb8/insights_timing.out), the second open of a session included. The cache
keeps the payload under a key made of everything that changes it, as the run's prompt asked:

- **the games**: their count, highest id and a checksum over each game's id, side, result, source, speed, rated and
  attribution (a colour repair or an attribution change moves it);
- **the complete runs**: their count, highest id, latest completion and a checksum over id, depth and
  classifier_version, so a new analysis, an Analyse again and a relabel each change it;
- **the labels themselves**: a checksum over move_analyses' classification and book flag, which a classifier
  relabel and a book relabel rewrite;
- **the classifier version** the code labels with (classification.CLASSIFIER_VERSION);
- **the book in use** (books.active_state: id, sha256, whether its relabel finished);
- **the pattern facts** the patterns card reads (count, versions, latest computed_at);
- **the request** (filters, view) and **the local date** (the monthly series end at the current month).

Any of them changing gives a new key, so the old entry is never read again (invalidation by key); the store keeps
the newest MAX_ENTRIES. It lives in memory, and in one JSON file beside the database (cache/insights.json), so the
first open after a restart is fast too when nothing changed. The fingerprint is read inside the same snapshot as the
build. A cache file that cannot be read or written is ignored: the payload is built as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bumped when the payload's shape or the key's parts change, so an old file is never read.
CACHE_VERSION = 1
MAX_ENTRIES = 8


def fingerprint(db) -> dict:
    """What the Insights payload depends on in the database and the code, read cheaply (no ply-level shaping)."""
    from zugzwang.core import books
    from zugzwang.core.classification import CLASSIFIER_VERSION
    from zugzwang.core.database import standard_run_sql

    c = db._conn
    owner_col = "not_owner" if db.attribution_migrated else "0"
    games = c.execute(
        f"""SELECT count(*), coalesce(max(id), 0),
                   total((id % 100003) * (1 + unicode(coalesce(player_color, '-')) + 3 * unicode(result)
                         + 5 * unicode(source) + 7 * length(coalesce(speed, '')) + 11 * coalesce(rated, 2)
                         + 13 * {owner_col} + 17 * length(played_at)))
            FROM games"""
    ).fetchone()
    runs = c.execute(
        f"""SELECT count(*), coalesce(max(r.id), 0), coalesce(max(r.completed_at), ''),
                   total((r.id % 100003) * (1 + r.depth + 31 * coalesce(r.classifier_version, 0)))
            FROM analysis_runs r WHERE r.completed_at IS NOT NULL AND {standard_run_sql()}"""
    ).fetchone()
    labels = c.execute(
        """SELECT count(*), total(coalesce(is_book, 0) * ((run_id + ply) % 1009 + 1)),
                  total(length(coalesce(classification, '')) * unicode(coalesce(classification, '-'))
                        * ((run_id * 7 + ply) % 1013 + 1))
           FROM move_analyses"""
    ).fetchone()
    try:
        facts = c.execute(
            """SELECT count(*), total(facts_version), total(coalesce(classifier_version, 0)),
                      total(coalesce(rule_version, 0)), coalesce(max(computed_at), '') FROM pattern_facts"""
        ).fetchone()
    except Exception:            # an older schema without the table
        facts = None
    book = books.active_state()
    return {
        "v": CACHE_VERSION,
        "classifier": CLASSIFIER_VERSION,
        "games": list(games), "runs": list(runs), "labels": list(labels),
        "facts": list(facts) if facts is not None else None,
        "book": None if book is None else [book.get("id"), book.get("sha256"), bool(book.get("relabelled"))],
    }


def cache_key(fp: dict, params: dict, today: str | None = None) -> str:
    today = today or datetime.now().astimezone().date().isoformat()
    blob = json.dumps({"fp": fp, "params": params, "today": today}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class InsightsCache:
    """Payloads by key, newest last; at most MAX_ENTRIES, in memory and in *path* (None: memory only)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._mem: OrderedDict[str, dict] = OrderedDict()
        self._loaded = False
        self.hits = 0
        self.misses = 0

    @classmethod
    def beside(cls, db_path: Path) -> "InsightsCache":
        return cls(Path(db_path).parent / "cache" / "insights.json")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text())
            if data.get("v") == CACHE_VERSION:
                for k, v in data.get("entries", []):
                    self._mem[k] = v
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"v": CACHE_VERSION, "entries": list(self._mem.items())}))
            os.replace(tmp, self.path)
        except OSError:
            logger.warning("insights cache: could not write %s", self.path, exc_info=True)

    def clear_file(self) -> None:
        with self._lock:
            self._mem.clear()
            self._loaded = False
            if self.path is not None:
                self.path.unlink(missing_ok=True)

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._load()
            v = self._mem.get(key)
            if v is not None:
                self._mem.move_to_end(key)
            return v

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._load()
            self._mem[key] = value
            self._mem.move_to_end(key)
            while len(self._mem) > MAX_ENTRIES:
                self._mem.popitem(last=False)
            self._save()

    def get_or_build(self, db, params: dict, build: Callable[[], dict], today: str | None = None) -> dict:
        """The cached payload for *params* on *db* as it is now, else *build()*'s, stored. Call it inside the
        database snapshot the build reads, so the key and the payload describe the same state."""
        key = cache_key(fingerprint(db), params, today)
        hit = self.get(key)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        value = build()
        self.put(key, value)
        return value
