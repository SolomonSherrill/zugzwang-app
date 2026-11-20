"""MECH-NAME (owner rulings M1–M7, 2026-11-14; ANALYSIS_ARCHITECTURE.md "MECH-NAME — the spec"):
back rank and discovered attack/check, named only inside a proven, printed line, as a clause after
the claim's sentence. The six mocked cases are the spec's §3, keyed there by chess.com id + ply;
their proofs (start FEN, line, hold) are the stored claims' own (cited by row, not by game id:
this file is published)."""

from __future__ import annotations

import pytest

from zugzwang.core import mechanisms as M
from zugzwang.core.findings import _GATE_P, Proof, ProvenClaim


def claim(kind, start_fen, line, held_from, subject="played", took=(), gave=()):
    proof = Proof(basis="engine", start_fen=start_fen, line=tuple(line), forcing_moves=len(line),
                  held_from=held_from, mate_on=None, token=_GATE_P)
    return ProvenClaim(kind=kind, subject=subject, proof=proof,
                       material=None if kind == "line_mates" else 9.0, took=took, gave=gave)


# (spec §3 row, kind, start FEN, line, held_from, the sentence, the sentence with the name)
MOCKS = [
    ("§3 row 1", "line_mates",
     "2r1r1k1/p1q2ppp/3p1b2/1Q6/3P2b1/1B6/PPP2PPP/RN2R1K1 w - - 0 17",
     ["b5e8", "c8e8", "e1e8"], 2,
     "Black allows a forced mate: 17.Qxe8+ Rxe8 18.Rxe8#.",
     "Black allows a forced mate: 17.Qxe8+ Rxe8 18.Rxe8# — a back-rank mate: the king on g8 is "
     "shut in by its own pawns on f7, g7 and h7."),
    ("§3 row 2", "line_mates",
     "6k1/p1R2ppp/8/8/2P5/1P3P1K/P2r2r1/8 w - - 0 34", ["c7c8", "d2d8", "c8d8"], 2,
     "Rc8+ would have forced mate: 34.Rc8+ Rd8 35.Rxd8#.",
     "Rc8+ would have forced mate: 34.Rc8+ Rd8 35.Rxd8# — a back-rank mate: the king on g8 is "
     "shut in by its own pawns on f7, g7 and h7."),
    ("§3 row 3", "line_mates",
     "r1br4/p2qp2Q/4kpp1/4P3/8/7R/P4PPP/R5K1 b - - 0 25", ["d7d1", "a1d1", "d8d1"], None,
     "White allows a forced mate: 25...Qd1+ 26.Rxd1 Rxd1#.",
     "White allows a forced mate: 25...Qd1+ 26.Rxd1 Rxd1# — a back-rank mate: the king on g1 is "
     "shut in by its own pawns on f2, g2 and h2."),
    ("§3 row 4", "line_wins_material",
     "r1bqk2r/ppp1p1bp/6p1/3Pnp2/3QpB2/2N5/PPP3PP/R3KBNR b KQkq - 3 10",
     ["e5d3", "c2d3", "g7d4", "d3e4"], 2,
     "This allows Black to win a queen for a knight and a pawn by force: 10...Nd3+ 11.cxd3 Bxd4 "
     "12.dxe4.",
     "This allows Black to win a queen for a knight and a pawn by force: 10...Nd3+ 11.cxd3 Bxd4 "
     "12.dxe4 — a discovered attack: Nd3+ opens the bishop on g7's line to the queen on d4."),
    ("§3 row 5", "line_wins_material",
     "1r2r1k1/pbpq1pp1/2p4p/2b5/2P2Q2/1P1B1N1P/P4PP1/3RR1K1 w - - 3 21",
     ["d3h7", "g8h7", "d1d7"], 2,
     "Bh7+ would have won a queen for the bishop by force: 21.Bh7+ Kxh7 22.Rxd7.",
     "Bh7+ would have won a queen for the bishop by force: 21.Bh7+ Kxh7 22.Rxd7 — a discovered "
     "attack: Bh7+ opens the rook on d1's line to the queen on d7."),
    ("§3 row 6", "line_wins_material",
     "r4rk1/pppqn1pp/2pbN3/8/4P3/1Q6/PB3PPP/RN3RK1 w - - 1 16", ["e6c5", "g8h8", "c5d7"], 2,
     "This allows White to win a queen by force: 16.Nc5+ Kh8 17.Nxd7.",
     "This allows White to win a queen by force: 16.Nc5+ Kh8 17.Nxd7 — a discovered check: Nc5+ "
     "uncovers the queen on b3's check, and the knight takes the queen on d7."),
]


