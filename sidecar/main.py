#!/usr/bin/env python3
"""
Zugzwang sidecar — exposes the existing Python core to the Tauri frontend.

Protocol: newline-delimited JSON over stdio (stdout = protocol, stderr = logs).

  Request   →  {"id": 1, "method": "new_game", "params": {...}}
  Response  ←  {"id": 1, "result": {...}}            (or {"id": 1, "error": {"message": ...}})
  Event     ←  {"event": "engine_move", "data": {...}}   (pushed, no id)

Threading mirrors the PyQt app's model:
  • app thread  — owns GameSession and the sqlite connection (the Qt "main
    thread" role); processes one inbox item at a time, so all state mutation
    and DB writes are serialized.
  • stdin thread — parses requests and enqueues them (never blocks on work).
  • engine thread — runs Stockfish searches; results re-enter the app thread
    through the inbox, like a queued signal. A generation counter discards
    stale results the same way StockfishWorker._skip does.
"""

from __future__ import annotations

import io
import json
import re
import logging
import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import chess
import chess.engine
import chess.pgn

import zugzwang.config as C
from zugzwang.config import (DB_PATH, DRAW_FAVOUR_CP, DRAW_FROM_MOVE, ENGINE_MOVE_TIME_MS, SKILL_DEFAULT,
                             skill_to_elo)
from zugzwang.core.analysis import (
    analyze_game_from_evals,
    analyze_game_plies,
    analyze_position,
    analyze_position_multipv,
    configure_engine_for_analysis,
    eval_coverage,
)
from zugzwang.core.database import (
    standard_run_sql,
    AttributionPending,
    Database,
    GameRecord,
    IncompleteRun,
    MoveAnalysis,
    rated_from_pgn,
)
from zugzwang.core.engine_locator import (
    find_stockfish, persist_path, popen_engine, stockfish_source,
)
from zugzwang.core.engine_supervisor import (
    ENGINE_GONE,
    DeathBreaker,
    SupervisedEngine,
    bury,
    is_engine_death,
)
from zugzwang.core.explain import RULE_VERSION, stored_ply_row
from zugzwang.core.compose import explain_ply_full
from zugzwang.core.explain_text import UNKNOWN_SIDE
from zugzwang.core import provenance
from zugzwang.core.positions import legal_board
from zugzwang.core.game_report import build_report, opening_exit, opening_sentence
from zugzwang.core import review_extras as RX
from zugzwang.core import home_summary as HS
from zugzwang.core import games_list as GL
from zugzwang.core import puzzle_summary as PS
from zugzwang.core.classification import PlyScore
from zugzwang.core.retry import judge as judge_try
from zugzwang.core.game import GameEnd, GameSession
from zugzwang.core.import_pgn import parse_pgn_report
from zugzwang.core.insights import build_insights
from zugzwang.core.patterns import FACTS_VERSION, facts_row, write_facts_for_run
from zugzwang.core import coach as coach_core
from zugzwang.core import practice as practice_core
from zugzwang.core.themes import THEMES_VERSION
from zugzwang.core.platform_sync import (
    SyncError,
    check_usernames,
    fetch_chesscom_games,
    fetch_lichess_games,
)
from zugzwang.core.openings import OpeningsBook
from zugzwang.core.friends.client import FriendsError
from zugzwang.core.friends.runner import FriendsRunner, linked_players, list_payload, profile_payload
from zugzwang.core.puzzle_core import (
    PuzzleFileError,
    alternate_final_mates,
    download_lichess_puzzles,
    glicko2_update,
    import_puzzles_file,
    lichess_file_info,
)
from zugzwang.core.trainer import (
    accepted_book_moves,
    has_coverage,
    parse_pgn_moves,
    top_book_reply,
    uniform_random_reply,
    weighted_random_reply,
)

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[sidecar] %(message)s")
logger = logging.getLogger(__name__)

#: Rotated at 1 MB, three old files kept: a month of ordinary use is well under that.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3


def _log_path() -> Path:
    """`logs/sidecar.log` beside the database in use, so a test's temp DB logs to its
    own temp directory, not the user's."""
    return Path(os.environ.get("ZUGZWANG_DB", DB_PATH)).parent / "logs" / "sidecar.log"


