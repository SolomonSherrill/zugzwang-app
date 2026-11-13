"""
SQLite persistence layer. All public methods are called from the main thread.
Schema is created on first use; future migrations are additive (new tables/columns only).
"""

import io
import json
import logging
import re
import sqlite3
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chess.pgn

import zugzwang.config as C
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.config import DB_PATH, USER_DIR

logger = logging.getLogger(__name__)


class AttributionPending(RuntimeError):
    """A game whose side cannot be attributed, offered to a database that has not
    run `Database.migrate_attribution` — so there is no honest way to store it."""

_TIME_CONTROL_RE = re.compile(r'\[TimeControl\s+"([^"]+)"\]')
_RATED_RE = re.compile(r'\[Rated\s+"([^"]+)"\]')
_EVENT_RE = re.compile(r'\[Event\s+"([^"]*)"\]')


def speed_from_time_control(tc: str | None) -> str | None:
    """Classify a PGN TimeControl string into bullet/blitz/rapid/classical using
    the Lichess estimate (base + 40·increment seconds). Returns None for
    correspondence ('-'), unclocked, or unparseable controls."""
    tc = (tc or "").strip()
    if not tc or tc in ("-", "?"):
        return None
    seg = tc.split(":")[0].split(",")[0].strip()
    if "/" in seg:  # correspondence, e.g. "1/259200"
        return None
    try:
        if "+" in seg:
            base_s, inc_s = seg.split("+", 1)
            base, inc = int(base_s), int(inc_s)
        else:
            base, inc = int(seg), 0
    except ValueError:
        return None
    estimate = base + 40 * inc
    if estimate < 180:
        return "bullet"
    if estimate < 480:
        return "blitz"
    if estimate < 1500:
        return "rapid"
    return "classical"


def speed_from_pgn(pgn: str | None) -> str | None:
    """Derive the game speed bucket from a PGN's TimeControl header, or None."""
    if not pgn:
        return None
    m = _TIME_CONTROL_RE.search(pgn)
    return speed_from_time_control(m.group(1)) if m else None


def rated_from_pgn(pgn: str | None) -> bool | None:
    """Derive rated vs. casual from a PGN's headers, or None if unknown.

    Chess.com sync injects a ``[Rated "true"/"false"]`` header; Lichess encodes
    it in the Event tag ("Rated …" / "Casual …"). Manual imports usually carry
    neither, so None means "unknown — don't filter or badge"."""
    if not pgn:
        return None
    m = _RATED_RE.search(pgn)
    if m:
        return m.group(1).strip().lower() == "true"
    e = _EVENT_RE.search(pgn)
    if e:
        event = e.group(1).lower()
        if "casual" in event:
            return False
        if "rated" in event:
            return True
    return None


def _rated_int(pgn: str | None) -> int | None:
    """rated_from_pgn as the 1/0/NULL form stored in the games.rated column."""
    rated = rated_from_pgn(pgn)
    return None if rated is None else int(rated)


@dataclass(frozen=True)
class InsightsFilter:
    """Optional filters applied to every insights query. `color` restricts to the
    side the player had; `speeds` restricts to the given time-control buckets
    (empty = all); `since` is an ISO timestamp lower bound on played_at; `rated`
    restricts to rated ('rated') or casual ('casual') games ('all' = both);
    `include_local` adds games played here against Stockfish, which are left out
    by default because the player chose the opponent's strength."""

    color: str = "all"  # 'all' | 'white' | 'black'
    speeds: tuple[str, ...] = ()
    since: str | None = None
    rated: str = "all"  # 'all' | 'rated' | 'casual'
    include_local: bool = False


@dataclass
class PuzzleRecord:
    id: str
    fen: str
    moves_uci: list[str]   # pre-split; [0] = opponent setup, rest = solution
    rating: int
    rating_deviation: int
    themes: str


@dataclass
class MoveAnalysis:
    ply: int
    fen_before: str
    played_uci: str
    # None when no best move was established. Rows written before this was
    # representable carry `''` instead; `move_analyses()` normalises them.
    best_uci: str | None
    pv_uci: str
    score_before_cp: int | None
    score_before_mate: int | None
    score_after_cp: int | None
    score_after_mate: int | None
    second_best_uci: str | None
    second_best_cp: int | None
    second_best_mate: int | None
    classification: str
    is_book: bool
    # top engine lines for the position before this ply: [{cp, mate, uci, san}]
    lines: list = field(default_factory=list)
    # The after-move search as the analysis loop ran it (depth `max(d−4, 10)`, MultiPV 1).
    # Since classifier version 3, `score_after_*` is the depth-14 score of the same
    # position (ply N+1's before-search; `labelling.after_score`) and this keeps the
    # shallower one, which only the game report's conservative swing reads (owner ruling
    # 10, 2026-11-11). None on rows labelled before version 3, whose `score_after_*` *is*
    # this search.
    after_search_cp: int | None = None
    after_search_mate: int | None = None
    # Owner ruling T8 (2026-11-12, FIXPLAN CLS-V3-T8): the position's best move is a hard
    # only move (`labelling.hard_only_move`) — the only one that holds, and quiet or a
    # sacrifice outside the old obvious strata. Not a label; stored for the game report.
    # None on rows labelled before it existed (migration v18).
    hard_only_move: bool | None = None


@dataclass
class AnalysisRun:
    id: int
    game_id: int
    engine_name: str
    depth: int
    created_at: str
    payload_json: str
    white_accuracy: float | None = None
    black_accuracy: float | None = None
    final_lines_json: str | None = None     # v15; NULL before STORE-FINALPLY

    @property
    def final_lines(self) -> list[dict]:
        return json.loads(self.final_lines_json) if self.final_lines_json else []


@dataclass
class RunSummary:
    """The part of a game's latest `analysis_runs` row a game *list* needs. Kept
    separate from `AnalysisRun` because that one carries `payload_json`, and
    loading 1 837 of those to read two floats is the cost this avoids."""
    id: int
    white_accuracy: float | None
    black_accuracy: float | None


@dataclass
class GameRecord:
    id: int
    played_at: str
    player_color: str | None  # 'white' | 'black' | None (unknown; see O5 / migrate_attribution)
    skill_level: int
    result: str              # '1-0' | '0-1' | '1/2-1/2' | '*'
    termination: str
    move_count: int
    pgn: str
    final_fen: str
    opening_eco: str | None
    opening_name: str | None
    source: str = 'local'    # 'local' | 'imported' | 'lichess' | 'chesscom'
    external_id: str | None = None   # source platform game id (sync dedup)
    speed: str | None = None  # 'bullet' | 'blitz' | 'rapid' | 'classical' | None
    rated: int | None = None  # 1 rated / 0 casual / None unknown (stored as INTEGER)
    # Which level→Elo ladder `skill_level` was chosen on. NULL = played before
    # the ladder was recorded, so the number cannot be mapped to a current one.
    ladder_version: int | None = None
    # 1 = not the user's game (no configured handle on either side); excluded from
    # every aggregate. Only present after `migrate_attribution` (FIXPLAN O5).
    not_owner: int = 0


#: The version `_apply_schema` leaves the database at, i.e. the highest
#: `_migrate_vN` it runs. Recorded in `meta.schema_version` as a *record* of
#: what happened, never as a gate on what to do: each migration decides for
#: itself by probing `PRAGMA table_info`, which is what lets them run
#: unconditionally on every open and stay correct on a database whose stored
#: version says nothing useful. Bump this when adding a migration.
SCHEMA_VERSION = 18

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at    TEXT    NOT NULL,
    player_color TEXT    NOT NULL,
    skill_level  INTEGER NOT NULL,
    result       TEXT    NOT NULL,
    termination  TEXT    NOT NULL,
    move_count   INTEGER NOT NULL,
    opening_eco  TEXT,
    opening_name TEXT,
    pgn          TEXT    NOT NULL,
    final_fen    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_played_at ON games(played_at DESC);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    engine_name  TEXT    NOT NULL,
    depth        INTEGER NOT NULL,
    created_at   TEXT    NOT NULL,
    payload_json TEXT    NOT NULL
);

-- `id DESC` because every reader of this table wants the *latest* run for a game,
-- so the ordering is part of the lookup rather than a sort applied after it. Not a
-- micro-optimisation: unindexed, `games_pending_analysis` scans the whole table
-- once per candidate game and takes 55 ms, and it is on the sync path.
CREATE INDEX IF NOT EXISTS idx_analysis_runs_game ON analysis_runs(game_id, id DESC);

