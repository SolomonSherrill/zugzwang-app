"""FRIENDS-2 F: the test opponent's own rules (sidecar/friends_bot.py); its run against a server is in
sidecar/friends_play_e2e.py (gate.sh's "play")."""
import importlib.util
import random
from pathlib import Path

import chess

_SPEC = importlib.util.spec_from_file_location("zz_friends_bot", Path(__file__).resolve().parents[1] / "sidecar" / "friends_bot.py")
bot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bot)


def test_it_plays_only_legal_moves_and_takes_a_mate_in_one():
    rnd = random.Random(1)
    board = chess.Board()
    for _ in range(80):
        if board.is_game_over():
            break
        uci = bot.choose_move(board.fen(), rnd)
        assert chess.Move.from_uci(uci) in board.legal_moves
        board.push_uci(uci)
    # Scholar's mate on the board: the bot finds Qxf7#, whatever the seed
    mate = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    assert {bot.choose_move(mate.fen(), random.Random(s)) for s in range(20)} == {"h5f7"}


def test_a_human_pace_bounded_by_the_clock():
    rnd = random.Random(3)
    times = [bot.think_seconds(600_000, 1.0, rnd) for _ in range(50)]
    assert all(2.0 <= t <= 8.0 for t in times)
    assert bot.think_seconds(30_000, 1.0, rnd) <= 1.0          # a thirtieth of 30 s
    assert bot.think_seconds(600_000, 0.05, rnd) <= 0.4         # --pace scales it


def test_it_answers_chat():
    assert bot.reply_to("Good luck!") == "thanks, you too!"
    assert bot.reply_to("gg") == "gg, thanks for the game"
    assert bot.reply_to("what a game") in bot.GENERIC


def test_its_handle_is_a_valid_unreserved_one():
    b = bot.Bot("http://127.0.0.1:1", "owner_demo")
    assert b.handle.startswith("testbot-") and 3 <= len(b.handle) <= 20
    assert set(b.handle) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-")
