"""UI-BUILD B3/B4: the redesigned Review's read-only figures (core/review_extras.py,
`rpc_review_extras`) and Analyse again's depth range (`rpc_analyze_game`)."""
import importlib.util
import io
from pathlib import Path

import chess
import chess.pgn
import pytest

import zugzwang.config as C
from zugzwang.core import review_extras as RX
from zugzwang.core.classification import PlyScore, game_accuracy
from zugzwang.core.database import Database, MoveAnalysis

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_rx", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

# A miniature: 1.e4 e5 2.Qh5 Nc6 3.Bc4 Nf6 4.Qxf7#, with clocks, 3+2.
PGN = """[Event "t"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[TimeControl "180+2"]

1. e4 {[%clk 0:03:01]} e5 {[%clk 0:03:00]} 2. Qh5 {[%clk 0:02:58]} Nc6 {[%clk 0:02:55]}
3. Bc4 {[%clk 0:02:57]} Nf6 {[%clk 0:02:40]} 4. Qxf7# {[%clk 0:02:55]} 1-0
"""
CPS = [30, -25, 20, -40, 60, -900, 0]   # mover's view before each ply (a made-up run)
CLASSES = ["book", "book", "good", "inaccuracy", "best", "blunder", "best"]


def _scores(cps):
    out = []
    for i, cp in enumerate(cps):
        nxt = cps[i + 1] if i + 1 < len(cps) else None
        out.append(PlyScore("white" if i % 2 == 0 else "black", cp, None,
                            -nxt if nxt is not None else None, 0 if nxt is None else None))
    return out


def test_accuracy_by_phase_gives_back_the_game_accuracy_when_one_phase_holds_every_move():
    cps = [20, -10, 35, -60, 15, -5, 120, -300, 40, 10, -15, 25]
    scores = _scores(cps)[:-1]
    whole = game_accuracy(scores)
    split = RX.accuracy_by_phase(scores, ["middlegame"] * len(scores))
    for color in ("white", "black"):
        assert split[color]["middlegame"] == round(whole[color], 1)
        assert split[color]["opening"] is None and split[color]["endgame"] is None


def test_accuracy_by_phase_groups_moves_by_their_own_phase():
    cps = [20, -10, 35, -60, 15, -5, 120, -300, 40, 10, -15, 25]
    scores = _scores(cps)[:-1]
    phases = ["opening"] * 4 + ["middlegame"] * 4 + ["endgame"] * 3
    split = RX.accuracy_by_phase(scores, phases)
    assert all(split["white"][p] is not None for p in RX.PHASES)
    assert split["black"]["endgame"] is not None
    assert RX.accuracy_by_phase([], []) == {c: {p: None for p in RX.PHASES} for c in ("white", "black")}


def test_phases_are_the_divider_s_over_the_boards_before_each_ply():
    game = chess.pgn.read_game(io.StringIO(PGN))
    fens = RX.fens_before_moves(game.board(), [n.move for n in game.mainline()])
    assert fens[0] == chess.STARTING_FEN
    assert RX.division(fens) == (None, None)          # a seven-ply game never leaves the opening
    assert RX.phase_of_plies(fens) == ["opening"] * 7


def test_error_kinds_are_tactical_only_where_gate_p_proves_a_line(monkeypatch):
    class Proven:   # stands in for ProvenClaim
        pass
    rows = {i: {"classification": c, "fen_before": ("x w x" if i % 2 == 0 else "x b x")}
            for i, c in enumerate(["good", "mistake", "blunder", "miss", "inaccuracy"])}
    monkeypatch.setattr(RX, "ProvenClaim", Proven)
    monkeypatch.setattr(RX, "_engine_output", lambda r, ply, fl: Proven() if ply == 2 else None)
    errors = RX.error_kinds(rows, None)
    assert [(e["ply"], e["side"], e["classification"], e["kind"]) for e in errors] == [
        (1, "black", "mistake", None),
        (2, "white", "blunder", "tactical"),
        (3, "black", "miss", None),
    ]
    assert RX.error_counts(errors) == {"white": {"tactical": 1, "errors": 1},
                                       "black": {"tactical": 0, "errors": 2}}
    assert "positional" not in repr(errors)   # ruling 1 (2026-11-20, third): never printed


