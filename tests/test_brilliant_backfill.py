"""BRIL-3 C (owner, 2026-11-27; BRILLIANT.md "BRIL-3"): the brilliant backfill (core/brilliant_backfill.py) and its
background job in the sidecar. Constructed positions only, no owner data; the engine is a stub, and BR-F's rule is
replaced by a stand-in so that a three-ply game has a candidate (the real rule's cases are tests/test_brilliant.py)."""
import json
import queue
import types

import chess
import chess.engine
import pytest

import sidecar.main as sidecar
from zugzwang import config as C
from zugzwang.core import brilliant_backfill as BB
from zugzwang.core import labelling
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.core.database import Database, MoveAnalysis

FEN = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
PGN = f'[Event "t"]\n[SetUp "1"]\n[FEN "{FEN}"]\n[Result "*"]\n\n1. Nc7+ Kd7 2. Nxa8 *\n'


def _store(db: Database, *, version: int | None = None) -> tuple[int, int]:
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
    if version is not None:
        db._conn.execute("UPDATE analysis_runs SET classifier_version=? WHERE id=?", (version, run))
    return gid, run


def _stand_in(ma, after=None, *, rating=None, verify=None):
    """BR-F's stand-in: ply 0 is a candidate, brilliant when its verification search holds (cp >= 0)."""
    if ma.ply != 0 or verify is None:
        return None
    v = verify(ma)
    return "eval" if v is not None and v[0] is not None and v[0] >= 0 else None


class Engine:
    """A stub engine: *score(board)* gives the side-to-move-relative score of each searched position."""

    def __init__(self, score):
        self.score = score
        self.searched: list[str] = []

    def analyse(self, board, limit, **kw):
        self.searched.append(board.fen())
        return [{"score": chess.engine.PovScore(self.score(board), board.turn)}]


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "b.db")
    yield d
    d.close()


def test_migration_v26_adds_the_columns_and_is_safe_to_rerun(db):
    db._migrate_v26()
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(move_analyses)")}
    assert {"avoids_mate_depth", "avoids_mate_json"} <= cols
    assert "brilliant_backfill" in {r[1] for r in db._conn.execute("PRAGMA table_info(analysis_runs)")}


def test_only_runs_at_this_version_are_listed_newest_first(db):
    _, old = _store(db, version=CLASSIFIER_VERSION - 1)    # waits for its relabel: never touched here
    _, a = _store(db)
    _, b = _store(db)
    assert BB.runs_to_backfill(db._conn) == [b, a]


def test_a_candidate_is_searched_stored_relabelled_and_the_run_stamped(db, monkeypatch):
    monkeypatch.setattr(labelling, "brilliant_path", _stand_in)
    _, run = _store(db)
    eng = Engine(lambda board: chess.engine.Cp(-50))       # the opponent to move: -50 for them, +50 for the mover
    plies, final, ratings = BB.load_run(db, run)
    res = BB.compute_run(plies, final, ratings, run, eng)
    assert res.candidates == [0] and res.verify == {0: (50, None)}
    assert res.brilliants == [0] and 0 in res.proofs       # M1's proof is searched for the new brilliant
    assert BB.apply(db._conn, res) == 1
    rows = {m.ply: m for m in db.load_move_analyses(run)}
    assert rows[0].classification == "brilliant"
    assert (rows[0].verify_cp, rows[0].verify_mate, rows[0].verify_depth) == (50, None, C.BRILLIANT_VERIFY_DEPTH)
    assert rows[0].avoids_mate_depth == BB.ONLY_MOVE_DEPTH and json.loads(rows[0].avoids_mate_json)["proven"] is False
    assert db._conn.execute("SELECT brilliant_backfill FROM analysis_runs WHERE id=?", (run,)).fetchone()[0] \
        == BB.backfill_key()
    assert BB.runs_to_backfill(db._conn) == []
    # the stored result is a relabel's input from now on: never searched again
    again = BB.compute_run(db.load_move_analyses(run), final, ratings, run, eng)
    assert again.candidates == [] and again.searches == 0


def test_without_a_stored_search_the_label_is_version_10s(db, monkeypatch):
    # BRIL-3: until the backfill has run, a candidate keeps the label version 10 gives it (not brilliant)
    monkeypatch.setattr(labelling, "brilliant_path", _stand_in)
    _, run = _store(db)
    plies, final, ratings = BB.load_run(db, run)
    assert labelling.label_game(plies, final, ratings=ratings)[0].classification != "brilliant"


def test_a_failed_search_is_not_stored_and_the_run_is_read_again(db, monkeypatch):
    monkeypatch.setattr(labelling, "brilliant_path", _stand_in)
    _, run = _store(db)

    class Dead:
        def analyse(self, *a, **k):
            raise chess.engine.EngineTerminatedError("gone")

    plies, final, ratings = BB.load_run(db, run)
    res = BB.compute_run(plies, final, ratings, run, Dead())
    assert res.failed and res.verify == {}
    BB.apply(db._conn, res)
    assert db.load_move_analyses(run)[0].verify_depth is None
    assert BB.runs_to_backfill(db._conn) == [run]


