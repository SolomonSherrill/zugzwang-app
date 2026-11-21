"""UI-BUILD-2 E3, ruling 18: the trainer's progress words come from what it records, per colour.
The sidecar sends each line's record per colour (`byColor`); the words are made in the frontend
(desktop/src/lib/trainer/trainerModel.ts)."""
import importlib.util
from pathlib import Path

import zugzwang.config as C
from zugzwang.core.database import Database

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_tw", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

ENDS = [
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
    "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq - 0 1",
]


def _server(tmp_path):
    srv = object.__new__(sidecar.Server)
    srv._db = Database(tmp_path / "t.db")
    return srv


def test_the_record_is_per_colour(tmp_path):
    s = _server(tmp_path)
    p = s._line_progress("B01", "Scandinavian Defense")
    assert p["byColor"]["white"] == {"attempts": 0, "completions": 0, "distinctLines": 0,
                                     "bestAccuracy": None, "mastered": False}
    s.rpc_trainer_attempt("B01", "Scandinavian Defense", "black")
    p = s._line_progress("B01", "Scandinavian Defense")
    assert p["byColor"]["black"]["attempts"] == 1 and p["byColor"]["white"]["attempts"] == 0


def test_mastered_needs_three_ends_and_one_good_run_in_that_colour(tmp_path):
    s = _server(tmp_path)
    for fen in ENDS:
        s.rpc_trainer_attempt("B01", "Scandinavian Defense", "white")
        out = s.rpc_trainer_complete(eco="B01", name="Scandinavian Defense", color="white",
                                     mode="varied", terminal_fen=fen, moves_played=6,
                                     errors_made=0, accuracy=C.TRAINER_MASTERY_MIN_ACCURACY)
    w = out["progress"]["byColor"]["white"]
    assert (w["attempts"], w["completions"], w["distinctLines"]) == (3, 3, 3)
    assert w["mastered"] is True
    assert out["progress"]["byColor"]["black"]["mastered"] is False
