"""
GameSession wraps chess.Board and chess.pgn.Game to track an in-progress game.
No Qt dependencies — purely data/logic.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import chess
import chess.pgn


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
        self._node: chess.pgn.GameNode = self._pgn

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

    def push(self, move: chess.Move) -> GameEnd | None:
        """Apply a move and check for game end. Returns GameEnd or None."""
        if self.over:
            return None
        self._node = self._node.add_variation(move)
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
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
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