def test_only_move_proof_needs_every_other_move_mated_and_stops_at_the_first_that_is_not():
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    ma = MoveAnalysis(ply=0, fen_before=board.fen(), played_uci="d1d8", best_uci="d1d8", pv_uci="d1d8",
                      score_before_cp=None, score_before_mate=1, score_after_cp=None, score_after_mate=None,
                      second_best_uci="g1f1", second_best_cp=0, second_best_mate=None, classification="best",
                      is_book=False, lines=[{"uci": ["d1d8"]}, {"uci": ["g1f1"]}])
    mated = Engine(lambda b: chess.engine.Mate(2))          # the opponent to move mates in 2 after every move
    proof = BB.only_move_proof(mated, ma)
    others = board.legal_moves.count() - 1
    assert proof["proven"] and proof["searched"] == others and len(proof["mates"]) == others
    assert all(m[2] == 2 for m in proof["mates"])
    held = Engine(lambda b: chess.engine.Cp(0))
    proof = BB.only_move_proof(held, ma)
    # the stored lines order the search: g1f1 first, and it is not mated, so one search and no proof
    assert not proof["proven"] and proof["searched"] == 1 and proof["refuted_by"] == "g1f1"
    assert held.searched == [chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R1K2 b - - 1 1").fen()]


def test_the_sentence_only_with_the_switch_a_brilliant_and_a_proof(monkeypatch):
    ma = MoveAnalysis(ply=0, fen_before=FEN, played_uci="b5c7", best_uci="b5c7", pv_uci="", score_before_cp=0,
                      score_before_mate=None, score_after_cp=0, score_after_mate=None, second_best_uci=None,
                      second_best_cp=None, second_best_mate=None, classification="brilliant", is_book=False,
                      avoids_mate_depth=14, avoids_mate_json=json.dumps({"proven": True}))
    assert C.ONLY_MOVE_AVOIDS_MATE is False and BB.only_move_sentence(ma) is None      # off until the owner's read
    monkeypatch.setattr(C, "ONLY_MOVE_AVOIDS_MATE", True)
    assert BB.only_move_sentence(ma) == "The only move that avoids mate."
    from dataclasses import replace
    assert BB.only_move_sentence(replace(ma, classification="best")) is None
    assert BB.only_move_sentence(replace(ma, avoids_mate_json=json.dumps({"proven": False}))) is None
    assert BB.only_move_sentence(replace(ma, avoids_mate_json=None)) is None


def test_the_explanation_carries_the_sentence_only_with_the_switch(db, monkeypatch):
    gid, run = _store(db)
    db._conn.execute("UPDATE move_analyses SET classification='brilliant', avoids_mate_depth=14, avoids_mate_json=? "
                     "WHERE run_id=? AND ply=0", (json.dumps({"proven": True, "depth": 14, "mates": []}), run))
    srv = object.__new__(sidecar.Server)
    srv._db = db
    texts = lambda: [c for c in srv.rpc_explain_move(gid, 0)["claims"] if c["source"] == "avoids_mate"]  # noqa: E731
    assert texts() == []                                     # off until the owner's read
    monkeypatch.setattr(C, "ONLY_MOVE_AVOIDS_MATE", True)
    assert texts() == [{"type": "claim", "source": "avoids_mate", "text": "The only move that avoids mate."}]


def _runner(engine):
    r = object.__new__(sidecar.AnalysisRunner)
    r._jobs = queue.Queue()
    r._stopping = False
    r._engine = engine
    r._post = lambda f: f()
    return r


def test_the_job_waits_while_an_interactive_screen_is_open(db, tmp_path, monkeypatch):
    monkeypatch.setattr(labelling, "brilliant_path", _stand_in)
    monkeypatch.setattr(sidecar.AnalysisRunner, "BRILLIANT_YIELD_S", 0.01)
    _, run = _store(db)
    eng = Engine(lambda b: chess.engine.Cp(-50))
    r = _runner(eng)
    got, done = [], []
    r.refill_brilliant(tmp_path / "b.db", [run], lambda res, d: got.append(res), done.append, interactive=lambda: True)
    kind, payload = r._jobs.get_nowait()
    r._do_brilliant(*payload)
    assert got == [] and eng.searched == []                 # nothing searched while the screen is open
    kind, payload = r._jobs.get(timeout=2)                  # and it comes back, behind whatever is queued
    assert kind == "brilliant"
    r._do_brilliant(*payload[:-1], lambda: False)
    assert [g.run_id for g in got] == [run] and done and done[0]["candidates"] == 1 and done[0]["runs"] == 1


def test_the_server_writes_reports_and_refills_the_facts(db, tmp_path, monkeypatch):
    monkeypatch.setattr(labelling, "brilliant_path", _stand_in)
    sent = []
    monkeypatch.setattr(sidecar, "_emit", lambda ev, d=None: sent.append((ev, d)))
    _, run = _store(db)
    srv = object.__new__(sidecar.Server)
    srv._db, srv._db_path = db, tmp_path / "b.db"
    srv._brilliant_running = srv._brilliant_again = False
    srv._brilliant_reading = None
    srv._facts_dirty = set()
    srv._facts_refill_running = True                        # the refill of dirty facts is the next step's
    srv._budget = sidecar.EngineBudget()
    srv._analysis_jobs_by_run = {}
    calls = {}
    srv._analysis = types.SimpleNamespace(refill_brilliant=lambda *a, **k: calls.update(a=a, k=k))
    srv._start_brilliant_backfill()
    assert srv._brilliant_reading == {"done": 0, "total": 1} and ("brilliant_progress", {"done": 0, "total": 1}) in sent
    db_path, todo, on_result, on_done = calls["a"]
    assert todo == [run]
    plies, final, ratings = BB.load_run(db, run)
    on_result(BB.compute_run(plies, final, ratings, run, Engine(lambda b: chess.engine.Cp(-50))), 1)
    assert srv._facts_dirty == {run}
    assert db.load_move_analyses(run)[0].classification == "brilliant"
    on_done({"runs": 1})
    assert srv._brilliant_reading is None and sent[-1][0] == "brilliant_progress" and sent[-1][1]["finished"]
    assert srv._brilliant_running is False
