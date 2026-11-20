"""R6 (PATTERNS.md §6a; owner rulings R6-1..R6-6, 2026-11-13): the stored pattern facts and the
Insights patterns card. Constructed games only; the figures on the owner's games are measured
in review/scratch/patterns/r6/."""

import io
import json

import chess
import chess.pgn
import pytest

from zugzwang.core import patterns
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.core.database import Database, InsightsFilter, MoveAnalysis
from zugzwang.core.explain import RULE_VERSION
from zugzwang.core.insights import build_insights

SCHOLAR = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"
#            0     1      2      3      4      5      6
LABELS = ["best", "best", "good", "good", "inaccuracy", "blunder", "best"]


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "pat.db")
    yield d
    d.close()


def _plies(movetext=SCHOLAR, labels=LABELS):
    game = chess.pgn.read_game(io.StringIO(f'[Event "t"]\n\n{movetext}'))
    board = game.board()
    out = []
    for i, move in enumerate(game.mainline_moves()):
        out.append(MoveAnalysis(
            ply=i, fen_before=board.fen(), played_uci=move.uci(), best_uci=move.uci(),
            pv_uci=move.uci(), score_before_cp=30, score_before_mate=None,
            score_after_cp=30, score_after_mate=None, second_best_uci=None,
            second_best_cp=None, second_best_mate=None, classification=labels[i],
            is_book=False))
        board.push(move)
    return out


def _complete_game(db, *, color="white", result="1-0", played_at="2026-11-01T00:00:00+00:00",
                   labels=LABELS):
    gid = db.save_game(
        played_at=played_at, player_color=color, skill_level=0, result=result,
        termination="checkmate", move_count=7,
        pgn=f'[White "Alice"]\n[Black "Bob"]\n[Result "{result}"]\n\n{SCHOLAR}',
        final_fen="8/8/8/8/8/8/8/8 w - - 0 1", source="lichess")
    run = db.save_analysis_run(game_id=gid, engine_name="SF", depth=14)
    db.complete_analysis_run(run, {}, plies=_plies(labels=labels))
    return gid, run


# ── P4's facts ─────────────────────────────────────────────────────────────────

def test_p4_counts_the_move_after_the_other_sides_serious_error():
    plies = _plies()
    # 3…Nf6 (ply 5) is Black's blunder; 4.Qxf7# (ply 6) answers it with the engine's move.
    # 3.Qh5 (ply 4) is an inaccuracy, not serious: 3…Nf6 is not counted.
    f = patterns.p4_facts(plies)
    assert f["white"] == {"n": 1, "best": 1, "missed": []}
    assert f["black"] == {"n": 0, "best": 0, "missed": []}


def test_p4_lists_a_reply_that_was_not_the_engines_move():
    # 4.Bxf7+ (not mate) where the engine's move was 4.Qxf7#: listed. (Before K2 this test
    # used 4.Qxf7# against 4.Bxf7+; a mate now counts as punishing.)
    plies = _plies()
    plies[5] = MoveAnalysis(**{**plies[5].__dict__, "classification": "mistake"})
    plies[6] = MoveAnalysis(**{**plies[6].__dict__, "best_uci": "h5f7", "played_uci": "c4f7"})
    f = patterns.p4_facts(plies)
    assert f["white"] == {"n": 1, "best": 0, "missed": [[6, "4.Bxf7+", "best"]]}


def test_k2_a_reply_that_mates_counts_as_punishing():
    # K2 (owner, 2026-11-14): 4.Qxf7# answers 3…Nf6's mistake with mate, though the engine's
    # move was another (constructed: best set to 4.Bxf7+). It punished: counted, not listed.
    plies = _plies()
    plies[5] = MoveAnalysis(**{**plies[5].__dict__, "classification": "mistake"})
    plies[6] = MoveAnalysis(**{**plies[6].__dict__, "best_uci": "c4f7"})
    f = patterns.p4_facts(plies)
    assert f["white"] == {"n": 1, "best": 1, "missed": []}


def test_k2_bumped_the_facts_version():
    assert patterns.FACTS_VERSION == 2


