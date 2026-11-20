"""Stage 3: the rendering layer.

Two kinds of test here, and the second kind is the one that matters.

The first kind checks a sentence reads correctly — the mood, the piece named, the
qualifier attached. The second kind checks a sentence cannot say something the
finding did not prove. Those are the tests that would have caught the four
falsehoods this layer shipped in its first sample: a discovered attack naming a
geometry only the check branch established, a saved piece named on the square it
fled *to*, a defended piece that was the opponent's captured one, and a mate on a
move the classifier approved read as though the position had been fine.
"""

import chess
import pytest

from zugzwang.core.findings import MoveAbout, MoveRole
from zugzwang.core.explain import (
    PATTERN_BACK_RANK,
    PATTERN_DISCOVERED_CHECK,
    PATTERN_DISCOVERED_LINE,
    PATTERN_FORCED,
    Finding,
    MoveRef,
    PieceOn,
    explain_ply,
)
from zugzwang.core.explain_text import (
    BOOKKEEPING_KINDS,
    CLAIMS,
    LOST,
    MATE_CUTOFF,
    QUAL_LOST,
    SECOND_PERSON,
    WINNING,
    describe_ply,
    describe_stored_ply,
    is_conditional,
    names_move,
    one_sentence_per_move,
    RunPlies,
    render,
    voice_for,
)

START = chess.STARTING_FEN


def ref(san, uci="e2e4"):
    return MoveRef(uci=uci, san=san)


def piece(symbol, square, color="white"):
    return PieceOn(piece=symbol, square=square, color=color)


# The move each kind's sentence names (STAGE5-MOVE): the table `explain.NAMES_MOVE` used to
# hold, kept here only so these hand-built findings carry `about` as the rules set it.
_ROLE = {"hangs_piece": "played", "ignored_threat": "played", "walks_into_mate": "played",
         "missed_material": "best", "missed_mate": "best", "best_defends_piece": "best",
         "best_saves_piece": "best"}


def finding(kind, **over):
    row = dict(
        kind=kind,
        subject="played",
        basis="see",
        pieces=(piece("R", "a8"),),
        moves={"played": ref("Nc7+", "b5c7")},
        material=5.0,
    )
    row.update(over)
    if "about" not in row:
        role = _ROLE.get(kind, row["subject"])
        m = row["moves"].get(role)
        row["about"] = MoveAbout(MoveRole(role), m.uci if m else None, m.san if m else None)
    return Finding(**row)


def one(fen, uci, classification=None, p_before=None, **kwargs):
    """The sentences for a position, rendered through the shipped path."""
    return describe_ply(
        fen, explain_ply(fen, uci, **kwargs), classification, p_before
    )


# ── mood ─────────────────────────────────────────────────────────────────────
#
# A sentence about a move that was not played must not read as though it were. The
# first sample got this wrong on every motif attributed to the best move.


def test_a_played_tactic_is_indicative():
    f = finding("fork", subject="played", pieces=(piece("R", "a8"), piece("K", "e8")))
    assert render(f, START, None, None) == (
        "Nc7+ forks the rook on a8 and king on e8 — the rook on a8 falls."
    )


def test_a_missed_tactic_is_conditional_throughout():
    f = finding(
        "fork", subject="best", pieces=(piece("R", "a8"), piece("K", "e8")),
        moves={"best": ref("Nc7+", "b5c7")},
    )
    assert render(f, START, None, None) == (
        "Nc7+ would fork the rook on a8 and king on e8 — the rook on a8 would fall."
    )


@pytest.mark.parametrize("kind", sorted(CLAIMS))
def test_every_motif_template_has_both_moods(kind):
    """Parametrised over the claim table so a motif added later cannot ship with
    one mood only — which is exactly how the first sample's trapped-piece and
    skewer sentences read as though the move had been played."""
    pieces = (piece("R", "a8"), piece("Q", "d8"))
    indicative = CLAIMS[kind](finding(kind, pieces=pieces), False)
    conditional = CLAIMS[kind](finding(kind, pieces=pieces), True)
    assert indicative != conditional
    assert "would" in conditional
    assert "would" not in indicative


def test_mood_follows_the_move_the_sentence_names_not_the_subject():
    """`missed_material` carries subject="played" and produces a sentence about
    the *best* move. Keying mood on `subject` would phrase it as though the
    player had made that move."""
    f = finding("missed_material", subject="played", moves={"best": ref("Rxa8")})
    assert names_move(f) == "best"
    assert is_conditional(f)
    assert render(f, START, None, None) == "Rxa8 would have won the rook on a8."


# ── the templates, one by one ────────────────────────────────────────────────


def test_a_fork_names_the_piece_that_falls_and_the_king_not_every_target():
    """The rule proves material against every attacked piece, so `pieces` can hold
    six and the sentence named all of them: "Qf7+ forks the knight on g8, pawn on
    g6, pawn on d7, bishop on g7 and king on e8 — the knight on g8 falls." True and
    unreadable; 181 of 956 fork sentences named four or more.

    The piece named in the claim is the one the consequence references, so the two
    clauses cannot disagree about which piece falls."""
    f = finding(
        "fork",
        pieces=(
            piece("N", "g8", "black"), piece("P", "g6", "black"),
            piece("P", "d7", "black"), piece("B", "g7", "black"),
            piece("K", "e8", "black"),
        ),
        moves={"played": ref("Qf7+")},
    )
    assert render(f, START, None, None) == (
        "Qf7+ forks the knight on g8 and king on e8 — the knight on g8 falls."
    )


def test_a_fork_that_does_not_check_names_only_the_piece_that_falls():
    f = finding(
        "fork",
        pieces=(
            piece("R", "a8", "black"), piece("B", "c8", "black"),
            piece("P", "d7", "black"),
        ),
        moves={"played": ref("Nb6")},
    )
    assert render(f, START, None, None) == (
        "Nb6 forks the rook on a8 — the rook on a8 falls."
    )


def test_a_hanging_piece_names_the_move_that_takes_it():
    f = finding(
        "hangs_piece", pieces=(piece("N", "f5"),),
        moves={"played": ref("Nf5"), "refutation": ref("Bxf5")},
    )
    assert render(f, START, None, None) == (
        "This drops the knight on f5 — Bxf5 takes it."
    )


def test_an_ignored_threat_says_left_hanging_never_drops():
    """The move did not drop the piece — it was already loose — so the sentence
    names the player's failure to rescue it, and what the opponent wins."""
    f = finding(
        "ignored_threat", pieces=(piece("N", "c5", "black"),), material=-2.0,
        moves={"played": ref("h5", "h7h5"), "refutation": ref("dxc5", "d4c5")},
    )
    assert render(f, START, "blunder", None) == (
        "You left the knight on c5 hanging — dxc5 wins it."
    )


