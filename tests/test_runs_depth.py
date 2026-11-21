"""RUNS-DEPTH (owner, 2026-11-20; DESIGN.md "RUNS-DEPTH"): a deeper Analyse again run is kept
beside the depth-14 run; finishing a run replaces only a run of the same depth (the standard
slot: a Stockfish depth-14 run or a non-Stockfish cloud run); Review shows the deepest complete
run and can switch back; every aggregate reads only the standard run. VAL-DEATH holds: only
complete runs count, and `audit_run_completeness` finds nothing on whole runs."""
import importlib.util
from pathlib import Path

import pytest

import zugzwang.config as C
from zugzwang.core.database import Database, MoveAnalysis, run_slot, standard_run_sql

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_rd", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

PGN = '[Event "t"]\n[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
FENS = ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]
UCIS = ["e2e4", "e7e5"]


def _plies(cls="best"):
    return [MoveAnalysis(ply=i, fen_before=FENS[i], played_uci=UCIS[i], best_uci=UCIS[i],
                         pv_uci=UCIS[i], score_before_cp=20, score_before_mate=None,
                         score_after_cp=-20, score_after_mate=None, second_best_uci=None,
                         second_best_cp=None, second_best_mate=None, classification=cls,
                         is_book=False) for i in range(2)]


def _game(db, source="chesscom", ext="1"):
    return db.save_game(played_at="2026-11-20T10:00:00+00:00", player_color="white",
                        skill_level=0, result="1-0", termination="resignation", move_count=2,
                        pgn=PGN, final_fen=FENS[1], source=source, external_id=ext)


def _run(db, gid, depth, acc, engine="Stockfish", complete=True):
    rid = db.save_analysis_run(game_id=gid, engine_name=engine, depth=depth)
    if complete:
        db.complete_analysis_run(rid, {}, white_accuracy=acc, black_accuracy=acc,
                                 plies=_plies())
    return rid


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "r.db")
    yield d
    d.close()


def _depths(db, gid):
    return [(r.depth, r.standard) for r in db.list_complete_runs(gid)]


def test_the_standard_slot_is_stockfish_at_14_or_any_cloud_run():
    assert C.ANALYSIS_STANDARD_DEPTH == 14
    assert run_slot("Stockfish", 14) == "standard"
    assert run_slot("Lichess evals", 0) == "standard"
    assert run_slot("Stockfish", 18) == "depth-18"
    assert run_slot("Stockfish", 10) == "depth-10"
    assert "r.depth = 14" in standard_run_sql()


def test_a_deeper_run_is_kept_beside_the_depth_14_run(db):
    gid = _game(db)
    r14 = _run(db, gid, 14, 80.0)
    r18 = _run(db, gid, 18, 90.0)
    assert _depths(db, gid) == [(18, False), (14, True)]
    assert db.load_latest_run(gid).id == r18            # Review: the deepest
    assert db.load_review_run(gid, r14).id == r14       # and it can switch back
    assert db.load_standard_run(gid).id == r14
    assert db.audit_run_completeness() == []            # VAL-DEATH: both runs whole


def test_finishing_a_run_replaces_only_a_run_of_the_same_depth(db):
    gid = _game(db)
    r14 = _run(db, gid, 14, 80.0)
    r18 = _run(db, gid, 18, 90.0)
    r24 = _run(db, gid, 24, 95.0)
    r18b = _run(db, gid, 18, 91.0)                      # a second 18 replaces the first
    assert [r.id for r in db.list_complete_runs(gid)] == [r24, r18b, r14]
    r14b = _run(db, gid, 14, 81.0)                      # a new 14 replaces only the 14
    assert [r.id for r in db.list_complete_runs(gid)] == [r24, r18b, r14b]
    assert r18 not in [r.id for r in db.list_complete_runs(gid)]


def test_a_stockfish_14_run_replaces_a_cloud_run_both_being_standard(db):
    gid = _game(db, source="lichess")
    _run(db, gid, 0, 70.0, engine="Lichess evals")
    r14 = _run(db, gid, 14, 80.0)
    assert [(r.id, r.depth) for r in db.list_complete_runs(gid)] == [(r14, 14)]


def test_an_incomplete_deeper_run_is_never_shown_and_never_counts(db):
    gid = _game(db)
    r14 = _run(db, gid, 14, 80.0)
    dead = _run(db, gid, 24, None, complete=False)
    assert db.load_latest_run(gid).id == r14
    assert db.load_review_run(gid, dead).id == r14      # an incomplete run is never picked
    assert _depths(db, gid) == [(14, True)]


