"""COACH-1 B, C: rule-based themes and the coach's moments, on constructed positions (no owner game)."""
from types import SimpleNamespace

import chess

from zugzwang.core import coach as CO
from zugzwang.core import themes as T

FORK_FEN = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"          # Nc7+ forks the king and the rook on a8
FORK_LINE = ["b5c7", "e8d7", "c7a8"]
BACK_RANK_FEN = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"     # Ra8#


def test_themes_ship_only_above_the_bar_and_the_left_out_are_not_shipped():
    assert "fork" in T.SHIPPED and "backRankMate" in T.SHIPPED and "pin" in T.SHIPPED
    for t in ("bodenMate", "doubleBishopMate", "arabianMate", "intermezzo", "interference", "exposedKing",
              "kingsideAttack", "queensideAttack"):
        assert t not in T.SHIPPED
    assert set(CO.COACH_THEMES) <= set(T.SHIPPED)


def test_a_knight_fork_is_a_fork_by_a_knight():
    line = T.ThemeLine.from_ucis(FORK_FEN, FORK_LINE)
    assert T.fork(line) == chess.KNIGHT
    assert "fork" in T.tag(line)
    assert CO.line_themes(FORK_FEN, FORK_LINE, None, None)[0] == "knightFork"


def test_a_back_rank_mate():
    line = T.ThemeLine.from_ucis(BACK_RANK_FEN, ["a1a8"])
    assert T.mate_in(line) == 1
    assert T.back_rank_mate(line)
    assert {"backRankMate", "mateIn1", "mate"} <= set(T.tag(line))


def test_a_puzzle_is_read_from_its_setup_move():
    # Lichess puzzle 00008 (CC0): tagged hangingPiece by Lichess
    line = T.ThemeLine.from_puzzle("r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24",
                                   "f2g3 e6e7 b2b1 b3c1 b1c1 h6c1")
    assert line.attacker == chess.WHITE
    assert "hangingPiece" in T.tag(line)


def _ply(ply, fen, played, pv, before_cp, after_cp, lines=None, book=False):
    return SimpleNamespace(ply=ply, fen_before=fen, played_uci=played, best_uci=pv[0] if pv else None,
                           pv_uci=" ".join(pv), score_before_cp=before_cp, score_before_mate=None,
                           score_after_cp=after_cp, score_after_mate=None, is_book=book,
                           lines=lines if lines is not None else [{"cp": before_cp, "mate": None, "uci": pv},
                                                                  {"cp": before_cp - 400, "mate": None,
                                                                   "uci": ["e1e2"]}])


def _after(fen, uci):
    b = chess.Board(fen)
    b.push_uci(uci)
    return b.fen()


def test_a_chance_caught_when_the_best_move_is_played():
    plies = [_ply(0, FORK_FEN, "b5c7", FORK_LINE, 300, 300),
             _ply(1, _after(FORK_FEN, "b5c7"), "e8d7", ["e8d7", "c7a8"], -300, -300)]
    ms = CO.moments_for_run(plies, [], "white")
    chances = [m for m in ms if m.kind == "chance"]
    assert len(chances) == 1 and chances[0].outcome == "caught" and chances[0].themes[0] == "knightFork"
    assert CO.sentence(chances[0], "knightFork", FORK_FEN) == "You found the knight fork that starts with 1. Nc7+."


def test_a_chance_missed_is_gate_p():
    after = _after(FORK_FEN, "e1e2")
    plies = [_ply(0, FORK_FEN, "e1e2", FORK_LINE, 300, -150),
             _ply(1, after, "a8a2", ["a8a2", "e2d3"], 150, 150)]
    ms = CO.moments_for_run(plies, [], "white")
    chances = [m for m in ms if m.kind == "chance"]
    assert len(chances) == 1 and chances[0].outcome == "missed"
    assert CO.sentence(chances[0], "knightFork", FORK_FEN) == "1. Nc7+ started a knight fork; you played 1. Ke2."


def test_no_chance_when_another_move_is_as_good():
    plies = [_ply(0, FORK_FEN, "b5c7", FORK_LINE, 300, 300,
                  lines=[{"cp": 300, "mate": None, "uci": FORK_LINE}, {"cp": 290, "mate": None, "uci": ["e1e2"]}])]
    assert [m for m in CO.moments_for_run(plies, [], "white") if m.kind == "chance"] == []