@pytest.mark.parametrize("case", MOCKS, ids=[m[0] for m in MOCKS])
def test_the_mocked_cases_read_as_the_spec_mocks_them(case):
    _, kind, fen, line, held, sentence, named = case
    name = M.name_claim(claim(kind, fen, line, held))
    assert name is not None
    assert M.with_name(sentence, name) == named
    # M6: the claim's text is unchanged up to the dash.
    assert named.startswith(sentence[:-1] + " — ")


def test_the_mechanism_kinds():
    kinds = [M.name_claim(claim(k, f, ln, h)).mechanism for _, k, f, ln, h, _, _ in MOCKS]
    assert kinds == [M.BACK_RANK] * 3 + [M.DISCOVERED_ATTACK] * 2 + [M.DISCOVERED_CHECK]


# ── constructed negatives ────────────────────────────────────────────────────

# The knight on e4 leaves the e-file, uncovering the rook on e1 onto e7; Black passes; Rxe7.
UNCOVER = "k7/4{}/8/8/4N3/8/8/K3R3 w - - 0 1"


def test_a_discovered_attack_on_a_piece_is_named():
    name = M.name_claim(claim("line_wins_material", UNCOVER.format("n3"),
                              ["e4c5", "a8b8", "e1e7"], 2))
    assert name is not None and name.clause == (
        "a discovered attack: Nc5 opens the rook on e1's line to the knight on e7")


def test_a_discovered_attack_that_wins_a_pawn_is_not_named():
    # M2: only a piece.
    assert M.name_claim(claim("line_wins_material", UNCOVER.format("p3"),
                              ["e4c5", "a8b8", "e1e7"], 2)) is None


def test_a_summarised_claim_is_not_named():
    # M5: a line past PV_PRINT_MAX_PLIES is printed as "by move N" — no moves to point at. The
    # same discovered attack, padded with quiet moves before it, so the geometry still holds.
    from zugzwang import config as C
    fen = "k7/4n3/8/8/4N3/8/8/K3R3 w - - 0 1"
    pad = ["a1b1", "a8a7", "b1a1", "a7a8"]
    line = pad + ["e4c5", "a8b8", "e1e7"]
    assert len(line) > C.PV_PRINT_MAX_PLIES
    assert M.discovered(fen, line, 4) is not None        # the geometry is there ...
    assert M.name_claim(claim("line_wins_material", fen, line, 4)) is None   # ... unnamed


def test_a_mate_that_is_not_back_rank_is_not_named():
    # Scholar's mate: the queen mates on f7, not on the back rank.
    fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    assert M.name_claim(claim("line_mates", fen, ["h5f7"], None)) is None


def test_a_back_rank_mate_with_an_open_escape_square_is_not_named():
    # The king on g8 is mated along the rank, but h7 is covered by a bishop, not shut by its own
    # piece: not the back-rank geometry.
    fen = "6k1/5pp1/8/8/8/3B4/8/R5K1 w - - 0 1"   # king g8, pawns f7 g7, h7 covered by Bd3
    import chess
    b = chess.Board(fen)
    b.push_uci("a1a8")
    assert b.is_checkmate()
    assert M.name_claim(claim("line_mates", fen, ["a1a8"], None)) is None


