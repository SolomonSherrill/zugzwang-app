"""BOOK-PREFIX (owner ruling 10, DESIGN.md "Owner rulings, 2026-11-20 (fourth)"; FIXPLAN
BOOK-PREFIX; classifier version 8): book is a prefix. A ply is labelled `book` only while every
earlier ply of the game passed the book rule (in the book, and unscored or costing at most
WPL_INACCURACY); once one fails it, no later ply is `book`, even one that transposes back into
a book position. The stored `is_book` stays the book probe."""
import json
import sqlite3
from dataclasses import replace

import chess
import chess.engine
import pytest

from tests.bookfile import write_book
from tests.test_engine_death import stockfish  # noqa: F401  (fixture)
from zugzwang.core import books, labelling, relabel
from zugzwang.core.analysis import analyze_game_from_evals, analyze_game_plies
from zugzwang.core.database import Database, MoveAnalysis
from zugzwang.core.openings import OpeningsBook

MAIN = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]          # 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6
# 1.e4 Nc6 2.Nf3 e5 reaches the position after 2...Nc6 of MAIN by another order: 1...Nc6
# leaves the book, 3.Bb5 and 3...a6 are book moves again by the probe.
TRANSPOSED = ["e2e4", "b8c6", "g1f3", "e7e5", "f1b5", "a7a6"]
TRANSPOSED_PGN = '[Event "t"]\n\n1. e4 Nc6 2. Nf3 e5 3. Bb5 a6 *'


def _fens(ucis):
    b = chess.Board()
    out = []
    for u in ucis:
        out.append(b.fen())
        b.push_uci(u)
    return out


def _plies(ucis, flags, *, before=None):
    """Constructed rows: every move the engine's best, level scores, *flags* the probe."""
    before = before or [0] * len(ucis)
    return [MoveAnalysis(
        ply=i, fen_before=f, played_uci=u, best_uci=u, pv_uci="",
        score_before_cp=before[i], score_before_mate=None, score_after_cp=0,
        score_after_mate=None, second_best_uci=None, second_best_cp=None,
        second_best_mate=None, classification="", is_book=fl)
        for i, (f, u, fl) in enumerate(zip(_fens(ucis), ucis, flags))]


def _labels(plies, final=None):
    return [m.classification for m in labelling.label_game(plies, final or [])]


@pytest.fixture
def book(tmp_path):
    b = chess.Board()
    pairs = []
    for u in MAIN:
        m = chess.Move.from_uci(u)
        pairs.append((b.copy(), m))
        b.push(m)
    return write_book(tmp_path / "main-line.bin", pairs)


def test_in_out_in_only_the_first_in_book_stretch_is_book():
    # in, in, out, in, in, in by the probe
    flags = [True, True, False, True, True, True]
    got = labelling.label_game(_plies(MAIN, flags), [])
    assert [m.classification for m in got] == ["book", "book", "best", "best", "best", "best"]
    assert [m.is_book for m in got] == flags                   # the flag stays the probe


def test_with_no_exit_every_ply_is_book():
    assert _labels(_plies(MAIN, [True] * 6)) == ["book"] * 6


def test_an_in_book_move_that_costs_too_much_ends_the_prefix():
    # Every move is in the book; 2.Nf3 costs 0.21 (Black's next before-search +300, i.e. -300
    # after the move for White), so it is labelled by the ladder and nothing after it is book.
    plies = _plies(MAIN, [True] * 6, before=[0, 0, 0, 300, 0, 0])
    got = _labels(plies)
    assert got[:2] == ["book", "book"]
    assert got[2] not in ("book", "brilliant")
    assert "book" not in got[3:]


def test_an_in_book_brilliant_does_not_end_the_prefix(monkeypatch):
    # Brilliant precedes book (ruling 9: "even if it's a book move it's still brilliant"): the
    # move was a book move, so the game has not left the book.
    real = labelling.brilliant
    monkeypatch.setattr(labelling, "brilliant",
                        lambda ma, after, **kw: ma.ply == 2 or real(ma, after, **kw))
    assert _labels(_plies(MAIN, [True] * 6)) == ["book", "book", "brilliant", "book", "book",
                                                  "book"]