def test_an_ignored_threat_names_the_side_on_the_opponents_move():
    fen = "r1bq1k1r/1pp1b1pp/p2p1p2/2n5/3P4/1B3Q2/PPP1RPPP/RNB3K1 b - - 1 12"
    found = explain_ply(fen, "h7h5", best_uci="c5b3")
    assert describe_ply(fen, found, "blunder", None, voice=voice_for(fen, "white")) == [
        "Black left the knight on c5 hanging — dxc5 wins it."
    ]


def test_an_ignored_threat_takes_the_lost_reframe():
    f = finding(
        "ignored_threat", pieces=(piece("N", "c5"),), material=-2.0,
        moves={"played": ref("h5", "h7h5"), "refutation": ref("dxc5", "d4c5")},
    )
    assert render(f, START, "blunder", LOST / 2) == (
        "You left the knight on c5 hanging — dxc5 wins it" + QUAL_LOST + "."
    )


def test_two_ignored_threats_on_one_move_are_one_sentence_naming_both():
    played = {"played": ref("h5", "h7h5")}
    a = finding("ignored_threat", pieces=(piece("N", "c5"),), material=-3.0,
                moves={**played, "refutation": ref("dxc5", "d4c5")})
    b = finding("ignored_threat", pieces=(piece("P", "b7"),), material=-1.0,
                moves={**played, "refutation": ref("Bxb7", "e4b7")})
    assert describe_ply(START, [a, b], "blunder", None) == [
        "You left the knight on c5 and pawn on b7 hanging."
    ]


def test_a_dropped_piece_and_an_ignored_one_get_a_sentence_each():
    """Game 5 ply 32. Both kinds name the played move, so sharing its dedupe slot
    would report a move that lost two things as losing one."""
    fen = "3r1rk1/4n1pp/2qN4/4p3/8/8/PPPP1PPP/R1BQ1RK1 w - - 1 17"
    assert one(fen, "d1f3", "blunder", best_uci="d6c4") == [
        "This drops the queen on f3 and pawn on c2.",
        "You left the knight on d6 hanging — Rxd6 wins it.",
    ]


def _threat(square="c5", symbol="N", **over):
    row = dict(
        pieces=(piece(symbol, square),), material=-2.0,
        moves={"played": ref("h5", "h7h5"), "refutation": ref("dxc5", "d4c5")},
    )
    row.update(over)
    return finding("ignored_threat", **row)


def test_an_ignored_threat_that_cost_nothing_says_so_and_no_more():
    """Keyed on WPL, not on the class. Near-zero WPL proves the move did not change
    the evaluation — not that the material returns, and not that it was meant."""
    line = render(_threat(), START, "excellent", 0.5, loss=0.0)
    assert line == "You left the knight on c5 hanging — dxc5 wins it, though it cost nothing here."
    assert "comes back" not in line


def test_an_ignored_threat_in_a_decided_position_cannot_prove_compensation():
    assert render(_threat(), START, "excellent", 0.9, loss=0.0) == (
        "You left the knight on c5 hanging — dxc5 wins it."
    )


def test_an_ignored_threat_that_cost_something_is_not_compensated():
    assert render(_threat(), START, "mistake", 0.5, loss=0.15) == (
        "You left the knight on c5 hanging — dxc5 wins it."
    )


def test_the_short_form_is_still_hanging():
    assert describe_ply(START, [_threat()], "mistake", None, forms={("c5", "N"): "short"}) == [
        "The knight on c5 is still hanging."
    ]


def test_a_silent_link_says_nothing():
    assert describe_ply(START, [_threat()], "mistake", None, forms={("c5", "N"): "silent"}) == []


def test_a_fresh_threat_and_a_repeated_one_are_not_merged():
    fresh = _threat("b7", "P", moves={"played": ref("h5", "h7h5"),
                                      "refutation": ref("Bxb7", "e4b7")})
    lines = describe_ply(START, [_threat(), fresh], "mistake", None,
                         forms={("c5", "N"): "short", ("b7", "P"): "full"})
    assert sorted(lines) == [
        "The knight on c5 is still hanging.",
        "You left the pawn on b7 hanging — Bxb7 wins it.",
    ]


# Game 90, run 42, plies 21 / 23 / 25: Black leaves the pawn on h7 to Qxh7 on three
# moves running — classified `good`, `mistake`, `miss`. Stored rows, verbatim. (The
# first chain used here, game 11's pawn on b7, lost its first link to the tempo gate:
# 15...Nxc4 attacks the queen on d2, so cxb7 was never available.)
H7 = {
    21: {"fen_before": "rnbqkr2/p2n1pQp/3b4/2p1p3/B2Pp3/8/PPP2PPP/R1B1K1NR b KQq d3 0 11",
         "played_uci": "c5d4", "best_uci": "d8a5", "classification": "good",
         "score_before_cp": 461, "score_before_mate": None,
         "score_after_cp": 387, "score_after_mate": None},
    23: {"fen_before": "rnbqkr2/p2n1pQp/3b3B/4p3/B2pp3/8/PPP2PPP/R3K1NR b KQq - 1 12",
         "played_uci": "d4d3", "best_uci": "d8a5", "classification": "mistake",
         "score_before_cp": 553, "score_before_mate": None,
         "score_after_cp": 346, "score_after_mate": None},
    25: {"fen_before": "rnbqkr2/p2n1pQp/3b3B/4p3/B3p3/3P4/PP3PPP/R3K1NR b KQq - 0 13",
         "played_uci": "e4d3", "best_uci": "d8a5", "classification": "miss",
         "score_before_cp": 502, "score_before_mate": None,
         "score_after_cp": 231, "score_after_mate": None},
}
FULL_H7 = "Black left the pawn on h7 hanging — Qxh7 wins it."
SHORT_H7 = "The pawn on h7 is still hanging."


def _h7_lines(rows, ply):
    """Sentences naming h7 on `ply` of a run made of `rows` (ply → stored row)."""
    run = RunPlies(rows, ply)
    return [line for line in describe_stored_ply(rows[ply], "white", run=run)
            if "h7" in line]


def test_the_full_sentence_goes_to_the_first_error_in_the_chain():
    """Head is 12...d3, the first link classified as an error; 11...cxd4 before it is
    `good`, so it says nothing, and the link after the head takes the short form."""
    assert _h7_lines(H7, 21) == []
    assert _h7_lines(H7, 23) == [FULL_H7]
    assert _h7_lines(H7, 25) == [SHORT_H7]


def test_a_chain_with_no_error_puts_the_full_sentence_first_and_ends_after_the_short():
    calm = {p: {**r, "classification": "good"} for p, r in H7.items()}
    assert _h7_lines(calm, 21) == [FULL_H7]
    assert _h7_lines(calm, 23) == [SHORT_H7]
    assert _h7_lines(calm, 25) == []


