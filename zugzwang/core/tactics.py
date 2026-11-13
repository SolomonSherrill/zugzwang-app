"""
Whole-game replay helpers — Qt-free, engine-free.

This module used to also carry a heuristic fork detector that fed the Insights
"forks found vs missed" panel. A stage 0 audit measured it at 57 % precision
and 44 % recall on constructed positions, and found that 8.8 % of the moves it
called forks were scored mistakes or blunders by the stored engine analysis, so
it was removed along with the panel rather than repaired. Its replacement is
being built from a material-after-best-defence definition in the move
explanation layer; see that work for the requirements the audit produced. The
old implementation is in git history at bfc0eca~1.
"""

from __future__ import annotations

import io

import chess
import chess.pgn


def analyze_castling(pgn_str: str, player_color: str) -> str:
    """Replay the game and report how the player castled: 'kingside',
    'queenside', or 'none'. Returns the first castling move the player makes."""
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        return "none"
    want_white = player_color == "white"
    board = game.board()
    for move in game.mainline_moves():
        if board.turn == (chess.WHITE if want_white else chess.BLACK):
            if board.is_kingside_castling(move):
                return "kingside"
            if board.is_queenside_castling(move):
                return "queenside"
        board.push(move)
    return "none"