def test_a_mate_line_takes_no_discovered_name():
    # A mate line takes "back rank" or nothing (stage 0's fork-in-a-mate errors).
    _, _, fen, line, held, _, _ = MOCKS[5]
    assert M.name_claim(claim("line_mates", fen, line, held)) is None


def test_no_name_leaves_the_sentence_alone():
    assert M.with_name("White allows a forced mate: 1.Qh7#.", None) == \
        "White allows a forced mate: 1.Qh7#."


def test_compose_appends_the_name_to_the_shown_claim():
    # The Review callout and the report cards read the same `shown_claims` (M7).
    from zugzwang.core import compose
    fen = "r4rk1/pppqn1pp/2pbN3/8/4P3/1Q6/PB3PPP/RN3RK1 w - - 1 16"
    # The played move before the claim's start position: Black's ...Qd7 (d8d7).
    before = "r2q1rk1/ppp1n1pp/2pbN3/8/4P3/1Q6/PB3PPP/RN3RK1 b - - 0 15"
    import chess
    b = chess.Board(before)
    b.push_uci("d8d7")
    assert b.fen() == fen
    rows = {
        29: {"fen_before": before, "played_uci": "d8d7", "best_uci": "d8c8",
             "classification": "good", "score_before_cp": 0, "score_before_mate": None,
             "score_after_cp": -800, "score_after_mate": None, "pv_uci": "d8c8 b3b4"},
        30: {"fen_before": fen, "played_uci": "a1a2", "best_uci": "e6c5",
             "classification": "blunder", "score_before_cp": 800, "score_before_mate": None,
             "score_after_cp": 0, "score_after_mate": None, "pv_uci": "e6c5 g8h8 c5d7"},
    }
    full = compose.explain_ply_full(rows, 29, "black")
    texts = [t for src, t in full.shown_claims if src == "engine_line"]
    assert texts and texts[0].endswith(
        "— a discovered check: Nc5+ uncovers the queen on b3's check, and the knight takes the "
        "queen on d7.")
    assert full.notes.get("mechanism") == M.DISCOVERED_CHECK


def test_a_discovered_attack_whose_claim_nets_a_pawn_is_not_named():
    # M2, as read on the held-out half: Rxf5+ gxf5 Qxh4 takes a rook at the hold, but the claim
    # nets a pawn (the rook given back), so "a discovered attack" would overstate it. Constructed:
    # the same uncovering as above, the claim's material a pawn.
    c = claim("line_wins_material", UNCOVER.format("n3"), ["e4c5", "a8b8", "e1e7"], 2)
    assert M.name_claim(c) is not None
    from dataclasses import replace
    assert M.name_claim(replace(c, material=1.0)) is None


# ── P1 (owner, 2026-11-19; ANALYSIS_ARCHITECTURE.md "MECH-NAME" §10): pin and skewer, at the hold ──

PIN_FEN = "4k3/7p/2n5/1B6/3P4/8/8/6K1 w - - 0 1"        # Bb5 pins Nc6 to the king; d5 wins it


def test_a_pin_at_the_hold_is_named():
    c = claim("line_wins_material", PIN_FEN, ["d4d5", "h7h6", "d5c6"], 2)
    name = M.name_claim(c)
    assert name is not None and name.mechanism == M.PIN
    assert name.clause == "a pin: the knight on c6 is pinned to the king on e8 by the bishop on b5"


def test_a_pinned_pawn_is_not_named():
    fen = "4k3/8/2p5/1B6/3P4/8/8/6K1 w - - 0 1"
    assert len(M._replay(fen, ["d4d5", "e8f8", "d5c6"])[1]) == 3
    assert M.name_claim(claim("line_wins_material", fen, ["d4d5", "e8f8", "d5c6"], 2)) is None