def test_a_run_of_another_game_is_never_picked(db):
    a, b = _game(db, ext="a"), _game(db, ext="b")
    _run(db, a, 14, 80.0)
    rb = _run(db, b, 14, 60.0)
    assert db.load_review_run(a, rb).game_id == a


def test_every_aggregate_reads_only_the_depth_14_run(db):
    gid = _game(db)
    _run(db, gid, 14, 80.0)
    _run(db, gid, 24, 99.0)
    ov = db.insights_overview()
    assert (ov["total"], ov["analyzed"]) == (1, 1)
    assert [round(r[2], 1) for r in db.insights_accuracy_trend()] == [80.0]
    assert [r[4] for r in db.insights_game_details()] == [80.0]
    assert sum(n for _c, _cls, n in db.insights_move_quality()) == 1     # one player ply, once
    assert len(db.insights_phase_quality()) == 2                         # two plies, once
    (_rec, summary), = db.list_games_with_runs()
    assert summary.white_accuracy == 80.0
    assert db.games_pending_analysis("chesscom", 14) == []


def test_a_game_with_only_a_deeper_run_stays_pending_and_out_of_aggregates(db):
    gid = _game(db)
    r24 = _run(db, gid, 24, 99.0)
    assert db.load_latest_run(gid).id == r24            # Review shows it
    assert db.load_standard_run(gid) is None
    assert db.insights_overview()["analyzed"] == 0
    assert [g.id for g in db.games_pending_analysis("chesscom", 14)] == [gid]
    r14 = _run(db, gid, 14, 80.0)                       # the sync's run joins it
    assert [r.id for r in db.list_complete_runs(gid)] == [r24, r14]


def test_the_patterns_card_reads_the_standard_runs_facts_only(db):
    import json
    gid = _game(db)
    r14 = _run(db, gid, 14, 80.0)
    r18 = _run(db, gid, 18, 90.0)
    # facts are kept for every complete run (completion writes them; refill keeps them current)
    assert db.runs_without_pattern_facts(1, rule_version=1) == [r14, r18]
    cv = {r: db._conn.execute("SELECT classifier_version FROM analysis_runs WHERE id=?", (r,)).fetchone()[0]
          for r in (r14, r18)}
    db.save_pattern_facts([(r, 1, cv[r], 1, json.dumps({"run": r})) for r in (r14, r18)])
    rows = db.insights_pattern_facts(None, 1, rule_version=1)
    assert [json.loads(f)["run"] for *_x, f in rows] == [r14]


# ── the sidecar ───────────────────────────────────────────────────────────────

@pytest.fixture
def server(db):
    srv = object.__new__(sidecar.Server)
    srv._db = db
    srv._openings = None
    return srv


def test_rpc_get_game_lists_the_runs_and_switches_between_them(server):
    gid = _game(server._db)
    r14 = _run(server._db, gid, 14, 80.0)
    r18 = _run(server._db, gid, 18, 90.0)
    out = server.rpc_get_game(gid)
    assert out["analysis"]["runId"] == r18 and out["analysis"]["depth"] == 18
    assert [(r["id"], r["depth"], r["standard"]) for r in out["runs"]] == [(r18, 18, False), (r14, 14, True)]
    back = server.rpc_get_game(gid, run_id=r14)
    assert back["analysis"]["runId"] == r14 and back["analysis"]["whiteAccuracy"] == 80.0
    assert server.rpc_review_extras(gid, run_id=r14)["depth"] == 14
    assert server.rpc_review_extras(gid)["depth"] == 18
    seen = []
    real = sidecar.build_report
    sidecar.build_report = lambda *a, **k: seen.append(k["depth"]) or {}
    try:
        server.rpc_game_report(gid, run_id=r14)
        server.rpc_game_report(gid)
    finally:
        sidecar.build_report = real
    assert seen == [14, 18]


def test_rpc_home_summary_reads_the_depth_14_run(server):
    gid = _game(server._db)
    _run(server._db, gid, 14, 80.0)
    _run(server._db, gid, 24, 99.0)
    out = server.rpc_home_summary(now="2026-11-20T12:00:00+00:00")
    assert (out["games"], out["analysed"], out["avgAccuracy"]) == (1, 1, 80.0)


def test_sync_always_analyses_at_the_standard_depth():
    # Ruling 17 + RUNS-DEPTH: a client's preset depth (Fast 10, Deep 18) is ignored.
    for asked in (None, 8, 10, 18, 24):
        assert sidecar.Server._clamp_depth(asked) == 14