CREATE TABLE IF NOT EXISTS puzzles (
    id          TEXT    PRIMARY KEY,
    fen         TEXT    NOT NULL,
    moves_uci   TEXT    NOT NULL,
    rating      INTEGER NOT NULL,
    themes      TEXT,
    imported_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS move_analyses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    ply               INTEGER NOT NULL,
    fen_before        TEXT    NOT NULL,
    played_uci        TEXT    NOT NULL,
    best_uci          TEXT,
    pv_uci            TEXT    NOT NULL,
    score_before_cp   INTEGER,
    score_before_mate INTEGER,
    score_after_cp    INTEGER,
    score_after_mate  INTEGER,
    second_best_uci   TEXT,
    second_best_cp    INTEGER,
    second_best_mate  INTEGER,
    classification    TEXT    NOT NULL,
    is_book           INTEGER NOT NULL DEFAULT 0,
    lines_json        TEXT,
    UNIQUE(run_id, ply)
);

CREATE INDEX IF NOT EXISTS idx_move_analyses_run ON move_analyses(run_id);

CREATE TABLE IF NOT EXISTS puzzle_rating (
    id         INTEGER PRIMARY KEY DEFAULT 1,
    rating     REAL    NOT NULL DEFAULT 800.0,
    rd         REAL    NOT NULL DEFAULT 350.0,
    volatility REAL    NOT NULL DEFAULT 0.06,
    updated_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS puzzle_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mode         TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    ended_at     TEXT,
    time_limit_s INTEGER,
    score        INTEGER NOT NULL DEFAULT 0,
    peak_rating  INTEGER
);

CREATE TABLE IF NOT EXISTS puzzle_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    puzzle_id     TEXT    NOT NULL,
    session_id    INTEGER,
    mode          TEXT    NOT NULL,
    attempted_at  TEXT    NOT NULL,
    solved        INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    used_hint     INTEGER NOT NULL DEFAULT 0,
    gave_up       INTEGER NOT NULL DEFAULT 0,
    solve_time_s  REAL,
    rating_before REAL,
    rating_after  REAL
);

CREATE INDEX IF NOT EXISTS idx_attempts_puzzle  ON puzzle_attempts(puzzle_id);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON puzzle_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_recent  ON puzzle_attempts(attempted_at DESC);

CREATE TABLE IF NOT EXISTS opening_book_coverage (
    eco         TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    color       TEXT    NOT NULL,
    has_moves   INTEGER NOT NULL,
    PRIMARY KEY (eco, name, color)
);

CREATE TABLE IF NOT EXISTS opening_trainer_progress (
    eco             TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    color           TEXT    NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    completions     INTEGER NOT NULL DEFAULT 0,
    distinct_lines  INTEGER NOT NULL DEFAULT 0,
    last_trained_at TEXT,
    best_accuracy   REAL,
    PRIMARY KEY (eco, name, color)
);

CREATE TABLE IF NOT EXISTS opening_trainer_completions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    eco                  TEXT    NOT NULL,
    name                 TEXT    NOT NULL,
    color                TEXT    NOT NULL,
    mode                 TEXT    NOT NULL,
    terminal_zobrist_hex TEXT    NOT NULL,
    completed_at         TEXT    NOT NULL,
    moves_played         INTEGER NOT NULL,
    errors_made          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trainer_completions ON opening_trainer_completions(eco, name, color);

-- A position that killed the engine twice (VAL-DEATH). Keyed the measurement house
-- rule's way — platform game id + ply + FEN — because `games.id` does not survive a
-- re-pull; `game_id` is kept only as a convenience and carries no foreign key.
CREATE TABLE IF NOT EXISTS engine_failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT    NOT NULL,
    context     TEXT    NOT NULL,
    source      TEXT,
    external_id TEXT,
    game_id     INTEGER,
    ply         INTEGER,
    fen         TEXT    NOT NULL,
    exit_code   INTEGER,
    engine      TEXT,
    message     TEXT    NOT NULL
);
"""


def pgn_ply_count(pgn: str | None) -> int:
    """Half-moves in a PGN's mainline — exactly the plies `analyze_game_plies` walks,
    so a run is complete when it stores each of them once. Not `games.move_count`: on
    four Lichess games that column is two higher than the PGN (VAL-DEATH)."""
    game = chess.pgn.read_game(io.StringIO(pgn or ""))
    return 0 if game is None else sum(1 for _ in game.mainline_moves())


class IncompleteRun(RuntimeError):
    """A run was about to be marked complete without every ply of its game."""


@dataclass(frozen=True)
class RunAudit:
    """One run whose stored plies are not exactly its game's (`audit_run_completeness`)."""
    run_id: int
    game_id: int
    source: str
    external_id: str | None
    engine_name: str
    depth: int
    stored_plies: int
    game_plies: int
    completed: bool         # marked complete anyway — the defect this guards against"""


