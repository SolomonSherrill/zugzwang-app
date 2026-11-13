import chess
import chess.pgn
import io

from zugzwang.core.game import GameSession, GameEnd


def _push_moves(session, uci_list):
    """Push a sequence of UCI moves; return the last GameEnd or None."""
    end = None
    for uci in uci_list:
        move = chess.Move.from_uci(uci)
        end = session.push(move)
    return end


def test_initial_state():
    s = GameSession(chess.WHITE, 10)
    assert s.board.fen() == chess.Board().fen()
    assert not s.over
    assert s.result is None


def test_push_move():
    s = GameSession(chess.WHITE, 5)
    end = s.push(chess.Move.from_uci("e2e4"))
    assert end is None
    assert s.board.ply() == 1
    assert not s.over


def test_scholar_mate():
    s = GameSession(chess.WHITE, 20)
    # Scholar's mate: 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7#
    moves = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]
    end = _push_moves(s, moves)
    assert end is not None
    assert end.termination == "checkmate"
    assert end.result == "1-0"
    assert s.over


def test_stalemate():
    # Construct a stalemate position manually
    s = GameSession(chess.BLACK, 5)
    # Set up a known stalemate: Black king on a8, White queen on b6, White king on c6
    board = chess.Board("k7/8/1QK5/8/8/8/8/8 b - - 0 1")
    s.board = board
    # It's Black's turn and they're already stalemated — check auto-detection by
    # calling _auto_detect_end directly
    end = s._auto_detect_end()
    assert end is not None
    assert end.termination == "stalemate"
    assert end.result == "1/2-1/2"


def test_resign_as_white():
    s = GameSession(chess.WHITE, 8)
    s.push(chess.Move.from_uci("e2e4"))
    end = s.resign()
    assert end.termination == "resignation"
    assert end.result == "0-1"  # White resigned → Black wins
    assert s.over


def test_resign_as_black():
    s = GameSession(chess.BLACK, 8)
    end = s.resign()
    assert end.termination == "resignation"
    assert end.result == "1-0"  # Black resigned → White wins


def test_draw_agreed():
    s = GameSession(chess.WHITE, 10)
    end = s.draw_agreed()
    assert end.termination == "draw_agreed"
    assert end.result == "1/2-1/2"
    assert s.over


def test_pgn_roundtrip():
    s = GameSession(chess.WHITE, 12)
    _push_moves(s, ["e2e4", "e7e5", "g1f3"])
    pgn_str = s.to_pgn()
    assert "e4" in pgn_str
    assert "e5" in pgn_str
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    assert game is not None
    assert game.headers["White"] == "You"
    assert game.headers["Black"] == "Stockfish"


def test_is_player_turn():
    s = GameSession(chess.WHITE, 10)
    assert s.is_player_turn()  # White's turn, player is White
    s.push(chess.Move.from_uci("e2e4"))
    assert not s.is_player_turn()  # Black's turn, player is White


def test_no_moves_after_game_over():
    s = GameSession(chess.WHITE, 5)
    end = s.resign()
    result_again = s.push(chess.Move.from_uci("e2e4"))
    assert result_again is None   # push returns None when game is over
    assert s.board.ply() == 0     # board was not modified