# ── the table ──────────────────────────────────────────────────────────────────

def test_the_facts_are_written_for_a_complete_run_and_count_at_its_classifier_version(db):
    gid, run = _complete_game(db)
    assert db.runs_without_pattern_facts(patterns.FACTS_VERSION, rule_version=RULE_VERSION) == [run]
    assert patterns.write_facts_for_run(db, run)
    assert db.runs_without_pattern_facts(patterns.FACTS_VERSION, rule_version=RULE_VERSION) == []
    rows = db.insights_pattern_facts(InsightsFilter(), patterns.FACTS_VERSION,
        rule_version=RULE_VERSION)
    assert [r[0] for r in rows] == [gid]
    facts = json.loads(rows[0][3])
    assert facts["p4"]["white"]["n"] == 1
    assert facts["players"] == {"white": "Alice", "black": "Bob"}
    stored = db._conn.execute(
        "SELECT classifier_version FROM pattern_facts WHERE run_id = ?", (run,)).fetchone()[0]
    assert stored == CLASSIFIER_VERSION


def test_a_relabelled_run_leaves_its_stale_facts_out(db):
    gid, run = _complete_game(db)
    patterns.write_facts_for_run(db, run)
    db._conn.execute("UPDATE analysis_runs SET classifier_version = ? WHERE id = ?",
                     (CLASSIFIER_VERSION + 1, run))
    db._conn.commit()
    assert db.insights_pattern_facts(InsightsFilter(), patterns.FACTS_VERSION,
        rule_version=RULE_VERSION) == []
    assert db.runs_without_pattern_facts(patterns.FACTS_VERSION, rule_version=RULE_VERSION) == [run]


def test_facts_of_another_rule_version_are_stale(db):
    # PATTERNS.md §6e (the orchestrator's process decision, 2026-11-14): a rule change makes
    # the facts stale; they are left out and listed for the refill.
    gid, run = _complete_game(db)
    patterns.write_facts_for_run(db, run)
    db._conn.execute("UPDATE pattern_facts SET rule_version = ? WHERE run_id = ?",
                     (RULE_VERSION - 1, run))
    db._conn.commit()
    assert db.insights_pattern_facts(InsightsFilter(), patterns.FACTS_VERSION,
                                     rule_version=RULE_VERSION) == []
    assert db.runs_without_pattern_facts(patterns.FACTS_VERSION,
                                         rule_version=RULE_VERSION) == [run]


def test_another_facts_version_does_not_count(db):
    gid, run = _complete_game(db)
    patterns.write_facts_for_run(db, run)
    assert db.insights_pattern_facts(InsightsFilter(), patterns.FACTS_VERSION + 1,
        rule_version=RULE_VERSION) == []


def test_a_deleted_run_takes_its_facts_with_it(db):
    gid, run = _complete_game(db)
    patterns.write_facts_for_run(db, run)
    run2 = db.save_analysis_run(game_id=gid, engine_name="SF", depth=14)
    db.complete_analysis_run(run2, {}, plies=_plies())     # deletes the game's other runs
    assert db._conn.execute("SELECT COUNT(*) FROM pattern_facts").fetchone()[0] == 0


def test_the_facts_obey_insights_filters(db):
    gw, rw = _complete_game(db, color="white")
    gb, rb = _complete_game(db, color="black", result="1-0")
    for r in (rw, rb):
        patterns.write_facts_for_run(db, r)
    rows = db.insights_pattern_facts(InsightsFilter(color="black"), patterns.FACTS_VERSION,
        rule_version=RULE_VERSION)
    assert [r[0] for r in rows] == [gb]


def test_a_database_without_the_table_reads_as_no_facts(tmp_path):
    d = Database(tmp_path / "x.db")
    d._conn.execute("DROP TABLE pattern_facts")
    d._conn.commit()
    assert d.insights_pattern_facts(InsightsFilter(), patterns.FACTS_VERSION,
        rule_version=RULE_VERSION) == []
    d.close()


# ── the card ───────────────────────────────────────────────────────────────────