def _setup_file_logging() -> Path | None:
    """W21: stderr reaches only the webview's `console.debug` (`sidecar.ts`), and the
    Tauri log file stayed 0 bytes while the sidecar reported a missing book. So the
    sidecar keeps its own log file, timestamped, for every build. Uncaught exceptions,
    on the main thread or a worker, go to it too. A log that cannot be opened is
    reported on stderr and is not fatal."""
    from logging.handlers import RotatingFileHandler
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUPS, encoding="utf-8")
    except OSError as exc:
        logger.warning("cannot open the log file %s: %s", path, exc)
        return None
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.getEffectiveLevel() > logging.INFO:     # basicConfig is a no-op if the root
        root.setLevel(logging.INFO)                 # already has a handler
    logging.captureWarnings(True)

    def log_uncaught(exc_type, exc, tb) -> None:
        logger.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    def log_thread_uncaught(args) -> None:
        if args.exc_type is not SystemExit:
            logger.critical("uncaught exception in thread %s",
                            args.thread.name if args.thread else "?",
                            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_uncaught
    logger.info("sidecar starting: protocol %s, pid %s, python %s, log %s",
                PROTOCOL_VERSION, os.getpid(), sys.version.split()[0], path)
    return path

PROTOCOL_VERSION = 2

_out_lock = threading.Lock()


def _send(obj: dict) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def _reply(req_id, result: dict) -> None:
    _send({"id": req_id, "result": result})


def _reply_error(req_id, message: str) -> None:
    _send({"id": req_id, "error": {"message": message}})


def _emit(event: str, data: dict) -> None:
    _send({"event": event, "data": data})


def _analysis_engine_starter(label: str):
    """How every bulk engine is opened — and reopened after a death, so a respawned
    engine has exactly the configuration of the one it replaces."""
    def start() -> chess.engine.SimpleEngine:
        path = find_stockfish()
        if path is None:
            raise RuntimeError("Stockfish not found — cannot run analysis.")
        engine = popen_engine(path)
        configure_engine_for_analysis(engine)
        logger.info("%s started: %s", label, path)
        return engine
    return start


def _move_label(fen: str) -> str:
    """'23.' or '23...' — the move a ply's position is waiting for."""
    board = chess.Board(fen)
    return f"{board.fullmove_number}{'.' if board.turn == chess.WHITE else '...'}"


def _death_message(fen: str, exc: BaseException) -> str:
    if getattr(exc, "poison", False):
        return (f"The engine crashed twice on the position before {_move_label(fen)}, "
                "so this game was skipped.")
    return f"The engine stopped and could not be restarted ({exc})."


class RunHalted(Exception):
    """The death breaker stopped a bulk run (VAL-DEATH)."""


def _pgn_label(pgn: str) -> str:
    """"White vs Black" from a PGN's headers, for an import issue."""
    import re as _re
    tags = dict(_re.findall(r'^\[(\w+) "(.*)"\]', pgn or "", _re.M))
    return f"{tags.get('White', '?')} vs {tags.get('Black', '?')}"


class EngineBudget:
    """How many single-threaded engines bulk analysis may run at once (ENG-ALLOC,
    ENGINE-BUDGET-M4B).

    Two numbers. With an interactive screen open, the budget is `ENGINE_BUDGET_CORES`,
    the performance cores, and interactive engines are reserved from it first: live
    play while the Play screen is showing, the FEN path while Review or a puzzle is. A
    running Re-analyse takes a slot too. Bulk sync gets what is left, and never fewer
    than one engine, so a sync always makes progress. With **no** interactive screen
    open, bulk may use up to `ENGINE_BUDGET_IDLE_CEILING` engines (8 on the 10-core M4),
    less any running Re-analyse.

    On the M4 (4 performance cores): sync runs two engines while the user reviews a
    game with a Re-analyse running, three on Play or Review alone, eight otherwise.
    The screen comes from the frontend (`set_active_screen`); the sidecar cannot see
    it, and an engine that is merely *started* is no evidence anyone is using it. A
    worker already in a game finishes it, so after switching to Play the extra engines
    stop at their next game boundary, not at once.
    """

    PLAY_SCREENS = frozenset({"play"})
    FEN_SCREENS = frozenset({"review", "puzzles"})

    def __init__(self, cores: int = C.ENGINE_BUDGET_CORES,
                 idle_ceiling: int = C.ENGINE_BUDGET_IDLE_CEILING) -> None:
        self._cores = max(1, cores)
        self._ceiling = max(self._cores, idle_ceiling)
        self._screen: str | None = None
        self._reanalysing = 0
        self._lock = threading.Lock()

    def set_screen(self, screen: str | None) -> None:
        with self._lock:
            self._screen = screen

    def reanalysis(self, running: bool) -> None:
        with self._lock:
            self._reanalysing = max(0, self._reanalysing + (1 if running else -1))

    def _interactive(self) -> bool:
        return self._screen in self.PLAY_SCREENS or self._screen in self.FEN_SCREENS

    def reserved(self) -> int:
        with self._lock:
            return (
                (self._screen in self.PLAY_SCREENS)
                + (self._screen in self.FEN_SCREENS)
                + self._reanalysing
            )

    def bulk_slots(self) -> int:
        with self._lock:
            interactive = self._interactive()
        if not interactive:
            return max(1, self._ceiling - self.reserved())
        return max(1, self._cores - self.reserved())

    @property
    def cores(self) -> int:
        return self._cores

    @property
    def ceiling(self) -> int:
        """The most engines bulk can ever run: how many workers a sync starts."""
        return self._ceiling


def draw_decision(fullmove: int, last_eval: tuple[str, int | None, int | None] | None,
                  opponent: str = "Stockfish") -> str | None:
    """None to accept a draw offer, else the exact message to show (COACH.md ruling 8). *last_eval* is the
    engine's evaluation from its last move's search, from its own side; with none, the offer is declined. The
    engine favours the position when it sees a mate for itself or more than DRAW_FAVOUR_CP centipawns."""
    if fullmove < DRAW_FROM_MOVE:
        return "Draw offers open after move 30."
    declined = f"{opponent} declined the draw."
    if last_eval is None:
        return declined
    _fen, cp, mate = last_eval
    if mate is not None:
        return declined if mate > 0 else None
    if cp is None or cp > DRAW_FAVOUR_CP:
        return declined
    return None


class EngineWorker:
    """StockfishWorker's contract on a plain thread: one engine, one job queue,
    a generation counter instead of the _skip flag."""

    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._engine: chess.engine.SimpleEngine | None = None
        self._path: str | None = None
        self._configured_skill: int | None = None
        # The engine's own evaluation from its last move's search, from its side: (fen searched, cp, mate).
        # A draw offer reads it (COACH.md ruling 8); nothing shows it.
        self.last_eval: tuple[str, int | None, int | None] | None = None
        self._generation = 0
        self._gen_lock = threading.Lock()
        self.ready = threading.Event()
        self.error: str | None = None
        threading.Thread(target=self._run, name="engine", daemon=True).start()

    def start(self, path: str) -> None:
        """Queue an engine (re)start. Clears the previous outcome first: on a
        second attempt — the user locating a binary after a failed boot — a
        stale `ready`/`error` would be read as the new result."""
        self.ready.clear()
        self.error = None
        self._jobs.put(("init", path))

    def request_move(self, fen: str, skill: int, on_move) -> None:
        with self._gen_lock:
            self._generation += 1
            gen = self._generation
        self._jobs.put(("move", (fen, skill, gen, on_move)))

    def cancel(self) -> None:
        """Discard any in-flight or queued search result."""
        with self._gen_lock:
            self._generation += 1

    def shutdown(self) -> None:
        self.cancel()
        self._jobs.put(("quit", None))

    # ── worker thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            kind, payload = self._jobs.get()
            if kind == "quit":
                self._quit_engine()
                return
            if kind == "init":
                self._init_engine(payload)
            elif kind == "move":
                self._search(*payload)

    def _init_engine(self, path: str) -> None:
        self._quit_engine()          # a re-init would otherwise orphan the old process
        self._configured_skill = None
        self._path = path
        try:
            self._engine = popen_engine(path)
            logger.info("Stockfish ready: %s", path)
        except Exception as exc:
            logger.error("Stockfish init failed: %s", exc)
            self.error = str(exc)
        self.ready.set()

    def _configure(self, skill: int) -> None:
        if self._engine is None or skill == self._configured_skill:
            return
        # `Skill Level` is deliberately not sent: the engine ignores it whenever
        # UCI_LimitStrength is on, and at the top level we want full strength.
        elo = skill_to_elo(skill)
        opts: dict = (
            {"UCI_LimitStrength": True, "UCI_Elo": elo}
            if elo is not None
            else {"UCI_LimitStrength": False}
        )
        try:
            self._engine.configure(opts)
            self._configured_skill = skill
        except Exception as exc:
            logger.warning("configure error: %s", exc)

    def _search(self, fen: str, skill: int, gen: int, on_move) -> None:
        """Play one move. If the engine dies — before this, a silent `return` that left
        the Play screen waiting forever (VAL-DEATH) — restart it, re-apply the skill
        level and retry once; failing that, say so with `engine_error`."""
        board = chess.Board(fen)
        limit = chess.engine.Limit(time=ENGINE_MOVE_TIME_MS / 1000)
        for attempt in (1, 2):
            if self._engine is None:
                self._fail(gen, self.error or "The engine is not running.")
                return
            self._configure(skill)
            try:
                result = self._engine.play(board, limit, info=chess.engine.INFO_SCORE)
                break
            except ENGINE_GONE as exc:
                code = bury(self._engine)
                self._engine = None
                logger.error("live engine died (exit code %s) on %s: %s", code, fen, exc)
                if attempt == 2 or not self._restart():
                    self._fail(gen, "The engine stopped unexpectedly and could not be "
                                    "restarted, so it has not moved. Start a new game to "
                                    "try again.")
                    return
            except Exception as exc:
                logger.error("play error: %s", exc)
                _emit("engine_error", {"message": str(exc)})
                return
        score = result.info.get("score") if result.info else None
        if score is not None:
            pov = score.pov(board.turn)
            self.last_eval = (fen, pov.score(), pov.mate())
        with self._gen_lock:
            stale = gen != self._generation
        if not stale and result.move is not None:
            on_move(result.move)

    def _restart(self) -> bool:
        """Reopen the engine on the path it was started with; the skill level is
        re-applied by the next `_configure`."""
        self._configured_skill = None
        if self._path is None:
            return False
        try:
            self._engine = popen_engine(self._path)
            logger.info("live engine restarted: %s", self._path)
            return True
        except Exception as exc:
            logger.error("live engine restart failed: %s", exc)
            self.error = str(exc)
            return False

    def _fail(self, gen: int, message: str) -> None:
        with self._gen_lock:
            stale = gen != self._generation
        if not stale:
            _emit("engine_error", {"message": message})

    def _quit_engine(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None


class AnalysisRunner:
    """AnalysisWorker's contract on a plain thread: separate engine from live
    play so the user can keep playing while a game is analysed. Results are
    marshalled back to the app thread (which owns the DB) via post_call."""

    def __init__(self, post_call, budget: EngineBudget | None = None) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._engine = SupervisedEngine(_analysis_engine_starter("Analysis engine"),
                                        label="analysis engine")
        self._cancel = False
        self._stopping = False
        self._post = post_call
        self._budget = budget
        self.games_pending = 0      # queued or running game analyses (BOOK-DL refuses a switch)
        threading.Thread(target=self._run, name="analysis", daemon=True).start()

    def analyze_game(self, game_id: int, run_id: int, pgn: str, depth: int,
                     openings: OpeningsBook | None, on_event) -> None:
        self.games_pending += 1
        self._jobs.put(("game", (game_id, run_id, pgn, depth, openings, on_event)))

    #: Runs per refill job. Each job re-queues the rest behind it, so a game the user asks
    #: to analyse waits for one batch at most (about 2 s on the owner's games), not the lot.
    FACTS_BATCH = 25

    def refill_facts(self, db_path: Path, run_ids: list[int], on_rows, on_done) -> None:
        """R6-REFILL (PATTERNS.md §6c): compute missing or stale pattern facts in the
        background, on this thread, with its own read-only connection. *on_rows(rows)* and
        *on_done(stats)* are posted to the app thread, which owns the writing connection."""
        stats = {"runs": len(run_ids), "computed": 0, "t0": time.monotonic()}
        self._jobs.put(("facts", (db_path, list(run_ids), on_rows, on_done, stats, None)))

    #: Runs per coach refill job: about 16 null-move searches each at depth 14 (COACH-1 B measured
    #: the cost), so a game the user asks to analyse waits for a few seconds at most.
    COACH_BATCH = 5

    def refill_coach(self, db_path: Path, run_ids: list[int], on_rows, on_done) -> None:
        """COACH-1 C: the coach's moments for runs that have none (or an old version), in the background,
        on this thread and engine (the parried threats need one search per ply, core/coach.py)."""
        stats = {"runs": len(run_ids), "computed": 0, "t0": time.monotonic()}
        self._jobs.put(("coach", (db_path, list(run_ids), on_rows, on_done, stats, None)))

    def cancel(self) -> None:
        self._cancel = True

    def shutdown(self) -> None:
        self._cancel = True
        self._stopping = True
        self._jobs.put(("quit", None))

    # ── worker thread ─────────────────────────────────────────────────────────

    def _coach_row(self, ro: Database, run_id: int) -> tuple | None:
        info = ro.coach_run_inputs(run_id)
        if info is None:
            return None
        colour, final_json = info
        plies = ro.load_move_analyses(run_id)
        final = json.loads(final_json) if final_json else []
        null_lines: dict[int, list[str]] = {}
        for i in coach_core.user_plies(plies, colour):
            fen = coach_core.needs_null_search(plies, i)
            if fen is None:
                continue
            res = self._engine.analyse(chess.Board(fen),
                                       chess.engine.Limit(depth=C.ANALYSIS_STANDARD_DEPTH))
            null_lines[i] = [m.uci() for m in res.get("pv", [])]
        moments = coach_core.moments_for_run(plies, final, colour, null_lines)
        return (run_id, coach_core.COACH_VERSION, THEMES_VERSION,
                json.dumps([m.to_dict() for m in moments]))

    def _do_coach(self, db_path, todo, on_rows, on_done, stats, ro) -> None:
        if self._stopping:
            if ro is not None:
                ro.close()
            return
        if ro is None:
            ro = Database(db_path, read_only=True)
        batch, rest = todo[:self.COACH_BATCH], todo[self.COACH_BATCH:]
        rows = []
        for run_id in batch:
            try:
                row = self._coach_row(ro, run_id)
            except Exception:
                logger.exception("coach moments for run %s not computed", run_id)
                continue
            if row is not None:
                rows.append(row)
        stats["computed"] += len(rows)
        if rows:
            self._post(lambda r=rows: on_rows(r))
        if rest and not self._stopping:
            self._jobs.put(("coach", (db_path, rest, on_rows, on_done, stats, ro)))
        else:
            ro.close()
            stats["seconds"] = round(time.monotonic() - stats.pop("t0"), 1)
            self._post(lambda: on_done(stats))

    def _run(self) -> None:
        while True:
            kind, payload = self._jobs.get()
            if kind == "quit":
                self._engine.quit()
                return
            try:
                if kind == "game":
                    try:
                        self._do_game(*payload)
                    finally:
                        self.games_pending -= 1
                elif kind == "facts":
                    self._do_facts(*payload)
                elif kind == "coach":
                    self._do_coach(*payload)
            except Exception as exc:
                if kind == "coach":
                    logger.exception("coach refill failed")
                    continue
                if kind == "facts":
                    logger.exception("pattern facts refill failed")
                    continue
                logger.exception("analysis job failed")
                _emit("analysis_error", {"message": str(exc)})

    def _do_facts(self, db_path, todo, on_rows, on_done, stats, ro) -> None:
        if self._stopping:
            if ro is not None:
                ro.close()
            return
        if ro is None:
            ro = Database(db_path, read_only=True)
        batch, rest = todo[:self.FACTS_BATCH], todo[self.FACTS_BATCH:]
        rows = []
        for run_id in batch:
            try:
                row = facts_row(ro, run_id)
            except Exception:
                logger.exception("pattern facts for run %s not computed", run_id)
                continue
            if row is not None:
                rows.append(row)
        stats["computed"] += len(rows)
        if rows:
            self._post(lambda r=rows: on_rows(r))
        if rest and not self._stopping:
            # Behind anything queued meanwhile: a game analysis waits one batch at most.
            self._jobs.put(("facts", (db_path, rest, on_rows, on_done, stats, ro)))
            return
        ro.close()
        stats["seconds"] = round(time.monotonic() - stats.pop("t0"), 1)
        self._post(lambda st=dict(stats): on_done(st))

    def _do_game(self, game_id, run_id, pgn, depth, openings, on_event) -> None:
        # The supervisor restarts a dead engine itself; touching `.engine` here only
        # surfaces a missing binary before the first ply.
        self._engine.engine
        engine = self._engine
        self._cancel = False  # reset at job start, as AnalysisWorker.start does
        if self._budget is not None:
            self._budget.reanalysis(True)
        try:
            for event in analyze_game_plies(
                engine, pgn, depth, openings=openings,
                is_cancelled=lambda: self._cancel,
            ):
                # bind via default arg — the app thread saves to DB and emits
                self._post(lambda ev=event: on_event(game_id, run_id, ev))
        finally:
            if self._budget is not None:
                self._budget.reanalysis(False)


class FenAnalysisRunner:
    """Live analysis of the one position the user is looking at.

    Its own thread and its own engine, because it used to share both with whole-game
    analysis: ask for a variation while a game is being analysed and the request sat
    behind every remaining ply of that game. Nothing about the two jobs makes them
    want the same queue — one is a background sweep the user is not waiting on, the
    other is the position in front of them.

    **One slot, not a queue.** A FIFO would faithfully analyse every position the
    user stepped through on the way to the one they stopped at, each at depth 18,
    and hand back answers for positions they had already left. Requests are
    coalesced instead: the newest wins and a superseded search is stopped mid-flight
    rather than run out and discarded, which is what makes stepping through a line
    cost roughly one search instead of one per step. `review/scratch/fen_queue_cost.py`
    measures both.

    A superseded search emits nothing at all. Letting it emit and having the webview
    filter by fen would mean the panel briefly shows the eval of a position that is
    no longer on the board.

    **Judging a Try is a second slot**, served first and *not* superseded by position
    requests: playing the Try move puts a new position on the board, which asks for
    live analysis at once, and in a one-slot runner that would cancel the judgement
    it was waiting for. Only a newer judgement (or shutdown) supersedes one.
    """

    def __init__(self) -> None:
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._pending: tuple[int, str] | None = None
        self._generation = 0
        self._judge_pending: tuple[int, str, str] | None = None
        self._judge_generation = 0
        self._quit = False
        self._wake = threading.Event()
        threading.Thread(target=self._run, name="fen-analysis", daemon=True).start()

    def analyze(self, fen: str) -> int:
        """Supersede whatever is in flight with `fen`. Returns its generation."""
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._pending = (gen, fen)
        self._wake.set()
        return gen

    def superseded(self, gen: int) -> bool:
        with self._lock:
            return gen != self._generation

    def judge(self, fen: str, uci: str) -> int:
        """Queue a Try judgement; supersedes only an earlier judgement. Returns its token."""
        with self._lock:
            self._judge_generation += 1
            token = self._judge_generation
            self._judge_pending = (token, fen, uci)
        self._wake.set()
        return token

    def _judge_superseded(self, token: int) -> bool:
        with self._lock:
            return self._quit or token != self._judge_generation

    def shutdown(self) -> None:
        with self._lock:
            self._quit = True
            self._generation += 1  # stops a search that is already running
        self._wake.set()

    # ── worker thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            self._wake.wait()
            with self._lock:
                self._wake.clear()
                if self._quit:
                    break
                judge = self._judge_pending
                self._judge_pending = None
                job = None if judge is not None else self._pending
                if judge is None:
                    self._pending = None
            if judge is not None:
                # A position request that arrived meanwhile waits for the next pass.
                self._wake.set()
                try:
                    self._do_judge(*judge)
                except Exception as exc:
                    logger.exception("judging a try failed")
                    _emit("move_judged", {"token": judge[0],
                                          "error": self._failed(exc)})
                continue
            if job is None:
                continue
            try:
                self._do_fen(*job)
            except Exception as exc:
                logger.exception("fen analysis failed")
                # fen: tells a live position's failure from a game analysis's (UI-BUILD-3 C)
                _emit("analysis_error", {"fen": job[1], "message": self._failed(exc)})
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            self._engine = _analysis_engine_starter("Live-analysis engine")()
        return self._engine

    def _failed(self, exc: Exception) -> str:
        """The message for a failed request. A dead engine is replaced now, so the next
        request works — it used to be kept, and every later request failed with
        "engine event loop dead" until the app restarted (VAL-DEATH). The request in
        hand is not retried: the user is looking at it and can ask again."""
        if not is_engine_death(exc):
            return str(exc)
        code = bury(self._engine)
        self._engine = None
        try:
            self._ensure_engine()
            return (f"The engine stopped unexpectedly (exit code {code}) and has been "
                    "restarted — try again.")
        except Exception as again:
            return f"The engine stopped unexpectedly and could not be restarted: {again}"

    def _do_judge(self, token: int, fen: str, uci: str) -> None:
        verdict = judge_try(self._ensure_engine(), fen, uci,
                            is_cancelled=lambda: self._judge_superseded(token))
        if verdict is None or self._judge_superseded(token):
            return
        _emit("move_judged", {"token": token, "fen": fen, **verdict})

    def _do_fen(self, gen: int, fen: str) -> None:
        self._ensure_engine()
        lines = analyze_position_multipv(
            self._engine, fen, C.ANALYSIS_DEPTH, multipv=3, pv_len=6,
            is_cancelled=lambda: self.superseded(gen),
        )
        if self.superseded(gen):
            return
        top = lines[0] if lines else None
        best_uci = top["uci"][0] if top and top["uci"] else None
        cp = top["cp"] if top else None
        mate = top["mate"] if top else None
        _emit(
            "fen_analyzed",
            # depth: what Review's engine lines show beside a live line (UI-BUILD-3 C)
            {"fen": fen, "bestUci": best_uci, "cp": cp, "mate": mate, "lines": lines,
             "depth": C.ANALYSIS_DEPTH},
        )


class PuzzleImportRunner:
    """A puzzle import on a plain thread, with its own SQLite connection: a download from Lichess
    (FIX-B6 B, PZ1) or a file the user picked (.csv or Lichess's .zst). Progress events go straight
    to stdout; the end is marshalled to the app thread. The new set is swapped in only at the end,
    so a cancelled or failed import leaves the previous one usable."""

    def __init__(self, post_call, install=None) -> None:
        self._post = post_call
        # Moves the finished puzzle file over the set in use (COACH-1 F); the app's does it on the
        # app thread, where the connection that attaches the file lives. None: moved directly.
        self._install = install
        self._cancel = False
        self._thread: threading.Thread | None = None
        self.kind: str | None = None
        # COACH-2 D (the sync's race, ruling CB2, found here too): the end is announced (done posted, or
        # cancelled / error emitted) while the thread still lives; running() is false from then on, so the
        # lobby's status check on puzzle_import_done never reads importing: true. Every run has an id.
        self.run_id = 0
        self._ended_run = 0
        self.last_progress: dict | None = None

    def running(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and self._ended_run != self.run_id)

    def _over(self) -> None:
        self._ended_run = self.run_id

    def start(self, csv_path: Path, db_path: Path, on_done) -> None:
        self._start("file", lambda cancelled: import_puzzles_file(
            csv_path, db_path, cancelled, install=self._install), on_done)

    def start_download(self, db_path: Path, on_done, url: str | None = None, open_fn=None) -> None:
        self._start("lichess", lambda cancelled: download_lichess_puzzles(
            db_path, cancelled, open_fn=open_fn, url=url, install=self._install), on_done)

    def _start(self, kind: str, events, on_done) -> None:
        if self.running():
            raise RuntimeError("A puzzle import is already running.")
        self._cancel = False
        self.kind = kind
        self.run_id += 1
        self.last_progress = None
        self._thread = threading.Thread(
            target=self._run, args=(kind, events, on_done), name="puzzle-import", daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def _run(self, kind: str, events, on_done) -> None:
        last = 0.0
        try:
            for event in events(lambda: self._cancel):
                what = event[0]
                if what == "progress":
                    now = time.monotonic()
                    if now - last >= 0.25:  # at most four a second: a batch can take 10 ms
                        last = now
                        self.last_progress = {"kind": kind, "bytes": event[1], "totalBytes": event[2],
                                              "imported": event[3], "run": self.run_id}
                        _emit("puzzle_import_progress", dict(self.last_progress))
                elif what == "finishing":
                    _emit("puzzle_import_finishing", {"kind": kind, "imported": event[1]})
                elif what == "done":
                    self._over()
                    self._post(lambda stats=event[1]: on_done(stats))
                elif what == "cancelled":
                    self._over()
                    _emit("puzzle_import_cancelled", {"kind": kind, "run": self.run_id})
                elif what == "error":
                    self._over()
                    _emit("puzzle_import_error", {"kind": kind, "message": event[1], "run": self.run_id})
        except PuzzleFileError as exc:
            self._over()
            _emit("puzzle_import_error", {"kind": kind, "message": str(exc), "run": self.run_id})
        except Exception as exc:
            logger.exception("puzzle import failed")
            reason = getattr(exc, "reason", None) or exc
            what = "The download stopped" if kind == "lichess" else "The import stopped"
            self._over()
            _emit("puzzle_import_error", {"kind": kind, "message": f"{what}: {reason}.", "run": self.run_id})
        finally:
            self._over()


class CoverageRunner:
    """The lobby's _CoverageWorker on a plain thread: probes the Polyglot book
    for every ECO entry × color and writes results on its own connection."""

    def __init__(self, post_call) -> None:
        self._post = post_call
        self._cancel = False
        self._thread: threading.Thread | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, entries: list, db_path: Path, book_path: Path, on_done) -> None:
        if self.running():
            return
        self._cancel = False
        self._thread = threading.Thread(
            target=self._run, args=(entries, db_path, book_path, on_done),
            name="coverage", daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def _run(self, entries: list, db_path: Path, book_path: Path, on_done) -> None:
        import sqlite3

        import chess.polyglot

        try:
            conn = sqlite3.connect(str(db_path))
            reader = chess.polyglot.open_reader(str(book_path))
            batch: list[tuple] = []
            total = len(entries) * 2
            done = 0
            for eco, name, fen, _pgn in entries:
                if self._cancel:
                    break
                try:
                    board = chess.Board(fen)
                except Exception:
                    done += 2
                    continue
                for color_str, chess_color in (("white", chess.WHITE), ("black", chess.BLACK)):
                    batch.append((eco, name, color_str, int(has_coverage(reader, board, chess_color))))
                    done += 1
                if len(batch) >= 200:
                    conn.executemany(
                        "INSERT OR REPLACE INTO opening_book_coverage"
                        " (eco, name, color, has_moves) VALUES (?,?,?,?)",
                        batch,
                    )
                    conn.commit()
                    batch = []
                    _emit("trainer_index_progress", {"done": done, "total": total})
            if batch and not self._cancel:
                conn.executemany(
                    "INSERT OR REPLACE INTO opening_book_coverage"
                    " (eco, name, color, has_moves) VALUES (?,?,?,?)",
                    batch,
                )
                conn.commit()
            reader.close()
            conn.close()
            if not self._cancel:
                self._post(on_done)
        except Exception as exc:
            logger.exception("coverage indexing failed")
            _emit("trainer_index_error", {"message": str(exc)})


class SyncRunner:
    """Background platform sync on its own thread + own DB connection (the
    PuzzleImportRunner / CoverageRunner pattern). Two phases, both resumable:

      1. fetch the player's recent rated games and save the new ones (dedup by
         external_id) — these land with no analysis_run yet;
      2. drain the 'pending analysis' queue (every synced game lacking a run,
         including leftovers from an interrupted earlier sync), classifying each
         from embedded [%eval]s when coverage is high enough, else with a local
         Stockfish search at the shallower bulk depth.

    If the app closes mid-sync, the saved-but-unanalysed games are picked up by
    games_pending_analysis() on the next run, so progress is never lost."""

    def __init__(self, post_call, budget: EngineBudget | None = None) -> None:
        self._post = post_call
        self._cancel = False
        self._thread: threading.Thread | None = None
        self._budget = budget or EngineBudget()
        self._engines: dict[int, SupervisedEngine] = {}
        self._engines_lock = threading.Lock()
        self.on_finished = None   # called on the app thread when a run ends (Server sets it)
        self._breaker = DeathBreaker()
        # COACH-2 D (ruling CB2): every run has an id, on sync_status and on every sync_ event. A run is over
        # once its sync_finished is emitted, though its thread lives a moment longer (and posts the coach's
        # refill): running() says so from then on, so a status check made on sync_finished never revives it.
        self.run_id = 0
        self._ended_run = 0
        self.kind: str | None = None             # "sync" | "analyse": what the current or last run does
        self.last_progress: dict | None = None   # its last sync_progress (background_jobs)

    def running(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and self._ended_run != self.run_id)

    def _emit(self, event: str, data: dict) -> None:
        if event == "sync_progress":
            self.last_progress = dict(data)
        _emit(event, {**data, "run": self.run_id})

    def _end(self) -> None:
        """The run is over: announced, and running() false from here on (ruling CB2)."""
        self._ended_run = self.run_id
        self._emit("sync_finished", {})

    _FETCHERS = {
        "lichess": fetch_lichess_games,
        "chesscom": fetch_chesscom_games,
    }

    def start(self, *, jobs: list[tuple[str, str]], usernames: list[str],
              db_path: Path, depth: int) -> None:
        """*jobs* is a list of (source, username) pairs, processed in order.
        *depth* is the Stockfish search depth for games analysed locally."""
        if self.running():
            raise RuntimeError("a sync is already running")
        self._cancel = False
        self.run_id += 1
        self.kind, self.last_progress = "sync", None
        self._thread = threading.Thread(
            target=self._run, args=(jobs, usernames, db_path, depth),
            name="sync", daemon=True,
        )
        self._thread.start()

    def start_analyze(self, *, sources: list[str], db_path: Path, depth: int,
                      count: int | None = None, chosen: dict | None = None) -> None:
        """Analyse already-synced games that still lack a satisfying run, with no
        network fetch. Shares the running()/cancel machinery with full sync so the
        two can never overlap on the engine or DB connection. *count* is "Analyse
        more" in a step: the *count* most recent pending games across *sources*;
        None is all of them (BETA-PUB Q4). *chosen* is an explicit queue by source (Import
        PGN's games, UI-BUILD-3 E), read before *count*."""
        if self.running():
            raise RuntimeError("a sync is already running")
        self._cancel = False
        self.run_id += 1
        self.kind, self.last_progress = "analyse", None
        self._thread = threading.Thread(
            target=self._run_analyze, args=(sources, db_path, depth, count, chosen),
            name="analyze-pending", daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def shutdown(self) -> None:
        self._cancel = True
        self._quit_engine()

    # ── worker thread ─────────────────────────────────────────────────────────

    def _run(self, jobs, usernames, db_path, depth) -> None:
        db: Database | None = None
        openings: OpeningsBook | None = None
        try:
            db = Database(db_path)
            openings = OpeningsBook()
            for source, username in jobs:
                if self._cancel:
                    break
                try:
                    new_count, analyzed = self._sync_source(
                        db, openings, source, username, usernames, depth
                    )
                    self._emit("sync_done",
                          {"source": source, "new": new_count, "analyzed": analyzed})
                except SyncError as exc:
                    # One platform failing shouldn't abort the others.
                    self._emit("sync_error", {"source": source, "message": str(exc)})
                except RunHalted as exc:
                    # A failing engine fails every platform alike: stop the run.
                    self._emit("sync_error", {"source": source, "message": str(exc)})
                    break
            if self._cancel:
                self._emit("sync_cancelled", {})
        except Exception as exc:
            logger.exception("sync failed")
            self._emit("sync_error", {"source": "", "message": str(exc)})
        finally:
            self._quit_engine()
            if openings is not None:
                openings.close()
            if db is not None:
                db.close()
            self._end()
            if self.on_finished is not None:      # COACH-1 C: the coach reads the new runs
                self._post(self.on_finished)

    @staticmethod
    def _newest_pending(db, sources, depth, count) -> dict[str, list]:
        """The *count* most recent pending games across *sources*, by source, each list
        newest first. One step of "Analyse more" (BETA-PUB Q4)."""
        merged = [rec for source in sources
                  for rec in db.games_pending_analysis(source, depth, limit=count)]
        merged.sort(key=lambda r: (r.played_at or "", r.id), reverse=True)
        picked = merged[:count]
        return {s: [r for r in picked if r.source == s] for s in sources}

    def _run_analyze(self, sources, db_path, depth, count=None, chosen=None) -> None:
        db: Database | None = None
        openings: OpeningsBook | None = None
        try:
            db = Database(db_path)
            openings = OpeningsBook()
            if chosen is None and count is not None:
                chosen = self._newest_pending(db, sources, depth, count)
            for source in sources:
                if self._cancel:
                    break
                if chosen is not None and not chosen[source]:
                    continue
                try:
                    total = self._analyze_pending(
                        db, openings, source, depth,
                        records=None if chosen is None else chosen[source])
                    self._emit("sync_done", {"source": source, "new": 0, "analyzed": total})
                except RunHalted as exc:
                    self._emit("sync_error", {"source": source, "message": str(exc)})
                    break
                except Exception as exc:
                    self._emit("sync_error", {"source": source, "message": str(exc)})
            if self._cancel:
                self._emit("sync_cancelled", {})
        except Exception as exc:
            logger.exception("analyze-pending failed")
            self._emit("sync_error", {"source": "", "message": str(exc)})
        finally:
            self._quit_engine()
            if openings is not None:
                openings.close()
            if db is not None:
                db.close()
            self._end()
            if self.on_finished is not None:      # COACH-1 C: the coach reads the new runs
                self._post(self.on_finished)

    def _sync_source(self, db, openings, source, username, usernames, depth):
        fetch = self._FETCHERS.get(source)
        if fetch is None:
            raise SyncError(f"unknown sync source: {source}")

        self._emit("sync_progress",
              {"phase": "fetching", "source": source, "done": 0, "total": 0})
        games = fetch(username, usernames=usernames, openings=openings)

        existing = db.existing_external_ids(source)
        new_count = 0
        for pg in games:
            if self._cancel:
                break
            if pg.external_id and pg.external_id in existing:
                continue
            try:
                db.save_game(
                    played_at=pg.played_at,
                    player_color=pg.player_color,
                    skill_level=0,
                    result=pg.result,
                    termination=pg.termination,
                    move_count=pg.move_count,
                    pgn=pg.pgn,
                    final_fen=pg.final_fen,
                    opening_eco=pg.opening_eco,
                    opening_name=pg.opening_name,
                    source=source,
                    external_id=pg.external_id,
                    not_owner=pg.not_owner,
                )
            except AttributionPending as exc:
                # Skipped, not guessed: it stays unsynced, so a later sync with the
                # right handle (or after the migration) picks it up.
                self._emit("sync_warning", {"source": source,
                                       "message": f"Skipped {_pgn_label(pg.pgn)}: {exc}"})
                continue
            new_count += 1

        # Only the account's most recent games are analysed by a sync (BETA-PUB Q4).
        total = self._analyze_pending(db, openings, source, depth,
                                      recent=C.SYNC_AUTO_ANALYSE_RECENT)
        return new_count, total

    def _analyze_pending(self, db, openings, source, depth, *,
                         recent: int | None = None, records=None) -> int:
        """Drain the analysis queue for *source*, emitting 'analyzing' progress.
        Shared by full sync and the standalone analyze-pending job. Returns the
        number of games processed.

        Games with embedded Lichess evals are classified here, on the sync thread.
        The rest go to up to `EngineBudget.ceiling` worker threads, each with its own
        single-threaded engine; worker *i* starts a game only while *i* is below
        `bulk_slots()`, so the number searching follows the screen the user is on,
        at game granularity — a game already started finishes. Workers only
        *compute*: every write happens here, on this thread's connection, and a
        game is saved whole or not at all, so a cancelled sync leaves no partial run
        (which `games_pending_analysis` would otherwise count as done).

        Engine death (VAL-DEATH): each worker's engine restarts itself and retries the
        search it died on once. A game whose position kills it twice is recorded in
        `engine_failures` and skipped, unsaved — still pending — and the run moves on.
        More than `ENGINE_BREAKER_DEATHS` deaths in the last
        `ENGINE_BREAKER_WINDOW_GAMES` games stops the run with `RunHalted`.

        Newest first (BETA-PUB Q4). *recent* limits the queue to the source's *recent*
        most recent games (a sync's automatic analysis); *records* is an explicit queue
        ("Analyse more" in a step)."""
        self._breaker = DeathBreaker()
        pending = (records if records is not None
                   else db.games_pending_analysis(source, depth, recent=recent))
        total = len(pending)
        done = 0
        self._emit("sync_progress",
              {"phase": "analyzing", "source": source, "done": 0, "total": total})

        def progressed() -> None:
            nonlocal done
            done += 1
            self._emit("sync_progress",
                  {"phase": "analyzing", "source": source, "done": done, "total": total})

        todo: queue.Queue = queue.Queue()
        stuck: set[int] | None = None
        for rec in pending:
            if self._cancel:
                return total
            try:
                if self._analyze_from_evals(db, openings, rec):
                    progressed()
                    continue
            except Exception as exc:
                self._skipped(source, rec, exc)
                progressed()
                continue
            if stuck is None:
                # Needs an engine version, so asked once, when the first game needs one.
                stuck = db.needs_attention_ids(source, self._ensure_engine(0).version)
                if stuck:
                    self._emit("sync_warning", {"source": source, "message": (
                        f"Not analysing {len(stuck)} game(s): the engine crashed on each "
                        f"in {C.ENGINE_POISON_MAX_ATTEMPTS} separate runs. They need "
                        "attention (see engine_failures).")})
            if rec.id in stuck:
                progressed()
                continue
            todo.put(rec)
        if todo.empty():
            return total

        finished: queue.Queue = queue.Queue()
        workers = [
            threading.Thread(target=self._worker, args=(i, todo, finished, depth),
                             name=f"sync-engine-{i}", daemon=True)
            for i in range(min(self._budget.ceiling, todo.qsize()))
        ]
        for w in workers:
            w.start()
        while any(w.is_alive() for w in workers) or not finished.empty():
            try:
                rec, analyses, (summary, final_lines), error, died = finished.get(timeout=0.2)
            except queue.Empty:
                continue
            if died is not None:
                _, ply, fen, exc = died
                db.record_engine_failure(
                    context="sync", fen=getattr(exc, "fen", None) or fen, message=str(exc),
                    source=rec.source,
                    external_id=rec.external_id, game_id=rec.id, ply=ply,
                    exit_code=getattr(exc, "exit_code", None),
                    engine=getattr(exc, "version", None),
                )
                self._skipped(source, rec, _death_message(fen, exc))
            elif error is not None:
                self._skipped(source, rec, error)
            elif summary is not None:
                try:
                    self._save_run(db, rec.id, "Stockfish", depth, analyses, summary,
                                   final_lines, provenance=provenance.engine_run(
                                       engine_name=self._ensure_engine(0).version,
                                       engine_path=find_stockfish(), depth=depth,
                                       has_book=openings is not None and openings.has_book))
                except IncompleteRun as exc:
                    self._skipped(source, rec, exc)
            else:
                continue            # cancelled mid-game: nothing saved, still pending
            progressed()
        if self._breaker.tripped:
            raise RunHalted(self._breaker.message())
        return total

    def _skipped(self, source, rec, exc) -> None:
        # A single malformed/variant game must not abort the whole run.
        logger.warning("analysis failed for game %s: %s", rec.id, exc)
        self._emit("sync_warning", {"source": source, "message": f"Skipped a game: {exc}"})

    def _analyze_from_evals(self, db: Database, openings: OpeningsBook,
                            rec: GameRecord) -> bool:
        """Prefer embedded Lichess evals — no engine needed. True if it saved a run."""
        if eval_coverage(rec.pgn) < C.SYNC_MIN_EVAL_COVERAGE:
            return False
        result = analyze_game_from_evals(rec.pgn, openings)
        if result is None:
            return False
        analyses, summary = result
        self._save_run(db, rec.id, "Lichess evals", 0, analyses, summary,
                       provenance=provenance.evals_run(
                           has_book=openings is not None and openings.has_book))
        return True

    def _worker(self, index: int, todo: queue.Queue, finished: queue.Queue,
                depth: int) -> None:
        """One single-threaded engine, taking games while the budget allows it."""
        openings = OpeningsBook()
        stopped = lambda: self._cancel or self._breaker.tripped  # noqa: E731
        try:
            while not stopped():
                # Checked before the gate, not after: a worker the budget is holding
                # back must still notice the queue has drained, or it waits for a
                # slot forever and the sync never finishes (found by the ENG-ALLOC
                # timing run, which hung on Review with 3 slots and 4 workers).
                if todo.empty():
                    return
                if index >= self._budget.bulk_slots():
                    time.sleep(0.25)
                    continue
                try:
                    rec = todo.get_nowait()
                except queue.Empty:
                    return
                analyses: list[MoveAnalysis] = []
                summary: dict | None = None
                error: Exception | None = None
                died: tuple | None = None
                final_lines: list[dict] = []
                self._breaker.game_started()
                try:
                    engine = self._ensure_engine(index)
                    for event in analyze_game_plies(
                        engine, rec.pgn, depth, openings=openings,
                        is_cancelled=stopped,
                    ):
                        if event[0] == "ply":
                            analyses.append(event[3])
                        elif event[0] == "done":
                            summary, final_lines = event[1], event[2]
                        elif event[0] == "error":
                            error = RuntimeError(event[1])
                        elif event[0] == "engine_died":
                            died = event
                except Exception as exc:
                    error = exc
                finished.put((rec, analyses, (summary, final_lines), error, died))
        finally:
            openings.close()

    def _save_run(self, db: Database, game_id: int, engine_name: str, depth: int,
                  analyses: list[MoveAnalysis], summary: dict,
                  final_lines: list[dict] | None = None,
                  provenance: dict | None = None) -> None:
        run_id = db.save_analysis_run(
            game_id=game_id, engine_name=engine_name, depth=depth, provenance=provenance,
        )
        white = (summary.get("white") or {}).get("accuracy")
        black = (summary.get("black") or {}).get("accuracy")
        try:
            db.complete_analysis_run(
                run_id, summary, white_accuracy=white, black_accuracy=black,
                plies=analyses, final_lines=final_lines,
            )
        except IncompleteRun:
            db.discard_analysis_run(run_id)
            raise
        _write_pattern_facts(db, run_id)

    def _ensure_engine(self, index: int = 0) -> SupervisedEngine:
        with self._engines_lock:
            engine = self._engines.get(index)
            if engine is None:
                engine = SupervisedEngine(
                    _analysis_engine_starter(f"Sync engine {index}"),
                    label=f"sync engine {index}")
                self._engines[index] = engine
        # Every death counts toward this run's breaker, recovered or not.
        engine.set_on_death(self._breaker.death)
        engine.engine           # surfaces a missing binary as this game's error
        return engine

    def _quit_engine(self) -> None:
        with self._engines_lock:
            engines, self._engines = list(self._engines.values()), {}
        for engine in engines:
            try:
                engine.quit()
            except Exception:
                pass


def _write_pattern_facts(db: Database, run_id: int) -> None:
    """R6 (PATTERNS.md §6a): store a just-completed run's pattern facts. An addition to the
    run, never a condition of it: a failure is logged and the run stands (the backfill tool
    fills what is missing)."""
    try:
        write_facts_for_run(db, run_id)
    except Exception:
        logger.exception("pattern facts for run %s not written", run_id)


_HEADER = re.compile(r'^\[(White|Black) "([^"]*)"\]', re.M)


def _coach_games(db: Database) -> list:
    """Every game with current coach moments, as core/coach.py's GameMoments."""
    out = []
    for gid, source, ext, played_at, colour, pgn, run_id, js in db.coach_rows(coach_core.COACH_VERSION,
                                                                            THEMES_VERSION):
        heads = dict(_HEADER.findall(pgn or ""))
        opp = heads.get("Black" if colour == "white" else "White") or None
        out.append(coach_core.GameMoments(
            game_id=gid, key=str(ext) if ext else f"local-{gid}", played_at=played_at or "", colour=colour,
            opponent=opp, fens=db.run_fens(run_id), moments=coach_core.moments_from_json(js),
            losses=db.run_losses(run_id), run_id=run_id))
    return out


def _utcnow() -> datetime:
    """The clock Practice reads (COACH-2 C); the tests replace it with a fake one."""
    return datetime.now(timezone.utc)


def _practice_items_for(db: Database, games: list, done: set) -> list:
    """COACH-2 C: the Practice items the games' missed moments give (core/practice.py), for games not in *done*
    (keys of (game key, run id) already read: a game read again only when its run changed). Read-only work: the
    stored best move of each allowed threat's ply. The caller writes the items on the app thread."""
    out = []
    for g in games:
        k = (g.key, g.run_id)
        if k in done:
            continue
        done.add(k)
        plies = [m.ply for m in g.moments if m.kind == "threat" and m.outcome == "missed"]
        best = {}
        if plies:
            best = {r[0]: r[1] for r in db._conn.execute(
                f"SELECT ply, best_uci FROM move_analyses WHERE run_id = ? AND ply IN ({','.join('?' * len(plies))})",
                (g.run_id, *plies))}
        out.extend(practice_core.items_from_game(g, best))
    return out


class CoachRunner:
    """COACH-1 C: builds the Coach page's overview off the dispatch thread, on a read-only connection,
    and keeps the latest one (with every game's moments, for the report's history lines). A rebuild
    asked for while one runs is done once more when it ends. Emits coach_updated when one is ready."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._jobs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.latest: dict | None = None
        self.pending = 0
        self._queued = False
        # COACH-2 C: after each overview, the Practice items of games not read before go to on_items (the Server
        # writes them on the app thread)
        self.on_items = None
        self._items_done: set = set()
        threading.Thread(target=self._run, name="coach", daemon=True).start()

    def rebuild(self, pending: int = 0) -> None:
        with self._lock:
            self.pending = pending
            if self._queued:
                return
            self._queued = True
        self._jobs.put("build")

    def shutdown(self) -> None:
        self._jobs.put(None)

    def _run(self) -> None:
        db: Database | None = None
        while True:
            job = self._jobs.get()
            if job is None:
                if db is not None:
                    db.close()
                return
            with self._lock:
                self._queued = False
                pending = self.pending
            try:
                if db is None:
                    db = Database(self._db_path, read_only=True)
                t0 = time.monotonic()
                games = _coach_games(db)
                overview = coach_core.build_overview(games, pending=pending)
                index = {g.game_id: g for g in games}
                with self._lock:
                    self.latest = {"overview": overview, "index": index,
                                   "order": sorted(games, key=lambda g: (g.played_at or "", g.game_id))}
                logger.info("coach overview: %d games, %d focus items, %.1f s", overview["games"],
                            len(overview["focus"]), time.monotonic() - t0)
                _emit("coach_updated", {"games": overview["games"], "focus": len(overview["focus"]),
                                        "pending": pending})
                if self.on_items is not None:
                    try:
                        items = _practice_items_for(db, games, self._items_done)
                    except Exception:
                        logger.exception("practice items not read")
                        items = []
                    self.on_items(items)
            except Exception:
                logger.exception("coach overview failed")

    def history(self, game_id: int) -> tuple[dict[str, list[str]], set[str]]:
        """The outcomes per (kind:theme) in the user's games before *game_id* (oldest first), and the
        focus keys; empty while no overview has been built."""
        with self._lock:
            latest = self.latest
        if latest is None:
            return {}, set()
        focus_keys = {f["key"] for f in latest["overview"]["focus"]}
        earlier: dict[str, list[str]] = {}
        for g in latest["order"]:
            if g.game_id == game_id:
                break
            for mo in g.moments:
                k = coach_core.moment_key(mo)         # the theme it counts under (CF1)
                if k is not None:
                    earlier.setdefault(k, []).append(mo.outcome)
        return earlier, focus_keys


class InsightsRunner:
    """Builds the Insights aggregate off the dispatch thread.

    build_insights() scans every analysed ply and takes ~11 s on a real
    database. Run inline it blocks the single request loop, so the whole app —
    board, navigation, every other RPC — stops responding for the duration.

    Replies are written straight from this thread; _send holds the stdout lock,
    so frames never interleave. The DB connection is opened here rather than
    shared: sqlite3 connections are check_same_thread=True.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._jobs: queue.Queue = queue.Queue()
        self._db: Database | None = None
        self._generation = 0
        self._gen_lock = threading.Lock()
        self._stopping = False
        self.closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="insights", daemon=True,
        )
        self._thread.start()

    def submit(self, req_id, params: dict) -> None:
        with self._gen_lock:
            self._generation += 1
            gen = self._generation
        self._jobs.put((req_id, params, gen))

    def shutdown(self, timeout: float = 1.0) -> None:
        """Stop the worker and close its connection.

        The join timeout is what actually bounds exit: profiling shows the build
        is mostly Python rather than SQLite, so interrupt() usually
        lands between queries and does nothing. It is still worth calling for the
        case where we are inside a long scan. Past the timeout we give up and let
        the daemon thread die with the process — the connection is read-only, so
        abandoning it cannot lose or corrupt anything.
        """
        if self.closed.is_set():
            return
        self._stopping = True
        self._jobs.put((None, None, 0))
        db = self._db
        if db is not None:
            try:
                db.interrupt()
            except sqlite3.ProgrammingError:
                pass  # the worker closed it between the read and the call
        self._thread.join(timeout)

    def _stale(self, gen: int) -> bool:
        with self._gen_lock:
            return gen != self._generation

    def _run(self) -> None:
        try:
            while True:
                req_id, params, gen = self._jobs.get()
                if params is None:
                    return
                if self._stale(gen):
                    # A newer request landed while this one sat in the queue.
                    # Skip the build — but still reply, or the frontend's pending
                    # promise never settles.
                    _reply(req_id, {"superseded": True})
                    continue
                self._build(req_id, params)
        finally:
            if self._db is not None:
                self._db.close()
                self._db = None
            self.closed.set()

    def _build(self, req_id, params: dict) -> None:
        try:
            if self._db is None:
                self._db = Database(self._db_path, read_only=True)
            with self._db.snapshot():
                result = build_insights(self._db, **params)
        except Exception as exc:
            if self._stopping:
                return  # interrupted by shutdown; nobody is listening
            logger.exception("insights build failed")
            _reply_error(req_id, str(exc))
            return
        _reply(req_id, result)


def _ma_dict(ma: MoveAnalysis) -> dict:
    return {
        "ply": ma.ply,
        "playedUci": ma.played_uci,
        "bestUci": ma.best_uci or None,
        "pvUci": ma.pv_uci,
        "scoreBeforeCp": ma.score_before_cp,
        "scoreBeforeMate": ma.score_before_mate,
        "scoreAfterCp": ma.score_after_cp,
        "scoreAfterMate": ma.score_after_mate,
        "classification": ma.classification,
        "isBook": ma.is_book,
        "lines": ma.lines,
    }


def _parse_elo(raw: str | None) -> int | None:
    """PGN Elo headers are strings; platform games use a number, unrated games
    often use '?' or omit the tag. Returns the int rating or None."""
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _game_names(pgn: str | None) -> tuple[str | None, str | None, int | None, int | None]:
    """Cheaply read the White/Black names and Elos from a stored PGN (header
    block only, no move parse). Each field is None if absent or unparseable."""
    if not pgn:
        return None, None, None, None
    try:
        headers = chess.pgn.read_headers(io.StringIO(pgn))
    except Exception:
        return None, None, None, None
    if headers is None:
        return None, None, None, None
    white = headers.get("White") or None
    black = headers.get("Black") or None
    white_elo = _parse_elo(headers.get("WhiteElo"))
    black_elo = _parse_elo(headers.get("BlackElo"))
    return white, black, white_elo, black_elo


#: the server's game endings (server/src/gamecore.ts) in the app's termination words (core/game.py)
_FRIEND_TERMINATION = {
    "checkmate": "checkmate", "resign": "resignation", "timeout": "timeout",
    "timeout_vs_insufficient": "timeout", "agreed": "draw_agreed", "stalemate": "stalemate",
    "repetition": "threefold_repetition", "fifty_moves": "fifty_moves",
    "insufficient": "insufficient_material", "abandoned": "abandoned", "abandoned_draw": "abandoned",
}


def _game_dict(rec: GameRecord) -> dict:
    white, black, white_elo, black_elo = _game_names(rec.pgn)
    return {
        "id": rec.id,
        "playedAt": rec.played_at,
        "playerColor": rec.player_color,
        "skillLevel": rec.skill_level,
        "ladderVersion": rec.ladder_version,
        "result": rec.result,
        "termination": rec.termination,
        "moveCount": rec.move_count,
        "openingEco": rec.opening_eco,
        "openingName": rec.opening_name,
        "source": rec.source,
        "externalId": rec.external_id,
        "speed": rec.speed,
        "rated": rated_from_pgn(rec.pgn),
        "white": white,
        "black": black,
        "whiteElo": white_elo,
        "blackElo": black_elo,
        # FRIENDS-2 (R1-R3): a friend game's ratings at its start, apart from the real ones
        "startRatings": GL.start_ratings(rec.start_white_rating, rec.start_white_est,
                                         rec.start_black_rating, rec.start_black_est),
    }


# Methods that reply from a worker thread instead of returning a result.
# _handle_request passes req_id through and does not reply on their behalf.
_DEFERRED_METHODS = {"insights", "check_usernames", "puzzle_check_update",
                     # Friends (FRIENDS-1): the server's answers come on the Friends thread
                     "friends_check_handle", "friends_signup", "friends_recover", "friends_me",
                     "friends_list", "friends_request", "friends_answer", "friends_cancel",
                     "friends_remove", "friends_block", "friends_unblock", "friends_appear_offline",
                     "friends_link_lichess", "friends_chesscom_start", "friends_chesscom_verify",
                     "friends_chesscom_cancel", "friends_save_recovery",
                     "friends_unlink", "friends_delete_account", "friends_profile",
                     # FRIENDS-2: challenges, rematches
                     "friends_challenge", "friends_challenge_answer", "friends_challenge_cancel",
                     "friends_rematch", "friends_ratings"}


class RelabelRunner:
    """Relabel on update (BETA item 5): on open, runs an older classifier labelled are
    relabelled from their stored rows (`core/relabel.py`) on this thread, after a verified
    backup, with `relabel_progress` / `relabel_done` / `relabel_error` events. Its own
    connection, one transaction per run, so the app stays usable while it works.

    Only in the packaged app, or with `ZUGZWANG_AUTO_RELABEL=1`: the owner's database is
    relabelled by hand with the stage-6 tool and its approval checks, so a dev run only
    reports stale runs (state `manual`) and changes nothing."""

    def __init__(self, on_done=None) -> None:
        self._on_done = on_done  # called (on this thread) once a relabel has finished
        self.state = "idle"     # idle | manual | running | done | error
        self.done = 0
        self.total = 0
        self.result: dict | None = None
        self.error: str | None = None
        self._cancel = False
        self._thread: threading.Thread | None = None

    @staticmethod
    def enabled() -> bool:
        return C.FROZEN or os.environ.get("ZUGZWANG_AUTO_RELABEL") == "1"

    def check(self, db_path: Path) -> None:
        from zugzwang.core import relabel
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            stale = relabel.stale_run_ids(con)
        finally:
            con.close()
        if not stale:
            return
        self.total = len(stale)
        if not self.enabled():
            self.state = "manual"
            logger.warning("%d complete runs carry an older classifier version; relabel "
                           "them with review/baselines/cls_v3_relabel.py (auto-relabel is "
                           "for the packaged app)", len(stale))
            return
        self.state = "running"
        _emit("relabel_progress", {"done": 0, "total": self.total, "phase": "backup"})
        self._thread = threading.Thread(target=self._run, args=(db_path,),
                                        name="relabel", daemon=True)
        self._thread.start()

    def _run(self, db_path: Path) -> None:
        from zugzwang.core import relabel
        t0 = time.monotonic()

        def progress(i: int, n: int) -> None:
            self.done, self.total = i, n
            if i == n or i % 10 == 0:
                _emit("relabel_progress", {"done": i, "total": n, "phase": "relabel"})

        try:
            out = relabel.relabel_stale(db_path, progress=progress,
                                        cancelled=lambda: self._cancel)
        except Exception as exc:
            logger.exception("relabel on update failed")
            self.state, self.error = "error", str(exc)
            _emit("relabel_error", {"message": str(exc)})
            return
        out["seconds"] = round(time.monotonic() - t0, 1)
        self.result = out
        self.state = "done" if out["integrity"] == "ok" and not out["unstamped"] else "error"
        if self.state == "error":
            self.error = (f"relabel incomplete: integrity {out['integrity']}, "
                          f"{out['unstamped']} runs left")
        logger.info("relabel on update: %s", out)
        _emit("relabel_done" if self.state == "done" else "relabel_error",
              {**out, "message": self.error})
        if self._on_done is not None:
            self._on_done()     # R6-REFILL: the relabel made the runs' facts stale

    def status(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total,
                "result": self.result, "error": self.error}

    def shutdown(self) -> None:
        self._cancel = True
        if self._thread is not None:
            self._thread.join(timeout=10)


class BookRunner:
    """BOOK-DL (owner ruling D, 2026-11-19): one opening-book job at a time on its own thread —
    download and verify (`books.download`), a verified backup, the book recorded as in use, the
    book relabel from stored rows (`books.relabel_for_book`, W20's rule, no engine) — with
    `book_progress` events ({id, phase: download | backup | relabel, done, total}), then
    `book_done` or `book_error`. A failed or cancelled download leaves the book in use; a
    failed backup writes nothing. The book is recorded with `relabelled: false` before the
    relabel and true after, so an interrupted switch resumes on the next open (`resume`)."""

    def __init__(self, post_call) -> None:
        self._post = post_call
        self._cancel = False
        self._thread: threading.Thread | None = None
        self.job: dict | None = None        # {"id", "phase", "done", "total"}
        self.last: dict | None = None       # the last job's outcome

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def relabelling(self) -> bool:
        return self.running() and bool(self.job) and self.job["phase"] in ("backup", "relabel")

    def start(self, book_id: str, db_path: Path, on_switched) -> None:
        from zugzwang.core import books
        books.spec(book_id)                 # unknown id: raise before any thread
        if self.running():
            raise RuntimeError("An opening book is already being installed.")
        self._cancel = False
        self.job = {"id": book_id, "phase": "download", "done": 0, "total": 0}
        self._thread = threading.Thread(target=self._run, args=(book_id, db_path, on_switched),
                                        name="book", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def _phase(self, phase: str, done: int, total: int) -> None:
        assert self.job is not None
        self.job.update(phase=phase, done=done, total=total)
        _emit("book_progress", dict(self.job))

    def _run(self, book_id: str, db_path: Path, on_switched) -> None:
        from zugzwang.core import books, relabel
        t0 = time.monotonic()
        b = books.spec(book_id)
        last_pct = {"v": -1}

        def dl_progress(got: int, total: int) -> None:
            pct = got * 100 // total
            if pct != last_pct["v"]:
                last_pct["v"] = pct
                self._phase("download", got, total)

        try:
            path = books.download(b, progress=dl_progress, cancelled=lambda: self._cancel)
            self._phase("backup", 0, 1)
            backup = relabel.backup_database(db_path, db_path.parent / "backups",
                                             f"pre-book-{b.id}")
            logger.info("opening book %s: backup %s", b.id, backup)
            books.set_active(b.id, relabelled=False)
            out = books.relabel_for_book(
                db_path, path, write=True,
                progress=lambda i, n: (i == n or i % 25 == 0) and self._phase("relabel", i, n))
            books.set_active(b.id, relabelled=True)
        except Exception as exc:
            logger.exception("opening book %s failed", book_id)
            self.last = {"id": book_id, "ok": False, "message": str(exc)}
            self.job = None
            _emit("book_error", {"id": book_id, "message": str(exc)})
            return
        out.update(id=b.id, ok=True, backup=str(backup),
                   seconds=round(time.monotonic() - t0, 1))
        logger.info("opening book %s in use: %s", b.id,
                    {k: v for k, v in out.items() if k != "relabelledRuns"})
        self.last = {k: v for k, v in out.items() if k != "relabelledRuns"}
        self.job = None
        self._post(lambda: on_switched(out))

    def status(self) -> dict:
        from zugzwang.core import books
        st = books.active_state()
        return {
            "books": [{"id": b.id, "label": b.label, "minGames": b.min_games, "bytes": b.bytes,
                       "sha256": b.sha256, "url": b.url, "default": b.default,
                       "installed": books.installed(b),
                       "active": bool(st and st["id"] == b.id)} for b in books.MANIFEST],
            "active": st["id"] if st else None,
            "defaultId": books.DEFAULT_ID,
            "job": dict(self.job) if self.job else None,
            "last": self.last,
        }

    def shutdown(self) -> None:
        self._cancel = True


class Server:
    """Runs on the app thread; everything that touches the session or the DB
    goes through the inbox."""

    #: COACH-2 D: the coach's reading for background_jobs (None: not reading); a class default as well, for a
    #: Server built without __init__ (the tests' object.__new__)
    _coach_reading: dict | None = None

    @property
    def _analysis_jobs(self) -> dict[int, dict]:
        """COACH-2 D: the game analyses in flight by run id (background_jobs); created on first use."""
        return self.__dict__.setdefault("_analysis_jobs_by_run", {})

    def __init__(self) -> None:
        self._inbox: queue.Queue = queue.Queue()
        self._engine = EngineWorker()
        self._budget = EngineBudget()
        self._analysis = AnalysisRunner(self.post_call, self._budget)
        self._live = FenAnalysisRunner()
        self._importer = PuzzleImportRunner(self.post_call, install=self._install_puzzles_file)
        self._coverage = CoverageRunner(self.post_call)
        self._sync = SyncRunner(self.post_call, self._budget)
        self._insights: InsightsRunner | None = None  # created in _boot, needs db_path
        self._relabel = RelabelRunner(
            on_done=lambda: self.post_call(self._start_facts_refill))
        self._books = BookRunner(self.post_call)
        # Friends (FRIENDS-1 C): created here, its threads start at the first friends_ call
        self._friends = FriendsRunner(self.post_call, _emit, lambda: self._db_path)
        self._friends._app_db = lambda: self._db
        self._friends._save_friend_game = self._save_friend_game
        self._facts_refill_running = False
        # COACH-1 C: the coach's moments refill (analysis thread) and the overview (its own thread)
        self._coach: CoachRunner | None = None       # created in _boot, needs db_path
        self._sync.on_finished = self._start_coach_refill
        self._coach_refill_running = False
        self._coach_again = False
        # COACH-2 D (ruling CB1): what background_jobs reports. A game analysis by its run id (the latest is
        # the one running: a new one cancels the one before), the coach's reading by runs done of runs to read.
        self._coach_reading = None
        # Runs a book switch relabelled while a refill was in flight: their facts are deleted
        # again and recomputed when that refill ends (it may have read the old labels).
        self._facts_dirty: set[int] = set()
        self._openings: OpeningsBook | None = None
        self._db: Database | None = None
        self._db_path: Path | None = None
        self._session: GameSession | None = None
        self._skill = SKILL_DEFAULT
        self._running = True

    # ── app-thread loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        self._boot()
        while self._running:
            kind, payload = self._inbox.get()
            if kind == "request":
                self._handle_request(payload)
            elif kind == "call":
                try:
                    payload()
                except Exception:
                    logger.exception("queued call failed")
            elif kind == "stop":
                self._running = False
        self._engine.shutdown()
        self._analysis.shutdown()
        self._live.shutdown()
        self._sync.shutdown()
        self._relabel.shutdown()
        self._books.shutdown()
        self._friends.shutdown()
        if self._insights:
            self._insights.shutdown()
        if self._coach:
            self._coach.shutdown()
        if self._openings:
            self._openings.close()
        if self._db:
            self._db.close()
        logger.info("sidecar stopped")

    def _start_facts_refill(self) -> None:
        """R6-REFILL (PATTERNS.md §6c; the orchestrator's process decision, 2026-11-14):
        refill every complete run with no counting `pattern_facts` row — none at this
        `FACTS_VERSION`, or one computed at another classifier version (a relabel, here or
        by hand) or another `RULE_VERSION` (a rule change, PATTERNS.md §6e) — on the analysis thread, in the dev run and the packaged app alike. App
        thread."""
        if self._db is None or self._db_path is None or self._facts_refill_running:
            return
        try:
            todo = self._db.runs_without_pattern_facts(FACTS_VERSION, rule_version=RULE_VERSION)
        except Exception:
            logger.exception("pattern facts refill: listing runs failed")
            return
        if not todo:
            return
        self._facts_refill_running = True
        logger.info("pattern facts refill: %d runs (facts version %d)", len(todo),
                    FACTS_VERSION)
        written = {"n": 0}

        def on_rows(rows: list) -> None:
            try:
                written["n"] += self._db.save_current_pattern_facts(rows)
            except Exception:
                logger.exception("pattern facts refill: write failed")

        def on_done(stats: dict) -> None:
            self._facts_refill_running = False
            stats["written"] = written["n"]
            logger.info("pattern facts refill done: %s", stats)
            _emit("pattern_facts_refilled", stats)
            if self._facts_dirty:
                self._refill_dirty_facts()

        self._analysis.refill_facts(self._db_path, todo, on_rows, on_done)

    def _start_coach_refill(self) -> None:
        """COACH-1 C: compute the coach's moments for every standard run of the user's that has none at
        this version, on the analysis thread in small batches (a game analysis waits one batch at most),
        then rebuild the overview. Asked again while running: once more when it ends. App thread."""
        if self._db is None or self._db_path is None:
            return
        if self._coach_refill_running:
            self._coach_again = True
            return
        todo = self._db.runs_without_coach_moments(coach_core.COACH_VERSION, THEMES_VERSION)
        if self._coach is not None:
            self._coach.rebuild(pending=len(todo))
        if not todo:
            return
        self._coach_refill_running = True
        logger.info("coach refill: %d runs", len(todo))
        written = {"n": 0}
        self._coach_reading = {"done": 0, "total": len(todo)}
        _emit("coach_progress", dict(self._coach_reading))

        def on_rows(rows: list) -> None:
            try:
                written["n"] += self._db.save_coach_moments(rows)
            except Exception:
                logger.exception("coach refill: write failed")
            self._coach_reading = {"done": min(len(todo), written["n"]), "total": len(todo)}
            _emit("coach_progress", dict(self._coach_reading))
            # the overview follows the refill every 100 runs, so a long first refill shows progress
            if self._coach is not None and written["n"] % 100 < len(rows):
                self._coach.rebuild(pending=max(0, len(todo) - written["n"]))

        def on_done(stats: dict) -> None:
            self._coach_refill_running = False
            self._coach_reading = None
            _emit("coach_progress", {"done": len(todo), "total": len(todo), "finished": True})
            stats["written"] = written["n"]
            logger.info("coach refill done: %s", stats)
            if self._coach_again:
                self._coach_again = False
                self._start_coach_refill()
            elif self._coach is not None:
                self._coach.rebuild(pending=0)

        self._analysis.refill_coach(self._db_path, todo, on_rows, on_done)

    def rpc_coach_overview(self) -> dict:
        """The Coach page (COACH-1 C): Focus and "Behind your focus". Built off this thread; while none
        is ready the answer is {"status": "building"} and a coach_updated event follows."""
        latest = self._coach.latest if self._coach is not None else None
        if latest is None:
            if self._coach is not None:
                self._coach.rebuild(pending=self._coach.pending)
            return {"status": "building"}
        return {"status": "ready", **latest["overview"]}

    # ── Practice (COACH-2 C; core/practice.py) ────────────────────────────────

    def _save_practice_items(self, items: list) -> None:
        """App thread: the missed moments' items (added once; "Added to Practice")."""
        if not items or self._db is None:
            return
        try:
            ids = self._db.add_practice_items(items)
        except Exception:
            logger.exception("practice items not saved")
            return
        if ids:
            logger.info("practice: %d items added", len(ids))
            _emit("practice_updated", self._practice_counts())

    def _practice_state(self):
        items = [practice_core.item_from_row(r) for r in self._db.practice_items()]
        log: dict[int, list] = {}
        for r in self._db.practice_attempt_rows():
            log.setdefault(r["item_id"], []).append(practice_core.attempt_from_row(r))
        latest = self._coach.latest if self._coach is not None else None
        focus = [f["key"] for f in latest["overview"]["focus"]] if latest else []
        return items, log, focus

    def _probes_possible(self) -> bool:
        try:
            return bool(self._db.puzzles_imported())
        except Exception:
            return False

    def _practice_counts(self, grp: str | None = None) -> dict:
        items, log, focus = self._practice_state()
        now = _utcnow()
        q = practice_core.build_queue(items, log, now, focus_keys=focus, grp=grp, probes=self._probes_possible())
        out = practice_core.panel(items, log, now, q, practice_core.seconds_each(log))
        out["probes"] = self._probes_possible()
        out["newPerDay"] = practice_core.NEW_PER_DAY
        return out

    def rpc_practice_status(self, group: str | None = None) -> dict:
        """The Coach page's Practice panel and the sidebar's due count (COACH-2 C)."""
        return self._practice_counts(group)

    def rpc_practice_session(self, group: str | None = None) -> dict:
        """Today's queue (the due items, then the new ones the day's cap allows, probes in their slots), each
        without its theme (ruling 6). *group* narrows it to one focus item ("kind:theme"), a focus card's Practise."""
        items, log, focus = self._practice_state()
        now = _utcnow()
        probes = self._probes_possible()
        q = practice_core.build_queue(items, log, now, focus_keys=focus, grp=group, probes=probes)
        new = list(q.new)
        if q.probe_slots:
            themes = practice_core.probe_themes(items, log, focus)
            if group:
                themes = [group.split(":", 1)[1]]       # a focus card's Practise: probes of its theme only
            rating = self._db.get_puzzle_rating()[0]
            used: set[str] = set()
            for slot in q.probe_slots:
                made = None
                for theme in themes:
                    if theme in used and len(themes) > 1:
                        continue
                    for rng in practice_core.PROBE_RANGES:
                        pz = self._db.pick_probe_puzzle(practice_core.LICHESS_TAG.get(theme, theme), rating, rng)
                        if pz is not None:
                            made = practice_core.probe_item(pz, theme)
                            break
                    if made is not None:
                        used.add(theme)
                        break
                if made is not None:
                    ids = self._db.add_practice_items([made])
                    if ids:
                        made.id = ids[0]
                        new[slot] = made
        queue = q.due + [it for it in new if it is not None]
        return {"items": [practice_core.view(it) for it in queue],
                "secondsEach": practice_core.seconds_each(log), "session": f"{now.isoformat()}"}

    def rpc_practice_answer(self, item_id: int, answer_uci: str | None = None, correct: bool = False,
                            time_ms: int | None = None, hint: bool = False, revealed: bool = False,
                            loss: float | None = None, session: str | None = None) -> dict:
        """Append one attempt to the log (append-only) and answer what the item shows after it: Right / Not quite,
        the sentence, the theme, focus or not, when it comes back. *correct* is the judge's verdict (judge_move, as
        Try it judges: any good move counts); an answer shown counts as wrong."""
        rows = {r["id"]: r for r in self._db.practice_items()}
        if item_id not in rows:
            raise RuntimeError(f"no practice item {item_id}")
        it = practice_core.item_from_row(rows[item_id])
        if answer_uci:
            board = legal_board(it.fen)
            if chess.Move.from_uci(answer_uci) not in board.legal_moves:
                raise RuntimeError(f"{answer_uci} is not legal here")
        now = _utcnow()
        correct = bool(correct) and not revealed
        self._db.add_practice_attempt(item_id=item_id, kind=it.kind, source=it.source, at=now.isoformat(),
                                      answer_uci=answer_uci, correct=correct, time_ms=time_ms, hint=hint,
                                      revealed=revealed, loss=loss, session=session)
        items, log, focus = self._practice_state()
        card = practice_core.card_for(item_id, log.get(item_id, []))
        out = practice_core.reveal(it, answer_uci, correct, revealed, focus, card.due, now)
        out["dueText"] = practice_core.short_when(card.due, now)
        _emit("practice_updated", self._practice_counts())
        return out

    def _coach_patterns(self, game_id: int, run_id: int) -> dict | None:
        """The report's "Your patterns in this game" (COACH-1 C): this run's stored moments, the focus
        keys and the history before this game from the latest overview. None until the run's moments
        are computed."""
        js = self._db.coach_moments_for_run(run_id, coach_core.COACH_VERSION, THEMES_VERSION)
        if js is None:
            return None
        rec = self._db.get_game(game_id)
        game = coach_core.GameMoments(game_id=game_id, key="", played_at=rec.played_at if rec else "",
                                      colour=rec.player_color if rec else "", opponent=None,
                                      fens=self._db.run_fens(run_id), moments=coach_core.moments_from_json(js))
        earlier, focus_keys = self._coach.history(game_id) if self._coach is not None else ({}, set())
        out = coach_core.report_patterns(game, earlier, focus_keys)
        # COACH-2 C (ruling 5): a missed moment in Practice says so ("Added to Practice")
        key = (str(rec.external_id) if rec and rec.external_id else f"local-{game_id}")
        try:
            practised = self._db.practice_keys_for_game(key)
        except Exception:
            practised = set()
        for p in out["items"]:
            p["practice"] = p["outcome"] == "missed" and (p["ply"], "find" if p["kind"] == "chance" else "threat") in practised
        return out

    def _refill_dirty_facts(self) -> None:
        """Delete the facts of runs a book switch relabelled and refill them. App thread."""
        ids = sorted(self._facts_dirty)
        if self._facts_refill_running or not ids or self._db is None:
            return
        self._facts_dirty.clear()
        self._db._conn.executemany("DELETE FROM pattern_facts WHERE run_id=?",
                                   [(i,) for i in ids])
        self._db._conn.commit()
        self._start_facts_refill()

    def _book_switched(self, out: dict) -> None:
        """A book switch finished (BookRunner, posted to the app thread): load the new book,
        drop the trainer's coverage index (it is per book; the lobby rebuilds it), and refill
        the pattern facts of every run whose labels changed."""
        old = self._openings
        self._openings = OpeningsBook()
        if old is not None:
            old.close()
        if self._db is not None:
            self._db._conn.execute("DELETE FROM opening_book_coverage")
            self._db._conn.commit()
        self._facts_dirty.update(out.get("relabelledRuns", []))
        self._refill_dirty_facts()
        _emit("book_done", {k: v for k, v in out.items() if k != "relabelledRuns"})

    def _refuse_during_book_relabel(self) -> None:
        books_runner = getattr(self, "_books", None)    # absent on a bare Server (tests)
        if books_runner is not None and books_runner.relabelling():
            raise RuntimeError("The opening book is being switched; analysis can start when "
                               "it has finished.")

    def post_request(self, req: dict) -> None:
        self._inbox.put(("request", req))

    def post_call(self, fn) -> None:
        self._inbox.put(("call", fn))

    def _install_puzzles_file(self, new_file: Path, _target: Path) -> None:
        """An import's last step, from its thread (COACH-1 F): the app thread's connection detaches
        the puzzle file, the new one replaces it, and it is attached again; the import waits."""
        done = threading.Event()
        failed: list[BaseException] = []

        def run() -> None:
            try:
                self._db.replace_puzzles_file(new_file)
            except BaseException as exc:  # noqa: BLE001 — handed back to the import's thread
                failed.append(exc)
            finally:
                done.set()

        self.post_call(run)
        if not done.wait(600):
            raise RuntimeError("The app did not swap the new puzzle set in.")
        if failed:
            raise failed[0]

    def post_stop(self) -> None:
        self._inbox.put(("stop", None))

    def _boot(self) -> None:
        db_path = Path(os.environ.get("ZUGZWANG_DB", DB_PATH))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._db = Database(db_path)
        self._insights = InsightsRunner(db_path)
        self._coach = CoachRunner(db_path)
        self._coach.on_items = lambda items: self.post_call(lambda: self._save_practice_items(items))
        # After the migrations (Database() ran them), before anything reads labels.
        try:
            self._relabel.check(db_path)
        except Exception:
            logger.exception("relabel check failed")
        # R6-REFILL: missing or stale pattern facts, in the background. A relabel in progress
        # would make them stale again; it starts the refill when it finishes.
        try:
            if self._relabel.state != "running":
                self._start_facts_refill()
        except Exception:
            logger.exception("pattern facts refill not started")   # never a reason to fail boot
        # COACH-1 C: the coach's moments for runs that have none, in the background; the overview
        # is built from what is there now and again when the refill ends.
        try:
            self._start_coach_refill()
        except Exception:
            logger.exception("coach refill not started")
        # BOOK-DL: a book switch the app closed during resumes (its download is done; it
        # backs up again and relabels what is left).
        try:
            from zugzwang.core import books
            st = books.active_state()
            if st and not st.get("relabelled", True):
                logger.info("opening book %s: resuming its relabel", st["id"])
                self._books.start(st["id"], db_path, self._book_switched)
        except Exception:
            logger.exception("opening book resume failed")
        # Before the engine, and unconditionally: nothing the book feeds —
        # opening labels, the whole trainer — needs Stockfish, so gating it on
        # the engine would take the trainer down with a missing binary.
        self._openings = OpeningsBook()
        self._start_engine(find_stockfish())

    def _start_engine(self, sf_path: Path | None) -> bool:
        """Bring the engine up and announce the outcome as `ready`.

        Shared by boot and `set_stockfish_path`, so a user who locates the binary
        after a failed boot lands in the state a successful boot would have left.
        """
        if sf_path is None:
            logger.warning("engine not found")
            _emit("ready", {"ok": False, "error": "Stockfish not found"})
            return False
        self._engine.start(str(sf_path))
        self._engine.ready.wait(timeout=15)
        ok = self._engine.error is None
        # The launch check (packaging/launch_check.py) and a tester's log both read this.
        if ok:
            logger.info("engine ready: %s", sf_path)
        else:
            logger.warning("engine failed to start: %s (%s)", sf_path, self._engine.error)
        _emit("ready", {
            "ok": ok,
            "error": self._engine.error,
            "protocol": PROTOCOL_VERSION,
            "stockfish": str(sf_path),
        })
        return ok

    # ── dispatch ──────────────────────────────────────────────────────────────

    def _handle_request(self, req: dict) -> None:
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}
        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            _reply_error(req_id, f"unknown method: {method}")
            return
        if method.startswith("friends_") and not C.FRIENDS_ENABLED:
            # ruling L4: kept out of packaged builds until the owner approves the legal texts
            _reply_error(req_id, "Friends is not in this build of Zugzwang.")
            return
        try:
            if method in _DEFERRED_METHODS:
                handler(req_id, **params)  # replies from its own thread
            else:
                _reply(req_id, handler(**params))
        except Exception as exc:
            logger.exception("error in %s", method)
            _reply_error(req_id, str(exc))

    # ── methods ───────────────────────────────────────────────────────────────

    def rpc_ping(self) -> dict:
        return {"pong": True, "protocol": PROTOCOL_VERSION}

    def rpc_app_info(self) -> dict:
        """What this build is and where it keeps things (BETA items 2 and 4): the
        Settings "About this build" card and the "flag this" record read it."""
        from zugzwang.build_info import info
        from zugzwang.core.classification import CLASSIFIER_VERSION
        b = info()
        sf = find_stockfish()
        return {
            "version": b["version"], "beta": b["beta"], "commit": b["commit"],
            "builtAt": b["built_at"], "target": b["target"], "frozen": C.FROZEN,
            "dataDir": str(self._db_path.parent if self._db_path else C.USER_DIR),
            "dbPath": str(self._db_path) if self._db_path else None,
            "logPath": str(_log_path()),
            "flagsPath": str(self._flags_path()),
            "flagsDir": str(self._flags_dir_ready()),
            "classifierVersion": CLASSIFIER_VERSION, "ruleVersion": RULE_VERSION,
            "stockfish": str(sf) if sf else None,
            "stockfishSource": C.STOCKFISH_SOURCE_URL,
            "source": C.source_url(b["version"]),
            "licence": "GPL-3.0-or-later",
        }

    # ── opening books (BOOK-DL) ──────────────────────────────────────────────

    def rpc_books_status(self) -> dict:
        """The three books, which are downloaded, which is in use, and any job in flight."""
        return self._books.status()

    def rpc_book_use(self, id: str) -> dict:
        """Download (if needed), verify and switch to book *id*: a verified backup, then the
        book relabel. Only on the user's click; refused while games are being analysed."""
        from zugzwang.core import books
        st = books.active_state()
        if st and st["id"] == id and st.get("relabelled", True):
            return {"started": False, "active": id}
        if self._sync.running() or self._analysis.games_pending:
            raise RuntimeError("Games are being analysed; switch the book when that has finished.")
        if self._relabel.state == "running":
            raise RuntimeError("Labels are being updated; switch the book when that has finished.")
        self._books.start(id, self._db_path, self._book_switched)
        return {"started": True, "id": id}

    def rpc_book_cancel(self) -> dict:
        """Cancels a download (the book in use stays). A relabel, once started, runs to the end."""
        if self._books.job and self._books.job["phase"] == "download":
            self._books.cancel()
            return {"cancelled": True}
        return {"cancelled": False}

    def rpc_relabel_status(self) -> dict:
        """Relabel on update (BETA item 5): idle | manual | running | done | error."""
        return self._relabel.status()

    # ── "flag this" (BETA item 4) ─────────────────────────────────────────────

    def _flags_path(self) -> Path:
        base = self._db_path.parent if self._db_path else C.USER_DIR
        return base / "flags" / "zugzwang-flags.jsonl"

    def _flags_dir_ready(self) -> Path:
        """The flags folder, created so "Show in folder" has something to reveal."""
        d = self._flags_path().parent
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    def rpc_flag_item(self, kind: str, shown: str, note: str = "",
                      game_id: int | None = None, ply: int | None = None,
                      label: str | None = None, context: str | None = None) -> dict:
        """Append one tester flag to `<data>/flags/zugzwang-flags.jsonl` and return its path.

        Keyed the house way (platform game id + ply, CLAUDE.md "Measurement house rule"),
        so the owner can find the ply whatever the tester's database ids are. Written
        locally only: nothing is sent anywhere (BETA scope 4). `kind` is what was flagged
        — label, claim, description, report line, report moment — and `shown` the exact
        text on screen."""
        from zugzwang.build_info import info
        from zugzwang.core.classification import CLASSIFIER_VERSION
        kind = str(kind or "").strip()[:40]
        shown = str(shown or "").strip()
        if not kind or not shown:
            raise RuntimeError("Nothing to flag.")
        rec: dict = {
            "flagged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind, "shown": shown[:2000], "label": label,
            "note": " ".join(str(note or "").split())[:500],
            "context": context,
            "app_version": info()["version"], "build_commit": info()["commit"],
            "classifier_version_app": CLASSIFIER_VERSION, "rule_version": RULE_VERSION,
            "source": None, "platform_game_id": None, "game_id": game_id,
            "ply": ply, "move": None, "fen_before": None, "played_uci": None,
            "run_classifier_version": None, "run_depth": None,
        }
        if game_id is not None and self._db is not None:
            g = self._db.get_game(int(game_id))
            if g is not None:
                rec["source"] = g.source
                rec["platform_game_id"] = g.external_id
                rec["played_at"] = g.played_at
                rec["white"], rec["black"], _, _ = _game_names(g.pgn)
            run = self._db.load_latest_run(int(game_id))
            if run is not None:
                row = self._db._conn.execute(
                    "SELECT classifier_version, depth FROM analysis_runs WHERE id=?",
                    (run.id,)).fetchone()
                if row is not None:
                    rec["run_classifier_version"], rec["run_depth"] = row[0], row[1]
                if ply is not None:
                    ma = next((m for m in self._db.load_move_analyses(run.id)
                               if m.ply == int(ply)), None)
                    if ma is not None:
                        rec["fen_before"], rec["played_uci"] = ma.fen_before, ma.played_uci
                        rec["move"] = f"{int(ply) // 2 + 1}{'.' if int(ply) % 2 == 0 else '...'}"
        path = self._flags_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with path.open(encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.strip())
        logger.info("flag saved: %s ply %s (%s)", rec["platform_game_id"], ply, kind)
        return {"path": str(path), "count": count}

    def rpc_set_active_screen(self, screen: str | None = None) -> dict:
        """The screen the user is looking at, so the engine budget reserves live play
        and the FEN path only while their screens are open (ENG-ALLOC)."""
        self._budget.set_screen(screen)
        return {"screen": screen, "bulkSlots": self._budget.bulk_slots(),
                "cores": self._budget.cores, "ceiling": self._budget.ceiling}

    def rpc_engine_status(self) -> dict:
        """Where Stockfish was resolved from, for the settings screen. Recomputed
        rather than cached because `set_stockfish_path` can change the answer.

        *source* is how it was found (`stockfish_source`: env, bundled, path, chosen);
        *name* is the version the running engine reports over UCI ("Stockfish 18"), given
        only when the running engine is that same binary, else None."""
        path = find_stockfish()
        name = None
        worker = getattr(self, "_engine", None)
        if path is not None and worker is not None and getattr(worker, "_path", None) == str(path):
            name = self._live_engine_version()
        return {"ok": path is not None, "path": None if path is None else str(path),
                "source": stockfish_source(path), "name": name}

    def rpc_set_stockfish_path(self, path: str) -> dict:
        """Adopt a user-picked Stockfish binary, persist it, and re-announce `ready`.

        Validation is a real UCI handshake, not an executable-bit check as the
        PyQt picker does: the mistake worth catching is picking the wrong
        *program*, and only starting it can tell that from a working engine. The
        handshake runs on a throwaway process so a rejected pick leaves the
        currently-running engine, if any, untouched.
        """
        p = Path(path).expanduser()
        try:
            probe = popen_engine(p)
        except Exception as exc:
            raise RuntimeError(f"Not a usable UCI engine: {exc}") from exc
        name = probe.id.get("name", "")
        probe.quit()
        # Persisted before the restart so the choice survives even if starting
        # the real engine then fails for an unrelated reason.
        persist_path(p)
        ok = self._start_engine(p)
        return {"ok": ok, "path": str(p), "name": name}

    def rpc_new_game(self, color: str = "white", skill: int = SKILL_DEFAULT,
                     fen: str | None = None, time_control: str | None = None) -> dict:
        """*time_control*: the clock the app runs, as a PGN TimeControl ("600+0"); written
        into the saved game's headers so it files under its speed. The clocks run in the
        frontend (it flags, see rpc_flag); the clock after each move is saved as [%clk]
        (UI-BUILD-3 F): the user's as the frontend sends it with the move (rpc_user_move), the
        engine's measured here (_apply_engine_move)."""
        self._engine.cancel()
        player_color = chess.WHITE if color == "white" else chess.BLACK
        self._skill = skill
        self._session = GameSession(
            player_color, skill, openings=self._openings, starting_fen=fen,
            time_control=time_control,
        )
        self._session.set_opening_listener(
            lambda eco, name: _emit("opening", {"eco": eco, "name": name})
        )
        engine_to_move = not self._session.is_player_turn()
        if engine_to_move:
            self._request_engine_move()
        return {"fen": self._session.board.fen(), "engineToMove": engine_to_move}

    def rpc_user_move(self, uci: str, clock_ms: float | None = None) -> dict:
        """*clock_ms*: the user's clock after this move, increment included, as the frontend
        shows it (UI-BUILD-3 F). Optional: an older frontend sends none, and the game then
        saves no clocks (GameSession.has_clocks)."""
        session = self._require_session()
        move = chess.Move.from_uci(uci)
        if move not in session.board.legal_moves:
            return {"ok": False, "fen": session.board.fen()}
        san = session.board.san(move)
        clock = (clock_ms / 1000.0 if isinstance(clock_ms, (int, float))
                 and not isinstance(clock_ms, bool) else None)
        end = session.push(move, clock)
        if end is None:
            self._request_engine_move()
        return {"ok": True, "san": san, "fen": session.board.fen(),
                "end": self._finish(end)}

    def rpc_resign(self) -> dict:
        session = self._require_session()
        self._engine.cancel()
        return {"end": self._finish(session.resign())}

    def rpc_draw(self) -> dict:
        """The user offers a draw (COACH.md ruling 8, DESIGN.md "Owner rulings, 2026-11-23"): accepted only
        from move 30 on and only when the engine's own evaluation does not favour it; otherwise the game goes
        on and the answer carries the message to show, which never states or implies an evaluation."""
        session = self._require_session()
        last = getattr(self._engine, "last_eval", None)
        if last is not None:              # only an evaluation of this game's own positions counts
            b = session.board.root()
            seen = {b.fen()}
            for mv in session.board.move_stack:
                b.push(mv)
                seen.add(b.fen())
            if last[0] not in seen:
                last = None
        verdict = draw_decision(session.board.fullmove_number, last)
        if verdict is not None:
            return {"end": None, "declined": verdict}
        self._engine.cancel()
        return {"end": self._finish(session.draw_agreed())}

    def rpc_flag(self, loser: str) -> dict:
        """A clock hit zero. The frontend owns clock timing (as the Qt UI did);
        the sidecar finalizes and saves the result."""
        session = self._require_session()
        self._engine.cancel()
        result = "0-1" if loser == "white" else "1-0"
        end = session._finalize("timeout", result)
        return {"end": self._finish(end)}

    def rpc_abandon(self) -> dict:
        session = self._require_session()
        self._engine.cancel()
        return {"end": self._finish(session.abandon())}

    def rpc_get_state(self) -> dict:
        session = self._session
        if session is None:
            return {"active": False}
        return {
            "active": not session.over,
            "fen": session.board.fen(),
            "playerColor": "white" if session.player_color == chess.WHITE else "black",
            "skill": session.skill_level,
        }

    # ── games / review ────────────────────────────────────────────────────────

    def rpc_list_games(self, limit: int | None = None) -> dict:
        games = []
        for rec, run in self._db.list_games_with_runs(limit):
            d = _game_dict(rec)
            d["whiteAccuracy"] = run.white_accuracy if run else None
            d["blackAccuracy"] = run.black_accuracy if run else None
            d["analyzed"] = run is not None
            games.append(d)
        return {"games": games}

    def rpc_games_page(self, **params) -> dict:
        """The Games screen's page (UI-BUILD-3 E; core/games_list.py): the games under the
        screen's filters, `offset`/`limit` at a time, the count they keep, and each month's
        record over all of them. Both players' accuracies from the standard run."""
        return GL.games_page(self._db._conn, GL.GamesQuery.from_params(params))

    def rpc_get_game(self, game_id: int, run_id: int | None = None) -> dict:
        rec = self._db.get_game(game_id)
        if rec is None:
            raise RuntimeError(f"no game with id {game_id}")
        game = chess.pgn.read_game(io.StringIO(rec.pgn))
        if game is None:
            raise RuntimeError("stored PGN could not be parsed")

        board = game.board()
        start_fen = board.fen()
        plies = []
        last_opening: tuple[str, str] | None = None
        for move in game.mainline_moves():
            uci = move.uci()
            san = board.san(move)
            board.push(move)
            if self._openings is not None:
                found = self._openings.name_after(board)
                if found is not None:
                    last_opening = found
            plies.append({
                "san": san,
                "uci": uci,
                "fen": board.fen(),
                "check": board.is_check(),
                "opening": (
                    {"eco": last_opening[0], "name": last_opening[1]}
                    if last_opening else None
                ),
            })

        out = _game_dict(rec)
        out["startFen"] = start_fen
        out["plies"] = plies
        out["white"] = game.headers.get("White", "White")
        out["black"] = game.headers.get("Black", "Black")

        # RUNS-DEPTH: the deepest complete run unless Review asked for another of the game's.
        run = self._db.load_review_run(rec.id, run_id)
        out["runs"] = [{"id": r.id, "depth": r.depth, "engine": r.engine_name,
                        "completedAt": r.completed_at, "standard": r.standard}
                       for r in self._db.list_complete_runs(rec.id)]
        if run is not None:
            analyses = self._db.load_move_analyses(run.id)
            out["analysis"] = {
                "runId": run.id,
                "depth": run.depth,
                "whiteAccuracy": run.white_accuracy,
                "blackAccuracy": run.black_accuracy,
                "summary": json.loads(run.payload_json or "{}"),
                "moves": [_ma_dict(ma) for ma in analyses],
            }
        else:
            out["analysis"] = None
        return out

    def rpc_explain_move(self, game_id: int, ply: int, run_id: int | None = None) -> dict:
        """Structured findings plus rendered sentences for one analysed ply.

        Reads the stored row rather than taking the position from the caller. The
        frontend has `fen` and `playedUci` already and could pass them, but then the
        frontend would be assembling the rule layer's inputs — and an omitted engine
        score there is silent, not an error. See `explain_stored_ply`.

        No engine, no network, no state. Cheap enough to serve on demand; see
        `review/scratch/explain_rpc_cost.py` for the measurement behind that.

        The game is loaded for one field, `player_color`, which decides whether a
        sentence about the played move addresses the reader or names the side. The
        stored ply does not carry it.

        *run_id* picks one of the game's complete runs (Review's run switch, RUNS-DEPTH);
        none, the deepest.
        """
        run = self._db.load_review_run(game_id, run_id)
        if run is None:
            return {"ply": ply, "findings": [], "sentences": [], "analysed": False}
        by_ply = {ma.ply: ma for ma in self._db.load_move_analyses(run.id)}
        match = by_ply.get(ply)
        if match is None:
            return {"ply": ply, "findings": [], "sentences": [], "analysed": False}
        rec = self._db.get_game(game_id)
        # The rest of the run: an ignored threat repeated move after move is said in
        # full once, where the lesson is, then "still hanging" (EXPLANATIONS.md); the
        # next ply's line is this move's refutation (stage 2); D1/D3 remember the game.
        rows = {p: {**stored_ply_row(ma), "pv_uci": ma.pv_uci, "lines": ma.lines,
                    "hard_only_move": ma.hard_only_move}
                for p, ma in by_ply.items()}
        full = explain_ply_full(
            rows, ply,
            # A game whose side is unknown names both players (O5).
            (rec.player_color or UNKNOWN_SIDE) if rec is not None else None,
            final_lines=run.final_lines,
        )
        return {
            "ply": ply,
            "findings": [f.to_dict() for f in full.findings],
            # Unchanged: the rule layer's sentences only (layer 5).
            "sentences": full.sentences,
            # Layer 5: claims and descriptions in separate arrays, never joined. A claim
            # from the engine's line passed gate P; a description carries no causation.
            # What the Review callout shows: the engine-line claim where there is one
            # (reversed precedence, owner 2026-11-09, provisional), else the rule sentences.
            "claims": [{"type": "claim", "source": src, "text": t,
                        **({"line": list(full.pv_claim_line)} if src == "engine_line" else {})}
                       for src, t in full.shown_claims],
            "descriptions": [{"type": "description", "descriptor": k, "text": str(t)}
                             for k, t in full.descriptions],
            "bestSan": full.best_san,
            "analysed": True,
            "ruleVersion": RULE_VERSION,
        }

    def rpc_game_report(self, game_id: int, run_id: int | None = None) -> dict:
        """The game report: moments, point of no return, ending, what it cost.

        Engine-free and computed on every call from the stored run; see
        `core/game_report.py` and GAME_REPORT.md. The game length comes from the
        PGN, not `games.move_count`, because a run shorter than the game (W12)
        has to be detected, and that comparison needs the true ply count.
        """
        rec = self._db.get_game(game_id)
        if rec is None:
            raise RuntimeError(f"no game with id {game_id}")
        game = chess.pgn.read_game(io.StringIO(rec.pgn))
        nodes = list(game.mainline()) if game is not None else []
        # (fen before, uci) per move, for the opening line — which needs the book,
        # not the engine, so an unanalysed game still gets it.
        pgn_moves = []
        board = game.board() if game is not None else None
        for n in nodes:   # one walk: `node.board()` replays from the root each call
            pgn_moves.append((board.fen(), n.move.uci()))
            board.push(n.move)
        book = getattr(self, "_openings", None)
        run = self._db.load_review_run(game_id, run_id)      # RUNS-DEPTH
        if run is None:
            op = opening_exit(pgn_moves, book)
            return {
                "analysed": False,
                "opening": op,
                "lines": [opening_sentence(op, rec.player_color, None)] if op else [],
            }
        report = build_report(
            self._db.load_move_analyses(run.id),
            game_plies=len(nodes),
            result=rec.result,
            termination=rec.termination,
            player_color=rec.player_color,
            depth=run.depth,
            clocks=[n.clock() for n in nodes],
            time_control=game.headers.get("TimeControl") if game is not None else None,
            pgn_moves=pgn_moves,
            book=book,
            final_lines=run.final_lines,
        )
        try:
            report["patterns"] = self._coach_patterns(game_id, run.id)   # COACH-1 C
        except Exception:
            logger.exception("coach patterns for game %s not built", game_id)
            report["patterns"] = None
        return report

    def rpc_review_extras(self, game_id: int, run_id: int | None = None) -> dict:
        """Read-only figures for the redesigned Review (UI-BUILD B3; core/review_extras.py):
        the game's own phase division, accuracy by phase, each error's tactical or
        positional kind (gate P, ruling 3) and the clocks. Engine-free, from the PGN and
        the stored run; an unanalysed game still gets its phases and clocks."""
        rec = self._db.get_game(game_id)
        if rec is None:
            raise RuntimeError(f"no game with id {game_id}")
        game = chess.pgn.read_game(io.StringIO(rec.pgn))
        nodes = list(game.mainline()) if game is not None else []
        board = game.board() if game is not None else chess.Board()
        fens = RX.fens_before_moves(board, [n.move for n in nodes])
        middle, end = RX.division(fens)
        clocks = RX.clock_series([n.clock() for n in nodes],
                                 game.headers.get("TimeControl") if game is not None else None,
                                 white_first=board.turn == chess.WHITE)
        out: dict = {"analysed": False, "depth": None, "plies": len(nodes),
                     "phases": {"middlegame": middle, "endgame": end}, "clock": clocks,
                     "accuracyByPhase": None, "errors": [], "errorCounts": None}
        run = self._db.load_review_run(game_id, run_id)      # RUNS-DEPTH
        if run is None:
            return out
        mas = self._db.load_move_analyses(run.id)
        rows = {ma.ply: {**stored_ply_row(ma), "pv_uci": ma.pv_uci, "lines": ma.lines,
                         "hard_only_move": ma.hard_only_move} for ma in mas}
        phases = RX.phase_of_plies([ma.fen_before for ma in mas])
        scores = [PlyScore("white" if " w " in ma.fen_before else "black",
                           ma.score_before_cp, ma.score_before_mate,
                           ma.score_after_cp, ma.score_after_mate) for ma in mas]
        errors = RX.error_kinds(rows, run.final_lines)
        out.update({"analysed": True, "depth": run.depth,
                    "accuracyByPhase": RX.accuracy_by_phase(scores, phases),
                    "errors": errors, "errorCounts": RX.error_counts(errors)})
        return out

    def rpc_home_summary(self, now: str | None = None) -> dict:
        """Read-only figures for the redesigned Home (UI-BUILD C; core/home_summary.py):
        games and analysed counts, average accuracy, win rate, ratings per time control
        with their 30-day change, the puzzle rating, and the five latest games. *now* (ISO)
        is for tests; the app sends none."""
        t = HS.parse_time(now) if now else None
        when = t or datetime.now(timezone.utc)
        rows = self._db._conn.execute(
            """SELECT g.id, g.played_at, g.player_color, g.result, g.termination, g.source,
                      g.speed, g.pgn, g.opening_eco, g.opening_name,
                      r.white_accuracy, r.black_accuracy, r.id IS NOT NULL
               FROM games g LEFT JOIN analysis_runs r
                 ON r.game_id = g.id AND r.completed_at IS NOT NULL
                    AND """ + standard_run_sql()).fetchall()     # RUNS-DEPTH: depth-14 runs only
        out = HS.summarize(rows, when)
        try:
            attempts = self._db._conn.execute(
                "SELECT attempted_at, rating_before, rating_after FROM puzzle_attempts").fetchall()
            cur = self._db._conn.execute(
                "SELECT rating FROM puzzle_rating ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            attempts, cur = [], None
        p = HS.puzzle_row(attempts, cur[0] if cur else None, when)
        out["puzzles"] = p
        return out

    def rpc_analyze_game(self, game_id: int, depth: int | None = None) -> dict:
        self._refuse_during_book_relabel()
        rec = self._db.get_game(game_id)
        if rec is None:
            raise RuntimeError(f"no game with id {game_id}")
        if depth is not None and not (
                C.ANALYSIS_DEPTH_MIN <= int(depth) <= C.ANALYSIS_AGAIN_DEPTH_MAX):
            # Analyse again goes to 24 for one game (ruling 7); nothing goes deeper.
            raise ValueError(f"depth {depth} is outside {C.ANALYSIS_DEPTH_MIN}.."
                             f"{C.ANALYSIS_AGAIN_DEPTH_MAX}")
        # No depth sent: the standard depth (ruling 17; was ANALYSIS_DEPTH, 18, RA-DEPTH).
        depth = int(depth) if depth else int(C.ANALYSIS_STANDARD_DEPTH)
        self._analysis.cancel()  # stop any in-flight run first
        run_id = self._db.save_analysis_run(
            game_id=game_id, engine_name="Stockfish", depth=depth,
            provenance=provenance.engine_run(
                engine_name=self._live_engine_version() or self._analysis_engine_version(),
                engine_path=find_stockfish(), depth=depth,
                has_book=self._openings is not None and self._openings.has_book),
        )
        self._analysis_jobs[run_id] = {"gameId": game_id, "runId": run_id, "depth": depth, "done": 0,
                                       "total": 0}
        self._analysis.analyze_game(
            game_id, run_id, rec.pgn, depth, self._openings, self._on_analysis_event,
        )
        return {"runId": run_id, "depth": depth}

    def rpc_cancel_analysis(self) -> dict:
        self._analysis.cancel()
        return {"ok": True}

    def _on_analysis_event(self, game_id: int, run_id: int, event: tuple) -> None:
        """Runs on the app thread: persist then emit, mirroring
        MainWindow._on_ply_analyzed / _on_analysis_finished."""
        kind = event[0]
        job = self._analysis_jobs.get(run_id)
        tag = {"runId": run_id, "depth": job["depth"] if job else None}     # ruling CB1: whose events
        if kind != "ply":
            self._analysis_jobs.pop(run_id, None)    # over: done, cancelled, failed
        if kind == "ply":
            _, ply, total, ma = event
            self._db.save_move_analysis(run_id, ma)
            if job is not None:
                job.update(done=ply + 1, total=total)
            _emit("analysis_ply", {
                "gameId": game_id, "ply": ply, "total": total,
                "analysis": _ma_dict(ma), **tag,
            })
        elif kind == "done":
            summary = event[1]
            white_acc = (summary.get("white") or {}).get("accuracy")
            black_acc = (summary.get("black") or {}).get("accuracy")
            try:
                # The run becomes the game's analysis only here, whole (VAL-DEATH).
                self._db.complete_analysis_run(
                    run_id, summary, white_accuracy=white_acc, black_accuracy=black_acc,
                    final_lines=event[2],
                )
            except IncompleteRun as exc:
                _emit("analysis_error", {"gameId": game_id, "message": str(exc), **tag})
                return
            _write_pattern_facts(self._db, run_id)
            _emit("analysis_done", {
                "gameId": game_id, "summary": summary,
                "whiteAccuracy": white_acc, "blackAccuracy": black_acc, **tag,
            })
            try:
                self._start_coach_refill()        # COACH-1 C: this game's moments, then the overview
            except Exception:
                logger.exception("coach refill not started")
        elif kind == "cancelled":
            _emit("analysis_cancelled", {"gameId": game_id, **tag})
        elif kind == "error":
            _emit("analysis_error", {"gameId": game_id, "message": event[1], **tag})
        elif kind == "engine_died":
            # The run stays incomplete — never shown, never counted — and the game's
            # previous analysis, if it had one, is untouched.
            _, ply, fen, exc = event
            message = _death_message(fen, exc)
            rec = self._db.get_game(game_id)
            self._db.record_engine_failure(
                context="reanalyse", fen=getattr(exc, "fen", None) or fen, message=str(exc),
                source=rec.source if rec else None,
                external_id=rec.external_id if rec else None,
                game_id=game_id, ply=ply, exit_code=getattr(exc, "exit_code", None),
                engine=getattr(exc, "version", None) or self._analysis_engine_version(),
            )
            _emit("analysis_error", {"gameId": game_id, "message": message, **tag})

    def _live_engine_version(self) -> str | None:
        """The binary's version as the running live engine reports it — the same
        binary every analysis engine resolves to."""
        engine = getattr(getattr(self, "_engine", None), "_engine", None)
        return engine.id.get("name") if engine is not None else None

    def _analysis_engine_version(self) -> str | None:
        return self._analysis._engine.version

    def rpc_import_pgn(self, pgn: str = "", usernames: list | None = None,
                       path: str | None = None) -> dict:
        """Import every game in the PGN (Gap A), detecting the user's colour
        from the White/Black headers via *usernames* (Gap B).

        *path* is the file-picker route and takes precedence over *pgn*. The file
        is read here rather than in the webview because an archive export runs to
        tens of megabytes, and sending that through the NDJSON pipe would mean
        holding three copies of it (JS string, JSON encoding, Python string) to
        move a file the sidecar can open directly.

        Reports per game. The single catch-all this replaces fired only when
        *nothing* parsed, which meant the worse case said nothing at all: a game
        python-chess gave up partway through was stored truncated and counted as a
        success.
        """
        if path:
            p = Path(path).expanduser()
            try:
                pgn = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise RuntimeError(f"Could not read {p.name}: {exc}") from exc
        report = parse_pgn_report(
            pgn, usernames=usernames or [], openings=self._openings,
        )
        parsed = report.games
        if not parsed:
            # There is no way to say "this isn't a PGN": python-chess returns a
            # game with default headers and no moves for *any* non-empty text, so
            # a paste of prose and a file of aborted games are literally the same
            # parse. Hence one message that covers both causes rather than a
            # confident guess between them.
            n = len(report.issues)
            raise RuntimeError(
                f"Found {n} game(s) in the PGN but none had any moves — the games "
                "may be aborted, or this may not be PGN at all."
                if n
                else "Nothing to import — the PGN is empty."
            )

        game_ids: list[int] = []
        refused: list[dict] = []
        # The platform game id is stored (FIXPLAN IMPORT-EXTID), so a game already in
        # the library — synced, or imported before, or twice in this file — is skipped
        # and reported, not duplicated. Games 32, 42 and 278 were such duplicates.
        known = self._db.all_external_ids()
        for n, pg in enumerate(parsed):
            if pg.external_id and pg.external_id in known:
                refused.append({"index": n, "label": _pgn_label(pg.pgn),
                                "reason": f"already in your library (game {pg.external_id})",
                                "imported": False})
                continue
            try:
                game_ids.append(self._db.save_game(
                    played_at=pg.played_at,
                    player_color=pg.player_color,
                    skill_level=0,
                    result=pg.result,
                    termination=pg.termination,
                    move_count=pg.move_count,
                    pgn=pg.pgn,
                    final_fen=pg.final_fen,
                    opening_eco=pg.opening_eco,
                    opening_name=pg.opening_name,
                    source="imported",
                    external_id=pg.external_id,
                    not_owner=pg.not_owner,
                ))
                if pg.external_id:
                    known.add(pg.external_id)
            except AttributionPending as exc:
                # Per game, not per file: one game nobody can attribute must not
                # abort the rest, and must not be stored under a guessed colour.
                refused.append({"index": n, "label": _pgn_label(pg.pgn),
                                "reason": str(exc), "imported": False})
        if not game_ids:
            raise RuntimeError(refused[0]["reason"] if refused else "Nothing imported.")
        # gameId kept for back-compat (first game); gameIds is the full list.
        return {
            "gameId": game_ids[0],
            "gameIds": game_ids,
            "count": len(game_ids),
            "issues": [
                {
                    "index": i.index,
                    "label": i.label,
                    "reason": i.reason,
                    "imported": i.imported,
                }
                for i in report.issues
            ] + refused,
        }

    def rpc_analyze_fen(self, fen: str) -> dict:
        legal_board(fen)  # legality, not just syntax, before an engine sees it (VAL-FEN)
        self._live.analyze(fen)
        return {"ok": True}

    def rpc_judge_move(self, fen: str, uci: str) -> dict:
        """Judge a move played from a game-report moment ("Try it"), on the live
        engine; the verdict arrives as a `move_judged` event carrying this token.
        See `core/retry.py` — the judge errs toward accepting."""
        board = legal_board(fen)
        if chess.Move.from_uci(uci) not in board.legal_moves:
            raise RuntimeError(f"{uci} is not legal here")
        return {"token": self._live.judge(fen, uci)}

    def rpc_probe_move(self, fen: str, uci: str) -> dict:
        """Play one move on a throwaway board and report where it lands.

        Exploration in the review screen needs a position per node, and board truth
        belongs here rather than in the webview's chess.js. No engine and no
        database: this is pure python-chess, so it answers on the dispatch thread.

        `legal: false` carries no position — an illegal move has no landing square,
        and inventing one is how a node ends up holding a fen nobody can reach.
        Its result feeds the FEN path, so an illegal start is refused here too.
        """
        board = legal_board(fen)
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return {"legal": False}
        if move not in board.legal_moves:
            return {"legal": False}
        san = board.san(move)
        board.push(move)
        return {
            "legal": True,
            "fen": board.fen(),
            "san": san,
            "check": board.is_check(),
            "gameOver": board.is_game_over(),
        }

    # ── platform sync ───────────────────────────────────────────────────────────

    @staticmethod
    def _clamp_depth(depth: int | None) -> int:
        """The depth sync and "Analyse more" analyse at: **always the standard depth**
        (`ANALYSIS_STANDARD_DEPTH`, 14), whatever a client sends (owner rulings 17 and
        RUNS-DEPTH, 2026-11-20: every game is analysed at depth 14 so all games compare; a
        sync at another depth would write runs no aggregate reads and queue the games
        forever). One game goes deeper only through Analyse again."""
        return int(C.ANALYSIS_STANDARD_DEPTH)

    def rpc_sync_status(self, depth: int | None = None) -> dict:
        min_depth = self._clamp_depth(depth)

        def counts(source: str) -> dict:
            total = self._db._conn.execute(
                "SELECT count(*) FROM games WHERE source=?", (source,)
            ).fetchone()[0]
            pending = len(self._db.games_pending_analysis(source, min_depth))
            # Queued no more (VAL-DEATH-2), so counted apart from the work one click does.
            stuck = self._db.needs_attention_ids(source, self._live_engine_version())
            # `pending` mixes two things a label must not conflate (W15): games with
            # no run at all, and games analysed below *min_depth*, which the bulk
            # action re-analyses. Only the first are unanalysed.
            unanalysed = self._db._conn.execute(
                "SELECT count(*) FROM games g WHERE g.source=? AND NOT EXISTS "
                "(SELECT 1 FROM analysis_runs r WHERE r.game_id = g.id"
                " AND r.completed_at IS NOT NULL)",
                (source,),
            ).fetchone()[0]
            return {"synced": total, "pending": pending - len(stuck),
                    "unanalysed": unanalysed - len(stuck),
                    "belowDepth": pending - unanalysed, "depth": min_depth,
                    "needsAttention": len(stuck)}

        return {
            "syncing": self._sync.running(),
            "run": self._sync.run_id,       # the current or last run (ruling CB2)
            "lichess": counts("lichess"),
            "chesscom": counts("chesscom"),
        }

    def rpc_background_jobs(self) -> dict:
        """COACH-2 D (ruling CB1): everything running in the background, for the sidebar's activity line, the
        Review header and the Games rows; the webview's store reads it at start and keeps it from the events.
        Each has the run id its events carry, so a snapshot never revives a run whose end was announced."""
        analysis = max(self._analysis_jobs.values(), key=lambda j: j["runId"], default=None)
        sync = self._sync
        imp = self._importer
        return {
            "sync": {"running": sync.running(), "run": sync.run_id, "kind": sync.kind,
                     "progress": sync.last_progress if sync.running() else None},
            "analysis": dict(analysis) if analysis else None,
            "coach": dict(self._coach_reading) if self._coach_reading else None,
            "puzzles": {"running": imp.running(), "run": imp.run_id, "kind": imp.kind if imp.running() else None,
                        "progress": imp.last_progress if imp.running() else None},
        }

    def rpc_check_usernames(self, req_id, chesscom: str = "", lichess: str = "") -> None:
        """Settings' check on Save (UI-BUILD-3 G, ruling 5): whether each username is a player on
        its site. Deferred: the two GETs run on a thread of their own and reply when both are
        done, within USERNAME_CHECK_TIMEOUT_S plus a second, so the dispatch loop never waits on
        the network. Replies {"chesscom": result | null, "lichess": result | null}, a result
        being {"status": "found" | "not_found" | "unreachable", "message": str | null}; null for
        an empty name, which is not checked."""
        names = {"chesscom": chesscom if isinstance(chesscom, str) else "",
                 "lichess": lichess if isinstance(lichess, str) else ""}

        def run() -> None:
            try:
                result = check_usernames(names)
            except Exception as exc:
                logger.exception("username check failed")
                _reply_error(req_id, str(exc))
                return
            _reply(req_id, result)

        threading.Thread(target=run, name="username-check", daemon=True).start()

    def rpc_start_sync(
        self, lichess: str = "", chesscom: str = "", depth: int | None = None
    ) -> dict:
        """Sync the player's recent rated games from any configured platforms.
        *usernames* is the full set of the player's handles so colour detection
        works across platforms. *depth* is the Stockfish search depth for games
        analysed locally (clamped into the supported range)."""
        lichess = (lichess or "").strip()
        chesscom = (chesscom or "").strip()
        if not lichess and not chesscom:
            raise RuntimeError("No platform username configured.")
        self._refuse_during_book_relabel()
        if self._sync.running():
            raise RuntimeError("A sync is already running.")
        usernames = [u for u in (lichess, chesscom) if u]
        # Fix any previously-imported games whose colour was stored before the
        # username was known (they default to white).
        self._db.repair_player_colors(usernames)
        jobs: list[tuple[str, str]] = []
        if lichess:
            jobs.append(("lichess", lichess))
        if chesscom:
            jobs.append(("chesscom", chesscom))
        self._sync.start(
            jobs=jobs, usernames=usernames, db_path=self._db_path,
            depth=self._clamp_depth(depth),
        )
        return {"started": True, "sources": [s for s, _ in jobs]}

    def rpc_analyze_pending(self, source: str = "", depth: int | None = None,
                            count: int | None = None,
                            game_ids: list | None = None) -> dict:
        """Analyse already-synced games that still lack a satisfying run, without
        re-fetching from the network. *source* picks one platform ('lichess' /
        'chesscom'); empty means all synced platforms. *depth* is clamped like
        sync, so selecting a deeper depth re-queues shallower games. *count* is
        "Analyse more" in a step the user chose: the *count* most recent pending
        games; omitted, all of them (BETA-PUB Q4). Newest first either way.

        *game_ids* (UI-BUILD-3 E: Import PGN's "analysed at depth 14") queues exactly those
        games, of any source, that still lack a satisfying standard run, through the same bulk
        queue and its `sync_*` events; *source* and *count* are then ignored."""
        if self._sync.running():
            raise RuntimeError("A sync is already running.")
        self._refuse_during_book_relabel()
        depth = self._clamp_depth(depth)
        if game_ids is not None:
            wanted = {int(g) for g in game_ids}
            done = self._db.games_with_standard_run(wanted, depth)
            records = [rec for gid in sorted(wanted - done)
                       if (rec := self._db.get_game(gid)) is not None]
            records.sort(key=lambda r: (r.played_at or "", r.id), reverse=True)
            chosen: dict[str, list] = {}
            for rec in records:
                chosen.setdefault(rec.source, []).append(rec)
            self._sync.start_analyze(sources=list(chosen), db_path=self._db_path, depth=depth,
                                     chosen=chosen)
            return {"started": True, "sources": list(chosen), "count": len(records)}
        if count is not None:
            count = int(count)
            if count < 1:
                raise RuntimeError("count must be at least 1")
        sources = [source] if source else ["lichess", "chesscom"]
        self._sync.start_analyze(
            sources=sources, db_path=self._db_path, depth=depth,
            count=count,
        )
        return {"started": True, "sources": sources, "count": count}

    def rpc_cancel_sync(self) -> dict:
        self._sync.cancel()
        return {"ok": True}

    def rpc_repair_colors(self, lichess: str = "", chesscom: str = "") -> dict:
        """Re-detect stored game colours from their PGN headers (fixes games
        imported before the username was set)."""
        usernames = [u for u in ((lichess or "").strip(), (chesscom or "").strip()) if u]
        changed = self._db.repair_player_colors(usernames)
        return {"changed": changed}

    # ── insights ──────────────────────────────────────────────────────────────

    def rpc_insights(
        self,
        req_id,
        color: str = "all",
        speeds: list[str] | None = None,
        since: str | None = None,
        rated: str = "all",
        include_local: bool = False,
        view: str = "full",
    ) -> None:
        """Deferred: hands off to InsightsRunner, which replies when done. *view* "v2" is the
        redesigned screen's payload (core/insights_v2.py, UI-BUILD-2 C)."""
        self._insights.submit(
            req_id,
            {
                "color": color,
                "speeds": speeds,
                "since": since,
                "rated": rated,
                "include_local": include_local,
                "view": "v2" if view == "v2" else "full",
            },
        )

    # ── puzzles ───────────────────────────────────────────────────────────────

    def rpc_puzzle_status(self) -> dict:
        """The lobby's state, and the copy you have (FIX-B6 B): its count from the import, its
        date from Lichess's file (the Last-Modified it was served with); a file import has no
        publication date, only the day it was imported."""
        rating, rd, _vol = self._db.get_puzzle_rating()
        conn = self._db._conn
        count_row = conn.execute("SELECT count(*) FROM puzzles").fetchone()
        meta = dict(conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('puzzles_source', 'puzzles_source_date',"
            " 'puzzles_imported_at', 'puzzles_source_bytes')").fetchall())
        return {
            "imported": self._db.puzzles_imported(),
            "count": count_row[0] if count_row else 0,
            "importing": self._importer.running(),
            "importKind": self._importer.kind if self._importer.running() else None,
            "importRun": self._importer.run_id,
            "source": meta.get("puzzles_source") or None,
            "sourceDate": meta.get("puzzles_source_date") or None,
            "importedAt": meta.get("puzzles_imported_at") or None,
            "rating": rating,
            "rd": rd,
            "csvPath": str(C.PUZZLE_CSV_PATH),
            "csvExists": C.PUZZLE_CSV_PATH.exists(),
        }

    def rpc_import_puzzles(self, csv_path: str | None = None) -> dict:
        """Import a puzzle file the user picked, for offline use: the CSV, or Lichess's .zst as
        downloaded (decompressed as it is read). Checked here, on the request, so a missing file
        is an answer to the click rather than an error event later."""
        path = Path(csv_path).expanduser() if csv_path else C.PUZZLE_CSV_PATH
        if not path.exists():
            raise RuntimeError(f"No such file: {path}")
        self._importer.start(path, self._db_path, self._on_import_done)
        return {"started": True}

    def rpc_download_puzzles(self) -> dict:
        """Download Lichess's puzzle file and import it as it arrives (FIX-B6 B, PZ1)."""
        self._importer.start_download(self._db_path, self._on_import_done)
        return {"started": True}

    def rpc_puzzle_check_update(self, req_id) -> None:
        """"Check for new puzzles": what Lichess serves now (a HEAD request), against the copy you
        have. Deferred (a thread), so the dispatch loop never waits on the network. Replies
        {date, bytes, newer}: newer is true when the copy came from a file, or Lichess's file is
        not the one imported (its ETag or date differs)."""
        conn = self._db._conn
        meta = dict(conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('puzzles_source', 'puzzles_source_date',"
            " 'puzzles_source_etag')").fetchall())

        def run() -> None:
            try:
                info = lichess_file_info()
            except Exception as exc:
                logger.warning("puzzle update check failed: %s", exc)
                _reply_error(req_id, f"Lichess could not be reached: {getattr(exc, 'reason', None) or exc}.")
                return
            have_etag = meta.get("puzzles_source_etag") or ""
            have_date = meta.get("puzzles_source_date") or ""
            newer = (meta.get("puzzles_source") != "lichess"
                     or (bool(info["etag"]) and info["etag"] != have_etag)
                     or (bool(info["date"]) and info["date"] > have_date))
            _reply(req_id, {"date": info["date"] or None, "bytes": info["bytes"], "newer": newer})

        threading.Thread(target=run, name="puzzle-check", daemon=True).start()

    def rpc_cancel_puzzle_import(self) -> dict:
        self._importer.cancel()
        return {"ok": True}

    def _on_import_done(self, stats: dict) -> None:
        """App thread: the import wrote its meta inside the swap; tell the webview."""
        logger.info("puzzle import done: %s", stats)
        _emit("puzzle_import_done", {"count": stats["count"], "added": stats["added"],
                                     "removed": stats["removed"],
                                     "removedAttempted": stats["removed_attempted"],
                                     "run": self._importer.run_id})

    def rpc_get_puzzle_rating(self) -> dict:
        rating, rd, volatility = self._db.get_puzzle_rating()
        return {"rating": rating, "rd": rd, "volatility": volatility}

    def rpc_next_puzzles(self, target_rating: float, rating_range: int,
                         themes: list[str] | None = None, limit: int = 10) -> dict:
        records = self._db.select_puzzles(
            user_rating=target_rating,
            rating_range=rating_range,
            themes=themes if themes else None,
            limit=limit,
        )
        return {"puzzles": [
            {
                "id": p.id,
                "fen": p.fen,
                "movesUci": p.moves_uci,
                "rating": p.rating,
                "ratingDeviation": p.rating_deviation,
                "themes": p.themes,
                # Precomputed here, not in Svelte: deciding what mates is chess
                # knowledge, and the replay it needs is cheap at fetch time (one
                # pass over a handful of puzzles) where the frontend would need a
                # full move generator to answer the same question per move.
                "finalMates": alternate_final_mates(p.fen, p.moves_uci),
            }
            for p in records
        ]}

    def rpc_rate_puzzle(self, puzzle_rating: int, puzzle_rd: int, outcome: float) -> dict:
        """Apply the Glicko-2 update for one puzzle result (the rating math
        stays in the Python core)."""
        r, rd, v = self._db.get_puzzle_rating()
        nr, nrd, nv = glicko2_update(r, rd, v, puzzle_rating, puzzle_rd, outcome)
        self._db.save_puzzle_rating(nr, nrd, nv)
        return {"before": r, "rating": nr, "rd": nrd}

    def rpc_save_puzzle_attempt(self, *, puzzle_id: str, session_id: int | None,
                                mode: str, solved: bool, failed: bool,
                                used_hint: bool, gave_up: bool,
                                solve_time_s: float | None,
                                rating_before: float | None,
                                rating_after: float | None) -> dict:
        attempt_id = self._db.save_puzzle_attempt(
            puzzle_id=puzzle_id, session_id=session_id, mode=mode,
            solved=solved, failed=failed, used_hint=used_hint, gave_up=gave_up,
            solve_time_s=solve_time_s,
            rating_before=rating_before, rating_after=rating_after,
        )
        return {"attemptId": attempt_id}

    def rpc_start_puzzle_session(self, mode: str, time_limit_s: int | None = None) -> dict:
        return {"sessionId": self._db.save_puzzle_session(mode=mode, time_limit_s=time_limit_s)}

    def rpc_update_puzzle_session(self, session_id: int, score: int,
                                  peak_rating: int | None = None) -> dict:
        self._db.update_puzzle_session(session_id, score=score, peak_rating=peak_rating)
        return {"ok": True}

    def rpc_puzzle_summary(self, now: str | None = None) -> dict:
        """Read-only figures for the redesigned Puzzles lobby (UI-BUILD-2 E2;
        core/puzzle_summary.py): the rating row (Home's), solved of tries, Rush and Survival
        bests, recent sessions. *now* (ISO) is for tests; the app sends none."""
        t = HS.parse_time(now) if now else None
        when = t or datetime.now(timezone.utc)
        conn = self._db._conn
        attempts = conn.execute(
            """SELECT id, session_id, mode, attempted_at, solved, failed, rating_before,
                      rating_after FROM puzzle_attempts""").fetchall()
        sessions = conn.execute(
            """SELECT id, mode, started_at, ended_at, time_limit_s, score
               FROM puzzle_sessions""").fetchall()
        cur = conn.execute("SELECT rating FROM puzzle_rating WHERE id = 1").fetchone()
        return PS.summarize([tuple(a) for a in attempts], [tuple(s) for s in sessions],
                            float(cur[0]) if cur else None, when)

    def rpc_count_theme_puzzles(self, themes: list[str], rating_range: int) -> dict:
        rating, _rd, _v = self._db.get_puzzle_rating()
        return {"count": self._db.count_puzzles_for_themes(themes, rating, rating_range)}

    def rpc_puzzle_leaderboard(self, mode: str, time_limit_s: int | None = None,
                               limit: int = 10) -> dict:
        entries, new_rank = self._db.get_leaderboard(mode, time_limit_s, limit)
        return {
            "entries": [{"score": s, "date": d} for s, d in entries],
            "newRank": new_rank,
        }

    # ── opening trainer ───────────────────────────────────────────────────────

    def _line_progress(self, eco: str, name: str) -> dict:
        """Per-line mastery display values (max over colors, as the PyQt panel
        shows) plus the mastered flag (any single color meets both thresholds)."""
        best_dl = 0
        best_acc: float | None = None
        mastered = False
        # Ruling 18 (2026-11-20): the trainer's words are per colour, from what is recorded.
        by_color: dict[str, dict] = {}
        for color in ("white", "black"):
            prog = self._db.get_trainer_progress(eco, name, color)
            by_color[color] = {
                "attempts": int((prog or {}).get("attempts") or 0),
                "completions": int((prog or {}).get("completions") or 0),
                "distinctLines": int((prog or {}).get("distinct_lines") or 0),
                "bestAccuracy": (prog or {}).get("best_accuracy"),
                "mastered": bool(prog) and (
                    int(prog.get("distinct_lines") or 0) >= C.TRAINER_MASTERY_DISTINCT_LINES
                    and prog.get("best_accuracy") is not None
                    and prog["best_accuracy"] >= C.TRAINER_MASTERY_MIN_ACCURACY),
            }
            if not prog:
                continue
            dl = prog.get("distinct_lines", 0) or 0
            acc = prog.get("best_accuracy")
            best_dl = max(best_dl, dl)
            if acc is not None and (best_acc is None or acc > best_acc):
                best_acc = acc
            if (dl >= C.TRAINER_MASTERY_DISTINCT_LINES
                    and acc is not None and acc >= C.TRAINER_MASTERY_MIN_ACCURACY):
                mastered = True
        return {"distinctLines": best_dl, "bestAccuracy": best_acc, "mastered": mastered,
                "byColor": by_color}

    def _family_progress(
        self, pairs: set[tuple[str, str]], progress: dict
    ) -> tuple[int, int]:
        """(drilled, mastered) over a family's (eco, name) line pairs."""
        drilled = mastered = 0
        for eco, name in pairs:
            done = False
            done_master = False
            for color in ("white", "black"):
                prog = progress.get((eco, name, color))
                if not prog:
                    continue
                if (prog.get("completions", 0) or 0) >= 1:
                    done = True
                dl = prog.get("distinct_lines", 0) or 0
                acc = prog.get("best_accuracy")
                if (dl >= C.TRAINER_MASTERY_DISTINCT_LINES
                        and acc is not None and acc >= C.TRAINER_MASTERY_MIN_ACCURACY):
                    done_master = True
            drilled += int(done)
            mastered += int(done_master)
        return drilled, mastered

    # ── Friends (FRIENDS.md, FRIENDS-1 C) ─────────────────────────────────────
    # The deferred ones run on the Friends thread (core/friends/runner.py) and reply from it; a
    # refusal by the server replies {"error": {code, message, status}} (api.ts raises FriendsError).

    def _friends_call(self, req_id, fn) -> None:
        self._friends.submit(fn, lambda out: _reply(req_id, out),
                             lambda msg: _reply_error(req_id, msg))

    def _friends_then_app(self, req_id, fn, then) -> None:
        """*fn* on the Friends thread, then *then(result)* on the app thread (the database)."""
        def run():
            out = fn()

            def on_app():
                try:
                    _reply(req_id, then(out))
                except Exception as exc:
                    logger.exception("friends: app-thread step failed")
                    _reply_error(req_id, str(exc))
            self.post_call(on_app)
            return None
        self._friends.submit(run, lambda out: _reply(req_id, out),
                             lambda msg: _reply_error(req_id, msg))

    def rpc_friends_status(self) -> dict:
        """Local only: is Friends set up, signed in, which keychain, the switches."""
        from zugzwang.core.friends import rating_compare
        return {**self._friends.service.state(), "ratingSource": rating_compare.credit()}

    def rpc_friends_check_handle(self, req_id, handle: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.check_handle(handle))

    def rpc_friends_signup(self, req_id, handle: str = "", ageConfirmed: bool = False,
                           termsAccepted: bool = False) -> None:
        self._friends_call(req_id, lambda: self._friends.service.signup(
            handle, age_confirmed=bool(ageConfirmed), terms_accepted=bool(termsAccepted)))

    def rpc_friends_recovery_code(self) -> dict:
        return {"code": self._friends.service.recovery_code()}

    def rpc_friends_recover(self, req_id, code: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.recover(code))

    def rpc_friends_me(self, req_id) -> None:
        self._friends_call(req_id, lambda: self._friends.service.me())

    def rpc_friends_list(self, req_id, mine: dict | None = None) -> None:
        """The friends list with presence and requests (server), each friend with their ratings,
        your record and last game from stored games (app thread). Friends with no stored games are
        fetched in the background, one at a time."""
        mine = {k: v for k, v in (mine or {}).items() if isinstance(v, str) and v.strip()}

        def then(lst: dict) -> dict:
            out = list_payload(self._db, lst, mine)
            for f in out["friends"]:
                if not f["hasData"] and linked_players(f):
                    self._friends.refresh(f["handle"], linked_players(f))
            return out
        self._friends_then_app(req_id, lambda: self._friends.service.friends(), then)

    def rpc_friends_request(self, req_id, handle: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().send_request(handle))

    def rpc_friends_answer(self, req_id, id: int = 0, accept: bool = False) -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().answer(id, bool(accept)))

    def rpc_friends_cancel(self, req_id, id: int = 0) -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().cancel(id))

    def rpc_friends_remove(self, req_id, handle: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().remove_friend(handle))

    def rpc_friends_block(self, req_id, handle: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().block(handle))

    def rpc_friends_unblock(self, req_id, handle: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().unblock(handle))

    def rpc_friends_appear_offline(self, req_id, on: bool = False) -> None:
        self._friends_call(req_id, lambda: self._friends.service.set_appear_offline(bool(on)))

    def rpc_friends_set_settings(self, chatEnabled: bool | None = None) -> dict:
        """"Chat in friend games", kept locally and (FRIENDS-2) sent to the server, which honours it: chat
        off means no messages either way and friends see it is off (H3). A failure to reach the server is
        the `friends_settings` event; the heartbeat sends it again. BETA-6 (ruling SG1): the sharing switch
        is hidden and not set here; its stored value is kept, unused."""
        from zugzwang.core.friends import settings as fsettings
        ch = {}
        if chatEnabled is not None:
            ch["chat_enabled"] = bool(chatEnabled)
        fsettings.save(**ch)
        state = self._friends.service.state()
        if ch and state["signedIn"]:
            self._friends._settings_pushed = False

            def push():
                try:
                    self._friends.push_settings()
                    _emit("friends_settings", {"saved": True})
                except FriendsError as exc:
                    _emit("friends_settings", {"saved": False, "error": exc.as_dict()})
                return None
            self._friends.submit(push, lambda _o: None, lambda _m: None)
        return state

    def rpc_friends_link_lichess(self, req_id) -> None:
        self._friends_call(req_id, lambda: self._friends.service.link_lichess())

    # Chess.com waits for Chess.com (BETA-5 ruling K3; core/friends/chesscom_link.py): the pending link is
    # kept in Friends' settings, checked by the heartbeat at most every 15 minutes (`friends_link` event).
    def rpc_friends_chesscom_start(self, req_id, username: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.chesscom.start(username))

    def rpc_friends_chesscom_verify(self, req_id, username: str = "") -> None:
        """Check now: the pending link's state after one check ({"state": "linked", "verified": true} when
        found); with no pending link, the server's answer for *username*."""
        def run():
            link = self._friends.service.chesscom
            if link.record() is None:
                return self._friends.service.client().chesscom_verify(username)
            return link.check(force=True)
        self._friends_call(req_id, run)

    def rpc_friends_chesscom_link(self) -> dict:
        """Local only: the pending Chess.com link ({"state": "none"} without one)."""
        return self._friends.service.chesscom.state()

    def rpc_friends_chesscom_cancel(self, req_id) -> None:
        self._friends_call(req_id, lambda: self._friends.service.chesscom.cancel())

    def rpc_friends_save_recovery(self, req_id, path: str = "") -> None:
        """Write the recovery code to the file the save dialog chose (BETA-5 B)."""
        self._friends_call(req_id, lambda: self._friends.service.save_recovery_code(path))

    def rpc_friends_unlink(self, req_id, site: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().unlink(site))

    def rpc_friends_delete_account(self, req_id) -> None:
        """Delete the account on the server (every row), then the key, the local switches and every
        friend's stored games; your own games stay."""
        def then(out: dict) -> dict:
            if "error" not in out and self._db is not None:
                out["friendGamesDeleted"] = self._db.delete_friend_data(None)
            return out
        def delete():
            self._friends.live.stop()
            return self._friends.service.delete_account()
        self._friends_then_app(req_id, delete, then)

    # ── Friends, FRIENDS-2: challenges and live games (core/friends/live.py) ────────
    def rpc_friends_live(self) -> dict:
        """Local only: the live connection (connected, the pending challenges, the games)."""
        if self._friends.service.state()["signedIn"]:
            self._friends.start()
            self._friends.live.ensure()
        return self._friends.live.snapshot()

    def rpc_friends_challenge(self, req_id, handle: str = "", tc: str = "", colour: str = "random") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().challenge(handle, tc, colour))

    def rpc_friends_challenge_answer(self, req_id, id: str = "", accept: bool = False) -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().challenge_answer(id, bool(accept)))

    def rpc_friends_challenge_cancel(self, req_id, id: str = "") -> None:
        self._friends_call(req_id, lambda: self._friends.service.client().challenge_cancel(id))

    def rpc_friends_rematch(self, req_id, id: str = "") -> None:
        """P3: the same time control, the colours swapped (the server decides both)."""
        self._friends_call(req_id, lambda: self._friends.service.client().rematch(id))

    def rpc_friends_ratings(self, req_id, handle: str = "", tc: str = "5+0") -> None:
        """The ratings line of a challenge (the banner, the popover): yours and the friend's for the time
        control, as the game will take them at its start (R1-R3): {"you", "them"}, each {rating, estimated}."""
        def run():
            svc = self._friends.service
            mine = [l for l in svc.me().get("linked", []) if l.get("verified")]
            entry = svc.friend_entry(handle) or {}
            return self._friends.live.preview_ratings(mine, entry.get("linked") or [], tc)
        self._friends_call(req_id, run)

    def rpc_friends_opening(self, id: str = "") -> dict:
        """Local only: the opening of a live friend game so far, by the app's book ({"eco", "name"} or nulls)."""
        st = self._friends.live.states.get(id) or {}
        board = chess.Board()
        found = None
        for uci in st.get("moves") or []:
            try:
                board.push_uci(uci)
            except ValueError:
                break
            if self._openings is not None:
                f = self._openings.name_after(board)
                if f is not None:
                    found = f
        return {"eco": found[0] if found else None, "name": found[1] if found else None}

    def rpc_friends_live_game(self, id: str = "") -> dict:
        """Local only: a live game's last state, its chat (this process's memory), the ratings at its
        start; opens its connection if it is not open."""
        self._friends.live.open_game(id)
        return self._friends.live.game_view(id)

    def rpc_friends_game_send(self, id: str = "", msg: dict | None = None) -> dict:
        """One message to a live game: move {uci, ply}, resign, draw_offer, draw_accept, draw_decline,
        claim_win, call_draw, chat {text}, mute {on}, sync. The answer is the next `friend_game` event."""
        try:
            return self._friends.live.send(id, dict(msg or {}))
        except FriendsError as exc:
            return {"error": exc.as_dict()}

    def rpc_friends_game_close(self, id: str = "") -> dict:
        """The game's screen was left: a finished game is acknowledged to the server (in the background)."""
        threading.Thread(target=self._friends.live.close_game, args=(id,), daemon=True).start()
        return {"ok": True}

    def _save_friend_game(self, gid: str, st: dict, ratings: dict | None) -> int | None:
        """A finished friend game into the library (G2: the "friends" source), with its ratings at the
        start (R1-R3), then analysed at the standard depth (14) like any synced game. App thread."""
        existing = self._db.friend_game_saved(gid)
        if existing is not None:
            return existing
        pgn_text = st["pgn"]
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            raise RuntimeError("the friend game's PGN could not be read")
        board = game.board()
        opening = None
        for mv in game.mainline_moves():
            board.push(mv)
            if self._openings is not None:
                found = self._openings.name_after(board)
                if found is not None:
                    opening = found
        created = st.get("created")
        played_at = (datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
                     if isinstance(created, (int, float)) else datetime.now(timezone.utc).isoformat())
        lib_id = self._db.save_game(
            played_at=played_at, player_color=st["you"], skill_level=0, result=st["result"],
            termination=_FRIEND_TERMINATION.get(st.get("termination") or "", st.get("termination") or ""),
            move_count=len(st.get("moves") or []), pgn=pgn_text, final_fen=board.fen(),
            opening_eco=opening[0] if opening else None, opening_name=opening[1] if opening else None,
            source="friends", external_id=gid, start_ratings=ratings)
        try:
            self.rpc_analyze_pending(game_ids=[lib_id], depth=C.ANALYSIS_STANDARD_DEPTH)
        except RuntimeError as exc:
            # a sync or a relabel is running: the game waits in the Games list's unanalysed games
            logger.info("friends: a saved friend game was not queued for analysis: %s", exc)
        return lib_id

    def rpc_friends_profile(self, req_id, handle: str = "", mine: dict | None = None,
                            recentLimit: int = 10, recentOffset: int = 0, refresh: bool = True) -> None:
        """A friend's profile from stored games (engine-free, S3). With *refresh*, data over an hour
        old (or never fetched) is fetched again in the background (G4): `friend_data` says when."""
        mine = {k: v for k, v in (mine or {}).items() if isinstance(v, str) and v.strip()}

        def fetch_entry() -> dict:
            # fresh: a friend may have linked an account since the list was read
            entry = self._friends.service.friend_entry(handle, fresh=True)
            if entry is None:
                raise FriendsError("not_friends", "You are not friends with that handle.")
            return entry

        def then(entry: dict) -> dict:
            if "error" in entry:
                return entry
            out = profile_payload(self._db, entry, mine, recent_limit=int(recentLimit),
                                  recent_offset=int(recentOffset),
                                  fetching=self._friends.fetching(handle))
            if refresh and out["data"]["stale"] and not out["data"]["fetching"]:
                out["data"]["fetching"] = self._friends.refresh(handle, linked_players(entry))
            return out
        self._friends_then_app(req_id, fetch_entry, then)

    def rpc_friends_refresh(self, handle: str = "", older: bool = False) -> dict:
        """The profile's Refresh (G4), or "Load games older than 12 months" (G3, *older*)."""
        entry = self._friends.service.friend_entry(handle) if self._friends.service.last_list else None
        if entry is None:
            raise RuntimeError("Open the friends list first.")
        return {"started": self._friends.refresh(handle, linked_players(entry), older=bool(older))}

    def rpc_friends_game(self, id: int) -> dict:
        """A friend's game for Analyse (G1: on request, nothing stored, never in your Games)."""
        row = self._db.friend_game(int(id)) if self._db else None
        if row is None:
            raise RuntimeError("No such game.")
        game = chess.pgn.read_game(io.StringIO(row["pgn"]))
        moves = [m.uci() for m in game.mainline_moves()] if game else []
        return {"id": row["id"], "site": row["site"], "white": row["white"], "black": row["black"],
                "whiteElo": row["white_elo"], "blackElo": row["black_elo"], "result": row["result"],
                "opening": row["opening"], "eco": row["eco"], "endedAt": row["ended_at"],
                "timeControl": row["time_control"], "startFen": chess.STARTING_FEN, "moves": moves}

    def rpc_trainer_lobby(self) -> dict:
        from zugzwang.core import books
        index = self._openings.family_index() if self._openings else []
        progress = self._db.get_all_trainer_progress()
        families = []
        for fi in index:
            pairs = {(eco, name) for eco, name, _fen, _pgn in fi.lines}
            drilled, mastered = self._family_progress(pairs, progress)
            families.append({
                "name": fi.name,
                "ecoLo": fi.eco_lo,
                "ecoHi": fi.eco_hi,
                "firstMove": fi.first_move,
                "popularity": fi.total_weight,
                "lineCount": fi.line_count,
                "threshold": fi.threshold,
                "available": fi.available,
                "sampleMoves": fi.sample_moves,
                "sharedMoves": fi.shared_moves,
                "drilled": drilled,
                "mastered": mastered,
            })
        return {
            "indexed": self._db.coverage_indexed(),
            "indexing": self._coverage.running(),
            # Reported so the lobby can explain an untrainable list instead of
            # showing every family gated as "limited coverage" with no reason.
            # Read off the loaded reader, not inferred from the line counts —
            # a book that is present but thin is a different fact from no book.
            "bookAvailable": self._openings.has_book if self._openings else False,
            "bookPath": str(books.active_book_path() or books.books_dir()),
            "bookId": (books.active_spec().id if books.active_spec() else None),
            "families": families,
        }

    def rpc_trainer_index_coverage(self) -> dict:
        if self._openings is None or not self._openings.entries():
            raise RuntimeError("ECO data not loaded — cannot index coverage")
        from zugzwang.core import books
        path = books.active_book_path()
        if path is None:
            raise RuntimeError("No opening book installed (Settings → Opening book)")
        self._coverage.start(
            self._openings.entries(), self._db_path, path,
            lambda: _emit("trainer_index_done", {}),
        )
        return {"started": True}

    def rpc_trainer_family(self, name: str) -> dict:
        index = self._openings.family_index() if self._openings else []
        fam = next((fi for fi in index if fi.name == name), None)
        if fam is None:
            raise RuntimeError(f"unknown opening family: {name!r}")
        out = []
        drilled_pairs: set[tuple[str, str]] = set()
        mastered_pairs: set[tuple[str, str]] = set()
        for eco, line_name, fen, pgn in fam.lines:
            prog = self._line_progress(eco, line_name)
            if prog["distinctLines"] > 0:
                drilled_pairs.add((eco, line_name))
            if prog["mastered"]:
                mastered_pairs.add((eco, line_name))
            out.append({
                "eco": eco,
                "name": line_name,
                "fen": fen,
                "pgn": pgn,
                "uci": [m.uci() for m in parse_pgn_moves(pgn)],
                "coverage": {
                    "white": self._db.get_coverage(eco, line_name, "white"),
                    "black": self._db.get_coverage(eco, line_name, "black"),
                },
                "progress": prog,
            })
        return {
            "label": fam.name,
            "lines": out,
            "mastered": len(mastered_pairs),
            "drilled": len(drilled_pairs),
        }

    def rpc_book_moves(self, fen: str, threshold: float = C.TRAINER_WEIGHT_THRESHOLD) -> dict:
        board = chess.Board(fen)
        reader = self._openings.reader if self._openings else None
        return {"accepted": [m.uci() for m in accepted_book_moves(reader, board, threshold)]}

    def rpc_book_reply(self, fen: str, mode: str = "varied") -> dict:
        board = chess.Board(fen)
        reader = self._openings.reader if self._openings else None
        if mode == "pinned":
            move = top_book_reply(reader, board)
        elif mode == "random":
            move = uniform_random_reply(reader, board)
        else:
            move = weighted_random_reply(reader, board)
        return {"uci": move.uci() if move else None}

    def rpc_opening_at(self, fen: str) -> dict:
        found = self._openings.name_after(chess.Board(fen)) if self._openings else None
        return {"opening": {"eco": found[0], "name": found[1]} if found else None}

    def rpc_trainer_attempt(self, eco: str, name: str, color: str) -> dict:
        self._db.record_trainer_attempt(eco, name, color)
        return {"ok": True}

    def rpc_trainer_complete(self, *, eco: str, name: str, color: str, mode: str,
                             terminal_fen: str, moves_played: int, errors_made: int,
                             accuracy: float | None) -> dict:
        import chess.polyglot
        zobrist_hex = hex(chess.polyglot.zobrist_hash(chess.Board(terminal_fen)))
        self._db.save_trainer_completion(
            eco=eco, name=name, color=color, mode=mode,
            terminal_zobrist_hex=zobrist_hex,
            moves_played=moves_played, errors_made=errors_made, accuracy=accuracy,
        )
        return {"progress": self._line_progress(eco, name)}

    # ── engine reply flow ─────────────────────────────────────────────────────

    def _request_engine_move(self) -> None:
        fen = self._session.board.fen()
        # The engine's thinking time is measured here, from the request to the move's arrival
        # on this thread (UI-BUILD-3 F); the frontend shows the clock it gets back.
        self._engine_asked_at = time.monotonic()
        # callback runs on the engine thread → marshal back to the app thread
        self._engine.request_move(
            fen, self._skill,
            lambda move: self.post_call(lambda: self._apply_engine_move(move)),
        )

    def _apply_engine_move(self, move: chess.Move) -> None:
        session = self._session
        if session is None or session.over or move not in session.board.legal_moves:
            return
        san = session.board.san(move)
        asked = getattr(self, "_engine_asked_at", None)
        clock = (session.clock_after(session.board.turn, time.monotonic() - asked)
                 if asked is not None else None)
        end = session.push(move, clock)
        _emit("engine_move", {
            "uci": move.uci(), "san": san, "fen": session.board.fen(),
            "end": self._finish(end),
            # The engine's clock after this move, increment included; null when untimed.
            "clockMs": round(clock * 1000) if clock is not None else None,
        })

    # ── game end / persistence ────────────────────────────────────────────────

    def _finish(self, end: GameEnd | None) -> dict | None:
        """Save the finished game (same fields the PyQt app writes, plus the
        opening, which the schema already has columns for) and describe it."""
        if end is None:
            return None
        session = self._session
        opening = session.opening
        game_id = self._db.save_game(
            played_at=session.started_at,
            player_color="white" if session.player_color == chess.WHITE else "black",
            skill_level=session.skill_level,
            result=end.result,
            termination=end.termination,
            move_count=session.ply_count(),
            pgn=session.to_pgn(),
            final_fen=session.board.fen(),
            opening_eco=opening[0] if opening else None,
            opening_name=opening[1] if opening else None,
        )
        return {"result": end.result, "termination": end.termination, "gameId": game_id}

    def _require_session(self) -> GameSession:
        if self._session is None:
            raise RuntimeError("no active game")
        return self._session