def test_a_parried_threat_needs_the_null_move_line_and_a_quiet_next_ply():
    # Black to move; White threatens Nc7+ (the fork) if Black passes. Black plays Rb8, out of the fork.
    fen = "r3k3/8/8/1N6/8/8/8/4K3 b - - 0 1"
    nf = CO.null_fen(fen)
    assert nf is not None and chess.Board(nf).turn == chess.WHITE
    after = _after(fen, "a8b8")
    plies = [_ply(0, fen, "a8b8", ["a8b8", "b5c7"], -300, -300),
             _ply(1, after, "b5c7", ["b5c7", "e8d7"], 300, 300)]
    m = CO.parried_threat_at(plies, [], 0, FORK_LINE)
    assert m is not None and m.kind == "threat" and m.outcome == "caught" and m.via == "parried"
    assert m.themes[0] == "knightFork"
    assert CO.sentence(m, "knightFork", fen) == "1... Rb8 dealt with the threat of a knight fork (Nc7+)."
    assert CO.parried_threat_at(plies, [], 0, None) is None


def test_history_lines():
    assert CO.history_line([]) is None
    assert CO.history_line(["missed"]) == "You missed this the last time it came up."
    assert CO.history_line(["caught"]) == "You caught this the last time it came up."
    assert CO.history_line(["missed", "caught", "missed"]) == "You had missed this 2 of the last 3 times."
    assert CO.history_line(["missed"] * 30) == f"You had missed this {CO.HISTORY_MAX} of the last {CO.HISTORY_MAX} times."


def _m(kind, outcome, themes, mt="capture"):
    return CO.Moment(ply=10, kind=kind, outcome=outcome, themes=themes, fen=FORK_FEN, line=FORK_LINE,
                     played="b5c7", key_move="b5c7", move_type=mt, mate=False, gain=5.0)


def _games(n, theme_miss, other_miss):
    games = []
    for g in range(n):
        ms = [_m("threat", "missed" if g % 10 < theme_miss else "caught", ["knightFork"]),
              _m("threat", "missed" if g % 10 < other_miss else "caught", ["pin"]),
              _m("threat", "missed" if g % 10 < other_miss else "caught", ["skewer"])]
        games.append((f"g{g}", ms))
    return games


def test_focus_names_a_theme_clearly_worse_than_the_others_and_nothing_when_level():
    fc = CO.focus(_games(400, theme_miss=8, other_miss=3))
    assert [f"{c['kind']}:{c['theme']}" for c in fc["focus"]] == ["threat:knightFork"]
    assert CO.focus(_games(400, theme_miss=3, other_miss=3))["focus"] == []
    assert CO.focus(_games(6, theme_miss=8, other_miss=3))["focus"] == []        # too few games to tell


def test_report_patterns_history_only_for_focus():
    game = CO.GameMoments(game_id=1, key="x", played_at="2026-11-01", colour="white", opponent=None,
                          fens={10: FORK_FEN}, moments=[_m("chance", "caught", ["knightFork"])])
    plain = CO.report_patterns(game, {"chance:knightFork": ["missed", "missed"]}, set())
    assert plain["items"][0]["history"] is None and plain["items"][0]["focus"] is False
    fo = CO.report_patterns(game, {"chance:knightFork": ["missed", "missed"]}, {"chance:knightFork"})
    assert fo["items"][0]["focus"] is True
    assert fo["items"][0]["history"] == "You had missed this 2 of the last 2 times."
    assert fo["items"][0]["sentence"] == "You found the knight fork that starts with 1. Nc7+."


def test_the_loose_piece_has_its_own_words():
    one = CO.Moment(ply=0, kind="chance", outcome="missed", themes=["hangingPiece"], fen=FORK_FEN, line=["b5c7"],
                    played="e1e2", key_move="b5c7", move_type="check", mate=False, gain=3.0)
    assert CO.sentence(one, "hangingPiece", FORK_FEN) == "1. Nc7+ took a loose piece; you played 1. Ke2."
    took = CO.Moment(**{**one.to_dict(), "outcome": "caught", "played": "b5c7"})
    assert CO.sentence(took, "hangingPiece", FORK_FEN) == "You took the loose piece: 1. Nc7+."
    after = chess.Board(FORK_FEN)
    after.push_uci("e1e2")
    left = CO.Moment(ply=0, kind="threat", outcome="missed", themes=["hangingPiece"], fen=after.fen(),
                     line=["a8a2"], played="e1e2", key_move="a8a2", move_type="other", mate=False, gain=3.0)
    assert CO.sentence(left, "hangingPiece", FORK_FEN) == "1. Ke2 left a piece hanging: 1... Ra2+ takes it."