class Database:
    def __init__(self, path: Path = DB_PATH, *, read_only: bool = False) -> None:
        """read_only=True opens a second connection for a reader on another
        thread, via a `mode=ro` URI so the worker structurally cannot write.

        sqlite3 connections are single-thread (check_same_thread=True), so a
        worker cannot borrow the app thread's. It also must not run the
        migrations — that would be a concurrent write against the connection the
        app thread is using — and mode=ro enforces that rather than trusting it.

        The cost of that is an ordering requirement: a read-only connection can
        only read a database some read-write connection has already migrated.
        Open one against a database still on an older schema and queries naming
        a newer column fail with `no such column`, not with a missing value.
        """
        self.read_only = read_only
        if read_only:
            uri = f"file:{urllib.parse.quote(str(path))}?mode=ro"
            # isolation_level=None: no implicit transaction management, so an
            # explicit BEGIN in snapshot() means exactly what it says.
            self._conn = sqlite3.connect(
                uri, uri=True, check_same_thread=True, isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            self._set_busy_timeout()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._set_busy_timeout()
        self._apply_schema()

    def _set_busy_timeout(self) -> None:
        # 5 000 ms is what these connections already had: sqlite3.connect's
        # `timeout=5.0` default is sqlite3_busy_timeout. Setting it here does not
        # change the value, it changes where the value comes from — a deliberate
        # choice rather than a stdlib default that a later `timeout=` argument or
        # a different sqlite3 build could remove without anyone noticing.
        self._conn.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def snapshot(self):
        """Hold one read transaction for the block.

        Without this, each SELECT is its own implicit transaction, so a long
        multi-query aggregate can mix rows from before and after a concurrent
        write and report totals that never existed at any single instant.
        """
        self._conn.execute("BEGIN")
        try:
            yield self
        finally:
            self._conn.execute("ROLLBACK")  # read-only: nothing to commit

    def interrupt(self) -> None:
        """Abort whatever this connection is running. Safe to call from another
        thread — it is how shutdown reclaims a worker mid-query."""
        self._conn.interrupt()

    def _apply_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._migrate_v3()
        self._migrate_v4()
        self._migrate_v5()
        self._migrate_v6()
        self._migrate_v7()
        self._migrate_v8()
        self._migrate_v9()
        self._migrate_v10()
        self._migrate_v11()
        self._migrate_v12()
        self._migrate_v13()
        self._migrate_v14()
        self._migrate_v15()
        self._migrate_v16()
        self._migrate_v17()
        self._migrate_v18()
        # Stamped last, and overwritten rather than inserted-if-absent: the old
        # `INSERT OR IGNORE` meant the first value a database ever received was
        # the only one it ever had. On the live database that value was '1',
        # eleven migrations behind the schema actually present.
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def _migrate_v3(self) -> None:
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "white_accuracy" not in cols:
            self._conn.execute(
                "ALTER TABLE analysis_runs ADD COLUMN white_accuracy REAL"
            )
        if "black_accuracy" not in cols:
            self._conn.execute(
                "ALTER TABLE analysis_runs ADD COLUMN black_accuracy REAL"
            )

    def _migrate_v5(self) -> None:
        # Rebuild puzzles table if it's the old stub (missing rating_deviation column).
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(puzzles)").fetchall()
        }
        if "rating_deviation" not in cols:
            self._conn.execute("DROP TABLE IF EXISTS puzzles")
            self._conn.execute("""
                CREATE TABLE puzzles (
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
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_puzzles_rating ON puzzles(rating)"
            )
        # FTS5 virtual table for theme search (content table backed by puzzles).
        fts_exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='puzzle_themes_fts'"
        ).fetchone()
        if not fts_exists:
            self._conn.execute("""
                CREATE VIRTUAL TABLE puzzle_themes_fts USING fts5(
                    themes,
                    content='puzzles',
                    content_rowid='rowid'
                )
            """)

    def _migrate_v4(self) -> None:
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(games)").fetchall()
        }
        if "source" not in cols:
            self._conn.execute(
                "ALTER TABLE games ADD COLUMN source TEXT NOT NULL DEFAULT 'local'"
            )

    def _migrate_v6(self) -> None:
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(move_analyses)").fetchall()
        }
        if "lines_json" not in cols:
            self._conn.execute("ALTER TABLE move_analyses ADD COLUMN lines_json TEXT")

    def _migrate_v7(self) -> None:
        # Platform-sync dedup: external_id holds the source platform's game id
        # (e.g. Lichess game id). NULL for locally-played games.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(games)").fetchall()
        }
        if "external_id" not in cols:
            self._conn.execute("ALTER TABLE games ADD COLUMN external_id TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_games_external"
            " ON games(source, external_id) WHERE external_id IS NOT NULL"
        )

    def _migrate_v8(self) -> None:
        # Time-control speed bucket (bullet/blitz/rapid/classical) for insights
        # filtering, derived from each game's PGN TimeControl header.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(games)").fetchall()
        }
        if "speed" in cols:
            return
        self._conn.execute("ALTER TABLE games ADD COLUMN speed TEXT")
        for row in self._conn.execute("SELECT id, pgn FROM games").fetchall():
            speed = speed_from_pgn(row["pgn"])
            if speed:
                self._conn.execute(
                    "UPDATE games SET speed=? WHERE id=?", (speed, row["id"])
                )

    def _migrate_v9(self) -> None:
        # Rated vs. casual flag (1/0/NULL) for insights filtering, derived from
        # each game's PGN headers. Mirrors the v8 speed backfill.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(games)").fetchall()
        }
        if "rated" in cols:
            return
        self._conn.execute("ALTER TABLE games ADD COLUMN rated INTEGER")
        for row in self._conn.execute("SELECT id, pgn FROM games").fetchall():
            rated = rated_from_pgn(row["pgn"])
            if rated is not None:
                self._conn.execute(
                    "UPDATE games SET rated=? WHERE id=?", (int(rated), row["id"])
                )

    def _migrate_v10(self) -> None:
        # Which classifier produced a run's labels. Nullable on purpose: NULL
        # means "written before versioning existed", which is a different claim
        # from any version number and is what every existing row honestly is.
        # No backfill here — stamping a version is the reclassification's job,
        # not the migration's, and a migration that guessed would erase the one
        # signal telling us which rows have not been through it yet.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "classifier_version" not in cols:
            self._conn.execute(
                "ALTER TABLE analysis_runs ADD COLUMN classifier_version INTEGER"
            )

    def _migrate_v11(self) -> None:
        # Let `best_uci` hold NULL, so "no best move was established" stops being
        # spelled `''` — a value that slices into `[NaN, NaN]` in the UI (W6) and
        # is indistinguishable from a real answer to the type system.
        #
        # SQLite cannot drop a NOT NULL constraint in place, so this rebuilds the
        # table. Cheap: `move_analyses` is ~48 MB of a 1.5 GB database, the rest
        # being puzzles. Existing `''` rows are deliberately *not* rewritten —
        # `load_move_analyses` normalises them on read, which keeps every stored
        # row exactly as whatever wrote it left it.
        info = self._conn.execute("PRAGMA table_info(move_analyses)").fetchall()
        best = next((r for r in info if r[1] == "best_uci"), None)
        if best is None or not best[3]:  # r[3] is "notnull"
            return
        self._conn.executescript("""
            PRAGMA foreign_keys=off;
            BEGIN;
            CREATE TABLE move_analyses_new (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            INTEGER NOT NULL
                                  REFERENCES analysis_runs(id) ON DELETE CASCADE,
                ply               INTEGER NOT NULL,
                fen_before        TEXT    NOT NULL,
                played_uci        TEXT    NOT NULL,
                best_uci          TEXT,
                pv_uci            TEXT    NOT NULL,
                score_before_cp   INTEGER,
                score_before_mate INTEGER,
                score_after_cp    INTEGER,
                score_after_mate  INTEGER,
                second_best_uci   TEXT,
                second_best_cp    INTEGER,
                second_best_mate  INTEGER,
                classification    TEXT    NOT NULL,
                is_book           INTEGER NOT NULL DEFAULT 0,
                lines_json        TEXT,
                UNIQUE(run_id, ply)
            );
            INSERT INTO move_analyses_new SELECT
                id, run_id, ply, fen_before, played_uci, best_uci, pv_uci,
                score_before_cp, score_before_mate, score_after_cp,
                score_after_mate, second_best_uci, second_best_cp,
                second_best_mate, classification, is_book, lines_json
            FROM move_analyses;
            DROP TABLE move_analyses;
            ALTER TABLE move_analyses_new RENAME TO move_analyses;
            CREATE INDEX IF NOT EXISTS idx_move_analyses_run ON move_analyses(run_id);
            COMMIT;
            PRAGMA foreign_keys=on;
        """)

    def _migrate_v12(self) -> None:
        # Which level→Elo ladder a locally-played game's `skill_level` was chosen
        # on (F5 replaced it). Nullable with no backfill, for the same reason as
        # v10's classifier_version: NULL means "played before this was recorded",
        # which is a different and weaker claim than any version number. Stamping
        # existing rows with 1 would assert they used today's ladder, and stamping
        # them 0 would assert they all used the piecewise one — neither is
        # knowable, since the database predates the repository.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(games)").fetchall()
        }
        if "ladder_version" not in cols:
            self._conn.execute(
                "ALTER TABLE games ADD COLUMN ladder_version INTEGER"
            )

    def _migrate_v13(self) -> None:
        # Where a ply's scores came from when it was not this run's own engine
        # (F4b-index). NULL means the run's engine, which every row written by
        # analysis is: `save_move_analysis` never sets it, so "Re-analyse"
        # (which replaces the whole run) drops any other source by construction.
        # The F4b-index backfill writes a versioned value such as
        # 'lichess-index-v1'; provenance for that value lives in `meta`.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(move_analyses)").fetchall()
        }
        if "score_source" not in cols:
            self._conn.execute(
                "ALTER TABLE move_analyses ADD COLUMN score_source TEXT"
            )

    def _migrate_v14(self) -> None:
        # VAL-DEATH: a run counts only once complete. `completed_at` is set in the
        # transaction that writes the summary (`complete_analysis_run`), and every
        # reader ignores a run without it.
        #
        # Existing runs are stamped by measurement, not assumed: complete (with its
        # `created_at`, the best time on record) exactly when its stored plies are its
        # PGN's plies, 0..n-1 each once. The ones a dead engine cut short stay NULL
        # and are not rewritten — readers stop showing them and sync re-analyses their
        # games. What the backfill found is recorded in `meta`.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "completed_at" in cols:
            return
        self._conn.execute("ALTER TABLE analysis_runs ADD COLUMN completed_at TEXT")
        short = {a.run_id for a in self.audit_run_completeness()}
        total = 0
        for (run_id,) in self._conn.execute("SELECT id FROM analysis_runs").fetchall():
            total += 1
            if run_id not in short:
                self._conn.execute(
                    "UPDATE analysis_runs SET completed_at = created_at WHERE id = ?",
                    (run_id,))
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('completed_at_backfill', ?)",
            (json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "rule": "complete iff stored plies are exactly 0..n-1, n = pgn_ply_count",
                "runs": total, "complete": total - len(short), "incomplete": len(short),
            }),),
        )

    def _migrate_v15(self) -> None:
        # The top lines of a game's final position (STORE-FINALPLY), so the last move
        # has a stored refutation like every other. Nullable, no backfill: NULL means
        # "analysed before this was stored", which a fresh analysis replaces.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "final_lines_json" not in cols:
            self._conn.execute("ALTER TABLE analysis_runs ADD COLUMN final_lines_json TEXT")

    def _migrate_v16(self) -> None:
        # What produced a run (RUN-PROVENANCE, `core/provenance.py`): binary hash,
        # threads, depth, commit, and whether an opening book was loaded. Nullable, no
        # backfill: NULL means "written before provenance existed", and nothing about
        # an old row's engine or book can be recovered after the fact.
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        if "provenance_json" not in cols:
            self._conn.execute("ALTER TABLE analysis_runs ADD COLUMN provenance_json TEXT")

    def _migrate_v17(self) -> None:
        # Classifier version 3 (CLS-V3-1): `score_after_*` becomes the depth-14 score of
        # the position the move created, and the after-move search it replaces is kept
        # here. Nullable, no backfill: NULL means "labelled before version 3", where
        # `score_after_*` still holds that search (`labelling.search_after`).
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(move_analyses)").fetchall()
        }
        for col in ("after_search_cp", "after_search_mate"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE move_analyses ADD COLUMN {col} INTEGER")

    def _migrate_v18(self) -> None:
        # Owner ruling T8 (2026-11-12, CLS-V3-T8): `hard_only_move`, 0/1, the internal
        # property behind the critical-move miss, kept for the game report. Nullable, no
        # backfill: NULL means "labelled before it existed".
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(move_analyses)").fetchall()
        }
        if "hard_only_move" not in cols:
            self._conn.execute("ALTER TABLE move_analyses ADD COLUMN hard_only_move INTEGER")

    def save_game(
        self,
        *,
        played_at: str,
        player_color: str | None,
        skill_level: int,
        result: str,
        termination: str,
        move_count: int,
        pgn: str,
        final_fen: str,
        opening_eco: str | None = None,
        opening_name: str | None = None,
        source: str = 'local',
        external_id: str | None = None,
        not_owner: bool = False,
    ) -> int:
        """`player_color` None and `not_owner` need the attribution schema
        (`migrate_attribution`). Before it has run, such a game is refused with
        `AttributionPending` rather than stored under a guessed colour — the old
        White default is what W11 was."""
        if (player_color is None or not_owner) and not self.attribution_migrated:
            raise AttributionPending(
                "This game's side cannot be attributed (no configured handle "
                + ("matches either player" if not_owner else "identifies the user")
                + "), and this database has not yet run the attribution migration "
                "that lets a colour be unknown. Set your username in Settings, or run "
                "the migration (FIXPLAN O5)."
            )
        if self.attribution_migrated:
            cur = self._conn.execute(
                """
                INSERT INTO games
                    (played_at, player_color, skill_level, result, termination,
                     move_count, opening_eco, opening_name, pgn, final_fen, source,
                     external_id, speed, rated, ladder_version, not_owner)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    played_at, player_color, skill_level, result, termination,
                    move_count, opening_eco, opening_name, pgn, final_fen, source,
                    external_id, speed_from_pgn(pgn), _rated_int(pgn),
                    C.ENGINE_LADDER_VERSION if source == 'local' else None,
                    int(bool(not_owner)),
                ),
            )
            self._conn.commit()
            logger.info("Game saved id=%s result=%s source=%s", cur.lastrowid, result,
                        source)
            return cur.lastrowid
        cur = self._conn.execute(
            """
            INSERT INTO games
                (played_at, player_color, skill_level, result, termination,
                 move_count, opening_eco, opening_name, pgn, final_fen, source,
                 external_id, speed, rated, ladder_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                played_at, player_color, skill_level, result, termination,
                move_count, opening_eco, opening_name, pgn, final_fen, source,
                external_id, speed_from_pgn(pgn),
                _rated_int(pgn),
                # Derived, not a parameter: only a game played here chose a
                # level, so only it can carry a ladder version. A synced game's
                # skill_level is a placeholder 0 and stamping it would assert
                # something about an opponent the app never configured.
                C.ENGINE_LADDER_VERSION if source == 'local' else None,
            ),
        )
        self._conn.commit()
        logger.info("Game saved id=%s result=%s source=%s", cur.lastrowid, result, source)
        return cur.lastrowid

    # ── Platform sync helpers ───────────────────────────────────────────────────

    def existing_external_ids(self, source: str) -> set[str]:
        """The platform game ids a game from *source* must not duplicate: those stored
        for *source* itself **and those stored by a file import**, which carries the
        same chess.com / Lichess id (FIXPLAN IMPORT-EXTID). chess.com ids are numeric
        and Lichess ids eight characters, so the two never collide."""
        rows = self._conn.execute(
            "SELECT external_id FROM games"
            " WHERE source IN (?, 'imported') AND external_id IS NOT NULL",
            (source,),
        ).fetchall()
        return {r["external_id"] for r in rows}

    def all_external_ids(self) -> set[str]:
        """Every stored platform game id, whatever its source — what a file import
        must not duplicate."""
        rows = self._conn.execute(
            "SELECT external_id FROM games WHERE external_id IS NOT NULL").fetchall()
        return {r["external_id"] for r in rows}

    def games_pending_analysis(
        self, source: str, min_depth: int = 0, *,
        recent: int | None = None, limit: int | None = None,
    ) -> list[GameRecord]:
        """Synced games of *source* still needing analysis at *min_depth* — the
        resume queue, ordered **newest first** (BETA-PUB Q4, owner 2026-11-12: a user's
        first reviews are of their latest games, not years-old ones; it was oldest
        first before).

        *recent* keeps only games among the source's *recent* most recent games
        (analysed or not): sync analyses the 100 most recent automatically and leaves
        the rest for "Analyse more" (`config.SYNC_AUTO_ANALYSE_RECENT`). *limit* caps
        how many are returned — "Analyse more" in a step the user chose.

        A game is pending unless it already has a *satisfying* run — a **complete**
        one (VAL-DEATH: a run cut short by a dead engine used to count as done, so
        nothing ever re-analysed its game) and either a non-Stockfish run (Lichess cloud evals, which store depth 0 but are far
        deeper than any local search and must never be clobbered) or a Stockfish
        run at depth >= ``min_depth``. With ``min_depth=0`` this collapses to the
        old "any run counts" behaviour, so a game analysed at a higher depth is
        skipped when a lower depth is later selected (upgrade-only re-analysis)."""
        params: list = [source, min_depth]
        window = ""
        if recent is not None:
            window = (
                "AND g.id IN (SELECT w.id FROM games w WHERE w.source = ? AND {owned_w}"
                " ORDER BY w.played_at DESC, w.id DESC LIMIT ?)"
            ).replace("{owned_w}", self._not_foreign_sql("w"))
            params += [source, max(0, int(recent))]
        cap = ""
        if limit is not None:
            cap = "LIMIT ?"
            params.append(max(0, int(limit)))
        rows = self._conn.execute(
            """
            SELECT g.id, g.played_at, g.player_color, g.skill_level, g.result,
                   g.termination, g.move_count, g.pgn, g.final_fen,
                   g.opening_eco, g.opening_name, g.source, g.external_id
            FROM games g
            WHERE g.source = ?
              AND {owned}
              AND NOT EXISTS (
                  SELECT 1 FROM analysis_runs r
                  WHERE r.game_id = g.id
                    AND r.completed_at IS NOT NULL
                    AND (r.engine_name != 'Stockfish' OR r.depth >= ?)
              )
              {window}
            ORDER BY g.played_at DESC, g.id DESC
            {cap}
            """.replace("{owned}", self._not_foreign_sql())
               .replace("{window}", window).replace("{cap}", cap),
            params,
        ).fetchall()
        return [GameRecord(**dict(r)) for r in rows]

    # ── Insights aggregation ────────────────────────────────────────────────────

    def _insights_in_clause(self) -> tuple[str, tuple]:
        sources = tuple(C.INSIGHTS_SOURCES)
        placeholders = ",".join("?" for _ in sources)
        return placeholders, sources

    def _insights_where(
        self, flt: "InsightsFilter | None", *, excluded_only: bool = False
    ) -> tuple[str, list]:
        """Build the shared WHERE body for insights queries: source membership
        plus the optional colour / speed filters. The games table must be
        aliased `g`. Returns (sql, params) to splice in after WHERE.

        `excluded_only` flips the source test to select exactly the games the
        screen is leaving out, so the count can be shown rather than implied."""
        sources = tuple(C.INSIGHTS_SOURCES)
        placeholders = ",".join("?" for _ in sources)
        # Not the user's game, or a side that cannot be attributed: never part of
        # an aggregate about the user (FIXPLAN O5). A no-op before the migration.
        clauses: list[str] = [self._owned_sql()]
        params: list = []
        if excluded_only:
            clauses.append(f"g.source NOT IN ({placeholders})")
            params += list(sources)
        elif not (flt and flt.include_local):
            clauses.append(f"g.source IN ({placeholders})")
            params += list(sources)
        if flt:
            if flt.color in ("white", "black"):
                clauses.append("g.player_color = ?")
                params.append(flt.color)
            if flt.speeds:
                clauses.append(f"g.speed IN ({','.join('?' for _ in flt.speeds)})")
                params.extend(flt.speeds)
            if flt.rated == "rated":
                clauses.append("g.rated = 1")
            elif flt.rated == "casual":
                clauses.append("g.rated = 0")
            if flt.since:
                clauses.append("g.played_at >= ?")
                params.append(flt.since)
        # Every source included and no other filter set leaves nothing to test.
        return " AND ".join(clauses) or "1", params

    def insights_overview(self, flt: "InsightsFilter | None" = None) -> dict:
        """Counts for the games this screen is built from, plus `excluded`: the
        games the source rule is leaving out under the same colour/speed/date
        filters. Zero when those games are being included."""
        where, params = self._insights_where(flt)
        total = self._conn.execute(
            f"SELECT COUNT(*) FROM games g WHERE {where}", params
        ).fetchone()[0]
        analyzed = self._conn.execute(
            f"""SELECT COUNT(*) FROM games g
                WHERE {where}
                  AND EXISTS (SELECT 1 FROM analysis_runs r WHERE r.game_id = g.id
                              AND r.completed_at IS NOT NULL)""",
            params,
        ).fetchone()[0]
        ex_where, ex_params = self._insights_where(flt, excluded_only=True)
        excluded = self._conn.execute(
            f"SELECT COUNT(*) FROM games g WHERE {ex_where}", ex_params
        ).fetchone()[0]
        return {
            "total": total,
            "analyzed": analyzed,
            "pending": total - analyzed,
            "excluded": 0 if (flt and flt.include_local) else excluded,
        }

    # Win / draw / loss from the player's POV, as SQL boolean expressions.
    _WIN_SQL = (
        "((g.result='1-0' AND g.player_color='white')"
        " OR (g.result='0-1' AND g.player_color='black'))"
    )
    _LOSS_SQL = (
        "((g.result='0-1' AND g.player_color='white')"
        " OR (g.result='1-0' AND g.player_color='black'))"
    )
    _DRAW_SQL = "(g.result='1/2-1/2')"

    def insights_opening_performance(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(eco, name, games, avg_player_accuracy, win, draw, loss)
        per opening, player-POV, over the player's analysed games."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT g.opening_eco AS eco,
                   g.opening_name AS name,
                   COUNT(*) AS games,
                   AVG(CASE WHEN g.player_color='white'
                            THEN r.white_accuracy ELSE r.black_accuracy END) AS acc,
                   SUM(CASE WHEN {self._WIN_SQL} THEN 1 ELSE 0 END) AS win,
                   SUM(CASE WHEN {self._DRAW_SQL} THEN 1 ELSE 0 END) AS draw,
                   SUM(CASE WHEN {self._LOSS_SQL} THEN 1 ELSE 0 END) AS loss
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            WHERE {where}
              AND g.opening_name IS NOT NULL
              AND (CASE WHEN g.player_color='white'
                        THEN r.white_accuracy ELSE r.black_accuracy END) IS NOT NULL
            GROUP BY g.opening_name
            """,
            params,
        ).fetchall()
        return [
            (r["eco"], r["name"], r["games"], r["acc"], r["win"], r["draw"], r["loss"])
            for r in rows
        ]

    def insights_accuracy_trend(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(game_id, played_at, player_accuracy, opening_name, result, player_color)
        per analysed game, chronological — enough for a rich per-point tooltip."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT g.id AS game_id,
                   g.played_at AS played_at,
                   CASE WHEN g.player_color='white'
                        THEN r.white_accuracy ELSE r.black_accuracy END AS acc,
                   g.opening_name AS opening_name,
                   g.result AS result,
                   g.player_color AS color
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            WHERE {where}
              AND (CASE WHEN g.player_color='white'
                        THEN r.white_accuracy ELSE r.black_accuracy END) IS NOT NULL
            ORDER BY g.played_at ASC
            """,
            params,
        ).fetchall()
        return [
            (r["game_id"], r["played_at"], r["acc"], r["opening_name"], r["result"], r["color"])
            for r in rows
        ]

    def insights_move_scores(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(ply, player_color, score_before_cp, score_before_mate, score_after_cp,
        score_after_mate) for the player's own moves — for the accuracy-by-move-
        number curve. Scores are mover-POV, as stored."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT m.ply AS ply,
                   g.player_color AS color,
                   m.score_before_cp AS sb_cp,
                   m.score_before_mate AS sb_mate,
                   m.score_after_cp AS sa_cp,
                   m.score_after_mate AS sa_mate
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            JOIN move_analyses m ON m.run_id = r.id
            WHERE {where}
              AND ((g.player_color='white' AND m.ply % 2 = 0)
                OR (g.player_color='black' AND m.ply % 2 = 1))
            """,
            params,
        ).fetchall()
        return [
            (r["ply"], r["color"], r["sb_cp"], r["sb_mate"], r["sa_cp"], r["sa_mate"])
            for r in rows
        ]

    def insights_castling_rows(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(pgn, player_color, result) for analysed games — used to detect the
        player's castling choice by replaying moves, and tie it to the outcome."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT g.pgn AS pgn, g.player_color AS color, g.result AS result
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            WHERE {where}
            """,
            params,
        ).fetchall()
        return [(r["pgn"], r["color"], r["result"]) for r in rows]

    def insights_move_quality(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(player_color, classification, count) for the player's own moves,
        split by the colour the player was. The player's plies are the even
        plies when they were White, odd plies when Black."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT g.player_color AS color,
                   m.classification AS cls,
                   COUNT(*) AS n
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            JOIN move_analyses m ON m.run_id = r.id
            WHERE {where}
              AND ((g.player_color='white' AND m.ply % 2 = 0)
                OR (g.player_color='black' AND m.ply % 2 = 1))
            GROUP BY g.player_color, m.classification
            """,
            params,
        ).fetchall()
        return [(r["color"], r["cls"], r["n"]) for r in rows]

    def insights_game_details(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(played_at, player_color, result, termination, accuracy) per game.
        LEFT JOIN so unanalysed games still count for W/D/L and terminations;
        accuracy is None for those."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT g.played_at AS played_at,
                   g.player_color AS color,
                   g.result AS result,
                   g.termination AS termination,
                   CASE WHEN g.player_color='white'
                        THEN r.white_accuracy ELSE r.black_accuracy END AS acc
            FROM games g
            LEFT JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            WHERE {where}
            """,
            params,
        ).fetchall()
        return [
            (r["played_at"], r["color"], r["result"], r["termination"], r["acc"])
            for r in rows
        ]

    def insights_phase_quality(self, flt: "InsightsFilter | None" = None) -> list[tuple]:
        """(run_id, ply, classification, fen_before, player_color), every ply.

        Not filtered to the player's own moves: the shaper divides each game into
        phases with Lichess's Divider, which reads the whole board sequence, so
        the opponent's positions are needed even though only the player's moves
        are counted."""
        where, params = self._insights_where(flt)
        rows = self._conn.execute(
            f"""
            SELECT r.id AS run, m.ply AS ply, m.classification AS cls,
                   m.fen_before AS fen, g.player_color AS color
            FROM games g
            JOIN analysis_runs r ON r.game_id = g.id AND r.completed_at IS NOT NULL
            JOIN move_analyses m ON m.run_id = r.id
            WHERE {where}
            ORDER BY r.id, m.ply
            """,
            params,
        ).fetchall()
        return [(r["run"], r["ply"], r["cls"], r["fen"], r["color"]) for r in rows]

    def list_games(self, limit: int | None = None) -> list[GameRecord]:
        sql = """
            SELECT id, played_at, player_color, skill_level, result, termination,
                   move_count, pgn, final_fen, opening_eco, opening_name, source,
                   speed, ladder_version
            FROM games
            ORDER BY played_at DESC
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        return [GameRecord(**dict(r)) for r in rows]

    def list_games_with_runs(
        self, limit: int | None = None
    ) -> list[tuple[GameRecord, RunSummary | None]]:
        """`list_games`, plus whether each game has a run and what it scored.

        Exists because calling `load_latest_run` per game was 1 859 unindexed
        scans of `analysis_runs` — 26 ms, growing with the library, and it only
        ever used three of the eight columns it loaded. The correlated subquery is
        a deliberate literal transcription of `load_latest_run`'s
        `ORDER BY id DESC LIMIT 1`, so the two cannot disagree about which run is
        latest; it is also the form a `LIMIT` still applies to.

        `None` means no run. A run with `None` accuracies is a different thing —
        analysed before v4 added the columns — which is why this returns a summary
        object rather than a bare pair of floats.

        The form depends on `idx_analysis_runs_game`: unindexed, the subquery is
        1 859 table scans and no faster than the loop it replaces. That is safe here
        only because this is never called on a read-only handle, which cannot create
        the index — if it ever is, switch to a materialised `GROUP BY game_id`, which
        measured the same 1.8 ms with or without it.
        """
        sql = """
            SELECT g.id, g.played_at, g.player_color, g.skill_level, g.result,
                   g.termination, g.move_count, g.pgn, g.final_fen,
                   g.opening_eco, g.opening_name, g.source, g.speed,
                   g.ladder_version, g.external_id,
                   r.id AS run_id, r.white_accuracy, r.black_accuracy
            FROM games g
            LEFT JOIN analysis_runs r ON r.id = (
                SELECT id FROM analysis_runs
                WHERE game_id = g.id AND completed_at IS NOT NULL
                ORDER BY id DESC LIMIT 1
            )
            ORDER BY g.played_at DESC
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        out: list[tuple[GameRecord, RunSummary | None]] = []
        for r in self._conn.execute(sql, params):
            d = dict(r)
            run_id = d.pop("run_id")
            wa, ba = d.pop("white_accuracy"), d.pop("black_accuracy")
            out.append((
                GameRecord(**d),
                None if run_id is None else RunSummary(run_id, wa, ba),
            ))
        return out

    def get_game(self, game_id: int) -> GameRecord | None:
        row = self._conn.execute(
            "SELECT * FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        return GameRecord(**dict(row)) if row else None

    def update_game_opening(
        self, game_id: int, eco: str, name: str
    ) -> None:
        self._conn.execute(
            "UPDATE games SET opening_eco=?, opening_name=? WHERE id=? AND opening_eco IS NULL",
            (eco, name, game_id),
        )
        self._conn.commit()

    def repair_player_colors(self, usernames: list[str]) -> int:
        """Re-detect player_color from each stored PGN's headers using the
        player's known username(s) and correct any mismatches. Only games whose
        PGN carries real platform handles are touched (imported / lichess /
        chesscom); local games vs Stockfish use 'You' headers and are left
        alone. Returns the number of rows changed.

        A game neither of whose players is in *usernames* is left as it is. The
        settings hold one handle per platform, so a game from another of the
        user's accounts matches nothing; resetting it to the import default
        ('white') is what put 826 games on the wrong side (W11), and every sync
        re-ran it."""
        # Imported locally to avoid a module-level cycle (import_pgn is Qt-free).
        import io as _io

        import chess.pgn as _pgn

        from .import_pgn import attribute

        wanted = [u for u in usernames if u and u.strip()]
        if not wanted:
            return 0
        migrated = self.attribution_migrated

        ph, _params = self._insights_in_clause()
        rows = self._conn.execute(
            f"SELECT id, pgn, player_color FROM games WHERE source IN ({ph})",
            tuple(C.INSIGHTS_SOURCES),
        ).fetchall()

        changed = 0
        for r in rows:
            headers = _pgn.read_headers(_io.StringIO(r["pgn"]))
            if headers is None:
                continue
            side = attribute(headers, wanted)
            if side.color is not None and side.color != r["player_color"]:
                # Former handles count (handles.former_handles), so a pre-rename
                # game is the user's and gets the side the old name played.
                self._conn.execute(
                    "UPDATE games SET player_color=? WHERE id=?", (side.color, r["id"])
                )
                changed += 1
            elif side.not_owner and migrated:
                # Not the user's game: marked, and its colour cleared rather than
                # left as a guess. Without the migration a game stays as it is.
                cur = self._conn.execute(
                    "UPDATE games SET not_owner=1, player_color=NULL"
                    " WHERE id=? AND (not_owner=0 OR player_color IS NOT NULL)", (r["id"],))
                changed += cur.rowcount
        if changed:
            self._conn.commit()
        logger.info("repair_player_colors: corrected %d games", changed)
        return changed

    def delete_game(self, game_id: int) -> int:
        """Delete one game and, by `ON DELETE CASCADE`, its runs and plies. Returns
        the number of games deleted (0 or 1)."""
        cur = self._conn.execute("DELETE FROM games WHERE id=?", (game_id,))
        self._conn.commit()
        return cur.rowcount

    # ── Attribution (FIXPLAN O5) ────────────────────────────────────────────────

    @property
    def attribution_migrated(self) -> bool:
        """Whether `migrate_attribution` has run: `player_color` nullable and
        `games.not_owner` present. Probed, not cached, so it is right immediately
        after the migration on this connection."""
        cols = {r[1]: r for r in self._conn.execute("PRAGMA table_info(games)")}
        return "not_owner" in cols and not cols["player_color"][3]

    def _not_foreign_sql(self, alias: str = "g") -> str:
        """A WHERE term excluding games marked not the user's; `1` before the migration."""
        return f"{alias}.not_owner = 0" if self.attribution_migrated else "1"

    def _owned_sql(self, alias: str = "g") -> str:
        """A WHERE term keeping only the user's games with a known side — what every
        aggregate about the user reads. `1` before the migration."""
        if not self.attribution_migrated:
            return "1"
        return f"({alias}.not_owner = 0 AND {alias}.player_color IS NOT NULL)"

    def migrate_attribution(self) -> bool:
        """Let `player_color` be NULL (unknown) and add `games.not_owner`.

        **Deliberately not in `_apply_schema`.** Every other migration runs on every
        open; this one rebuilds the `games` table, and the owner ruled that it does
        not run unattended (2026-10-22). It runs when called — by the owner, with a
        backup taken first. Idempotent: returns False if already applied.

        SQLite cannot drop NOT NULL in place, so the table is rebuilt (as v11 was for
        `best_uci`): create, copy every row and column, drop, rename. Foreign keys
        from `analysis_runs` name `games` and follow the rename; `foreign_key_check`
        must come back empty, or the transaction is rolled back.
        """
        if self.attribution_migrated:
            return False
        before = self._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        self._conn.commit()
        self._conn.execute("PRAGMA foreign_keys=off")
        try:
            self._conn.executescript("""
                BEGIN;
                CREATE TABLE games_new (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    played_at      TEXT    NOT NULL,
                    player_color   TEXT,
                    skill_level    INTEGER NOT NULL,
                    result         TEXT    NOT NULL,
                    termination    TEXT    NOT NULL,
                    move_count     INTEGER NOT NULL,
                    opening_eco    TEXT,
                    opening_name   TEXT,
                    pgn            TEXT    NOT NULL,
                    final_fen      TEXT    NOT NULL,
                    source         TEXT    NOT NULL DEFAULT 'local',
                    external_id    TEXT,
                    speed          TEXT,
                    rated          INTEGER,
                    ladder_version INTEGER,
                    not_owner      INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO games_new
                    (id, played_at, player_color, skill_level, result, termination,
                     move_count, opening_eco, opening_name, pgn, final_fen, source,
                     external_id, speed, rated, ladder_version)
                SELECT id, played_at, player_color, skill_level, result, termination,
                       move_count, opening_eco, opening_name, pgn, final_fen, source,
                       external_id, speed, rated, ladder_version
                FROM games;
                DROP TABLE games;
                ALTER TABLE games_new RENAME TO games;
                CREATE INDEX IF NOT EXISTS idx_games_played_at ON games(played_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_games_external
                    ON games(source, external_id) WHERE external_id IS NOT NULL;
            """)
            bad = self._conn.execute("PRAGMA foreign_key_check").fetchall()
            after = self._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            if bad or after != before:
                self._conn.execute("ROLLBACK")
                raise RuntimeError(f"attribution migration rolled back: {len(bad)} "
                                   f"foreign-key violations, {before} -> {after} games")
            self._conn.execute("COMMIT")
        finally:
            self._conn.execute("PRAGMA foreign_keys=on")
        logger.info("attribution migration applied: %d games", before)
        return True

    def save_analysis_run(
        self,
        *,
        game_id: int,
        engine_name: str,
        depth: int,
        summary_json: str = "{}",
        provenance: dict | None = None,
    ) -> int:
        # Clear abandoned attempts only. The game's complete run stays until this one
        # completes (`complete_analysis_run` replaces it then): deleting it here, as
        # this used to, meant a Re-analyse that lost its engine destroyed the good run
        # it was meant to improve. FK cascade removes the plies.
        self._conn.execute(
            "DELETE FROM analysis_runs WHERE game_id = ? AND completed_at IS NULL",
            (game_id,),
        )
        cur = self._conn.execute(
            """
            INSERT INTO analysis_runs
                (game_id, engine_name, depth, created_at, payload_json, provenance_json,
                 classifier_version)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                game_id,
                engine_name,
                depth,
                datetime.now(timezone.utc).isoformat(),
                summary_json,
                json.dumps(provenance) if provenance is not None else None,
                # Every run's plies are labelled by today's `classify()` (W22).
                CLASSIFIER_VERSION,
            ),
        )
        self._conn.commit()
        logger.info("Analysis run saved id=%s game_id=%s", cur.lastrowid, game_id)
        return cur.lastrowid

    def save_move_analysis(self, run_id: int, ma: MoveAnalysis) -> None:
        self._insert_move_analysis(run_id, ma)
        self._conn.commit()

    def _insert_move_analysis(self, run_id: int, ma: MoveAnalysis) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO move_analyses
                (run_id, ply, fen_before, played_uci, best_uci, pv_uci,
                 score_before_cp, score_before_mate, score_after_cp, score_after_mate,
                 second_best_uci, second_best_cp, second_best_mate,
                 classification, is_book, lines_json, after_search_cp, after_search_mate,
                 hard_only_move)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id, ma.ply, ma.fen_before, ma.played_uci, ma.best_uci, ma.pv_uci,
                ma.score_before_cp, ma.score_before_mate,
                ma.score_after_cp, ma.score_after_mate,
                ma.second_best_uci, ma.second_best_cp, ma.second_best_mate,
                ma.classification, int(ma.is_book),
                json.dumps(ma.lines) if ma.lines else None,
                ma.after_search_cp, ma.after_search_mate,
                None if ma.hard_only_move is None else int(ma.hard_only_move),
            ),
        )

    def complete_analysis_run(
        self,
        run_id: int,
        summary: dict,
        *,
        white_accuracy: float | None = None,
        black_accuracy: float | None = None,
        plies: list[MoveAnalysis] = (),
        final_lines: list[dict] | None = None,
    ) -> None:
        """Make *run_id* the game's analysis, in one transaction: write *plies* (any not
        streamed already), check the run now holds every ply of its game, write the
        summary and `completed_at`, and delete the game's other runs.

        Raises `IncompleteRun`, writing nothing, if a ply is missing — the guard on
        the class of defect VAL-DEATH found, where 15 runs a dead engine cut short were
        summarised as if complete."""
        try:
            for ma in plies:
                self._insert_move_analysis(run_id, ma)
            game_id, pgn = self._conn.execute(
                "SELECT g.id, g.pgn FROM analysis_runs r JOIN games g ON g.id = r.game_id"
                " WHERE r.id = ?", (run_id,)).fetchone()
            n = pgn_ply_count(pgn)
            stored, lo, hi = self._conn.execute(
                "SELECT COUNT(*), MIN(ply), MAX(ply) FROM move_analyses WHERE run_id = ?",
                (run_id,)).fetchone()
            if not _exact_plies(stored, lo, hi, n):
                raise IncompleteRun(
                    f"run {run_id} holds {stored} of its game's {n} plies; not completing it")
            self._conn.execute(
                """UPDATE analysis_runs
                   SET payload_json=?, white_accuracy=?, black_accuracy=?, completed_at=?,
                       final_lines_json=?
                   WHERE id=?""",
                (json.dumps(summary), white_accuracy, black_accuracy,
                 datetime.now(timezone.utc).isoformat(),
                 json.dumps(final_lines) if final_lines else None, run_id),
            )
            self._conn.execute(
                "DELETE FROM analysis_runs WHERE game_id = ? AND id != ?", (game_id, run_id))
        except BaseException:
            self._conn.rollback()
            raise
        self._conn.commit()

    def audit_run_completeness(self) -> list[RunAudit]:
        """Every run whose stored plies are not exactly its game's plies — complete or
        not. A row with `completed=True` is a defect (a partial run counted as done);
        rows with `completed=False` are abandoned or engine-killed attempts, which the
        readers already ignore. Part of the re-pull's cutover check (FIXPLAN REPULL).

        Measured against the PGN (`pgn_ply_count`), not `games.move_count`. Reads every
        game's PGN once: 1.7 s on the 3 261-game library."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(analysis_runs)")}
        done = "r.completed_at IS NOT NULL" if "completed_at" in cols else "0"
        rows = self._conn.execute(f"""
            SELECT r.id, g.id, g.source, g.external_id, r.engine_name, r.depth, g.pgn,
                   {done}, COUNT(m.id), MIN(m.ply), MAX(m.ply)
            FROM analysis_runs r JOIN games g ON g.id = r.game_id
            LEFT JOIN move_analyses m ON m.run_id = r.id
            GROUP BY r.id ORDER BY r.id""").fetchall()
        plies: dict[int, int] = {}
        out: list[RunAudit] = []
        for run_id, game_id, source, ext, engine, depth, pgn, completed, stored, lo, hi in rows:
            if game_id not in plies:
                plies[game_id] = pgn_ply_count(pgn)
            n = plies[game_id]
            if not _exact_plies(stored, lo, hi, n):
                out.append(RunAudit(run_id, game_id, source, ext, engine, depth,
                                    stored, n, bool(completed)))
        return out

    def record_engine_failure(self, *, context: str, fen: str, message: str,
                              source: str | None = None, external_id: str | None = None,
                              game_id: int | None = None, ply: int | None = None,
                              exit_code: int | None = None,
                              engine: str | None = None) -> None:
        self._conn.execute(
            """INSERT INTO engine_failures
               (occurred_at, context, source, external_id, game_id, ply, fen, exit_code,
                engine, message)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (datetime.now(timezone.utc).isoformat(), context, source, external_id,
             game_id, ply, fen, exit_code, engine, message),
        )
        self._conn.commit()

    def discard_analysis_run(self, run_id: int) -> None:
        """Drop a run that will never complete (its plies go with it)."""
        self._conn.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))
        self._conn.commit()

    def needs_attention_ids(self, source: str, engine: str | None) -> set[int]:
        """Games of *source* that have poisoned *engine* (a version string such as
        'Stockfish 18') on `ENGINE_POISON_MAX_ATTEMPTS` or more runs and still have no
        complete analysis (VAL-DEATH-2). Keyed by platform id, which survives a re-pull.
        No engine version, no answer: a count across binaries would keep a game stuck
        after the binary that crashed on it is gone."""
        if engine is None:
            return set()
        rows = self._conn.execute(
            """
            SELECT g.id FROM games g
            JOIN engine_failures f ON f.source = g.source AND f.external_id = g.external_id
            WHERE g.source = ? AND f.engine = ?
              AND NOT EXISTS (SELECT 1 FROM analysis_runs r
                              WHERE r.game_id = g.id AND r.completed_at IS NOT NULL)
            GROUP BY g.id HAVING COUNT(*) >= ?
            """, (source, engine, C.ENGINE_POISON_MAX_ATTEMPTS)).fetchall()
        return {r[0] for r in rows}

    def update_analysis_summary(
        self,
        run_id: int,
        summary: dict,
        *,
        white_accuracy: float | None = None,
        black_accuracy: float | None = None,
    ) -> None:
        self._conn.execute(
            """UPDATE analysis_runs
               SET payload_json=?, white_accuracy=?, black_accuracy=?
               WHERE id=?""",
            (json.dumps(summary), white_accuracy, black_accuracy, run_id),
        )
        self._conn.commit()

    def load_latest_run(self, game_id: int) -> AnalysisRun | None:
        """The game's latest *complete* run; an incomplete one is never shown."""
        row = self._conn.execute(
            """
            SELECT id, game_id, engine_name, depth, created_at, payload_json,
                   white_accuracy, black_accuracy, final_lines_json
            FROM analysis_runs WHERE game_id=? AND completed_at IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (game_id,),
        ).fetchone()
        return AnalysisRun(**dict(row)) if row else None

    def load_move_analyses(self, run_id: int) -> list[MoveAnalysis]:
        rows = self._conn.execute(
            """
            SELECT ply, fen_before, played_uci, best_uci, pv_uci,
                   score_before_cp, score_before_mate, score_after_cp, score_after_mate,
                   second_best_uci, second_best_cp, second_best_mate,
                   classification, is_book, lines_json, after_search_cp, after_search_mate,
                   hard_only_move
            FROM move_analyses WHERE run_id=? ORDER BY ply
            """,
            (run_id,),
        ).fetchall()
        return [
            MoveAnalysis(
                ply=r["ply"],
                fen_before=r["fen_before"],
                played_uci=r["played_uci"],
                # `''` is how "no best move" was stored before the column could
                # hold NULL. Normalised here rather than backfilled so the rows
                # keep whatever they were actually written with.
                best_uci=r["best_uci"] or None,
                pv_uci=r["pv_uci"],
                score_before_cp=r["score_before_cp"],
                score_before_mate=r["score_before_mate"],
                score_after_cp=r["score_after_cp"],
                score_after_mate=r["score_after_mate"],
                second_best_uci=r["second_best_uci"],
                second_best_cp=r["second_best_cp"],
                second_best_mate=r["second_best_mate"],
                classification=r["classification"],
                is_book=bool(r["is_book"]),
                lines=json.loads(r["lines_json"]) if r["lines_json"] else [],
                after_search_cp=r["after_search_cp"],
                after_search_mate=r["after_search_mate"],
                hard_only_move=(None if r["hard_only_move"] is None
                                else bool(r["hard_only_move"])),
            )
            for r in rows
        ]

    # ── Puzzle helpers ────────────────────────────────────────────────────────

    def puzzles_imported(self) -> bool:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'puzzles_imported'"
        ).fetchone()
        return row is not None and row["value"] == "1"

    def mark_puzzles_imported(self, count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for key, val in [
            ("puzzles_imported", "1"),
            ("puzzles_imported_at", now),
            ("puzzles_count", str(count)),
        ]:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, val)
            )
        self._conn.commit()

    def get_puzzle_rating(self) -> tuple[float, float, float]:
        """Returns (rating, rd, volatility). Inserts default row on first call."""
        row = self._conn.execute(
            "SELECT rating, rd, volatility FROM puzzle_rating WHERE id = 1"
        ).fetchone()
        if row is None:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT OR IGNORE INTO puzzle_rating"
                " (id, rating, rd, volatility, updated_at) VALUES (1,?,?,?,?)",
                (C.PUZZLE_RATING_DEFAULT, C.PUZZLE_RD_DEFAULT,
                 C.PUZZLE_VOLATILITY_DEFAULT, now),
            )
            self._conn.commit()
            return (C.PUZZLE_RATING_DEFAULT, C.PUZZLE_RD_DEFAULT,
                    C.PUZZLE_VOLATILITY_DEFAULT)
        return float(row["rating"]), float(row["rd"]), float(row["volatility"])

    def save_puzzle_rating(self, rating: float, rd: float, volatility: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO puzzle_rating"
            " (id, rating, rd, volatility, updated_at) VALUES (1,?,?,?,?)",
            (rating, rd, volatility, now),
        )
        self._conn.commit()

    def count_puzzles_for_themes(
        self,
        themes: list[str],
        user_rating: float,
        rating_range: int,
    ) -> int:
        lo = int(user_rating - rating_range)
        hi = int(user_rating + rating_range)
        match_str = " ".join(f'"{t}"' for t in themes)
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM puzzles p
            INNER JOIN puzzle_themes_fts ON p.rowid = puzzle_themes_fts.rowid
            WHERE puzzle_themes_fts MATCH ?
              AND p.rating BETWEEN ? AND ?
            """,
            (match_str, lo, hi),
        ).fetchone()
        return row[0] if row else 0

    def select_puzzles(
        self,
        *,
        user_rating: float,
        rating_range: int,
        themes: list[str] | None = None,
        exclude_recent: int = 200,
        limit: int = 10,
    ) -> list[PuzzleRecord]:
        lo = int(user_rating - rating_range)
        hi = int(user_rating + rating_range)
        if themes:
            match_str = " ".join(f'"{t}"' for t in themes)
            rows = self._conn.execute(
                """
                SELECT p.id, p.fen, p.moves_uci, p.rating, p.rating_deviation, p.themes
                FROM puzzles p
                INNER JOIN puzzle_themes_fts ON p.rowid = puzzle_themes_fts.rowid
                WHERE puzzle_themes_fts MATCH ?
                  AND p.rating BETWEEN ? AND ?
                  AND p.id NOT IN (
                      SELECT puzzle_id FROM puzzle_attempts
                      ORDER BY attempted_at DESC LIMIT ?
                  )
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (match_str, lo, hi, exclude_recent, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, fen, moves_uci, rating, rating_deviation, themes
                FROM puzzles
                WHERE rating BETWEEN ? AND ?
                  AND id NOT IN (
                      SELECT puzzle_id FROM puzzle_attempts
                      ORDER BY attempted_at DESC LIMIT ?
                  )
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (lo, hi, exclude_recent, limit),
            ).fetchall()
        return [
            PuzzleRecord(
                id=r["id"],
                fen=r["fen"],
                moves_uci=r["moves_uci"].split(),
                rating=r["rating"],
                rating_deviation=r["rating_deviation"],
                themes=r["themes"],
            )
            for r in rows
        ]

    def save_puzzle_attempt(
        self,
        *,
        puzzle_id: str,
        session_id: int | None,
        mode: str,
        solved: bool,
        failed: bool,
        used_hint: bool,
        gave_up: bool,
        solve_time_s: float | None,
        rating_before: float | None,
        rating_after: float | None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO puzzle_attempts
                (puzzle_id, session_id, mode, attempted_at, solved, failed,
                 used_hint, gave_up, solve_time_s, rating_before, rating_after)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                puzzle_id, session_id, mode,
                datetime.now(timezone.utc).isoformat(),
                int(solved), int(failed), int(used_hint), int(gave_up),
                solve_time_s, rating_before, rating_after,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def save_puzzle_session(self, *, mode: str, time_limit_s: int | None) -> int:
        cur = self._conn.execute(
            "INSERT INTO puzzle_sessions (mode, started_at, time_limit_s) VALUES (?,?,?)",
            (mode, datetime.now(timezone.utc).isoformat(), time_limit_s),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_puzzle_session(
        self, session_id: int, *, score: int, peak_rating: int | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE puzzle_sessions SET ended_at=?, score=?, peak_rating=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), score, peak_rating, session_id),
        )
        self._conn.commit()

    def get_leaderboard(
        self, mode: str, time_limit_s: int | None, limit: int = 10
    ) -> tuple[list[tuple[int, str]], int]:
        """Return (entries, new_rank) for the given board.

        entries: [(score, formatted_date), …] sorted by score DESC.
        new_rank: 0-indexed position of the most-recently-ended session in that
                  list, or -1 if it didn't make the top-N.
        """
        if time_limit_s is None:
            where  = "mode=? AND time_limit_s IS NULL"
            params = (mode,)
        else:
            where  = "mode=? AND time_limit_s=?"
            params = (mode, time_limit_s)

        recent = self._conn.execute(
            f"SELECT id FROM puzzle_sessions WHERE {where} AND ended_at IS NOT NULL"
            " ORDER BY ended_at DESC LIMIT 1",
            params,
        ).fetchone()
        recent_id = recent["id"] if recent else None

        rows = self._conn.execute(
            f"""SELECT id, score, started_at FROM puzzle_sessions
                WHERE {where} AND ended_at IS NOT NULL
                ORDER BY score DESC, started_at ASC LIMIT ?""",
            params + (limit,),
        ).fetchall()

        entries: list[tuple[int, str]] = []
        new_rank = -1
        for i, r in enumerate(rows):
            try:
                dt = datetime.fromisoformat(r["started_at"])
                date_str = dt.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                date_str = str(r["started_at"])[:10]
            entries.append((r["score"], date_str))
            if r["id"] == recent_id:
                new_rank = i

        return entries, new_rank

    # ── Opening Trainer ───────────────────────────────────────────────────────

    def coverage_indexed(self) -> bool:
        """True if the opening_book_coverage table has been populated."""
        row = self._conn.execute(
            "SELECT 1 FROM opening_book_coverage LIMIT 1"
        ).fetchone()
        return row is not None

    def save_coverage_batch(self, rows: list[tuple[str, str, str, int]]) -> None:
        """Persist coverage rows: [(eco, name, color, has_moves), ...]."""
        self._conn.executemany(
            "INSERT OR REPLACE INTO opening_book_coverage"
            " (eco, name, color, has_moves) VALUES (?,?,?,?)",
            rows,
        )
        self._conn.commit()

    def get_coverage(self, eco: str, name: str, color: str) -> bool:
        """Return True if the book has moves for this opening/color."""
        row = self._conn.execute(
            "SELECT has_moves FROM opening_book_coverage"
            " WHERE eco=? AND name=? AND color=?",
            (eco, name, color),
        ).fetchone()
        return bool(row["has_moves"]) if row is not None else True

    def record_trainer_attempt(self, eco: str, name: str, color: str) -> None:
        """Increment the attempt counter for this opening/color.
        Called on the first accepted move of a session (not on controller start).
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO opening_trainer_progress (eco, name, color, attempts, last_trained_at)
            VALUES (?,?,?,1,?)
            ON CONFLICT(eco, name, color) DO UPDATE SET
                attempts        = attempts + 1,
                last_trained_at = excluded.last_trained_at
            """,
            (eco, name, color, now),
        )
        self._conn.commit()

    def save_trainer_completion(
        self,
        *,
        eco: str,
        name: str,
        color: str,
        mode: str,
        terminal_zobrist_hex: str,
        moves_played: int,
        errors_made: int,
        accuracy: float | None,
    ) -> None:
        """Record an end-of-book completion and refresh distinct_lines cache."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO opening_trainer_completions
                (eco, name, color, mode, terminal_zobrist_hex,
                 completed_at, moves_played, errors_made)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (eco, name, color, mode, terminal_zobrist_hex, now, moves_played, errors_made),
        )
        distinct = self._conn.execute(
            "SELECT COUNT(DISTINCT terminal_zobrist_hex)"
            " FROM opening_trainer_completions WHERE eco=? AND name=? AND color=?",
            (eco, name, color),
        ).fetchone()[0]
        self._conn.execute(
            """
            INSERT INTO opening_trainer_progress
                (eco, name, color, attempts, completions, distinct_lines,
                 last_trained_at, best_accuracy)
            VALUES (?,?,?,1,1,?,?,?)
            ON CONFLICT(eco, name, color) DO UPDATE SET
                completions    = completions + 1,
                distinct_lines = excluded.distinct_lines,
                last_trained_at = excluded.last_trained_at,
                best_accuracy  = CASE
                    WHEN excluded.best_accuracy IS NOT NULL
                         AND (best_accuracy IS NULL
                              OR excluded.best_accuracy > best_accuracy)
                    THEN excluded.best_accuracy
                    ELSE best_accuracy
                END
            """,
            (eco, name, color, distinct, now, accuracy),
        )
        self._conn.commit()

    def get_trainer_progress(
        self, eco: str, name: str, color: str
    ) -> dict | None:
        row = self._conn.execute(
            """
            SELECT attempts, completions, distinct_lines, last_trained_at, best_accuracy
            FROM opening_trainer_progress WHERE eco=? AND name=? AND color=?
            """,
            (eco, name, color),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_all_trainer_progress(self) -> dict[tuple[str, str, str], dict]:
        """Return all trainer progress rows keyed by (eco, name, color)."""
        rows = self._conn.execute(
            "SELECT eco, name, color, attempts, completions, distinct_lines,"
            " last_trained_at, best_accuracy FROM opening_trainer_progress"
        ).fetchall()
        return {(r["eco"], r["name"], r["color"]): dict(r) for r in rows}

    def get_family_drilled_count(self, eco_lo: str, eco_hi: str) -> int:
        """Number of distinct (eco, name) pairs in the ECO range with ≥1 completion."""
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT eco || '|' || name) FROM opening_trainer_progress"
            " WHERE eco >= ? AND eco <= ? AND completions >= 1",
            (eco_lo, eco_hi),
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()


def _exact_plies(stored: int, lo: int | None, hi: int | None, n: int) -> bool:
    """`UNIQUE(run_id, ply)` makes count + range exact: n rows spanning 0..n-1."""
    return stored == n and (n == 0 or (lo == 0 and hi == n - 1))