def test_a_missing_ply_breaks_the_chain():
    gap = {21: H7[21], 25: H7[25]}
    assert _h7_lines(gap, 21) == [FULL_H7]
    assert _h7_lines(gap, 25) == [FULL_H7]


def test_a_silent_ply_breaks_the_chain():
    """Nothing is said on a book move, so it cannot be a link."""
    booked = {**H7, 23: {**H7[23], "classification": "book"}}
    assert _h7_lines(booked, 21) == [FULL_H7]
    assert _h7_lines(booked, 25) == [FULL_H7]


# Game 285, plies 21 and 23, stored rows verbatim. 11...d6 (`excellent`) is the first
# move to leave the knight on c5 loose; 12...h5 (`blunder`) is the one that lost it.
GAME_285 = {
    21: {"fen_before": "r1bq1k1r/1pppb1pp/p4p2/2n1R3/3P4/1B3Q2/PPP2PPP/RNB3K1 b - - 0 11",
         "played_uci": "d7d6", "best_uci": "c5b3", "classification": "excellent",
         "score_before_cp": -123, "score_before_mate": None,
         "score_after_cp": -130, "score_after_mate": None},
    23: {"fen_before": "r1bq1k1r/1pp1b1pp/p2p1p2/2n5/3P4/1B3Q2/PPP1RPPP/RNB3K1 b - - 1 12",
         "played_uci": "h7h5", "best_uci": "c5b3", "classification": "blunder",
         "score_before_cp": -121, "score_before_mate": None,
         "score_after_cp": -481, "score_after_mate": None},
}


def test_the_required_case_gets_the_full_sentence_on_the_blunder():
    """The chain head is the blunder, not the harmless move before it. The owner
    played White, so Black's move is named rather than addressed."""
    lines = lambda ply: describe_stored_ply(  # noqa: E731
        GAME_285[ply], "white", run=RunPlies(GAME_285, ply))
    assert lines(23) == ["Black left the knight on c5 hanging — dxc5 wins it."]
    assert lines(21) == []


def test_an_ignored_threat_says_nothing_beside_a_mate_that_leads():
    mate = finding("walks_into_mate", pieces=(), material=None, mate_in=4,
                   moves={"played": ref("h5", "h7h5")})
    assert describe_ply(START, [mate, _threat()], "blunder", None) == [
        "This allows a forced mate in 4."
    ]


def test_beside_a_demoted_long_mate_the_hanging_sentence_leads():
    mate = finding("walks_into_mate", pieces=(), material=None, mate_in=8,
                   moves={"played": ref("h5", "h7h5")})
    assert describe_ply(START, [mate, _threat()], "blunder", None) == [
        "You left the knight on c5 hanging — dxc5 wins it.",
        "This allows a forced mate in 8.",
    ]


def test_an_ignored_threat_says_nothing_beside_a_missed_mate():
    mate = finding("missed_mate", pieces=(), material=None, mate_in=1,
                   moves={"played": ref("h5", "h7h5"), "best": ref("Qe2#", "d1e2")})
    assert describe_ply(START, [mate, _threat()], "excellent", None) == [
        "Qe2# was mate in 1."
    ]


def test_a_sacrifice_is_not_reported_as_a_blunder():
    """The classifier has already called this brilliant. A screen that says
    "this drops the knight" under a brilliancy is arguing with itself."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "f5"),),
        moves={"played": ref("Nf5"), "refutation": ref("Bxf5")},
    )
    assert render(f, START, "brilliant", None) == (
        "This gives up the knight on f5 — Bxf5 takes it, and that is the point."
    )


def test_great_does_not_claim_the_sacrifice_was_deliberate():
    """`great` is `is_best` plus a win-probability gap to the second line. It
    proves the position was hard, not that anything was offered, so it gets the
    forced-move sentence rather than "and that is the point"."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "f5"),), material=-3.0,
        pattern=PATTERN_FORCED,
        moves={"played": ref("Nf5"), "refutation": ref("Bxf5")},
    )
    assert render(f, START, "great", 0.5, loss=0.0) == (
        "This drops the knight on f5 — Bxf5 takes it, "
        "but everything else was worse."
    )


def test_material_shed_at_no_cost_to_the_evaluation():
    """WPL near zero in a position that is not yet decided means the move cost
    nothing. It does not mean the material returns, or that anyone meant it to, so
    the sentence says neither."""
    f = finding(
        "hangs_piece", pieces=(piece("B", "f7"),), material=-2.0,
        moves={"played": ref("Bxf7+"), "refutation": ref("Kxf7")},
    )
    assert render(f, START, "excellent", 0.60, loss=0.008) == (
        "This gives up the bishop on f7 — Kxf7 takes it, though it costs nothing here."
    )


def test_a_decided_position_cannot_prove_compensation():
    """`win_prob` is flat near the ends, so a free-looking loss there is
    saturation. Measured, 58.9 % of these findings above 0.9 cost under 0.02 WPL
    while shedding 2.2 pawns on average — the material does not come back."""
    f = finding(
        "hangs_piece", pieces=(piece("B", "f7"),), material=-2.0,
        moves={"played": ref("Bxf7+"), "refutation": ref("Kxf7")},
    )
    assert render(f, START, "excellent", 0.93, loss=0.008) == (
        "This drops the bishop on f7 — Kxf7 takes it."
    )