def _facts(you, *, mine=(0, 0), theirs=(0, 0), decided=None, single=False):
    opp = "black" if you == "white" else "white"
    p4 = {you: {"n": mine[0], "best": mine[1],
                "missed": [[10 + k, "6.Nf3", "mistake"] for k in range(mine[0] - mine[1])]},
          opp: {"n": theirs[0], "best": theirs[1], "missed": []}}
    side = None if decided is None else (you if decided == "won" else opp)
    return json.dumps({"p4": p4, "p6": {"decided": decided is not None, "side": side,
                                        "byPly": 20 if single else None,
                                        "byMove": "11.Bxf7+" if single else None},
                       "players": {"white": "Alice", "black": "Bob"}})


def _rows(n, make):
    return [(g, f"2026-01-{1 + g % 28:02d}T00:00:00", "white", make(g)) for g in range(n)]


def test_a_clear_pattern_on_many_games_is_shown_with_its_link():
    # 400 games: you answer 6 of 10 with the engine's move, they answer 4 of 10; your losses
    # (half the games) are all decided by one move, your wins one in five.
    rows = _rows(400, lambda g: _facts(
        "white", mine=(10, 6), theirs=(10, 4),
        decided="lost" if g % 2 else "won", single=bool(g % 2) or g % 10 == 0))
    card = patterns.build_patterns(rows, 410)
    assert card["covered"] == 400 and card["analysed"] == 410
    keys = [s["key"] for s in card["sentences"]]
    assert keys == ["punish", "decided"]
    s = card["sentences"][0]
    assert s["text"] == ("When your opponent makes a serious error, you punish it more often "
                         "than they punish yours: you played the engine's move or mated after "
                         "2,400 of "
                         "their 4,000 (60.0 %); they did after 1,600 of your 4,000 (40.0 %).")
    assert s["link"]["count"] == 1600
    assert s["link"]["label"] == "Your answers that weren't the engine's move, newest first"
    assert s["link"]["items"][0]["date"] >= s["link"]["items"][-1]["date"]   # newest first
    d = card["sentences"][1]
    assert d["link"]["count"] == 200 and all(it["ply"] == 20 for it in d["link"]["items"])


def test_thirty_games_with_noise_show_nothing():
    # The same direction, far too few games and too small a gap for the interval.
    rows = _rows(30, lambda g: _facts("white", mine=(3, 2 if g % 3 else 1), theirs=(3, 1 + g % 2),
                                      decided="lost" if g % 2 else "won", single=g % 3 == 0))
    card = patterns.build_patterns(rows, 30)
    assert card["sentences"] == []
    assert {t["key"] for t in card["tested"]} == {"punish", "decided"}
    assert not any(t["shown"] for t in card["tested"])


def test_the_direction_is_fixed_a_significant_reverse_is_not_shown():
    # You punish *less* often, clearly: not the sentence's claim, so nothing is said.
    rows = _rows(400, lambda g: _facts("white", mine=(10, 3), theirs=(10, 6)))
    card = patterns.build_patterns(rows, 400)
    t = next(t for t in card["tested"] if t["key"] == "punish")
    assert t["hi"] < 1.0 and not t["shown"]
    assert card["sentences"] == []


def test_the_clustered_interval_treats_the_game_as_the_unit():
    # The same totals, concentrated in a few games, give a wider interval.
    spread = [(10, 7 if k % 2 else 5, 10, 4) for k in range(100)]
    lumpy = [(100, 70 if k % 20 else 50, 100, 40) if k % 10 == 0 else (0, 0, 0, 0)
             for k in range(100)]
    a, b = patterns.clustered_rr(spread), patterns.clustered_rr(lumpy)
    assert a["rr"] == pytest.approx(b["rr"]) == pytest.approx(1.5)
    assert (b["hi"] - b["lo"]) > (a["hi"] - a["lo"])


def test_build_insights_carries_the_card_and_its_coverage(db):
    _gid, run = _complete_game(db)
    _complete_game(db)                       # analysed, no facts yet
    patterns.write_facts_for_run(db, run)
    out = build_insights(db)
    assert out["patterns"]["covered"] == 1 and out["patterns"]["analysed"] == 2
