"""Multi-game PGN parsing and colour detection (Phase 2, priority 4 — Gaps A/B)."""

import io

import chess.pgn
import pytest

from zugzwang.core.import_pgn import (
    _external_id,
    _match_color,
    attribute,
    _termination,
    parse_pgn_games,
    parse_pgn_report,
)


TWO_GAMES = """[Event "Game One"]
[White "alice"]
[Black "bob"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0

[Event "Game Two"]
[White "carol"]
[Black "alice"]
[Result "0-1"]

1. d4 d5 2. c4 e6 0-1
"""


# ── Gap A: every game in a multi-game PGN is parsed ──────────────────────────

def test_parses_all_games_not_just_first():
    games = list(parse_pgn_games(TWO_GAMES))
    assert len(games) == 2


def test_each_game_has_independent_pgn():
    games = list(parse_pgn_games(TWO_GAMES))
    # StringExporter is recreated per game; game two must not carry game one's moves.
    assert "Qxf7" in games[0].pgn
    assert "Qxf7" not in games[1].pgn
    assert "Game Two" in games[1].pgn


def test_zero_move_games_are_skipped():
    pgn = (
        '[Event "Empty"]\n[White "a"]\n[Black "b"]\n[Result "*"]\n\n*\n\n'
        '[Event "Real"]\n[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
    )
    games = list(parse_pgn_games(pgn))
    assert len(games) == 1
    assert games[0].result == "1-0"


def test_empty_string_yields_nothing():
    assert list(parse_pgn_games("")) == []


# ── Gap B: colour detection from username ────────────────────────────────────

def test_color_white_match():
    games = list(parse_pgn_games(TWO_GAMES, usernames=["alice"]))
    assert games[0].player_color == "white"   # alice is White in game one


def test_color_black_match():
    games = list(parse_pgn_games(TWO_GAMES, usernames=["alice"]))
    assert games[1].player_color == "black"   # alice is Black in game two


NO_ALIASES: dict = {}


def test_color_case_and_whitespace_insensitive():
    side = attribute({"White": "Alice", "Black": "bob"}, ["  ALICE "], NO_ALIASES)
    assert (side.color, side.status) == ("white", "matched")


# The White default these tests used to pin is gone (FIXPLAN O5): defaulting a miss
# to White is what put 826 games on the wrong side (W11).

def test_no_username_leaves_the_colour_unknown():
    side = attribute({"White": "x", "Black": "y"}, [], NO_ALIASES)
    assert (side.color, side.status) == (None, "no_handles")


def test_no_match_is_not_the_users_game():
    side = attribute({"White": "x", "Black": "y"}, ["zoe"], NO_ALIASES)
    assert (side.color, side.status, side.not_owner) == (None, "not_owner", True)


def test_blank_usernames_count_as_none_configured():
    side = attribute({"White": "x", "Black": "y"}, ["", "  "], NO_ALIASES)
    assert (side.color, side.status) == (None, "no_handles")


def test_both_sides_the_users_is_ambiguous_not_a_guess():
    side = attribute({"White": "new_handle", "Black": "old_handle"},
                     ["new_handle"], {"new_handle": ["old_handle"]})
    assert (side.color, side.status) == (None, "ambiguous")


# ── O5 acceptance (owner ruling 2026-10-22) ──────────────────────────────────

GAME_32_HEADERS = (
    '[Event "Live Chess"]\n[Site "Chess.com"]\n[White "some_opponent"]\n'
    '[Black "old_handle"]\n[Link "https://www.chess.com/game/live/900000000032?move=0"]\n'
    '[Result "*"]\n\n1. e4 g6 *\n'
)


def test_a_game_under_a_former_handle_gets_the_colour_it_was_played_as():
    """Headers shaped like a real game's: played as Black under `old_handle`, before the
    rename to `new_handle`. With only the current handle configured this used to be stored
    White (`review/scratch/o5_detect_today.out`)."""
    headers = chess.pgn.read_headers(io.StringIO(GAME_32_HEADERS))
    side = attribute(headers, ["new_handle"], {"new_handle": ["old_handle"]})
    assert (side.color, side.status) == ("black", "matched")


def test_without_the_alias_a_former_handle_game_is_not_given_a_guessed_colour():
    headers = chess.pgn.read_headers(io.StringIO(GAME_32_HEADERS))
    side = attribute(headers, ["new_handle"], NO_ALIASES)
    assert side.color is None            # never White by default


GAME_41_HEADERS = (
    '[Event "Live Chess"]\n[Site "Chess.com"]\n[White "someone_else"]\n'
    '[Black "another_player"]\n'
    '[Link "https://www.chess.com/analysis/game/live/900000000041/analysis"]\n'
    '[Result "*"]\n\n1. e4 *\n'
)


def test_a_game_neither_of_whose_players_is_the_user_is_marked_not_owner():
    """Headers shaped like game 41's (a game between two other players): no configured handle on either side. It is not the
    user's game, so it is marked — and excluded from every aggregate (see
    test_database's not-owner test)."""
    headers = chess.pgn.read_headers(io.StringIO(GAME_41_HEADERS))
    side = attribute(headers, ["new_handle"], {"new_handle": ["old_handle"]})
    assert (side.color, side.not_owner) == (None, True)