def test_a_forced_move_cannot_prove_compensation():
    """`PATTERN_FORCED` means the move *was* the engine's first choice, which
    makes WPL zero by construction. Reading that as compensation would turn the
    reframe into a restatement of `played == best`."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "f5"),), material=-3.0,
        pattern=PATTERN_FORCED,
        moves={"played": ref("Nf5"), "refutation": ref("Bxf5")},
    )
    assert render(f, START, "excellent", 0.5, loss=0.0) == (
        "This drops the knight on f5 — Bxf5 takes it, "
        "but everything else was worse."
    )


def test_a_book_move_says_nothing():
    """A book move is named by the opening, not by what it leaves loose. The
    rules still fire; the layer declines to render them."""
    f = finding(
        "hangs_piece", pieces=(piece("P", "e5"),), material=-1.0,
        moves={"played": ref("Nc5"), "refutation": ref("Nxe5")},
    )
    assert render(f, START, "book", 0.5) is None
    assert describe_ply(START, [f], "book", 0.5) == []


def test_a_skewer_names_the_piece_in_front_and_the_one_behind():
    f = finding(
        "skewer", pieces=(piece("R", "h8"), piece("K", "e8")),
        moves={"played": ref("Re1+")},
    )
    assert render(f, START, None, None) == (
        "Re1+ skewers the king on e8, and the rook on h8 behind it "
        "— the rook on h8 falls."
    )


def test_a_trapped_piece_states_what_falls_once():
    """"traps" already says the piece is lost, so the consequence slot stays
    empty. Without that the sentence ends "— the knight on a5 falls" after
    having just said it has nowhere to go."""
    f = finding("trapped_piece", pieces=(piece("N", "a5"),), moves={"played": ref("b4")})
    assert render(f, START, None, None) == (
        "b4 traps the knight on a5 — it has nowhere safe to go."
    )


def test_a_mate_walked_into_names_the_refutation():
    f = finding(
        "walks_into_mate", pieces=(), material=None, mate_in=2,
        moves={"played": ref("Kh1"), "refutation": ref("Qg2+")},
    )
    assert render(f, START, None, None) == "This allows Qg2+, mate in 2."


def test_a_mate_walked_into_without_a_refutation_still_says_so():
    """The engine branch has a mate score and no move to name."""
    f = finding(
        "walks_into_mate", pieces=(), material=None, mate_in=3,
        basis="engine", moves={"played": ref("Kh1")},
    )
    assert render(f, START, None, None) == "This allows a forced mate in 3."


def test_the_back_rank_annotation_rides_on_a_mate_and_names_the_pawns():
    f = finding(
        "missed_mate", pieces=(piece("P", "f7"), piece("P", "g7")),
        material=None, mate_in=1, pattern=PATTERN_BACK_RANK,
        moves={"best": ref("Ra8#")},
    )
    assert render(f, START, None, None) == (
        "Ra8# was mate in 1 — a back-rank mate, with the king's own pawns "
        "on f7, g7 in the way."
    )


def test_a_saved_piece_is_never_named_on_the_square_it_fled_to():
    """Falsehood 2. The rule reads this piece off the board *after* the best
    move, so the square it carries is the destination, not where it stood in
    danger. "Nc4 would have saved the knight on c4" was the result."""
    f = finding(
        "best_saves_piece", subject="best", pieces=(piece("N", "c4"),),
        moves={"best": ref("Nc4")},
    )
    sentence = render(f, START, None, None)
    assert sentence == "Nc4 would have saved the knight."
    assert "c4" not in sentence.replace("Nc4", "")


# ── the gate ─────────────────────────────────────────────────────────────────


def test_a_mate_too_long_to_calculate_is_not_rendered():
    f = finding(
        "missed_mate", pieces=(), material=None, mate_in=MATE_CUTOFF + 1,
        basis="engine", moves={"best": ref("Rd1")},
    )
    assert render(f, START, None, None) is None


def test_a_short_mate_is_rendered():
    f = finding(
        "missed_mate", pieces=(), material=None, mate_in=MATE_CUTOFF,
        basis="engine", moves={"best": ref("Rd1")},
    )
    assert render(f, START, None, None) == f"Rd1 was mate in {MATE_CUTOFF}."


def test_a_long_mate_you_walked_into_is_still_rendered():
    """Only `missed_mate` is cut. A mate against you says the move lost, however
    long it is, and the already-lost reframe below handles the case where the
    position was gone before the move."""
    f = finding(
        "walks_into_mate", pieces=(), material=None, mate_in=19,
        basis="engine", moves={"played": ref("Kc1")},
    )
    assert render(f, START, None, None) == "This allows a forced mate in 19."


def test_material_won_by_a_mating_move_is_not_reported():
    """"Qxc2# would have won the pawn on c2" is true and it is bookkeeping.

    Rank order cannot solve this, which is why it is a gate: rule 3 declines to emit
    a `missed_mate` finding when the player still has mate after the played move, so
    there is no mate sentence for the material one to lose to.
    """
    f = finding(
        "missed_material", subject="played", pieces=(piece("P", "c2"),),
        material=1.0, moves={"best": ref("Qxc2#", "c1c2")},
    )
    assert render(f, START, None, None) is None


def test_material_won_by_a_move_that_only_checks_is_still_reported():
    """The gate reads the SAN, so it must not catch `+` as well as `#`."""
    f = finding(
        "missed_material", subject="played", pieces=(piece("P", "c2"),),
        material=1.0, moves={"best": ref("Qxc2+", "c1c2")},
    )
    assert render(f, START, None, None) == "Qxc2+ would have won the pawn on c2."


def test_a_suppressed_finding_does_not_silence_the_move_it_shares():
    """A finding that renders nothing must not win its move's slot.

    A mate in 19 outranks everything and then says nothing, so before this the
    material sentence beside it vanished too — the opposite of the recorded policy
    that a material sentence in place of a suppressed unactionable mate is the right
    trade.
    """
    long_mate = finding(
        "missed_mate", pieces=(), material=None, mate_in=MATE_CUTOFF + 1,
        basis="engine", moves={"best": ref("Rd8", "d1d8")},
    )
    material = finding(
        "missed_material", pieces=(piece("q", "d8", "black"),), material=9.0,
        moves={"best": ref("Rd8", "d1d8")},
    )
    kept = one_sentence_per_move([long_mate, material])
    assert [f.kind for f in kept] == ["missed_material"]


@pytest.mark.parametrize("kind", sorted(BOOKKEEPING_KINDS))
def test_a_mating_move_never_has_its_merits_itemised(kind):
    """Parametrised over the gate's own table so a kind added to it cannot ship
    without the behaviour the table promises.

    "Qxc2# would have won the pawn on c2" and "Ne5# would have saved the knight"
    are the same sentence: a move that ends the game, credited for a side effect.
    """
    f = finding(
        kind, subject="played", pieces=(piece("N", "e5"),),
        material=3.0, moves={"best": ref("Ne5#", "d3e5")},
    )
    assert render(f, START, None, None) is None


@pytest.mark.parametrize("kind", sorted(BOOKKEEPING_KINDS))
def test_the_same_move_without_mate_still_renders(kind):
    """The companion to the gate: it must key on the `#`, not on the kind."""
    f = finding(
        kind, subject="played", pieces=(piece("N", "e5"),),
        material=3.0, moves={"best": ref("Ne5+", "d3e5")},
    )
    assert render(f, START, None, None) is not None


# ── a hang on the engine's own move ──────────────────────────────────────────


def test_a_hang_on_the_best_move_says_everything_else_was_worse():
    """A `Best move` badge above "This drops the knight on e5" reads as a
    contradiction. Both are true, and the clause that reconciles them is a fact the
    rule established, not one the template works out."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
        pattern=PATTERN_FORCED,
        moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
    )
    assert render(f, START, None, None) == (
        "This drops the knight on e5 — Qxe5 takes it, but everything else was worse."
    )


