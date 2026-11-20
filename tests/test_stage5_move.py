"""STAGE5-MOVE (owner ruling 2026-11-10, ANALYSIS_ARCHITECTURE.md "For STAGE 5"; built 2026-11-19).

Every rule finding carries the move it is about (`Finding.about`: UCI, SAN, and whose move it is),
the renderer reads the move it names from that field and nothing else, and for every rule kind the
field names the move its sentence names.

The cases (`data/stage5_move_cases.json`) are stored plies, one per rule kind, subject and basis
(both subjects for the four motifs, the board and engine branches of the two mate kinds), harvested
from a backup-API copy with `review/scratch/stage5/harvest_cases.py`; each row is the ply's stored
columns (`explain.STORED_PLY_COLUMNS`) and the sentence `render` gave it.
"""
import dataclasses
import json
from pathlib import Path

import chess
import pytest

from zugzwang.core import explain_text as ET
from zugzwang.core.classification import win_prob
from zugzwang.core.explain import Finding, MoveRef, explain_stored_ply
from zugzwang.core.findings import MoveAbout, MoveRole

CASES = json.loads((Path(__file__).parent / "data" / "stage5_move_cases.json").read_text())

# The move each kind's sentence names. Motifs name the move they are found on (their subject).
ROLE = {"hangs_piece": "played", "ignored_threat": "played", "walks_into_mate": "played",
        "missed_material": "best", "missed_mate": "best", "best_defends_piece": "best",
        "best_saves_piece": "best"}
MOTIFS = {"fork", "skewer", "discovered_attack", "trapped_piece"}
ALL_KINDS = set(ROLE) | MOTIFS
SENTINEL = "Zz9"


def _p(row):
    if row["score_before_cp"] is None and row["score_before_mate"] is None:
        return None
    return win_prob(row["score_before_cp"], row["score_before_mate"])


def _finding(case):
    kind, subject, basis, _ = case["key"]
    row = case["row"]
    for f in explain_stored_ply(row):
        if (f.kind, f.subject, f.basis) == (kind, subject, basis):
            s = ET.render(f, row["fen_before"], row["classification"], _p(row))
            if s == case["sentence"]:
                return f, row, s
    raise AssertionError(f"no finding renders the recorded sentence for {case['key']}")


def test_the_cases_cover_every_rule_kind():
    assert {c["key"][0] for c in CASES} == ALL_KINDS
    assert {(c["key"][0], c["key"][1]) for c in CASES if c["key"][0] in MOTIFS} == \
        {(k, s) for k in MOTIFS for s in ("played", "best")}


@pytest.mark.parametrize("case", CASES, ids=lambda c: "-".join(str(x) for x in c["key"][:3]))
def test_about_names_the_move_the_sentence_names(case):
    f, row, s = _finding(case)
    role = f.subject if f.kind in MOTIFS else ROLE[f.kind]
    assert f.about.role == MoveRole(role)
    board = chess.Board(row["fen_before"])
    if role == "played":
        assert f.about.uci == row["played_uci"]
        assert f.about.san == board.san(chess.Move.from_uci(row["played_uci"]))
    else:
        assert f.about.uci is not None
        assert chess.Move.from_uci(f.about.uci) in board.legal_moves
        if f.kind != "missed_mate" or f.basis == "engine":
            assert f.about.uci == row["best_uci"]
    ref = f.moves.get(role)
    if ref is not None:
        assert (ref.uci, ref.san) == (f.about.uci, f.about.san)
    # The sentence opens on the move it is about: its SAN, or, for the three rules about the
    # played move that speak to the player, the voice ("This" / "You", second person here).
    # A reply named later in the sentence ("— Qxb2 takes it") is not what it is about.
    if f.kind in ROLE and ROLE[f.kind] == "played":
        assert s.split()[0] in (ET.SECOND_PERSON.subject, ET.SECOND_PERSON.agent)
    else:
        assert s.startswith(f.about.san)


@pytest.mark.parametrize("case", CASES, ids=lambda c: "-".join(str(x) for x in c["key"][:3]))
def test_the_renderer_reads_the_move_from_about_and_nothing_else(case):
    f, row, s = _finding(case)
    args = (row["fen_before"], row["classification"], _p(row))
    # Changing `about` changes the move the sentence names …
    moved = dataclasses.replace(f, about=MoveAbout(f.about.role, f.about.uci, SENTINEL))
    if f.about.san in s:
        assert SENTINEL in ET.render(moved, *args)
    # … and changing the same move in `moves` changes nothing.
    role = f.about.role.value
    if role in f.moves:
        other = dict(f.moves)
        other[role] = MoveRef(uci=f.moves[role].uci, san="Yy8")
        assert ET.render(dataclasses.replace(f, moves=other), *args) == s


def test_a_finding_without_about_cannot_be_made():
    with pytest.raises(TypeError):
        Finding(kind="hangs_piece", subject="played", basis="see")


def test_move_about_carries_uci_and_san_together():
    with pytest.raises(TypeError):
        MoveAbout(MoveRole.BEST, "e2e4", None)
    with pytest.raises(TypeError):
        MoveAbout("best", "e2e4", "e4")
    assert MoveAbout(MoveRole.BEST, None, None).uci is None