def test_clock_series_is_empty_without_a_time_control():
    assert RX.clock_series([None, None], None, True)["clocks"] == []
    s = RX.clock_series([181.0, 180.0, 178.0], "180+2", True)
    assert s["base"] == 180 and s["increment"] == 2 and s["clocks"] == [181.0, 180.0, 178.0]
    assert len(s["spent"]) == 3


@pytest.fixture
def server(tmp_path):
    srv = object.__new__(sidecar.Server)
    srv._db = Database(tmp_path / "t.db")
    return srv


def _store_game(db, analysed=True):
    game = chess.pgn.read_game(io.StringIO(PGN))
    moves = [n.move for n in game.mainline()]
    gid = db.save_game(played_at="2026-11-20T00:00:00", player_color="white", skill_level=0,
                       result="1-0", termination="checkmate", move_count=len(moves), pgn=PGN,
                       final_fen=game.end().board().fen(), source="imported")
    if not analysed:
        return gid
    fens = RX.fens_before_moves(game.board(), moves)
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=14)
    plies = []
    for i, (fen, mv) in enumerate(zip(fens, moves)):
        nxt = CPS[i + 1] if i + 1 < len(CPS) else None
        plies.append(MoveAnalysis(
            ply=i, fen_before=fen, played_uci=mv.uci(), best_uci=mv.uci(), pv_uci=mv.uci(),
            score_before_cp=CPS[i], score_before_mate=None,
            score_after_cp=-nxt if nxt is not None else None,
            score_after_mate=None if nxt is not None else 0,
            second_best_uci=None, second_best_cp=None, second_best_mate=None,
            classification=CLASSES[i], is_book=CLASSES[i] == "book"))
    db.complete_analysis_run(run, {}, white_accuracy=None, black_accuracy=None, plies=plies)
    return gid


def test_rpc_review_extras_on_an_analysed_game(server):
    gid = _store_game(server._db)
    out = server.rpc_review_extras(gid)
    assert out["analysed"] is True and out["depth"] == 14 and out["plies"] == 7
    assert out["phases"] == {"middlegame": None, "endgame": None}
    assert out["clock"]["timeControl"] == "180+2" and out["clock"]["clocks"][0] == 181.0
    assert len(out["clock"]["spent"]) == 7
    assert set(out["accuracyByPhase"]) == {"white", "black"}
    assert out["accuracyByPhase"]["white"]["middlegame"] is None
    assert [(e["ply"], e["classification"]) for e in out["errors"]] == [(5, "blunder")]
    assert out["errors"][0]["kind"] in ("tactical", None)
    assert out["errorCounts"]["black"]["errors"] == 1


def test_rpc_review_extras_on_an_unanalysed_game_still_gives_phases_and_clocks(server):
    gid = _store_game(server._db, analysed=False)
    out = server.rpc_review_extras(gid)
    assert out["analysed"] is False and out["accuracyByPhase"] is None and out["errors"] == []
    assert out["clock"]["base"] == 180 and out["phases"] == {"middlegame": None, "endgame": None}


def test_rpc_review_extras_refuses_an_unknown_game(server):
    with pytest.raises(RuntimeError):
        server.rpc_review_extras(999)


@pytest.mark.parametrize("depth", [7, 25, 40])
def test_analyse_again_refuses_a_depth_outside_8_to_24(server, depth):
    gid = _store_game(server._db, analysed=False)
    server._refuse_during_book_relabel = lambda: None
    with pytest.raises(ValueError):
        server.rpc_analyze_game(gid, depth)


def test_analyse_again_offers_14_18_24_and_reaches_24():
    assert C.ANALYSIS_AGAIN_DEPTHS == (14, 18, 24)
    assert C.ANALYSIS_AGAIN_DEPTH_MAX == 24
    assert C.ANALYSIS_DEPTH_MAX == 18          # the sync clamp is unchanged


def test_analyse_again_accepts_24(server, monkeypatch):
    gid = _store_game(server._db, analysed=False)
    started = {}

    class FakeAnalysis:
        def cancel(self):
            pass

        def analyze_game(self, game_id, run_id, pgn, depth, openings, cb):
            started["depth"] = depth
    server._analysis = FakeAnalysis()
    server._openings = None
    server._refuse_during_book_relabel = lambda: None
    monkeypatch.setattr(server, "_live_engine_version", lambda: "Stockfish 18", raising=False)
    monkeypatch.setattr(sidecar, "find_stockfish", lambda: None)
    out = server.rpc_analyze_game(gid, 24)
    assert out["depth"] == 24 and started["depth"] == 24