def test_a_forced_hang_drops_the_qualifier_rather_than_stacking_it():
    """Two contrastive clauses in one sentence say one thing badly."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
        pattern=PATTERN_FORCED,
        moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
    )
    sentence = render(f, START, "blunder", LOST)
    assert sentence.endswith("but everything else was worse.")
    assert QUAL_LOST not in sentence


def test_a_sacrifice_that_was_also_the_best_move_keeps_the_sacrifice_framing():
    """Most brilliancies are the engine's move too, so both branches fire. The
    sacrifice reading is the stronger claim: the material was spent, not endured."""
    f = finding(
        "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
        pattern=PATTERN_FORCED,
        moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
    )
    assert render(f, START, "brilliant", None) == (
        "This gives up the knight on e5 — Qxe5 takes it, and that is the point."
    )


def test_a_hang_on_a_move_that_was_not_best_is_unchanged():
    f = finding(
        "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
        moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
    )
    assert render(f, START, None, None) == (
        "This drops the knight on e5 — Qxe5 takes it."
    )


def test_the_rule_stamps_forced_only_when_the_played_move_was_best():
    """The renderer must never infer this from the classification label, so the
    rule has to be the one that knows.

    `Nf3` steps onto the b7 bishop's diagonal either way — the position is the rule
    tests' own hang case, verified at -3.0 by playing the capture out. What changes
    between the two calls is only whether the engine would have played it.
    """
    fen = "4k3/1b6/8/8/8/8/8/4K1N1 w - - 0 1"
    hangs = [f for f in explain_ply(fen, "g1f3") if f.kind == "hangs_piece"]
    assert hangs and all(f.pattern is None for f in hangs)

    forced = [
        f for f in explain_ply(fen, "g1f3", best_uci="g1f3")
        if f.kind == "hangs_piece"
    ]
    assert forced and all(f.pattern == PATTERN_FORCED for f in forced)

    other = [
        f for f in explain_ply(fen, "g1f3", best_uci="e1e2")
        if f.kind == "hangs_piece"
    ]
    assert other and all(f.pattern is None for f in other)


# ── the qualifier ────────────────────────────────────────────────────────────


def test_a_tactic_in_a_won_position_is_framed_as_converting_it():
    f = finding("fork", pieces=(piece("R", "a8"), piece("K", "e8")))
    assert render(f, START, "best", WINNING).endswith(
        "converting a position you were already winning."
    )


def test_a_missed_tactic_in_a_won_position_did_not_convert_anything():
    """The wording has to differ by mood, because the fact does. Telling a player
    a move they did not make converted the position would be false."""
    f = finding(
        "fork", subject="best", pieces=(piece("R", "a8"), piece("K", "e8")),
        moves={"best": ref("Nc7+")},
    )
    assert render(f, START, "best", WINNING).endswith("though you were winning anyway.")


def test_a_mate_in_a_lost_position_says_the_position_was_already_gone():
    """The stage-3 extension. This carries no material at all, so the reframe has
    to key on `p_before` alone. 52.4 % of kept long `walks_into_mate` findings
    land on moves the classifier called `best` or `excellent`, which is this
    case: the move did not lose the game, the position was already lost."""
    f = finding(
        "walks_into_mate", pieces=(), material=None, mate_in=19,
        basis="engine", moves={"played": ref("Kc1")},
    )
    assert render(f, START, "best", LOST) == (
        "This allows a forced mate in 19, though the position was lost either way."
    )


def test_losing_a_piece_does_not_convert_a_won_position():
    """The already-winning reframe is about a gain. Attached to a loss it asserts
    the opposite of the finding — this sentence said dropping the queen converted
    the game."""
    f = finding(
        "hangs_piece", pieces=(piece("Q", "g2"),),
        moves={"played": ref("Kg2"), "refutation": ref("Kxg2")},
    )
    assert render(f, START, "blunder", WINNING) == (
        "This drops the queen on g2 — Kxg2 takes it."
    )


def test_being_mated_does_not_convert_a_won_position():
    f = finding(
        "walks_into_mate", pieces=(), material=None, mate_in=1,
        moves={"played": ref("Kg1"), "refutation": ref("Rf8#")},
    )
    assert render(f, START, "blunder", WINNING) == "This allows Rf8#, mate in 1."


def test_a_missed_mate_is_never_dismissed_as_winning_anyway():
    """A forced mate *is* a win probability of about 1, so keying the reframe on
    `p_before` alone fires it on almost every `missed_mate` — and the sentence
    then tells the reader the mate they missed did not matter."""
    f = finding(
        "missed_mate", pieces=(), material=None, mate_in=1,
        moves={"best": ref("Qxh2#")},
    )
    assert render(f, START, "miss", 0.999) == "Qxh2# was mate in 1."


def test_the_already_lost_reframe_applies_to_a_loss():
    """The other half does apply to both, because it is about the position rather
    than the claim."""
    f = finding(
        "hangs_piece", pieces=(piece("B", "e2"),),
        moves={"played": ref("Be2"), "refutation": ref("Nxe2")},
    )
    assert render(f, START, "blunder", LOST) == (
        "This drops the bishop on e2 — Nxe2 takes it, though the position was "
        "lost either way."
    )


def test_an_undecided_position_gets_no_qualifier():
    f = finding("fork", pieces=(piece("R", "a8"), piece("K", "e8")))
    assert render(f, START, "blunder", 0.5).endswith("the rook on a8 falls.")


def test_no_score_means_no_qualifier():
    f = finding("fork", pieces=(piece("R", "a8"), piece("K", "e8")))
    assert render(f, START, None, None).endswith("the rook on a8 falls.")


def test_material_that_cannot_mate_is_not_reported_as_a_gain():
    """The Nc7+ case, and the one form of policy 4 the board can prove on its
    own: after Nxa8 White has king and knight. Measured over the whole corpus
    this fires once."""
    fen = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
    sentences = one(fen, "b5c7")
    assert sentences == [
        "Nc7+ forks the rook on a8 and king on e8 — the rook on a8 falls, "
        "but what is left cannot mate."
    ]


# ── the dedupe ───────────────────────────────────────────────────────────────


def test_one_move_gets_one_sentence():
    """3259 of 8485 multi-sentence blocks opened two sentences with the same move
    name before this, the second almost always implied by the first."""
    mate = finding(
        "missed_mate", subject="played", pieces=(), material=None, mate_in=2,
        moves={"best": ref("Qa3", "d1a3")},
    )
    defends = finding(
        "best_defends_piece", subject="best", pieces=(piece("P", "c3"),),
        material=None, moves={"best": ref("Qa3", "d1a3")},
    )
    assert one_sentence_per_move([mate, defends]) == [mate]


def test_two_different_moves_keep_their_own_sentences():
    a = finding("hangs_piece", moves={"played": ref("Nf5", "h4f5")})
    b = finding(
        "missed_material", subject="played", moves={"best": ref("Rxa8", "a1a8")}
    )
    assert one_sentence_per_move([a, b]) == [a, b]


def test_the_same_move_as_played_and_as_best_are_different_sentences():
    """A tactic the player found produces a `played` finding; the dedupe keys on
    the move *and* which of the two it names, so a `best` finding about the same
    uci is not folded into it."""
    played = finding("fork", subject="played", moves={"played": ref("Nc7+", "b5c7")})
    best = finding("trapped_piece", subject="best", moves={"best": ref("Nc7+", "b5c7")})
    assert one_sentence_per_move([played, best]) == [played, best]


def test_two_hanging_pieces_become_one_sentence_naming_both():
    """A move that loses two pieces must not read as losing one. The dedupe keeps
    one sentence per move, so the two findings merge rather than one being
    dropped — the earlier behaviour kept the queen and silently lost the pawn."""
    pawn = finding(
        "hangs_piece", pieces=(piece("P", "b2"),), material=-1.0,
        moves={"played": ref("Kg1", "h1g1"), "refutation": ref("Rxb2", "b8b2")},
    )
    queen = finding(
        "hangs_piece", pieces=(piece("Q", "d1"),), material=-9.0,
        moves={"played": ref("Kg1", "h1g1"), "refutation": ref("Rxd1", "d8d1")},
    )
    kept = one_sentence_per_move([pawn, queen])
    assert len(kept) == 1
    assert [p.square for p in kept[0].pieces] == ["d1", "b2"]
    assert kept[0].material == -10.0
    assert render(kept[0], START, None, None) == (
        "This drops the queen on d1 and pawn on b2."
    )


def test_a_merged_loss_names_no_single_capture():
    """Each finding carries the capture that takes *its* piece and there is no
    move that takes both, so keeping one would name one capture and imply it
    answered everything."""
    a = finding(
        "hangs_piece", pieces=(piece("R", "a1"),), material=-5.0,
        moves={"played": ref("Kg1", "h1g1"), "refutation": ref("Rxa1", "a8a1")},
    )
    b = finding(
        "hangs_piece", pieces=(piece("N", "f3"),), material=-3.0,
        moves={"played": ref("Kg1", "h1g1"), "refutation": ref("Bxf3", "g4f3")},
    )
    kept = one_sentence_per_move([a, b])[0]
    assert "refutation" not in kept.moves
    assert "takes it" not in render(kept, START, None, None)


def test_one_hanging_piece_still_names_its_capture():
    """The merge must not cost the single-piece case its refutation clause."""
    lone = finding(
        "hangs_piece", pieces=(piece("R", "a1"),), material=-5.0,
        moves={"played": ref("Kg1", "h1g1"), "refutation": ref("Rxa1", "a8a1")},
    )
    kept = one_sentence_per_move([lone])[0]
    assert render(kept, START, None, None) == (
        "This drops the rook on a1 — Rxa1 takes it."
    )


def test_a_finding_that_names_no_move_is_dropped_rather_than_crashing():
    orphan = finding("hangs_piece", moves={})
    assert one_sentence_per_move([orphan]) == []


# ── no template may recompute geometry ───────────────────────────────────────


def test_a_discovered_check_does_not_claim_a_line_onto_the_piece():
    """Falsehood 1, at the level it was actually fixed.

    On the check branch the opened line reaches the king, and the piece that
    falls is one the *moved* piece attacks — the material is proven, because the
    defender may only answer the check, but no opened line reaches it. The
    template reads `pattern` rather than looking at the board, because a template
    that recomputes geometry can disagree with the rule that proved the material.
    """
    f = finding(
        "discovered_attack", pieces=(piece("Q", "a6"),),
        pattern=PATTERN_DISCOVERED_CHECK, moves={"played": ref("Nd5+")},
    )
    sentence = render(f, START, None, None)
    assert "opens a line" not in sentence
    assert sentence == (
        "Nd5+ attacks the queen on a6 and discovers a check, which has to be "
        "answered first — the queen on a6 falls."
    )


def test_a_discovered_attack_on_the_line_does_claim_the_line():
    f = finding(
        "discovered_attack", pieces=(piece("Q", "a6"),),
        pattern=PATTERN_DISCOVERED_LINE, moves={"played": ref("Nd5")},
    )
    assert render(f, START, None, None) == (
        "Nd5 opens a line onto the queen on a6 — the queen on a6 falls."
    )


def test_every_sentence_only_names_squares_its_finding_carries():
    """The governing constraint, asserted directly over real positions.

    Any square name in a rendered sentence must come from a piece the finding
    carries or from the SAN of a move it carries. A template that invented one
    would be asserting something the rule never proved, which is the failure this
    layer exists to avoid.
    """
    positions = [
        ("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", "b5c7", None),
        ("4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4", "e1f2"),
        ("4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4", "f3e5"),
        ("rnb1k2r/2q1n1pp/p2b4/1p2pp2/7N/2NB4/PPPP1PPP/R1BQ1RK1 w kq - 0 10",
         "h4f5", "b2b3"),
        ("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "a1a8", None),
    ]
    checked = 0
    for fen, uci, best in positions:
        for f in explain_ply(fen, uci, best_uci=best):
            sentence = render(f, fen, None, None)
            if sentence is None:
                continue
            allowed = {p.square for p in f.pieces}
            allowed |= {
                chess.square_name(s)
                for m in f.moves.values()
                for s in (
                    chess.Move.from_uci(m.uci).from_square,
                    chess.Move.from_uci(m.uci).to_square,
                )
            }
            for name in (chess.square_name(s) for s in chess.SQUARES):
                if name in sentence:
                    assert name in allowed, (
                        f"{f.kind} sentence names {name}, which the finding does "
                        f"not carry: {sentence!r}"
                    )
            checked += 1
    assert checked >= 5


# ── the whole block ──────────────────────────────────────────────────────────


def test_the_cap_holds():
    findings = [
        finding("hangs_piece", pieces=(piece("N", f),), moves={"played": ref("Kg1", u)})
        for f, u in (("b2", "h1g1"), ("c3", "h2g2"), ("d4", "h3g3"), ("e5", "h4g4"))
    ]
    assert len(describe_ply(START, findings, cap=3)) == 3


def test_only_the_first_sentence_in_a_block_carries_the_qualifier():
    """The dedupe keys on the move a sentence names, so two sentences about two
    different moves each earn the reframe independently. It is a fact about the
    position, not about either move, so saying it twice says it once too often."""
    findings = [
        finding(
            "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
            moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
        ),
        finding(
            "missed_material", pieces=(piece("R", "a8"),), material=5.0,
            moves={"best": ref("Rxa8", "a1a8")},
        ),
    ]
    block = describe_ply(START, findings, "blunder", LOST)
    assert block == [
        "This drops the knight on e5 — Qxe5 takes it, though the position was "
        "lost either way.",
        "Rxa8 would have won the rook on a8.",
    ]


def test_the_qualifier_moves_to_the_first_sentence_that_can_take_one():
    """A leading sentence whose kind never qualifies must not consume the block's
    one qualifier — `best_defends_piece` has no qualifier slot at all, so the
    sentence after it is still the first that can carry one."""
    findings = [
        finding(
            "best_defends_piece", pieces=(piece("P", "f3"),), material=None,
            moves={"best": ref("Rf1", "a1f1")},
        ),
        finding(
            "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
            moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
        ),
    ]
    block = describe_ply(START, findings, "blunder", LOST)
    assert block == [
        "This drops the knight on e5 — Qxe5 takes it, though the position was "
        "lost either way.",
        "Rf1 would have defended the pawn on f3.",
    ]


def test_a_quiet_move_says_nothing_at_all():
    assert one(START, "e2e4") == []


def test_the_stored_entry_point_renders_a_real_ply():
    """Through `describe_stored_ply`, which is what the sidecar will call — same
    row shape, same arguments. The probes that assembled their own call are the
    reason this test names the entry point rather than `describe_ply`."""
    row = {
        "fen_before": "8/3p4/2p5/p4bk1/BP3p1p/5P2/7r/1K6 w - - 1 38",
        "played_uci": "b1c1",
        "best_uci": "b1a1",
        "classification": "blunder",
        "score_before_cp": -1149,
        "score_before_mate": None,
        "score_after_cp": None,
        "score_after_mate": -19,
    }
    assert describe_stored_ply(row, "white") == [
        "This allows a forced mate in 19, though the position was lost either way."
    ]


def test_the_stored_entry_point_names_the_side_on_the_opponents_move():
    """Same row, same sentence, but the user played Black — so it was White who
    walked into the mate, and the sentence must not tell the reader they did.

    The FEN has White to move; `player_color="black"` makes the mover the opponent.
    """
    row = {
        "fen_before": "8/3p4/2p5/p4bk1/BP3p1p/5P2/7r/1K6 w - - 1 38",
        "played_uci": "b1c1",
        "best_uci": "b1a1",
        "classification": "blunder",
        "score_before_cp": -1149,
        "score_before_mate": None,
        "score_after_cp": None,
        "score_after_mate": -19,
    }
    assert describe_stored_ply(row, "black") == [
        "White allows a forced mate in 19, though the position was lost either way."
    ]


def test_the_already_winning_reframe_inflects_with_the_voice():
    """The one qualifier that names the mover. Second person says "you were", and
    the third-person form has to agree with the side it names rather than reusing
    the pronoun's verb."""
    fen = "7k/8/8/8/8/8/1r6/3QK3 w - - 0 1"
    findings = explain_ply(fen, "d1d4")
    assert findings, "expected a fork finding to qualify"
    mine = describe_ply(fen, findings, "good", 0.99, voice=SECOND_PERSON)
    theirs = describe_ply(
        fen, findings, "good", 0.99, voice=voice_for(fen, "black")
    )
    assert mine == [
        "Qd4+ forks the rook on b2 and king on h8 — the rook on b2 falls, "
        "converting a position you were already winning."
    ]
    assert theirs == [
        "Qd4+ forks the rook on b2 and king on h8 — the rook on b2 falls, "
        "converting a position White was already winning."
    ]


