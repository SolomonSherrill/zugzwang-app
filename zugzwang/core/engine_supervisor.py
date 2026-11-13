"""Engine death recovery for bulk analysis (FIXPLAN VAL-DEATH, approved 2026-10-22).

Before this, a Stockfish process that died mid-job was never noticed as such: whole-game
analysis caught the error per ply and emitted an empty ply, then reported the game done;
the runners kept the dead engine (they only checked for `None`), so every later search
failed instantly the same way. `review/scratch/engine_death.py` measured each path.

`SupervisedEngine` stands in for a `SimpleEngine` wherever analysis calls `analyse`. On a
death it reaps the dead process, starts a new one with the same configuration (after
each delay in `ENGINE_RESPAWN_BACKOFF_S` until a start succeeds) and retries the search
once. A search that kills the engine twice raises `EngineDied` with `poison=True`: the
position, not the engine, is the problem, and the caller skips the game.

`DeathBreaker` is the run-level cut-off: more than `ENGINE_BREAKER_DEATHS` deaths in the
last `ENGINE_BREAKER_WINDOW_GAMES` games means something systemic, and the run stops.

A retried search starts on a cold hash, so its numbers can differ slightly from what an
uninterrupted run would have produced — the same order of effect as ENG-ALLOC's hash
note, and only on a ply that already lost its engine once.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Callable

import chess
import chess.engine

import zugzwang.config as C

logger = logging.getLogger(__name__)


class EngineDied(Exception):
    """The engine died and this search has no answer.

    *poison* — it died twice on the same search, so the position is the suspect.
    Otherwise it could not be restarted at all."""

    def __init__(self, message: str, *, fen: str | None = None,
                 exit_code: int | None = None, version: str | None = None,
                 poison: bool = False) -> None:
        super().__init__(message)
        self.fen = fen
        self.exit_code = exit_code
        self.version = version
        self.poison = poison


#: What a dying engine raises from python-chess 1.11.2, measured by SIGKILL in
#: `tests/test_engine_death.py`: a search in flight when the process dies fails with
#: `concurrent.futures.CancelledError` (its command is cancelled, with an empty message);
#: a call on the dead handle afterwards fails with `EngineTerminatedError` ("engine
#: event loop dead"). Both are death. Nothing in this app cancels a search that way — a
#: superseded search is stopped with `stop()` and returns normally.
ENGINE_GONE = (chess.engine.EngineTerminatedError, concurrent.futures.CancelledError)

#: Everything that means "this search has no answer because the engine died".
DEATH = (*ENGINE_GONE, EngineDied)


def is_engine_death(exc: BaseException) -> bool:
    return isinstance(exc, DEATH)


def bury(engine: chess.engine.SimpleEngine | None) -> int | None:
    """Release a dead engine's handle and return its exit code, if the OS reported one."""
    if engine is None:
        return None
    code = None
    try:
        code = engine.transport.get_returncode()
    except Exception:
        pass
    try:
        engine.close()
    except Exception:
        pass
    return code


class SupervisedEngine:
    """A `SimpleEngine` that restarts itself and retries a search once after a death.

    *start* opens and configures a new engine; it is called lazily for the first engine
    and again for each respawn, so every engine this hands out has one configuration.
    *on_death* is told about every death, recovered or not (the breaker counts them).
    """

    def __init__(self, start: Callable[[], chess.engine.SimpleEngine], *,
                 backoff: tuple[float, ...] = C.ENGINE_RESPAWN_BACKOFF_S,
                 on_death: Callable[[], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 label: str = "engine") -> None:
        self._start = start
        self._backoff = backoff
        self._on_death = on_death
        self._sleep = sleep
        self._label = label
        self._engine: chess.engine.SimpleEngine | None = None
        self.deaths = 0
        self.version: str | None = None

    @property
    def engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            self._engine = self._start()
            self.version = self._engine.id.get("name")
        return self._engine

    def set_on_death(self, on_death: Callable[[], None] | None) -> None:
        self._on_death = on_death

    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs):
        try:
            return self.engine.analyse(board, limit, **kwargs)
        except ENGINE_GONE as exc:
            self._died(board, exc)
        self._respawn(board)
        try:
            return self.engine.analyse(board, limit, **kwargs)
        except ENGINE_GONE as exc:
            code = self._died(board, exc)
            raise EngineDied(
                f"the engine died twice on this position (exit code {code})",
                fen=board.fen(), exit_code=code, version=self.version, poison=True,
            ) from exc

    def quit(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                bury(engine)

    # ── internals ─────────────────────────────────────────────────────────────

    def _died(self, board: chess.Board, exc: BaseException) -> int | None:
        engine, self._engine = self._engine, None
        code = bury(engine)
        self.deaths += 1
        logger.error("%s died (exit code %s) on %s: %s", self._label, code, board.fen(), exc)
        if self._on_death is not None:
            self._on_death()
        return code

    def _respawn(self, board: chess.Board) -> None:
        last: Exception | None = None
        for delay in self._backoff:
            self._sleep(delay)
            try:
                self._engine = self._start()
                self.version = self._engine.id.get("name")
                logger.info("%s restarted after %.1f s", self._label, delay)
                return
            except Exception as exc:
                last = exc
                logger.error("%s restart failed: %s", self._label, exc)
        raise EngineDied(f"the engine died and could not be restarted: {last}",
                         fen=board.fen(), version=self.version)


class DeathBreaker:
    """Stops a bulk run once more than *max_deaths* deaths fall in its last *window*
    games. Shared by every worker of one run, so it is thread-safe."""

    def __init__(self, max_deaths: int = C.ENGINE_BREAKER_DEATHS,
                 window: int = C.ENGINE_BREAKER_WINDOW_GAMES) -> None:
        self._max = max_deaths
        self._window = window
        self._games = 0
        self._deaths: list[int] = []      # the game count when each death happened
        self._lock = threading.Lock()

    def game_started(self) -> None:
        with self._lock:
            self._games += 1

    def death(self) -> None:
        with self._lock:
            self._deaths.append(self._games)

    def recent_deaths(self) -> int:
        with self._lock:
            return sum(1 for g in self._deaths if g > self._games - self._window)

    @property
    def tripped(self) -> bool:
        return self.recent_deaths() > self._max

    def message(self) -> str:
        return (f"Stopped: the engine died {self.recent_deaths()} times within the last "
                f"{self._window} games. That points at the engine binary or the machine, "
                "not one position. Games already analysed are kept; the rest are still "
                "pending.")
