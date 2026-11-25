"""COACH-1 C: the sidecar's coach path on a stored game (constructed position, no owner data)."""
import json
import types

import chess
import pytest

import sidecar.main as sidecar
from zugzwang.core import coach as CO
from zugzwang.core.database import Database, MoveAnalysis
from zugzwang.core.themes import THEMES_VERSION

FEN = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
PGN = f'[Event "t"]\n[SetUp "1"]\n[FEN "{FEN}"]\n[Result "*"]\n\n1. Nc7+ Kd7 2. Nxa8 *\n'


def _store(db: Database) -> tuple[int, int]:
    b = chess.Board(FEN)
    moves = ["b5c7", "e8d7", "c7a8"]
    pvs = [["b5c7", "e8d7", "c7a8"], ["e8d7", "c7a8"], ["c7a8", "d7c6"]]
    cps = [300, -300, 400]
    gid = db.save_game(played_at="2026-11-20T00:00:00", player_color="white", skill_level=0, result="*",
                       termination="unterminated", move_count=3, pgn=PGN, final_fen=FEN, source="imported")
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=14)
    plies = []
    for i, mv in enumerate(moves):
        fen = b.fen()
        nxt = cps[i + 1] if i + 1 < len(cps) else 0
        plies.append(MoveAnalysis(
            ply=i, fen_before=fen, played_uci=mv, best_uci=pvs[i][0], pv_uci=" ".join(pvs[i]),
            score_before_cp=cps[i], score_before_mate=None, score_after_cp=-nxt, score_after_mate=None,
            second_best_uci=None, second_best_cp=None, second_best_mate=None, classification="best",
            is_book=False, lines=[{"cp": cps[i], "mate": None, "uci": pvs[i], "san": []},
                                  {"cp": cps[i] - 400, "mate": None, "uci": ["e1e2"], "san": []}]))
        b.push_uci(mv)
    db.complete_analysis_run(run, {}, white_accuracy=None, black_accuracy=None, plies=plies)
    return gid, run


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "c.db")


def test_the_refill_computes_moments_and_the_report_reads_them(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sidecar, "_send", lambda obj: None)
    gid, run = _store(db)
    assert db.runs_without_coach_moments(CO.COACH_VERSION, THEMES_VERSION) == [run]
    runner = object.__new__(sidecar.AnalysisRunner)
    searched = []
    runner._engine = types.SimpleNamespace(analyse=lambda board, limit: searched.append(board.fen()) or {"pv": []})
    row = runner._coach_row(db, run)
    assert row[0] == run and row[1] == CO.COACH_VERSION and row[2] == THEMES_VERSION
    moments = json.loads(row[3])
    assert [(m["kind"], m["outcome"], m["themes"][0]) for m in moments] == [("chance", "caught", "knightFork")]
    assert searched, "the null-move search ran for the user's plies"
    assert db.save_coach_moments([row]) == 1
    assert db.runs_without_coach_moments(CO.COACH_VERSION, THEMES_VERSION) == []

    srv = object.__new__(sidecar.Server)
    srv._db = db
    srv._coach = None
    pat = srv._coach_patterns(gid, run)
    assert pat["items"][0]["sentence"] == "You found the knight fork that starts with 1. Nc7+."
    assert pat["items"][0]["focus"] is False and pat["items"][0]["history"] is None

    games = sidecar._coach_games(db)
    assert len(games) == 1 and games[0].opponent is None and games[0].key == f"local-{gid}"
    ov = CO.build_overview(games)
    assert ov["games"] == 1 and ov["focus"] == []          # one game passes no bar


def test_the_overview_is_building_until_the_runner_has_one(db, monkeypatch):
    monkeypatch.setattr(sidecar, "_send", lambda obj: None)
    srv = object.__new__(sidecar.Server)
    srv._db = db
    asked = []
    srv._coach = types.SimpleNamespace(latest=None, pending=3, rebuild=lambda pending=0: asked.append(pending))
    assert srv.rpc_coach_overview() == {"status": "building"}
    assert asked == [3]
    srv._coach.latest = {"overview": {"games": 0, "pending": 0, "focus": [], "behind": [], "moments": 0}}
    assert srv.rpc_coach_overview()["status"] == "ready"


def test_the_report_has_no_patterns_until_the_run_is_read(db, monkeypatch):
    gid, run = _store(db)
    srv = object.__new__(sidecar.Server)
    srv._db = db
    srv._coach = None
    assert srv._coach_patterns(gid, run) is None