def test_only_the_first_sentence_carries_a_qualifier_in_third_person():
    """The at-most-one-qualifier rule is enforced by asking `qualifier` the question
    again, not by matching a fixed list of strings. Once those strings became
    templates over `Voice`, a fixed list would have stopped matching the
    third-person rendering and every sentence in the block would have carried the
    reframe. Same findings as the second-person case above, so the only difference
    under test is the voice."""
    findings = [
        finding(
            "hangs_piece", pieces=(piece("N", "e5"),), material=-3.0,
            moves={"played": ref("Ne5", "d3e5"), "refutation": ref("Qxe5", "d8e5")},
        ),
        finding(
            "best_defends_piece", pieces=(piece("P", "f3"),), material=None,
            moves={"best": ref("Rf1", "a1f1")},
        ),
    ]
    block = describe_ply(
        START, findings, "blunder", LOST, voice=voice_for(START, "black")
    )
    assert block == [
        "White drops the knight on e5 — Qxe5 takes it, though the position was "
        "lost either way.",
        "Rf1 would have defended the pawn on f3.",
    ]


@pytest.mark.parametrize(
    "kind,fen,uci,kwargs",
    [
        # Rules 1-4, each on its board branch. Rules 3 and 4 prove mate in one
        # without a score; anything longer needs the stored mate and is not
        # available with no engine, which is a narrower answer rather than no answer.
        ("hangs_piece", "4k3/1b6/8/8/8/8/8/4K1N1 w - - 0 1", "g1f3", {}),
        ("missed_material", "3q4/8/8/7k/8/8/8/3RK3 w - - 0 1", "d1d2",
         {"best_uci": "d1d8"}),
        ("missed_mate", "6k1/5ppp/8/8/8/8/8/R3K2R w KQ - 0 1", "h1h7", {}),
        ("walks_into_mate", "4r1k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a7", {}),
        # The four motifs, which never had an engine branch to lose.
        ("fork", "7k/8/8/8/8/8/1r6/3QK3 w - - 0 1", "d1d4", {}),
        ("skewer", "Rn1k2r1/4ppbp/2p3p1/2N1P2n/8/5N1P/3BBPP1/6K1 w - - 3 27",
         "a8b8", {}),
        ("discovered_attack", "8/8/rB1RN1kp/5p2/5P2/5K2/8/8 w - - 6 49", "e6c7", {}),
        ("trapped_piece", "b4k2/4R3/p1p2p2/1p3N2/5P2/2P3PB/PP5P/2K5 w - - 7 30",
         "e7a7", {}),
    ],
)
def test_every_rule_still_produces_a_sentence_with_no_engine(kind, fen, uci, kwargs):
    """Stage 4's open question: does the screen go blank when Stockfish is absent?

    No score arguments are passed at all — not None-by-default, but genuinely
    absent, which is the state the fresh-install audit found to be real. Each
    position is one already verified by the rule tests in `test_explain.py`.
    """
    findings = explain_ply(fen, uci, **kwargs)
    assert kind in [f.kind for f in findings], f"{kind} did not fire"
    mine = [f for f in findings if f.kind == kind]
    assert any(render(f, fen, None, None) for f in mine), f"{kind} rendered nothing"


