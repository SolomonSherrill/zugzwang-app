"""Judging a Try: err toward accepting (owner ruling, GAME_REPORT.md slice 5)."""

import chess
import chess.engine
import pytest

from zugzwang.core.retry import TRY_TOLERANCE, judge

START = chess.STARTING_FEN


class FakeEngine:
    """Scripted search: `lines` for the position (mover's cp, best first), and
    `after` for the position after each move (cp for the side that moved)."""

    def __init__(self, lines, after):
        self.lines = lines
        self.after = after

    def analyse(self, board, limit, multipv=None, game=None):
        if multipv:
            return [{"pv": [chess.Move.from_uci(u)],
                     "score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn)}
                    for u, cp in self.lines]
        moved = board.move_stack[-1].uci()
        mover = not board.turn
        return {"score": chess.engine.PovScore(chess.engine.Cp(self.after[moved]), mover)}


LINES = [("e2e4", 40), ("d2d4", 35), ("g1f3", 30)]


def test_the_best_move_is_accepted():
    v = judge(FakeEngine(LINES, {"e2e4": 40}), START, "e2e4")
    assert v["accepted"] and v["loss"] == 0.0 and v["bestSan"] == "e4"


def test_a_move_within_the_tolerance_is_accepted():
    v = judge(FakeEngine(LINES, {"d2d4": 35}), START, "d2d4")
    assert v["accepted"] and v["loss"] <= TRY_TOLERANCE


def test_a_move_worse_on_both_searches_is_rejected():
    v = judge(FakeEngine(LINES, {"a2a3": -150}), START, "a2a3")
    assert not v["accepted"] and v["loss"] > TRY_TOLERANCE


def test_the_kinder_of_two_searches_decides():
    # The MultiPV line undervalues g1f3 (-200), but the search of the position after it
    # finds it fine (+35): one search that undervalues a move cannot reject it.
    lines = [("e2e4", 40), ("d2d4", 35), ("g1f3", -200)]
    v = judge(FakeEngine(lines, {"g1f3": 35}), START, "g1f3")
    assert v["accepted"]


def test_a_mating_move_is_accepted_without_a_search_after_it():
    fen = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
    v = judge(FakeEngine([("a1a8", 900)], {}), fen, "a1a8")
    assert v["accepted"] and v["value"] == 1.0


def test_an_illegal_move_is_refused():
    with pytest.raises(ValueError):
        judge(FakeEngine(LINES, {}), START, "e2e5")



class NoisyEngine(FakeEngine):
    """Each judgement sees the move's after-search value from `sequence` in turn."""

    def __init__(self, lines, uci, sequence):
        super().__init__(lines, {})
        self.uci, self.sequence, self.calls = uci, list(sequence), 0

    def analyse(self, board, limit, multipv=None, game=None):
        if multipv:
            return super().analyse(board, limit, multipv)
        self.calls += 1
        self.after = {self.uci: self.sequence.pop(0)}
        return super().analyse(board, limit)


LINE = [("e2e4", 40), ("d2d4", -300), ("g1f3", -300)]


def test_a_borderline_rejection_is_judged_again_and_may_flip():
    # First judgement 0.055 short (just over 0.05), the independent second 0.046.
    eng = NoisyEngine(LINE, "a2a3", [-20, -10])
    v = judge(eng, START, "a2a3")
    assert v["rejudged"] and v["accepted"] and len(v["losses"]) == 2 and eng.calls == 2


def test_a_borderline_rejection_both_judgements_reject_stays_rejected():
    eng = NoisyEngine(LINE, "a2a3", [-20, -20])
    v = judge(eng, START, "a2a3")
    assert v["rejudged"] and not v["accepted"]


def test_an_acceptance_is_never_rechecked():
    # One-directional by ruling: a borderline acceptance stands on one judgement.
    eng = NoisyEngine(LINE, "a2a3", [35])
    v = judge(eng, START, "a2a3")
    assert v["accepted"] and not v["rejudged"] and eng.calls == 1


def test_a_clear_rejection_is_not_rechecked():
    eng = NoisyEngine(LINE, "a2a3", [-300])
    v = judge(eng, START, "a2a3")
    assert not v["accepted"] and not v["rejudged"] and eng.calls == 1
