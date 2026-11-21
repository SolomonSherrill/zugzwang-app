"""
GameSession wraps chess.Board and chess.pgn.Game to track an in-progress game.
No Qt dependencies — purely data/logic.
"""

from __future__ import annotations

import io
import re
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import chess
import chess.pgn

_TIME_CONTROL_RE = re.compile(r"(\d+)\+(\d+)")


@dataclass(frozen=True)
class GameEnd:
    result: str      # '1-0' | '0-1' | '1/2-1/2'
    termination: str # 'checkmate' | 'stalemate' | 'insufficient_material' |
                     # 'fifty_moves' | 'threefold_repetition' |
                     # 'resignation' | 'draw_agreed' | 'abandoned'


class GameSession:
    def __init__(
        self,
        player_color: chess.Color,
        skill_level: int,
        openings=None,              # OpeningsBook | None — optional to keep core Qt-free
        starting_fen: str | None = None,
        time_control: str | None = None,   # PGN TimeControl, "600+0" (seconds+increment)
    ) -> None:
        self.player_color = player_color
        self.skill_level = skill_level
        self.started_at = datetime.now(timezone.utc).isoformat()

        if starting_fen is not None:
            # Legality, not just syntax: this position goes to the live engine, and
            # one with no kings crashes it (VAL-FEN).
            from .positions import legal_board
            self.board = legal_board(starting_fen)
        else:
            self.board = chess.Board()

        self.result: str | None = None
        self.termination: str | None = None
        self.over = False

        self._pgn = chess.pgn.Game()
        if starting_fen is not None:
            self._pgn.setup(self.board)  # sets FEN + SetUp headers before other headers
        self._pgn.headers.update({
            "Event":    "Zugzwang",
            "Site":     "Local",
            "Date":     datetime.now(timezone.utc).strftime("%Y.%m.%d"),
            "White":    "You" if player_color == chess.WHITE else "Stockfish",
            "Black":    "Stockfish" if player_color == chess.WHITE else "You",
            "WhiteElo": "?",
            "BlackElo": "?",
            "Result":   "*",
        })
        # The clock the game was played on, so the saved game files under its speed
        # (database.speed_from_pgn) and Review can name it. Only "base+increment" in whole
        # seconds is written; anything else is left out rather than stored malformed.
        tc = _TIME_CONTROL_RE.fullmatch(time_control) if time_control is not None else None
        if tc is not None:
            self._pgn.headers["TimeControl"] = time_control
        self._node: chess.pgn.GameNode = self._pgn

        # Clocks (UI-BUILD-3 F, DESIGN.md fourth rulings, ruling 9): the clock each mover had
        # left after each move, increment included (the convention of chess.com's and Lichess's
        # [%clk], which game_report.time_spent reads), written as [%clk] when the game is saved.
        # Only a timed game keeps them; an untimed one writes none.
        self._tc: tuple[int, int] | None = (int(tc.group(1)), int(tc.group(2))) if tc else None
        self._clocks: list[float | None] = []
        base = float(self._tc[0]) if self._tc else 0.0
        self._clock_left: dict[chess.Color, float] = {chess.WHITE: base, chess.BLACK: base}

        self._openings = openings
        self._last_opening: tuple[str, str] | None = None
        self._opening_listener: Callable[[str, str], None] | None = None

    # ── Opening integration ──────────────────────────────────────────────────

    @property
    def opening(self) -> tuple[str, str] | None:
        return self._last_opening

    def set_opening_listener(self, cb: Callable[[str, str], None] | None) -> None:
        self._opening_listener = cb

    def _update_opening(self) -> None:
        if self._openings is None:
            return
        found = self._openings.name_after(self.board)
        if found is not None and found != self._last_opening:
            self._last_opening = found
            if self._opening_listener:
                self._opening_listener(found[0], found[1])

    # ── Move application ─────────────────────────────────────────────────────

    def push(self, move: chess.Move, clock: float | None = None) -> GameEnd | None:
        """Apply a move and check for game end. Returns GameEnd or None.

        *clock*: the mover's time left after the move, in seconds, increment included. Kept
        (to the tenth) only in a timed game, and only when it is a real, non-negative number."""
        if self.over:
            return None
        mover = self.board.turn
        self._node = self._node.add_variation(move)
        self._record_clock(mover, clock)
        self.board.push(move)
        self._update_opening()
        return self._auto_detect_end()

    def _auto_detect_end(self) -> GameEnd | None:
        b = self.board
        if b.is_checkmate():
            winner = not b.turn
            result = "1-0" if winner == chess.WHITE else "0-1"
            return self._finalize("checkmate", result)
        if b.is_stalemate():
            return self._finalize("stalemate", "1/2-1/2")
        if b.is_insufficient_material():
            return self._finalize("insufficient_material", "1/2-1/2")
        if b.can_claim_fifty_moves():
            return self._finalize("fifty_moves", "1/2-1/2")
        if b.can_claim_threefold_repetition():
            return self._finalize("threefold_repetition", "1/2-1/2")
        return None

    # ── Clocks ───────────────────────────────────────────────────────────────

    @property
    def timed(self) -> bool:
        """True when the game was started with a time control ("base+increment")."""
        return self._tc is not None

    @property
    def clocks(self) -> list[float | None]:
        """The clock after each ply so far (None where none was given)."""
        return list(self._clocks)

    def has_clocks(self) -> bool:
        """A timed game whose every move carries a clock: only then is [%clk] written. A game
        with a gap (an older frontend that sends no clock) writes none rather than half."""
        return self.timed and bool(self._clocks) and all(c is not None for c in self._clocks)

    def clock_after(self, color: chess.Color, elapsed_s: float) -> float | None:
        """The clock *color* would have after a move that took *elapsed_s* seconds: its last
        clock less the time (never below zero), plus the increment. None when untimed. The
        sidecar measures the engine's moves with it."""
        if self._tc is None:
            return None
        spent = elapsed_s if isinstance(elapsed_s, (int, float)) and math.isfinite(elapsed_s) else 0.0
        return round(max(0.0, self._clock_left[color] - max(0.0, spent)) + self._tc[1], 1)

    def _record_clock(self, mover: chess.Color, clock: float | None) -> None:
        value: float | None = None
        if (self._tc is not None and isinstance(clock, (int, float)) and not isinstance(clock, bool)
                and math.isfinite(clock) and clock >= 0):
            value = round(float(clock), 1)
        self._clocks.append(value)
        if value is not None:
            self._node.set_clock(value)
            self._clock_left[mover] = value

    # ── Voluntary endings ────────────────────────────────────────────────────

    def resign(self) -> GameEnd:
        result = "0-1" if self.player_color == chess.WHITE else "1-0"
        return self._finalize("resignation", result)

    def draw_agreed(self) -> GameEnd:
        return self._finalize("draw_agreed", "1/2-1/2")

    def abandon(self) -> GameEnd:
        result = "*"
        return self._finalize("abandoned", result)

    # ── Serialization ────────────────────────────────────────────────────────

    def to_pgn(self) -> str:
        # The only comments a session writes are its [%clk] tags.
        exporter = chess.pgn.StringExporter(headers=True, variations=False,
                                            comments=self.has_clocks())
        return self._pgn.accept(exporter)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def ply_count(self) -> int:
        return self.board.ply()

    def is_player_turn(self) -> bool:
        return self.board.turn == self.player_color and not self.over

    def _finalize(self, termination: str, result: str) -> GameEnd:
        self.termination = termination
        self.result = result
        self.over = True
        self._pgn.headers["Result"] = result
        friendly = termination.replace("_", " ").title()
        self._pgn.headers["Termination"] = friendly
        return GameEnd(result=result, termination=termination)