def test_a_pin_the_defender_broke_is_not_named():
    # the king steps off the pin; the knight is taken anyway, but not because of a pin
    c = claim("line_wins_material", PIN_FEN, ["d4d5", "e8d8", "d5c6"], 2)
    assert M.pin(c.proof.start_fen, c.proof.line, 2) is None


def test_a_pin_elsewhere_in_the_line_is_not_named():
    # the knight is pinned, but the hold is the capture of the loose rook on a6
    fen = "4k3/8/r1n5/1B6/8/8/8/R5K1 w - - 0 1"
    c = claim("line_wins_material", fen, ["a1a6", "e8f7"], 1)
    name = M.name_claim(c)
    assert name is None or name.mechanism != M.PIN


SKEWER_FEN = "6r1/8/8/3k4/8/8/8/3B3K w - - 0 1"         # Bb3+ drives the king off; Bxg8


def test_a_skewer_at_the_hold_is_named():
    c = claim("line_wins_material", SKEWER_FEN, ["d1b3", "d5e5", "b3g8"], 2)
    name = M.name_claim(c)
    assert name is not None and name.mechanism == M.SKEWER
    assert name.clause == ("a skewer: the bishop on b3 drives the king on d5 off its line and takes "
                           "the rook on g8 behind it")


def test_a_skewered_pawn_is_not_named():
    fen = "8/5p2/8/3k4/8/8/8/3B3K w - - 0 1"
    assert len(M._replay(fen, ["d1b3", "d5e5", "b3f7"])[1]) == 3
    assert M.name_claim(claim("line_wins_material", fen, ["d1b3", "d5e5", "b3f7"], 2)) is None


def test_a_capture_that_is_not_behind_the_piece_that_moved_is_not_a_skewer():
    # the king moves, but the bishop takes a rook that was never behind it
    fen = "8/8/8/3k4/r7/8/8/3B3K w - - 0 1"
    c = claim("line_wins_material", fen, ["d1b3", "d5e5", "b3a4"], 2)
    assert M._hold(c.proof.start_fen, c.proof.line, 2) is not None      # a real capture at the hold
    assert M.skewer(c.proof.start_fen, c.proof.line, 2) is None


def test_a_summarised_pin_is_not_named():
    long = ["d4d5", "h7h6", "g1f1", "h6h5", "f1e1", "h5h4", "d5c6"]
    assert M.name_claim(claim("line_wins_material", PIN_FEN, long, 4)) is None


def test_the_sentence_is_unchanged_up_to_the_dash():
    text = "This allows White to win a knight by force: 1.d5 h6 2.dxc6."
    name = M.name_claim(claim("line_wins_material", PIN_FEN, ["d4d5", "h7h6", "d5c6"], 2))
    out = M.with_name(text, name)
    assert out.startswith(text[:-1] + " — a pin: ")


def test_a_pinned_piece_taken_by_the_pinner_itself_is_not_named():
    # Bxc6+ takes the pinned knight with the pinning bishop: a capture, not a pin's doing
    fen = "4k3/8/2n5/1B6/8/8/8/6K1 w - - 0 1"
    assert M.pin(fen, ["b5c6"], 1) is None


def test_a_capture_that_uncovers_a_check_is_not_named_a_pin():
    # Nxc6+ uncovers the e1 rook's check; the knight on c6 is pinned by Bb5, but the check wins it
    fen = "r1bqkb1r/1pp2ppp/p1n5/1BnpN3/8/3P4/PPP2PPP/RNBQR1K1 w kq - 0 8"
    assert M.pin(fen, ["e5c6"], 1) is None


def test_a_pinned_piece_that_could_take_its_pinner_is_not_named():
    # the white queen on d2 is "pinned" by the queen on e3 but could take it: Bxd2+ is a plain capture
    fen = "r1b1k2r/p1pp1ppp/1p6/8/1b3P2/4q3/PP1QB1PP/2KR3R b kq - 3 13"
    assert M.pin(fen, ["b4d2", "d1d2"], 1) is None