def test_the_renderer_imports_no_qt():
    """The golden rule, by the same AST walk `test_engine_locator` uses.

    Reading `sys.modules` cannot work here: the rest of the suite has already
    imported PyQt by the time this runs, so the assertion passes alone and fails
    in the full run. The AST is what the packaging rule is actually about — a
    sidecar bundle must not drag in PyQt6 — and it catches a deferred import
    inside a function body, which is how one hid in `engine_locator`.
    """
    import ast
    from pathlib import Path

    import zugzwang.core.explain_text as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not {"PyQt6", "PyQt5", "PySide6"} & imported


# ── RULE_VERSION 12: the long-mate lead slot (owner's option 1) ──────────────

def _long_mate(n):
    return finding("walks_into_mate", pieces=(), material=None, mate_in=n,
                   basis="engine", moves={"played": ref("Nc7+", "b5c7")})


def _order(findings):
    from zugzwang.core.explain import rank_findings
    from zugzwang.core.explain_text import one_sentence_per_move
    return [f.kind for f in one_sentence_per_move(rank_findings(findings))]


def test_a_long_mate_against_you_gives_up_the_lead_to_a_concrete_finding():
    # Same move, so the dedupe used to keep only the mate and hide the material loss.
    hangs = finding("hangs_piece")
    assert _order([_long_mate(10), hangs]) == ["hangs_piece", "walks_into_mate"]