#: The argument the app passes when it spawns the packaged sidecar (`src/lib/sidecar.ts`,
#: `capabilities/beta.json`). Nothing else passes it.
APP_LAUNCH_FLAG = "--app"

#: Exit status of a frozen sidecar that refused to open the default database.
EXIT_REFUSED_DEFAULT_DB = 2


def refuse_default_db(frozen: bool, argv: list[str], env) -> str | None:
    """The live-database guard (BETA-PUB, owner 2026-11-12): a packaged or frozen sidecar
    started by anything but the app — a test, a script, `--help` typed at a shell — must
    not open the user's database. It opens one only when given an explicit path
    (`ZUGZWANG_DB`, or a data folder in `ZUGZWANG_DATA_DIR`) or when the app launched it
    (`--app`). Returns why it refuses, or None to go ahead. A checkout (not frozen) is
    unchanged: the owner's dev run and the test suite pass paths as before.

    The incident it closes: an early BETA session ran a frozen build's `--help`; it opened
    `~/.zugzwang/zugzwang.db`, ran the migrations and waited on stdin (BETA.md, "Found
    while building")."""
    if not frozen:
        return None
    if env.get("ZUGZWANG_DB") or env.get("ZUGZWANG_DATA_DIR"):
        return None
    if APP_LAUNCH_FLAG in argv[1:]:
        return None
    return ("zugzwang-sidecar: refusing to open the default user database "
            f"({DB_PATH}) — this sidecar was not started by the app. Set ZUGZWANG_DB to a "
            "database file (or ZUGZWANG_DATA_DIR to a data folder) to run it by hand.")


def main() -> None:
    # The webview writes UTF-8; Windows' locale code page is not (BETA, M13). The packaged
    # build also runs in UTF-8 mode (packaging/sidecar.spec); this covers a dev run.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    # Before the log file: it lives beside the database, so even opening it would write
    # into the folder the guard protects.
    refusal = refuse_default_db(bool(getattr(sys, "frozen", False)), sys.argv, os.environ)
    if refusal:
        sys.stderr.write(refusal + "\n")
        sys.stderr.flush()
        raise SystemExit(EXIT_REFUSED_DEFAULT_DB)
    _setup_file_logging()
    server = Server()

    def read_stdin() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("bad json: %.120s", line)
                continue
            server.post_request(req)
        # stdin closed → frontend is gone; stop so chess.engine's non-daemon
        # asyncio threads don't block interpreter exit
        server.post_stop()

    threading.Thread(target=read_stdin, name="stdin", daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