# ── FIX-B8, rulings D9a and D9b (owner, 2026-11-25; COACH.md "Owner rulings, 2026-11-25, second") ──

LOOSE_KNIGHT_FEN = "4k3/4p3/8/3n4/8/8/8/3RK3 b - - 0 1"   # Black to move; Rxd5 would take the knight


def _parry(played, next_pv):
    after = _after(LOOSE_KNIGHT_FEN, played)
    plies = [_ply(0, LOOSE_KNIGHT_FEN, played, [played, *next_pv[:1]], -20, -20),
             _ply(1, after, next_pv[0], next_pv, 20, 20)]
    return CO.parried_threat_at(plies, [], 0, ["d1d5"])


def test_d9a_moving_the_attacked_piece_away_from_a_one_move_capture_is_not_a_catch():
    assert CO.moved_away(CO.null_fen(LOOSE_KNIGHT_FEN), ["d1d5"], "d5f4")
    assert _parry("d5f4", ["e1e2", "e8d7"]) is None


def test_d9a_a_defence_still_counts_as_caught_and_so_does_moving_away_from_a_longer_threat():
    m = _parry("e7e6", ["e1e2", "e8d7"])
    assert m is not None and m.outcome == "caught" and m.via == "parried" and m.line == ["d1d5"]
    assert not CO.moved_away(CO.null_fen(LOOSE_KNIGHT_FEN), ["d1d5"], "e7e6")
    # a threat longer than one move (the knight fork) is a catch even when the forked rook steps away
    assert not CO.moved_away(CO.null_fen("r3k3/8/8/1N6/8/8/8/4K3 b - - 0 1"), FORK_LINE, "a8b8")
    assert CO.COACH_VERSION == 2      # moments refill under the new rule


def test_d9b_the_threat_side_says_hanging_piece_the_chance_side_loose_piece():
    assert CO.theme_name("threat", "hangingPiece") == "Hanging piece"
    assert CO.theme_name("chance", "hangingPiece") == "Loose piece"
    assert CO.theme_name("threat", "fork") == "Fork" == CO.theme_name("chance", "fork")
    assert CO.item_title("threat", "hangingPiece") == "Hanging pieces against you"
    assert CO.item_title("chance", "hangingPiece") == "Your own loose pieces"
    m = _parry("e7e6", ["e1e2", "e8d7"])
    assert CO.sentence(m, "hangingPiece", LOOSE_KNIGHT_FEN) == "1... e6 dealt with a hanging piece (Rxd5 would have taken it)."
    game = CO.GameMoments(game_id=1, key="g1", played_at="2026-11-01", colour="black", opponent=None,
                          fens={0: LOOSE_KNIGHT_FEN}, moments=[m])
    pat = CO.report_patterns(game, {}, set())
    assert [(p["kind"], p["name"]) for p in pat["items"]] == [("threat", "Hanging piece")]



# ── COACH-2 ruling CF1: Focus by what costs the user most ──

from datetime import datetime, timezone  # noqa: E402

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def _gm(i, moments, losses, date="2026-10-01T12:00:00+00:00"):
    return CO.GameMoments(game_id=i, key=f"g{i}", played_at=date, colour="white", opponent=None,
                          fens={10: FORK_FEN, 11: FORK_FEN, 12: FORK_FEN}, moments=moments, losses=losses)


def _cost_games(n=60):
    """Per game: a missed loose piece against the user (0.10), a missed pin (0.04) and a caught skewer; every
    third game a missed fork of its own (0.25): loose pieces cost most (6.0), then forks (5.0), then pins (2.4)."""
    out = []
    for g in range(n):
        ms = [_m("threat", "missed", ["hangingPiece"]), _m("threat", "missed", ["pin"]),
              _m("threat", "caught", ["skewer"])]
        ms[1].ply = 11
        losses = {10: 0.10, 11: 0.04}
        if g % 3 == 0:
            ms.append(CO.Moment(**{**_m("chance", "missed", ["fork", "hangingPiece"]).to_dict(), "ply": 12}))
            losses[12] = 0.25
        out.append(_gm(g, ms, losses))
    return out