@pytest.mark.parametrize("link, want", [
    ("https://www.chess.com/game/live/900000000032?move=0", "900000000032"),
    ("https://www.chess.com/analysis/game/live/900000000041/analysis", "900000000041"),
    ("https://www.chess.com/game/live/900000000099", "900000000099"),
    ("https://www.chess.com/game/daily/123456789", "123456789"),
])
def test_the_chesscom_game_id_is_the_number_wherever_it_sits(link, want):
    """`/analysis` links used to yield the literal 'analysis', so a file import of a
    synced game never deduplicated (three such duplicates were in the corpus)."""
    headers = chess.pgn.Headers()
    headers["Link"] = link
    assert _external_id(headers) == want


def test_a_lichess_game_id_is_unchanged():
    headers = chess.pgn.Headers()
    headers["Site"] = "https://lichess.org/AbCd1234"
    assert _external_id(headers) == "AbCd1234"


# ── termination resolution ───────────────────────────────────────────────────

def test_termination_keyword_resignation():
    board = chess.Board()
    assert _termination({"Termination": "alice won by resignation"}, board) == "resignation"


def test_termination_draw_before_time_keyword_order():
    board = chess.Board()
    # "drawn by timeout vs insufficient material" -> the draw/insufficient reason,
    # not "timeout" (keyword ordering puts insufficient before time).
    out = _termination(
        {"Termination": "Game drawn by insufficient material vs timeout"}, board
    )
    assert out == "insufficient material"


def test_termination_won_on_time_falls_through_to_timeout():
    board = chess.Board()
    assert _termination({"Termination": "alice won on time"}, board) == "timeout"


@pytest.mark.parametrize("winner, header, want", [
    # AUDIT-K4's four cases, handles changed (the originals are in the private
    # repository): the winner's handle held the keyword.
    ("42-Checkmate-42", "42-Checkmate-42 won by resignation", "resignation"),
    ("xxcheckmatedyou", "xxcheckmatedyou won by resignation", "resignation"),
    ("Timely-2501", "Timely-2501 won on time", "timeout"),
    ("resign999999", "resign999999 won on time", "timeout"),
])
def test_termination_ignores_the_winners_handle(winner, header, want):
    """W13 / AUDIT-K4 (owner, 2026-11-11): only the words after the handle decide."""
    headers = {"White": "new_handle", "Black": winner, "Termination": header}
    assert _termination(headers, chess.Board()) == want


def test_termination_normal_falls_back_to_board():
    # Lichess uses the generic "Normal"; resolve from board state instead.
    board = chess.Board()
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):  # Fool's mate
        board.push_uci(uci)
    assert _termination({"Termination": "Normal"}, board) == "checkmate"


# ── Per-game import reporting ────────────────────────────────────────────────

TRUNCATED = (
    '[Event "Broken"]\n[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n'
    '[Date "2026.01.01"]\n\n1. e4 e5 2. Qh9 Nf6 3. Nf3 1-0\n'
)


def test_report_agrees_with_the_silent_parser():
    # The report is the same parse, so the games it returns must be exactly the
    # ones the silent path yields — otherwise platform sync and manual import
    # would disagree about what a file contains.
    report = parse_pgn_report(TWO_GAMES)
    assert [g.pgn for g in report.games] == [g.pgn for g in parse_pgn_games(TWO_GAMES)]
    assert report.issues == []


def test_a_truncated_game_is_imported_and_reported():
    # The bug this item is really about: python-chess stops at the first move it
    # cannot play, and the game was stored as if it were whole. Two of the five
    # plies survive here, and that must be said out loud.
    report = parse_pgn_report(TRUNCATED)
    assert len(report.games) == 1
    assert report.games[0].move_count == 2
    (issue,) = report.issues
    assert issue.imported is True
    assert issue.index == 1
    assert issue.label == "alice vs bob, 2026.01.01"
    assert "stopped after 2 plies" in issue.reason


def test_a_moveless_game_is_reported_as_skipped():
    pgn = (
        '[Event "Aborted"]\n[White "a"]\n[Black "b"]\n[Result "*"]\n\n*\n\n'
        '[Event "Real"]\n[White "c"]\n[Black "d"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
    )
    report = parse_pgn_report(pgn)
    assert len(report.games) == 1
    (issue,) = report.issues
    assert issue.imported is False
    assert issue.reason == "no moves"
    assert issue.index == 1   # file position, not position among the survivors


def test_issue_index_counts_every_game_in_the_file():
    # Indices are how a user finds the game again, so they must count games the
    # parser rejected too.
    pgn = TWO_GAMES + "\n" + TRUNCATED
    report = parse_pgn_report(pgn)
    assert len(report.games) == 3
    assert [i.index for i in report.issues] == [3]


def test_issues_carry_no_move_text():
    # The label is built from headers so an import report can be shown, logged or
    # pasted without dragging the game's moves along.
    (issue,) = parse_pgn_report(TRUNCATED).issues
    assert "e4" not in issue.label


def test_an_invalid_token_is_dropped_without_an_issue():
    # Documented divergence, not an aspiration: python-chess's tokeniser discards
    # `Qh9` without recording anything, and only the *next* move gets reported —
    # as illegal, which it only was because the move before it vanished. So an
    # issue proves something is wrong; no issue does not prove the game is whole.
    report = parse_pgn_report(
        '[White "a"]\n[Black "b"]\n[Result "0-1"]\n\n1. d4 Qh9 0-1\n'
    )
    assert report.issues == []
    assert report.games[0].move_count == 1   # the `Qh9` is simply gone


def test_match_color_is_none_when_no_handle_matches():
    # Repair needs "nobody here is the user" distinguishable from "the user is White".
    assert _match_color({"White": "x", "Black": "y"}, ["zoe"]) is None
    assert _match_color({"White": "x", "Black": "Zoe"}, ["zoe"]) == "black"
