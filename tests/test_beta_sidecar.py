"""BETA: the sidecar methods the beta build adds (`app_info`, `flag_item`, relabel)."""

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_beta",
                                               _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

from zugzwang.core.classification import CLASSIFIER_VERSION  # noqa: E402
from zugzwang.core.database import Database  # noqa: E402
from zugzwang.core.explain import RULE_VERSION  # noqa: E402


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("ZUGZWANG_DB", str(tmp_path / "z.db"))
    s = object.__new__(sidecar.Server)
    s._db_path = tmp_path / "z.db"
    s._db = Database(s._db_path)
    yield s
    s._db.close()


def test_app_info_reports_versions_and_paths(server, tmp_path):
    info = server.rpc_app_info()
    assert info["classifierVersion"] == CLASSIFIER_VERSION
    assert info["ruleVersion"] == RULE_VERSION
    assert info["dataDir"] == str(tmp_path)
    assert info["logPath"] == str(tmp_path / "logs" / "sidecar.log")
    assert info["version"] == "dev" and info["beta"] is False and info["frozen"] is False
    assert info["stockfishSource"].endswith("/tree/sf_18")
    assert info["source"] == "https://github.com/SolomonSherrill/zugzwang-app"   # a dev run
    assert info["licence"] == "GPL-3.0-or-later"


PGN = '[White "alice"]\n[Black "bob"]\n[Result "*"]\n\n1. e4 e5 *\n'


def _analysed_game(db):
    from tests.runs import mark_complete
    from zugzwang.core.database import MoveAnalysis
    gid = db.save_game(played_at="2026-11-01T10:00:00+00:00", player_color="white",
                       skill_level=0, result="*", termination="unknown", move_count=2,
                       pgn=PGN, final_fen="x", source="lichess", external_id="AbCdEfGh")
    rid = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=14)
    fens = ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]
    for ply, (fen, uci) in enumerate(zip(fens, ["e2e4", "e7e5"])):
        db.save_move_analysis(rid, MoveAnalysis(
            ply=ply, fen_before=fen, played_uci=uci, best_uci=uci, pv_uci=uci,
            score_before_cp=20, score_before_mate=None, score_after_cp=20,
            score_after_mate=None, second_best_uci=None, second_best_cp=None,
            second_best_mate=None, classification="best", is_book=False))
    mark_complete(db, rid)
    db._conn.execute("UPDATE analysis_runs SET classifier_version=3 WHERE id=?", (rid,))
    db._conn.commit()
    return gid


def test_flag_item_records_the_house_key_and_versions(server, tmp_path):
    import json
    gid = _analysed_game(server._db)
    out = server.rpc_flag_item(kind="claim", shown="…e5 hangs nothing", note="  wrong\nhere ",
                               game_id=gid, ply=1, label="best")
    path = tmp_path / "flags" / "zugzwang-flags.jsonl"
    assert out == {"path": str(path), "count": 1}
    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["platform_game_id"] == "AbCdEfGh" and rec["source"] == "lichess"
    assert rec["ply"] == 1 and rec["move"] == "1..." and rec["played_uci"] == "e7e5"
    assert rec["fen_before"].startswith("rnbqkbnr/pppppppp/8/8/4P3")
    assert rec["label"] == "best" and rec["note"] == "wrong here"
    assert rec["run_classifier_version"] == 3 and rec["run_depth"] == 14
    assert rec["classifier_version_app"] == CLASSIFIER_VERSION
    assert rec["rule_version"] == RULE_VERSION
    assert rec["white"] == "alice" and rec["black"] == "bob"
    assert server.rpc_flag_item(kind="report line", shown="x")["count"] == 2


def test_flag_item_refuses_an_empty_flag(server):
    with pytest.raises(RuntimeError):
        server.rpc_flag_item(kind="claim", shown="   ")


# The two tests that start the real sidecar on a version-2 database are in
# tests/test_relabel_on_update.py, beside the fixture they use (built from the owner's games,
# so not published: BETA-PUB allowlist).
