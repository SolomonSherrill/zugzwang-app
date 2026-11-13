"""Tests for the PGN import parser — Gap A (multi-game) and Gap B (colour)."""

from zugzwang.core.import_pgn import parse_pgn_games

_TWO_GAMES = """[Event "Rated Blitz"]
[White "alice"]
[Black "Bob"]
[Result "0-1"]
[UTCDate "2024.03.01"]

1. e4 e5 2. Nf3 Nc6 0-1

[Event "Rated Blitz"]
[White "Carol"]
[Black "ALICE"]
[Result "1-0"]
[Date "2024.03.02"]

1. d4 d5 2. c4 e6 1-0
"""


def test_gap_a_reads_all_games():
    games = list(parse_pgn_games(_TWO_GAMES))
    assert len(games) == 2


def test_gap_b_detects_colour_case_insensitive():
    games = list(parse_pgn_games(_TWO_GAMES, usernames=["Alice"]))
    assert games[0].player_color == "white"   # alice == White
    assert games[1].player_color == "black"   # ALICE == Black


# These two pinned the old White default, which is gone (FIXPLAN O5: defaulting a
# miss to White is W11). No username leaves the side unknown; a username that
# matches neither player marks the game as not the user's.

def test_gap_b_leaves_the_side_unknown_without_username():
    games = list(parse_pgn_games(_TWO_GAMES))
    assert all(g.player_color is None and not g.not_owner for g in games)


def test_gap_b_marks_a_game_nobody_configured_played_as_not_the_users():
    games = list(parse_pgn_games(_TWO_GAMES, usernames=["nobody"]))
    assert all(g.player_color is None and g.not_owner for g in games)


def test_metadata_parsed():
    g = next(parse_pgn_games(_TWO_GAMES))
    assert g.result == "0-1"
    assert g.played_at.startswith("2024-03-01")
    assert g.move_count == 4
    assert g.final_fen


def test_empty_and_moveless_games_skipped():
    assert list(parse_pgn_games("")) == []
    moveless = '[White "x"]\n[Black "y"]\n[Result "*"]\n\n*\n'
    assert list(parse_pgn_games(moveless)) == []