def test_a_long_mate_is_demoted_not_dropped():
    # Option 1 never makes a ply silent and never deletes the mate sentence.
    assert _order([_long_mate(10)]) == ["walks_into_mate"]


def test_a_mate_against_you_up_to_six_keeps_the_lead():
    # A mate in 5 is a better headline than a dropped pawn (owner ruling).
    hangs = finding("hangs_piece")
    assert _order([_long_mate(6), hangs]) == ["walks_into_mate"]


def test_demotion_starts_at_mate_in_seven_on_its_own_constant():
    # Deliberately not MATE_CUTOFF: a missed mate and an allowed mate differ in value
    # at the same length, so one threshold for both would contradict that.
    from zugzwang.core.explain import MATE_CUTOFF, MATE_DEMOTE_FROM, is_long_mate_against
    from zugzwang.core.explain_text import MATE_CUTOFF as TEXT_CUTOFF
    assert MATE_CUTOFF == TEXT_CUTOFF == 4
    assert MATE_DEMOTE_FROM == 7
    assert not is_long_mate_against(_long_mate(6))
    assert is_long_mate_against(_long_mate(7))


def test_a_game_whose_side_is_unknown_names_both_players():
    """FIXPLAN O5: `player_color` NULL. Neither move is addressed as the reader's —
    "you" on both sides would be wrong on one of them."""
    from zugzwang.core.explain_text import UNKNOWN_SIDE
    white_to_move = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
    black_to_move = "4k3/8/8/8/8/8/8/4K3 b - - 0 1"
    assert voice_for(white_to_move, UNKNOWN_SIDE).subject == "White"
    assert voice_for(black_to_move, UNKNOWN_SIDE).subject == "Black"
    assert voice_for(white_to_move, UNKNOWN_SIDE).agent == "White"
    assert voice_for(white_to_move, None) == SECOND_PERSON     # no game: unchanged


# ── the adjacent-ply check (owner, 2026-11-09) ───────────────────────────────

# A real game's plies 29 and 30, stored rows verbatim (its platform id is in the private
# repository). 15...Bxg3 was rendered
# "This drops the bishop on g3 — fxg3 takes it." while the same run labels 16.fxg3 a
# blunder: 16.fxg3 Nxg3+ forks the king and the f1 rook, beyond gate P's two plies.
BXG3 = {
    29: {"fen_before": "rn2r3/ppp1ppk1/3q2p1/7n/6b1/2NBBNP1/PPP2P1b/R2Q1R1K b - - 0 15",
         "played_uci": "h2g3", "best_uci": "e8h8", "classification": "mistake",
         "score_before_cp": 119, "score_before_mate": None, "score_after_cp": -60,
         "score_after_mate": None},
    30: {"fen_before": "rn2r3/ppp1ppk1/3q2p1/7n/6b1/2NBBNb1/PPP2P2/R2Q1R1K w - - 0 16",
         "played_uci": "f2g3", "best_uci": "c3e4", "classification": "blunder",
         "score_before_cp": 96, "score_before_mate": None, "score_after_cp": -175,
         "score_after_mate": None},
}


def test_a_capture_the_next_ply_contradicts_is_not_claimed():
    from zugzwang.core.explain_text import RunPlies, explain_and_describe_stored_ply
    alone = explain_and_describe_stored_ply(BXG3[29], "black")[1]
    assert alone == ["This drops the bishop on g3 — fxg3 takes it."]   # gate P passes it
    checked = explain_and_describe_stored_ply(BXG3[29], "black", run=RunPlies(BXG3, 29))[1]
    assert checked == []


def test_next_ply_contradicts_names_the_reason():
    from zugzwang.core.explain import explain_stored_ply
    from zugzwang.core.explain_text import RunPlies, next_ply_contradicts
    f = next(f for f in explain_stored_ply(BXG3[29]) if f.kind == "hangs_piece")
    assert next_ply_contradicts(f, RunPlies(BXG3, 29)) == "played, and labelled an error"
    # Not played, not among the stored lines: its loss cannot be read, so it is silenced.
    unplayed = {**BXG3, 30: {**BXG3[30], "played_uci": "d1e1", "classification": "good"}}
    assert next_ply_contradicts(f, RunPlies(unplayed, 29)) == "not among the engine's top replies"
    # Not played, but among the stored lines: judged by its win-probability loss against
    # the best line (side-to-move view) — the non-error band (≤ WPL_GOOD) keeps it.
    near = {**unplayed, 30: {**unplayed[30], "lines": [
        {"uci": ["c3e4"], "cp": 96, "mate": None}, {"uci": ["f2g3"], "cp": 80, "mate": None}]}}
    assert next_ply_contradicts(f, RunPlies(near, 29)) is None
    far = {**unplayed, 30: {**unplayed[30], "lines": [
        {"uci": ["c3e4"], "cp": 96, "mate": None}, {"uci": ["f2g3"], "cp": -175, "mate": None}]}}
    assert next_ply_contradicts(f, RunPlies(far, 29)) == "would itself be an error"
    # Played and not an error: it stands, best reply or not.
    sound = {**BXG3, 30: {**BXG3[30], "classification": "good"}}
    assert next_ply_contradicts(f, RunPlies(sound, 29)) is None
    agrees = {**BXG3, 30: {**BXG3[30], "best_uci": "f2g3", "played_uci": "f2g3",
                           "classification": "best"}}
    assert next_ply_contradicts(f, RunPlies(agrees, 29)) is None
    # The last ply: checked against the final position's line; nothing stored, kept.
    last = {29: BXG3[29]}
    assert next_ply_contradicts(f, RunPlies(last, 29, ({"uci": ["c3e4"]},))) \
        == "not among the engine's top replies"
    assert next_ply_contradicts(f, RunPlies(last, 29, ({"uci": ["f2g3"]},))) is None
    assert next_ply_contradicts(f, RunPlies(last, 29)) is None