def test_the_book_switch_check_allows_leaving_book_past_the_prefix():
    # (ply, old, new, old_is_book, new_is_book, open)
    assert not books.outside_w20((4, "book", "best", True, True, False))
    assert books.outside_w20((4, "book", "best", True, True, True))
    assert books.outside_w20((4, "best", "book", True, True, False))
    assert not books.outside_w20((4, "best", "book", False, True, True))
    assert not books.outside_w20((4, "best", "book", False, True))       # no open: open


def test_a_transposition_back_into_book_stays_out_of_the_embedded_eval_path(book):
    pgn = ('[Event "t"]\n\n1. e4 { [%eval 0.2] } 1... Nc6 { [%eval 0.3] } 2. Nf3 { [%eval 0.3] } '
           '2... e5 { [%eval 0.3] } 3. Bb5 { [%eval 0.3] } 3... a6 { [%eval 0.3] } *')
    analyses, _ = analyze_game_from_evals(pgn, OpeningsBook(book))
    assert [m.is_book for m in analyses] == [True, False, False, False, True, True]
    assert analyses[0].classification == "book"
    assert "book" not in [m.classification for m in analyses[1:]]


def _store(db_path, plies, final, *, flags=None, labels=None):
    db = Database(db_path)
    gid = db.save_game(played_at="2026-11-20T00:00:00", player_color="white", skill_level=1,
                       result="*", termination="", move_count=len(plies), pgn=TRANSPOSED_PGN,
                       final_fen=chess.STARTING_FEN)
    rid = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=10)
    rows = [replace(m, is_book=flags[i] if flags else m.is_book,
                    classification=labels[i] if labels else m.classification)
            for i, m in enumerate(plies)]
    summ = labelling.summary(rows)
    db.complete_analysis_run(rid, summ, white_accuracy=summ["white"]["accuracy"],
                             black_accuracy=summ["black"]["accuracy"], plies=rows,
                             final_lines=final)
    db.close()
    return rid


def _stored(db_path, rid):
    con = sqlite3.connect(str(db_path))
    try:
        return [(r[0], bool(r[1])) for r in con.execute(
            "SELECT classification, is_book FROM move_analyses WHERE run_id=? ORDER BY ply",
            (rid,))]
    finally:
        con.close()


def test_a_transposition_back_into_book_stays_out_and_every_path_agrees(tmp_path, book,
                                                                        stockfish):  # noqa: F811
    engine = chess.engine.SimpleEngine.popen_uci(stockfish)
    try:
        events = list(analyze_game_plies(engine, TRANSPOSED_PGN, 10, OpeningsBook(book)))
    finally:
        engine.quit()
    assert events[-1][0] == "done"
    fresh = [e[3] for e in events if e[0] == "ply"]
    final = events[-1][2]
    assert [m.played_uci for m in fresh] == TRANSPOSED
    assert [m.is_book for m in fresh] == [True, False, False, False, True, True]
    assert fresh[0].classification == "book"
    assert "book" not in [m.classification for m in fresh[1:]]
    want = [(m.classification, m.is_book) for m in fresh]

    # A relabel from the stored rows gives the analysis's labels.
    assert [m.classification for m in labelling.label_game(fresh, final)] == [w[0] for w in want]

    # The book relabel: the run stored as if analysed with no book, then the book switched on.
    db = tmp_path / "z.db"
    no_book = labelling.label_game([replace(m, is_book=False) for m in fresh], final)
    rid = _store(db, no_book, final)
    assert "book" not in [c for c, _ in _stored(db, rid)]
    out = books.relabel_for_book(db, book, write=True)
    assert out["integrity"] == "ok" and out["labelsChanged"] >= 1
    assert _stored(db, rid) == want

    # The relabel on update: a run at an older classifier with stale labels.
    db2 = tmp_path / "z2.db"
    rid2 = _store(db2, fresh, final, labels=["book"] * len(fresh))
    con = sqlite3.connect(str(db2))
    con.execute("UPDATE analysis_runs SET classifier_version = 7 WHERE id = ?", (rid2,))
    con.commit()
    con.close()
    res = relabel.relabel_stale(db2, backup_dir=tmp_path / "pre")
    assert res["runs"] == 1 and res["integrity"] == "ok"
    assert _stored(db2, rid2) == want
    con = sqlite3.connect(str(db2))
    summ = json.loads(con.execute("SELECT payload_json FROM analysis_runs WHERE id=?",
                                  (rid2,)).fetchone()[0])
    con.close()
    assert summ == labelling.summary(fresh)