def test_cost_focus_ranks_by_the_win_probability_lost_on_missed_moments():
    fc = CO.cost_focus(_cost_games(), now=NOW)
    assert [f["key"] for f in fc["focus"]] == ["threat:hangingPiece", "chance:fork", "threat:pin"]
    first = fc["focus"][0]
    assert first["missed"] == 60 and first["total"] == 60 and abs(first["cost"] - 6.0) < 1e-9
    assert all(f["held"] >= CO.BOOT_SHARE for f in fc["focus"])
    # a moment counts under one theme, its primary: the fork is not also a loose piece of the user's
    assert "chance:hangingPiece" not in {g["key"] for g in fc["groups"]}


def test_cost_focus_reads_the_last_12_months_only():
    old = [_gm(100 + i, [_m("threat", "missed", ["backRankMate"])], {10: 0.9}, date="2024-01-01T00:00:00+00:00")
           for i in range(30)]
    fc = CO.cost_focus(_cost_games() + old, now=NOW)
    assert "threat:backRankMate" not in {g["key"] for g in fc["groups"]}
    assert fc["games"] == 60
    assert CO.cost_focus(_cost_games() + old, now=NOW, days=36500)["focus"][0]["key"] == "threat:backRankMate"


def test_an_item_whose_place_does_not_hold_is_not_shown():
    """One game's single costly miss puts a group third by its sum, but resampling the games drops it out of the
    top three in far more than a fifth of the resamples: it is not shown."""
    games = _cost_games(30)
    games.append(_gm(999, [CO.Moment(**{**_m("threat", "missed", ["smotheredMate"]).to_dict(), "ply": 10})],
                     {10: 1.3}))
    fc = CO.cost_focus(games, now=NOW)
    top3 = [g["key"] for g in fc["groups"][:3]]
    assert "threat:smotheredMate" in top3
    sm = next(g for g in fc["groups"] if g["key"] == "threat:smotheredMate")
    assert sm["held"] < CO.BOOT_SHARE
    assert "threat:smotheredMate" not in [f["key"] for f in fc["focus"]]


def test_cost_focus_is_the_same_for_the_same_games_and_empty_with_no_misses():
    a = CO.cost_focus(_cost_games(), now=NOW)
    b = CO.cost_focus(list(reversed(_cost_games())), now=NOW)
    assert [(f["key"], f["held"]) for f in a["focus"]] == [(f["key"], f["held"]) for f in b["focus"]]
    caught = [_gm(i, [_m("threat", "caught", ["pin"])], {10: 0.2}) for i in range(10)]
    assert CO.cost_focus(caught, now=NOW)["focus"] == []


def test_the_overview_shows_missed_x_of_y_in_the_window():
    ov = CO.build_overview(_cost_games(), now=NOW)
    assert [f["key"] for f in ov["focus"]] == ["threat:hangingPiece", "chance:fork", "threat:pin"]
    assert ov["windowDays"] == 365 and ov["windowGames"] == 60
    pin = ov["focus"][2]
    assert (pin["missed"], pin["total"], pin["rowCount"]) == (60, 60, 60)
    assert pin["title"] == "Pins against you"


def test_the_report_names_a_moment_by_the_theme_it_counts_under():
    """CF1: a moment's theme in the report is its primary one, focus or not, so a history line counts the
    same moments the focus card does."""
    mo = _m("threat", "missed", ["knightFork", "fork", "hangingPiece"])
    game = CO.GameMoments(game_id=1, key="x", played_at="2026-11-01", colour="white", opponent=None,
                          fens={10: FORK_FEN}, moments=[mo])
    pat = CO.report_patterns(game, {"threat:knightFork": ["missed"]}, {"threat:hangingPiece"})
    assert pat["items"][0]["theme"] == "knightFork" and pat["items"][0]["focus"] is False
    assert CO.moment_key(mo) == "threat:knightFork"
