"""Stage 1 move-explanation rules.

Every position here has a known answer worked out on the board, not taken from
the implementation's output. A rule that cannot prove its claim must emit
nothing, so most of these assert *absence*.
"""

import chess
import pytest

from zugzwang.core.explain import (
    PATTERN_DISCOVERED_CHECK,
    PATTERN_DISCOVERED_LINE,
    RULE_VERSION,
    STORED_PLY_COLUMNS,
    Finding,
    MoveRef,
    _boxed_in,
    _holds_after_reply,
    explain_ply,
    explain_stored_ply,
    rank_findings,
    see,
)


def kinds(findings):
    return {f.kind for f in findings}


def only(findings, kind):
    matched = [f for f in findings if f.kind == kind]
    assert len(matched) == 1, f"expected exactly one {kind}, got {kinds(findings)}"
    return matched[0]


# ── position guards ──────────────────────────────────────────────────────────
#
# Every position below is constructed by hand, and hand-constructed positions
# are wrong more often than they look. Three in this file's first draft were
# impossible -- a knight on d1 asked to move to f3, a knight on c6 said to
# defend d5 -- and each one surfaced as a rule quietly returning no findings,
# which is indistinguishable from a rule bug. These helpers make a bad position
# fail as a bad position, at the line that wrote it.


def verify(fen, uci=None):
    """The board, checked for legality, and the move, checked for being legal
    in it. Raises with the piece and its actual options rather than a bare
    False, because "that knight cannot reach that square" is the whole bug."""
    board = chess.Board(fen)
    assert board.is_valid(), f"impossible position {fen}: {board.status()!r}"
    if uci is None:
        return board, None
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        piece = board.piece_at(move.from_square)
        origin = chess.square_name(move.from_square)
        legal = sorted(
            m.uci() for m in board.legal_moves if m.from_square == move.from_square
        )
        raise AssertionError(
            f"{uci} is not legal in {fen} -- "
            f"{'empty square' if piece is None else repr(piece.symbol())} on {origin}, "
            f"legal from there: {legal or 'nothing'}"
        )
    return board, move


def explained(fen, uci, **kwargs):
    """`explain_ply` on a position that has been checked first."""
    verify(fen, uci)
    if kwargs.get("best_uci"):
        verify(fen, kwargs["best_uci"])
    return explain_ply(fen, uci, **kwargs)


def guards(fen, square):
    """Every piece bearing on `square`, as e.g. {'n', 'f6'} -> 'nf6'.

    A test about trades and recaptures rests entirely on who actually defends
    the contested square. Asserting that set makes the assumption explicit, and
    catches the defender that is two files away from where it was imagined.
    """
    board, _ = verify(fen)
    target = chess.parse_square(square)
    return {
        f"{board.piece_at(s).symbol()}{chess.square_name(s)}"
        for color in (chess.WHITE, chess.BLACK)
        for s in board.attackers(color, target)
    }


# ── static exchange evaluation ───────────────────────────────────────────────

def test_see_counts_a_simple_win():
    # Black queen on d8 is undefended; the rook simply takes it.
    fen = "3q4/8/8/7k/8/8/8/3RK3 w - - 0 1"
    assert guards(fen, "d8") == {"Rd1"}, "the queen must be undefended"
    board, move = verify(fen, "d1d8")
    assert see(board, move) == pytest.approx(9.0)


def test_see_counts_the_recapture():
    # Rxd5 wins a pawn but the rook is taken by the e6 pawn: 1 - 5.
    fen = "4k3/8/4p3/3p4/8/8/8/3R2K1 w - - 0 1"
    assert guards(fen, "d5") == {"Rd1", "pe6"}
    board, move = verify(fen, "d1d5")
    assert see(board, move) == pytest.approx(-4.0)


def test_see_knows_a_pinned_defender_cannot_recapture():
    # Same position plus a white rook on e1, which pins the e6 pawn to the king.
    # exd5 would leave the e-file open, so it is illegal and Rxd5 just wins a pawn.
    fen = "4k3/8/4p3/3p4/8/8/8/3RR1K1 w - - 0 1"
    assert guards(fen, "d5") == {"Rd1", "pe6"}, "the pawn still nominally defends"
    verify("4k3/8/4p3/3R4/8/8/8/4R1K1 b - - 0 1")
    assert chess.Move.from_uci("e6d5") not in chess.Board(
        "4k3/8/4p3/3R4/8/8/8/4R1K1 b - - 0 1"
    ).legal_moves, "but it is pinned, so the recapture is illegal"
    board, move = verify(fen, "d1d5")
    assert see(board, move) == pytest.approx(1.0)


def test_see_lets_a_side_decline_a_losing_recapture():
    # exd5 is available but loses the pawn for nothing, so SEE stops short.
    fen = "4k3/8/4p3/3n4/8/8/8/3RR1K1 w - - 0 1"
    assert guards(fen, "d5") == {"Rd1", "pe6"}
    board, move = verify(fen, "d1d5")
    assert see(board, move) == pytest.approx(3.0)


# ── rule 1: hangs_piece ──────────────────────────────────────────────────────

def test_hangs_piece_when_the_move_walks_into_an_attack():
    # Ng1-f3 steps onto the b7 bishop's diagonal, undefended.
    found = explained("4k3/1b6/8/8/8/8/8/4K1N1 w - - 0 1", "g1f3")
    hang = only(found, "hangs_piece")
    assert hang.material == pytest.approx(-3.0)
    assert hang.pieces[0].square == "f3"
    assert hang.pieces[0].piece == "N"
    assert hang.moves["refutation"].san == "Bxf3"


def test_a_piece_already_hanging_is_not_blamed_on_this_move():
    # The f3 knight has been en prise to Bb7 for some time. Moving the rook
    # elsewhere does not drop it -- it was already loose, and blaming this move
    # would point the reader at the wrong mistake.
    found = explained("4k3/1b6/8/8/8/5N2/8/R3K3 w - - 0 1", "a1a2")
    assert "hangs_piece" not in kinds(found)


def test_removing_a_defender_does_hang_the_piece_it_defended():
    # The g2 pawn is the only thing holding f3. Pushing it to g4 leaves the
    # knight free, and that IS this move's fault.
    found = explained("4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4")
    hang = only(found, "hangs_piece")
    assert hang.pieces[0].square == "f3"
    assert hang.material == pytest.approx(-3.0)


def test_a_defended_piece_is_not_hanging():
    # Same position, pawn stays home: Bxf3 gxf3 is an even trade, not a hang.
    found = explained("4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "e1e2")
    assert "hangs_piece" not in kinds(found)


def test_an_even_trade_is_not_a_hang():
    # exd5 Nxd5 is a pawn for a pawn. The recapture is part of the trade.
    fen = "4k3/8/5n2/3p4/4P3/8/8/4K3 w - - 0 1"
    assert guards(fen, "d5") == {"Pe4", "nf6"}, "the knight must really defend d5"
    found = explained(fen, "e4d5")
    assert "hangs_piece" not in kinds(found)


def test_a_losing_capture_is_a_hang():
    # Qxd5 grabs a pawn defended by the f6 knight and drops the queen.
    fen = "4k3/8/5n2/3p4/8/8/8/3QK3 w - - 0 1"
    assert guards(fen, "d5") == {"Qd1", "nf6"}
    found = explained(fen, "d1d5")
    hang = only(found, "hangs_piece")
    assert hang.material == pytest.approx(-8.0)


# ── rule 2: missed_material ──────────────────────────────────────────────────

def test_missed_material_names_what_was_available():
    found = explained("3q4/8/8/7k/8/8/8/3RK3 w - - 0 1", "d1d2", best_uci="d1d8")
    missed = only(found, "missed_material")
    assert missed.material == pytest.approx(9.0)
    assert missed.moves["best"].san == "Rxd8"
    assert missed.pieces[0].piece == "Q"


def test_no_missed_material_when_the_best_move_wins_nothing():
    found = explained("4k3/8/8/8/8/8/8/3RK3 w - - 0 1", "d1d2", best_uci="d1d8")
    assert "missed_material" not in kinds(found)


def test_no_missed_material_when_the_played_move_took_it():
    found = explained("3q4/8/8/7k/8/8/8/3RK3 w - - 0 1", "d1d8", best_uci="d1d8")
    assert "missed_material" not in kinds(found)


# ── rules 3 and 4: mate ──────────────────────────────────────────────────────

def test_missed_mate_is_proven_on_the_board():
    found = explained("6k1/5ppp/8/8/8/8/8/R3K2R w KQ - 0 1", "h1h7")
    mate = only(found, "missed_mate")
    assert mate.basis == "board"
    assert mate.mate_in == 1
    assert mate.moves["best"].san == "Ra8#"


def test_delivering_mate_is_not_a_missed_mate():
    found = explained("6k1/5ppp/8/8/8/8/8/R3K2R w KQ - 0 1", "a1a8")
    assert "missed_mate" not in kinds(found)
    assert "walks_into_mate" not in kinds(found)


def test_missed_mate_falls_back_to_the_stored_score():
    # No mate in one on the board, but the engine recorded mate in three.
    found = explained(
        "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d2", score_before_mate=3
    )
    mate = only(found, "missed_mate")
    assert mate.basis == "engine"
    assert mate.mate_in == 3


def test_playing_the_mate_yourself_is_not_a_missed_mate():
    # Mate in three was on and the move played is the engine's own choice. It
    # took the mate; there is nothing to report.
    found = explained(
        "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d2",
        best_uci="d1d2", score_before_mate=3,
    )
    assert "missed_mate" not in kinds(found)


def test_a_slower_mate_is_not_a_missed_mate():
    # Mate was available before and is still available after. The mover picked
    # a different route, not a worse move.
    found = explained(
        "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d2",
        score_before_mate=3, score_after_mate=4,
    )
    assert "missed_mate" not in kinds(found)


def test_being_mated_already_is_not_blamed_on_this_move():
    # The mover was getting mated in two before they moved. Whatever they
    # played, they were lost; this move did not walk into anything.
    found = explained(
        "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d2",
        score_before_mate=-2, score_after_mate=-1,
    )
    assert "walks_into_mate" not in kinds(found)


def test_walks_into_mate_is_proven_on_the_board():
    # Ra7 abandons the back rank and Re1 is mate.
    found = explained("4r1k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a7")
    mate = only(found, "walks_into_mate")
    assert mate.basis == "board"
    assert mate.mate_in == 1
    assert mate.moves["refutation"].san == "Re1#"


def test_walks_into_mate_falls_back_to_the_stored_score():
    found = explained(
        "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d2", score_after_mate=-4
    )
    mate = only(found, "walks_into_mate")
    assert mate.basis == "engine"
    assert mate.mate_in == 4


# ── rule 7: what the best move does instead ──────────────────────────────────

def test_best_move_defending_the_piece_is_reported():
    found = explained(
        "4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4", best_uci="e1f2"
    )
    saved = only(found, "best_defends_piece")
    assert saved.subject == "best"
    assert saved.pieces[0].square == "f3"
    assert saved.moves["best"].san == "Kf2"


def test_best_move_moving_the_piece_to_safety_is_reported():
    found = explained(
        "4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4", best_uci="f3e5"
    )
    saved = only(found, "best_saves_piece")
    assert saved.pieces[0].square == "e5"


def test_the_square_the_played_move_captured_on_is_never_defended():
    """A real ply. Nxf5 hangs the knight, and the rule used to read f5 off the
    board *before* the capture and report "b3 would have defended the pawn on
    f5" — the pawn being the black one Nxf5 had just taken. 44.0 % of this
    rule's findings over the stored corpus were this."""
    found = explained(
        "rnb1k2r/2q1n1pp/p2b4/1p2pp2/7N/2NB4/PPPP1PPP/R1BQ1RK1 w kq - 0 10",
        "h4f5", best_uci="b2b3",
    )
    assert only(found, "hangs_piece").pieces[0].square == "f5"
    assert [f for f in found if f.kind == "best_defends_piece"] == []


def test_a_piece_already_loose_gets_neither_a_hang_nor_a_rescue():
    """After 1.e4 e5 2.Nf3, e5 is attacked and undefended — which is why 2...Nc6
    exists. Black plays 2...d5 instead.

    Rule 1 already declined, because the pawn was not dropped by d5. The rescue
    rules read the same `exposed` map without that filter, so the block rendered as
    "Nc6 would have defended the pawn on e5" with no sentence saying e5 was in
    trouble at all. Measured on the emitted sentences: 6284 of 25 607 blocks, 24.5 %.

    This exact ply is where the audit sample surfaced it.
    """
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    assert guards(fen, "e5") == {"Nf3"}  # attacked once, defended not at all
    found = explained(fen, "d7d5", best_uci="b8c6")
    assert [f.kind for f in found if f.kind.startswith(("hangs", "best_"))] == []


# ── ignored_threat ───────────────────────────────────────────────────────────
#
# Rule 12: a piece already loose, left loose by the played move, when the best
# move would have dealt with it. EXPLANATIONS.md, "`ignored_threat`".

# Game 285 ply 23, 12...h5, read out of `move_analyses`. The knight on c5 has been
# attacked by d4 since 11.d4; rule 1 correctly declines it, and before this rule
# the ply was silent on a 3.6-pawn drop.
H5_ROW = {
    "fen_before": "r1bq1k1r/1pp1b1pp/p2p1p2/2n5/3P4/1B3Q2/PPP1RPPP/RNB3K1 b - - 1 12",
    "played_uci": "h7h5",
    "best_uci": "c5b3",
    "classification": "blunder",
    "score_before_cp": -121,
    "score_before_mate": None,
    "score_after_cp": -481,
    "score_after_mate": None,
}


def test_ignored_threat_fires_on_game_285_ply_23():
    """The required case. The best move is 12...Nxb3, the knight trading itself
    for the bishop — which is also why clause 3 is read on c5 and not on b3,
    where axb3 recaptures: a piece that leaves by an even trade was rescued."""
    found = explain_stored_ply(H5_ROW)
    assert "hangs_piece" not in kinds(found)
    threat = only(found, "ignored_threat")
    assert threat.pieces[0].square == "c5"
    assert threat.pieces[0].piece == "N"
    assert threat.moves["refutation"].san == "dxc5"
    assert threat.material == pytest.approx(-2.0)


def test_ignored_threat_needs_the_best_move_to_have_saved_the_piece():
    """Clause 3 is mandatory: with a best move that leaves c5 loose too, no move
    on record rescued the knight, so this one cannot be blamed for not doing so."""
    found = explained(H5_ROW["fen_before"], "h7h5", best_uci="a8b8")
    assert "ignored_threat" not in kinds(found)


def test_ignored_threat_needs_a_best_move():
    found = explained(H5_ROW["fen_before"], "h7h5")
    assert "ignored_threat" not in kinds(found)


def test_the_engines_own_move_never_ignores_a_threat():
    found = explained(H5_ROW["fen_before"], "c5b3", best_uci="c5b3")
    assert "ignored_threat" not in kinds(found)


def test_a_counterattack_answers_the_threat_so_nothing_was_ignored():
    """The 2...d5 ply above. e5 is loose before and after, and Nc6 would have
    defended it — but 2...d5 attacks e4, so 3.Nxe5 is met by ...dxe4 and wins
    nothing. The tempo gate (`_holds_after_reply`) sees the counter-capture that
    `_survives_reply` discounts as "already loose".

    Checked with Stockfish at depth 20: after 3.Nxe5 the line is ...Bd6 d4 dxe4 —
    material level; 2...d5 costs about half a pawn (+0.88 against +0.39 after
    2...Nc6), which is positional, not the pawn this rule would have claimed."""
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    found = explained(fen, "d7d5", best_uci="b8c6")
    assert "ignored_threat" not in kinds(found)


def test_a_threat_the_opponent_has_no_time_for_is_not_named():
    """Game 285 ply 21, 11...d6: the knight on c5 is loose, but d6 attacks the rook
    on e5, so White never has time for dxc5 — the game went 12.Re2. The capture is
    answered by ...dxe5, which `_survives_reply` discounted as "already loose" and
    `_holds_after_reply` counts (EX-IT-T, EX-TEMPO)."""
    fen = "r1bq1k1r/1pppb1pp/p4p2/2n1R3/3P4/1B3Q2/PPP2PPP/RNB3K1 b - - 0 11"
    found = explained(fen, "d7d6", best_uci="c5b3")
    assert "ignored_threat" not in kinds(found)


def test_a_counter_grab_of_a_defended_pawn_does_not_refute_a_pawn_claim():
    """Why `_holds_after_reply` lets the capturer recapture on the reply's square.

    Rxd5 wins a pawn. Black's only counter is Rxa2, and a2 is defended by the rook on
    a1. Cashing only on the capture square — the motifs' rule applied literally —
    reads Rxd5 Rxa2 as level and refutes the claim; that over-suppression removed
    46.9 % of `hangs_piece`, 40.7 % of it still captured on the next ply."""
    fen = "r5k1/8/8/3p4/8/8/P7/R2R2K1 w - - 0 1"
    board, _ = verify(fen, "d1d5")
    assert guards(fen, "a2") == {"Ra1", "ra8"}
    capture = chess.Move.from_uci("d1d5")
    assert see(board, capture) == pytest.approx(1.0)
    assert _holds_after_reply(board, capture, 1.0) == pytest.approx(1.0)


# Game 5 ply 32, 17.Qf3: drops the queen on f3 *and* leaves the knight on d6, which
# Nc4 would have saved. Both rules fire on the one ply, on different squares.
BOTH_FEN = "3r1rk1/4n1pp/2qN4/4p3/8/8/PPPP1PPP/R1BQ1RK1 w - - 1 17"


@pytest.mark.parametrize("fen, uci, best", [
    (BOTH_FEN, "d1f3", "d6c4"),
    (H5_ROW["fen_before"], "h7h5", "c5b3"),
    ("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2", "d7d5", "b8c6"),
    ("4k3/1b6/8/8/8/8/8/4K1N1 w - - 0 1", "g1f3", "g1e2"),
    ("4k3/1b6/8/8/8/5N2/8/R3K3 w - - 0 1", "a1a2", "f3d4"),
])
def test_ignored_threat_and_hangs_piece_never_share_a_square(fen, uci, best):
    """Disjoint by construction — rule 1 requires the square out of `baseline`
    and rule 12 requires it in. Pinned so a change to either cannot quietly
    make one ply say both "drops" and "left hanging" about one piece."""
    found = explained(fen, uci, best_uci=best)

    def squares(kind):
        return {p.square for f in found if f.kind == kind for p in f.pieces}

    assert not squares("hangs_piece") & squares("ignored_threat")


def test_one_ply_can_drop_one_piece_and_ignore_another():
    found = explained(BOTH_FEN, "d1f3", best_uci="d6c4")
    assert {p.square for f in found if f.kind == "hangs_piece" for p in f.pieces} == {
        "f3", "c2"}
    assert only(found, "ignored_threat").pieces[0].square == "d6"


# ── no engine is required ────────────────────────────────────────────────────

def test_explanations_need_no_engine():
    """Stockfish may simply not be installed, and the fresh-install audit showed
    that is a real state. Nothing here may depend on a live search: every rule
    runs off the board plus the scores already stored for the ply."""
    import inspect

    assert "engine" not in inspect.signature(explain_ply).parameters

    for fen, uci in [
        ("6k1/5ppp/8/8/8/8/8/R3K2R w KQ - 0 1", "h1h7"),
        ("4r1k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a7"),
        ("4k3/8/5n2/3p4/8/8/8/3QK3 w - - 0 1", "d1d5"),
        ("4k3/1b6/8/8/8/5N2/6P1/4K3 w - - 0 1", "g2g4"),
    ]:
        assert explained(fen, uci), f"no findings for {uci}"


# ── input handling and shape ─────────────────────────────────────────────────

def test_illegal_or_unparseable_input_yields_nothing():
    assert explain_ply("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "a1a8") == []
    assert explain_ply("not a fen", "e2e4") == []
    assert explain_ply(chess.STARTING_FEN, "zzzz") == []


def test_a_quiet_move_in_a_quiet_position_says_nothing():
    assert explained("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e2") == []


def test_findings_serialize_to_json_safe_dicts():
    import json

    found = explained("4k3/1b6/8/8/8/8/8/4K1N1 w - - 0 1", "g1f3")
    payload = [f.to_dict() for f in found]
    assert json.loads(json.dumps(payload)) == payload
    assert payload[0]["moves"]["refutation"]["san"] == "Bxf3"
    assert payload[0]["ruleVersion"] == RULE_VERSION


def test_ranking_puts_mate_first_then_what_happened_then_what_was_offered():
    """`missed_material` carries the larger material and still ranks below the
    hang, because the hang is on the board and the 9 pawns are hypothetical.

    It carries `subject="played"` — it is a finding about the played move — so
    ordering on `subject` alone put it in the same tier as the hang and let
    material decide, which told a player who dropped a knight about a rook they
    never won. `NAMES_MOVE` is the field that separates them.
    """
    findings = [
        Finding(kind="best_defends_piece", subject="best", basis="see"),
        Finding(kind="hangs_piece", subject="played", basis="see", material=-3.0),
        Finding(kind="missed_material", subject="played", basis="see", material=-9.0),
        Finding(kind="walks_into_mate", subject="played", basis="board", mate_in=2),
    ]
    assert [f.kind for f in rank_findings(findings)] == [
        "walks_into_mate",
        "hangs_piece",
        "missed_material",
        "best_defends_piece",
    ]


def test_material_still_orders_findings_inside_one_tier():
    """The tier split must not cost the within-tier ordering: two real losses
    still report the bigger one first."""
    findings = [
        Finding(kind="hangs_piece", subject="played", basis="see", material=-1.0),
        Finding(kind="hangs_piece", subject="played", basis="see", material=-5.0),
    ]
    assert [f.material for f in rank_findings(findings)] == [-5.0, -1.0]


def test_mate_findings_rank_by_how_forced_they_are():
    findings = [
        Finding(kind="walks_into_mate", subject="played", basis="engine", mate_in=5),
        Finding(kind="missed_mate", subject="played", basis="board", mate_in=1),
    ]
    assert [f.mate_in for f in rank_findings(findings)] == [1, 5]


# ── stage 2: fork, pin and skewer ────────────────────────────────────────────
#
# The required cases from EXPLANATIONS.md, plus real plies from the stored
# database so the set is not all bare endgames. Every delta below was produced
# by playing the line out with Stockfish, never read off the board -- three of
# the original required positions were wrong precisely because they were read
# off the board.

MOTIFS = ("fork", "pin", "skewer", "discovered_attack", "trapped_piece")
# `pin` is only ever asserted absent; it is not a shipped kind.


def motifs(fen, uci, subject="played", **kwargs):
    return {
        f.kind: f
        for f in explained(fen, uci, **kwargs)
        if f.kind in MOTIFS and f.subject == subject
    }


def test_queen_forks_king_and_loose_knight():
    """Requirement (a). The old rule could not see this: a queen was allowed to
    fork only another queen, so the commonest double attack in chess was
    structurally invisible."""
    found = motifs("6k1/8/8/n7/8/8/8/3QK3 w - - 0 1", "d1d5")
    assert set(found) == {"fork"}
    assert found["fork"].material == pytest.approx(3.0)
    # The piece that actually falls leads, so a renderer naming one names right.
    assert (found["fork"].pieces[0].piece, found["fork"].pieces[0].square) == ("N", "a5")


def test_rook_check_wins_the_bishop_behind_it():
    """Bishop on b8 and king on g8 lie on opposite sides of e8, so this is a
    double attack along the rank, not a skewer: nothing is behind anything."""
    found = motifs("1b4k1/8/8/8/8/8/8/4RK2 w - - 0 1", "e1e8")
    assert set(found) == {"fork"}
    assert found["fork"].material == pytest.approx(3.0)
    assert found["fork"].pieces[0].square == "b8"


def test_fork_fires_on_material_the_engine_scores_as_lost():
    """Requirement (a) in one position. `Nc7+` wins a rook and Stockfish scores
    it -20, because K+R vs K is drawn. A centipawn test fails this and a
    material test passes it -- which is why this layer counts material."""
    found = motifs("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", "b5c7")
    assert set(found) == {"fork"}
    assert found["fork"].material == pytest.approx(5.0)
    assert found["fork"].pieces[0].square == "a8"


def test_queen_forks_king_and_rook():
    found = motifs("7k/8/8/8/8/8/1r6/3QK3 w - - 0 1", "d1d4")
    assert set(found) == {"fork"}
    assert found["fork"].material == pytest.approx(5.0)


def test_real_game_skewer_wins_the_rook_behind_the_king():
    """From the owner's stored plies. `Rxb8+` and the king must step off the
    back rank, abandoning the rook on g8 behind it."""
    fen = "Rn1k2r1/4ppbp/2p3p1/2N1P2n/8/5N1P/3BBPP1/6K1 w - - 3 27"
    found = motifs(fen, "a8b8")
    assert set(found) == {"skewer"}
    assert found["skewer"].material == pytest.approx(5.0)


def test_pin_is_not_a_shipped_motif():
    """Pin was implemented, measured and dropped. It pays off by *constraint* --
    the pinned piece cannot move -- and the material arrives later or never, so
    a two-ply material minimax cannot measure it. It produced 32 findings in
    157 178 stored plies, too few for the class-gradient test to resolve.

    Both positions below are real pins from the owner's games: `Rd1` pins the
    d4 knight against the king on d5, and `Rxc1` pins the b1 knight against the
    a1 rook. The geometry is genuinely there and the layer says nothing.
    """
    for fen, uci in (
        ("8/8/8/3k4/3n4/2K1p1P1/8/5R2 w - - 0 52", "f1d1"),
        ("7k/pp4pp/3p1n2/8/8/8/PPb2PPP/RNB1rBK1 b - - 3 20", "e1c1"),
    ):
        assert motifs(fen, uci) == {}


def test_a_pin_shaped_ray_is_never_reported_as_a_skewer():
    """The discarded pin shape still has to be *matched*, or a pin falls through
    to the skewer branch and gets reported as the opposite motif: a cheap piece
    shielding a dear one is a pin, a dear one shielding a cheap one a skewer."""
    found = motifs("8/8/8/3k4/3n4/2K1p1P1/8/5R2 w - - 0 52", "f1d1")
    assert "skewer" not in found


def test_one_square_yields_one_motif():
    """`Qc7+` attacks the king and the e7 bishop, and also lines that bishop up
    in front of the f7 pawn along the rank. Fork and skewer are both true and
    both win the same bishop; two of three render slots on one tactic is noise,
    so the square keeps one finding."""
    fen = "r2k4/pp2bp2/8/3NQ2r/3P2p1/2P5/PP5P/R3KB1R w KQ - 0 24"
    found = motifs(fen, "e5c7")
    assert set(found) == {"fork"}
    assert found["fork"].pieces[0].square == "e7"


# The refutations. Each fails for a different reason, which is why all six are
# worth keeping.


def test_geometric_fork_is_ignored_when_the_counter_threat_is_bigger():
    """The Nb2 case, from the owner's own games. A real double attack on both
    rooks that loses five pawns: White answers `Rxd7` and never saves either."""
    assert motifs("3r2k1/p2r1ppp/8/8/2R5/2Pn3P/P4PP1/3R2K1 b - - 0 25", "d3b2") == {}


def test_no_fork_when_the_recapturing_rook_is_pinned():
    """Requirement (b). SEE resolves exchanges through legal moves, so an
    absolutely pinned defender correctly cannot recapture."""
    assert motifs("r3k3/8/n7/1N6/8/8/8/r1R1K3 w - - 0 1", "b5c7") == {}


def test_no_fork_with_two_attackers_against_one_defender():
    assert motifs("r3k3/8/n7/1N1n4/8/8/8/2R1K3 w - - 0 1", "b5c7") == {}


def test_no_fork_when_the_check_can_be_interposed():
    """`1...Rf7` blocks the d5-g8 diagonal and saves the rook with tempo."""
    assert motifs("6k1/1r6/8/8/8/8/8/3QK3 w - - 0 1", "d1d5") == {}


def test_no_fork_when_the_defender_counter_forks_with_check():
    """`1...Nce4 2.Ke2 Nc3+ 3.Kd3 Nxd5` -- measured -5, not the +3 claimed."""
    assert motifs("4k3/8/8/2n3n1/8/8/8/3RK3 w - - 0 1", "d1d5") == {}
    # Same defence class one rank down, so it is a regression guard, not a case.
    assert motifs("4k3/8/8/8/1n3n2/8/8/3RK3 w - - 0 1", "d1d4") == {}


def test_no_fork_when_a_zwischenzug_check_intervenes():
    """`1...Rbe5+ 2.Kd2 Rd5 3.Kc3 Rxd3+ 4.Kxd3` -- measured -4."""
    assert motifs("4k3/8/8/1r3r2/8/8/8/3QK3 w - - 0 1", "d1d3") == {}


def test_recapture_is_not_a_won_piece():
    """Material is counted from after the move, not before it. Counted from
    before, every recapture restoring the balance reads as winning a piece;
    measured against stored plies that way, 54.6 % of firings had the engine's
    own evaluation fall while the rule claimed material.

    `Rxd4` really does win five pawns relative to the position before it, and
    really does attack two enemy pieces from d4. Both are defended, so the move
    wins nothing *subsequently*, which is the only thing a motif may claim.
    """
    fen = "7k/8/8/1p5p/n2r2b1/8/8/3RK3 w - - 0 1"
    board, move = verify(fen, "d1d4")
    assert see(board, move) == pytest.approx(5.0), "the recapture is worth a rook"
    after = board.copy()
    after.push(move)
    attacked = {
        chess.square_name(s)
        for s in after.attacks(move.to_square)
        if after.color_at(s) is chess.BLACK
    }
    assert attacked == {"a4", "g4"}, "and the geometry really does propose a fork"
    assert motifs(fen, "d1d4") == {}


def test_mate_is_not_a_material_claim():
    """Stage 1's `missed_mate` owns mate, so this layer stays quiet on it.
    Scoring a position with no legal replies as a huge material win made every
    mating fork look like a motif as well as a mate.

    `Qg7#` is a genuine three-way geometric fork -- rook, knight and king -- so
    the silence here is the mate guard and not an absence of geometry.
    """
    fen = "5r1k/7n/8/8/6Q1/8/8/6RK w - - 0 1"
    board, move = verify(fen, "g4g7")
    after = board.copy()
    after.push(move)
    assert after.is_checkmate()
    attacked = {
        chess.square_name(s)
        for s in after.attacks(move.to_square)
        if after.color_at(s) is chess.BLACK
    }
    assert attacked == {"f8", "h7", "h8"}, "the geometry proposes a fork"
    assert motifs(fen, "g4g7") == {}


def test_a_missed_motif_is_attributed_to_the_best_move():
    """The tactic on offer, on a move the player did not make. `subject` is the
    whole found-versus-missed distinction: stage 3 renders `played` as found."""
    fen = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
    found = motifs(fen, "e1e2", subject="best", best_uci="b5c7")
    assert set(found) == {"fork"}
    assert found["fork"].moves["best"].san == "Nc7+"
    assert motifs(fen, "e1e2", subject="played", best_uci="b5c7") == {}


def test_a_found_tactic_is_never_reported_twice():
    """When the played move is the best move the motif rules run once, under
    subject="played". Measured over all 157 178 stored plies, subject="best"
    with played_uci == best_uci occurs zero times."""
    fen = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
    found = [f for f in explained(fen, "b5c7", best_uci="b5c7") if f.kind in MOTIFS]
    assert [f.subject for f in found] == ["played"]


# ── stage 2: discovered attack ───────────────────────────────────────────────
#
# All four positions below are real plies from the owner's games except the
# last, which is constructed to isolate one clause. Geometry alone proposes a
# discovery on about 6 % of moves and is flat across classifications (3.3 % to
# 9.9 %), so as with fork the material test does all of the deciding.


def test_discovered_check_lets_the_moved_piece_collect():
    """`Bg4+` is check from the rook on e1, not from the bishop: vacating e6
    opened the e-file onto the king. The bishop is then free to take the h5
    knight, because the opponent's only legal moves answer the check."""
    fen = "rr6/pp2k3/2p1B2p/6pn/3P4/2N2P1P/PPP3K1/R3R3 w - - 0 25"
    found = motifs(fen, "e6g4")
    assert set(found) == {"discovered_attack"}
    assert found["discovered_attack"].material == pytest.approx(3.0)
    assert (
        found["discovered_attack"].pieces[0].piece,
        found["discovered_attack"].pieces[0].square,
    ) == ("N", "h5")
    # No opened line reaches h5 -- the bishop that moved is what attacks it. A
    # sentence saying "opens a line onto the knight on h5" would be false, so the
    # branch is recorded here for the renderer rather than left for it to guess.
    assert found["discovered_attack"].pattern == PATTERN_DISCOVERED_CHECK


def test_the_discovered_piece_can_be_the_one_that_wins_the_material():
    """The mirror image. `Nd3+` is a direct check from the knight, and the
    discovery is the d6 bishop unmasked onto the queen on f4. Here the moved
    piece checks and the *unmasked* piece collects."""
    fen = "r1bqk2r/pppp1ppp/3b1n2/4n3/4NQ2/8/PPPP1PPP/R1B1KBNR b KQkq - 1 7"
    found = motifs(fen, "e5d3")
    assert set(found) == {"discovered_attack"}
    assert found["discovered_attack"].pieces[0].square == "f4"
    assert found["discovered_attack"].material == pytest.approx(6.0)
    # The bishop unmasked onto f4 is what wins the queen, so here the opened line
    # really does reach the piece that falls and the plain sentence is true.
    assert found["discovered_attack"].pattern == PATTERN_DISCOVERED_LINE


def test_discovered_check_wins_a_rook_in_an_endgame():
    """`Nc7+` uncovers the d6 rook along the sixth rank onto the king on g6,
    and the knight takes the rook on a6 while the check is being answered."""
    found = motifs("8/8/rB1RN1kp/5p2/5P2/5K2/8/8 w - - 6 49", "e6c7")
    assert set(found) == {"discovered_attack"}
    assert found["discovered_attack"].material == pytest.approx(5.0)
    assert found["discovered_attack"].pieces[0].square == "a6"
    # The unmasked rook checks along the sixth rank; the knight that moved is what
    # takes on a6. Same shape as the `Bg4+` case, in an endgame.
    assert found["discovered_attack"].pattern == PATTERN_DISCOVERED_CHECK


def test_every_discovered_attack_says_which_branch_it_proved():
    """The renderer reads `pattern` and must never have to recompute geometry.

    A template that works the branch out for itself can disagree with the rule
    that proved the material, and then the layer holds two answers with no way to
    pick. So the field is not optional: a `discovered_attack` with `pattern` unset
    would silently take whichever sentence the renderer defaults to.
    """
    branches = {
        "rr6/pp2k3/2p1B2p/6pn/3P4/2N2P1P/PPP3K1/R3R3 w - - 0 25": ("e6g4", None),
        "r1bqk2r/pppp1ppp/3b1n2/4n3/4NQ2/8/PPPP1PPP/R1B1KBNR b KQkq - 1 7": ("e5d3", None),
        "8/8/rB1RN1kp/5p2/5P2/5K2/8/8 w - - 6 49": ("e6c7", None),
    }
    seen = set()
    for fen, (uci, _) in branches.items():
        for f in explained(fen, uci):
            if f.kind != "discovered_attack":
                continue
            assert f.pattern in (PATTERN_DISCOVERED_LINE, PATTERN_DISCOVERED_CHECK)
            seen.add(f.pattern)
    assert seen == {PATTERN_DISCOVERED_LINE, PATTERN_DISCOVERED_CHECK}, (
        "the three positions must exercise both branches, or this test proves "
        "nothing about the one it missed"
    )


def test_a_discovery_that_is_not_check_does_not_lend_its_targets():
    """The clause that keeps this rule honest.

    `Nf5` opens the d-file from the rook onto the queen, so the geometry really
    does propose a discovery -- but it is not check, so Black is free to deal
    with it by moving the queen. The knight also attacks the rook on h6, and
    that material is *not* the discovery's doing, so it must not be credited
    here. Only a discovered **check** forces the opponent to leave the moved
    piece alone, and only then are its targets counted.
    """
    fen = "3q3k/8/7r/8/3N4/8/8/2KR4 w - - 0 1"
    board, move = verify(fen, "d4f5")
    after = board.copy()
    after.push(move)
    assert not after.is_check(), "the discovery does not check"
    assert "h6" in {
        chess.square_name(s)
        for s in after.attacks(move.to_square)
        if after.color_at(s) is chess.BLACK
    }, "and the moved knight really does attack the rook"
    assert motifs(fen, "d4f5") == {}


# ── stage 2: the back-rank annotation ────────────────────────────────────────
#
# Back-rank is not a claim of its own. It annotates a mate this layer has
# already proved by playing it, and says why the king had no square: its own
# pawns. So every test below first asserts the mate finding is there, then
# asserts what the annotation does or does not say about it.


def annotated(fen, uci, kind, **kwargs):
    """The board-proved mate finding of `kind`, with its pattern and pawns."""
    found = only([f for f in explained(fen, uci, **kwargs) if f.kind == kind], kind)
    assert found.basis == "board", "the annotation only applies to a proved mate"
    return found.pattern, [p.square for p in found.pieces]


def test_back_rank_annotates_a_mate_that_was_missed():
    """A real ply. `Qd1` declines `Rxe1#`, and the mate works only because
    White's own f2, g2 and h2 pawns leave the king on g1 nowhere to go."""
    pattern, pawns = annotated(
        "4r1k1/p4p1p/2p2p2/2p5/8/8/P1P2PPP/1q2Q1K1 b - - 3 24", "b1d1", "missed_mate"
    )
    assert pattern == "back_rank"
    assert pawns == ["f2", "g2", "h2"]


def test_back_rank_annotates_a_mate_that_was_walked_into():
    """A real ply, and the commoner direction by a wide margin -- 52 of the 53
    walked-into back-rank annotations in the corpus are on blunders. `Rd1`
    abandons the first rank and `Qxd1#` follows."""
    pattern, pawns = annotated(
        "3r4/p1k4p/3q2p1/2p2p2/4p3/8/PPP2PPP/4R1K1 w - - 0 24", "e1d1",
        "walks_into_mate",
    )
    assert pattern == "back_rank"
    assert pawns == ["f2", "g2", "h2"]


def test_a_king_in_the_corner_is_boxed_in_by_two_pawns_not_three():
    """`Rxc5` lets `Re8#` in. The king is on h8, so only g7 and h7 exist to be
    blocked, and the annotation must not require a phantom third pawn off the
    edge of the board."""
    pattern, pawns = annotated(
        "2r4k/6pp/p7/2B2b2/6n1/N7/PPP2PPP/R3R1K1 b - - 0 20", "c8c5",
        "walks_into_mate",
    )
    assert pattern == "back_rank"
    assert pawns == ["g7", "h7"]


def test_a_mate_away_from_the_back_rank_is_not_annotated():
    """A real ply. `Rh1` allows `Rf5#` with the black king on g5, in the middle
    of the board. The mate is proved and reported; the annotation stays quiet."""
    pattern, pawns = annotated(
        "8/8/R6P/2p3k1/p5P1/P4RK1/5P2/2r5 b - - 0 43", "c1h1", "walks_into_mate"
    )
    assert pattern is None
    assert pawns == []


def test_the_fools_mate_is_on_the_back_rank_but_is_not_a_back_rank_mate():
    """`g4` allows `Qh4#`. The king is on e1 on its own back rank, but f2 is
    empty -- the pawn that would have blocked it is the one that just moved to
    f3 -- so the king's own pawns are not the reason it is stuck, and saying so
    would teach the wrong lesson about a two-move opening blunder."""
    pattern, pawns = annotated(
        "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2", "g2g4",
        "walks_into_mate",
    )
    assert pattern is None
    assert pawns == []


def test_an_escape_square_covered_rather_than_blocked_is_not_annotated():
    """The narrowness that keeps the annotation honest. `Rd1` declines `Re8#`,
    which mates because the b2 bishop covers g7 -- g7 is empty, not blocked.
    The pawns are not the whole reason, so a sentence about the pawns would be
    false, and widening the test to catch this would buy volume with accuracy.
    """
    fen = "6k1/5p1p/8/8/8/8/1B6/4R1K1 w - - 0 1"
    board, _ = verify(fen, "e1d1")
    mated = board.copy()
    mated.push(chess.Move.from_uci("e1e8"))
    assert mated.is_checkmate(), "Re8 really is mate"
    assert mated.piece_at(chess.G7) is None, "and g7 is empty, not blocked"
    assert chess.B2 in mated.attackers(chess.WHITE, chess.G7), "the bishop covers it"

    pattern, pawns = annotated(fen, "e1d1", "missed_mate")
    assert pattern is None
    assert pawns == []


def test_the_annotation_survives_the_json_round_trip():
    """`pattern` is a new field on `Finding`, so the wire shape needs asserting
    alongside the others rather than after the sidecar disagrees with it."""
    findings = explained(
        "3r4/p1k4p/3q2p1/2p2p2/4p3/8/PPP2PPP/4R1K1 w - - 0 24", "e1d1"
    )
    wire = only(findings, "walks_into_mate").to_dict()
    assert wire["pattern"] == "back_rank"
    assert wire["ruleVersion"] == RULE_VERSION
    assert [p["square"] for p in wire["pieces"]] == ["f2", "g2", "h2"]


# ── stage 2: trapped piece ───────────────────────────────────────────────────
#
# Every position here is a real ply from the owner's games, and the three
# negative cases are not hypotheticals: each one *would* prove the material
# floor if its guard were removed, which is how they were selected. Trapped
# piece is the first rule shipped under the stop-and-report threshold rather
# than over it -- see EXPLANATIONS.md.


def test_the_king_walks_up_and_the_knight_has_nowhere_to_go():
    """`Kf2` attacks the e2 knight, and all six squares it can reach are covered
    by the pawn chain and the rook. Nothing else on the board changed, so the
    knight is lost to this move and no earlier one."""
    found = motifs("8/pp5p/8/1k3P2/8/2P2PP1/PP2n2P/3R2K1 w - - 1 29", "g1f2")
    assert set(found) == {"trapped_piece"}
    assert found["trapped_piece"].material == pytest.approx(2.0)
    assert found["trapped_piece"].basis == "see"
    # The finding names the trapped piece and only it. The squares it could run
    # to are empty or hold one of *white's* pieces, so naming them would put the
    # mover's own men in a finding about the opponent's loss.
    assert [(p.piece, p.square, p.color) for p in found["trapped_piece"].pieces] == [
        ("N", "e2", "black")
    ]


def test_the_bishop_in_the_corner_is_trapped_by_a_rook_on_the_seventh():
    """`Ra7` takes b7 away from the a8 bishop, which has no other square. The
    textbook shape, and the one that most needs naming: 'wins a bishop' does not
    tell the player that the bishop was stuck in the corner."""
    found = motifs("b4k2/4R3/p1p2p2/1p3N2/5P2/2P3PB/PP5P/2K5 w - - 7 30", "e7a7")
    assert set(found) == {"trapped_piece"}
    assert found["trapped_piece"].material == pytest.approx(3.0)
    assert found["trapped_piece"].pieces[0].square == "a8"


def test_a_knight_on_the_rim_is_trapped_by_a_queen():
    """`Qg4` covers g3, f4 and g7 at once, which are every square the h5 knight
    has."""
    fen = "r1bqk2r/ppppb2p/5p2/7n/4Q3/2N5/PPP2PPP/R1B1KB1R w KQkq - 2 10"
    found = motifs(fen, "e4g4")
    assert set(found) == {"trapped_piece"}
    assert found["trapped_piece"].material == pytest.approx(3.0)
    assert found["trapped_piece"].pieces[0].square == "h5"


def test_a_trap_can_be_a_tactic_the_player_missed():
    """Attribution by subject works the same here as for fork: `Bxg7` traps the
    h8 rook, which has no square at all, and the player did not play it."""
    fen = "r3k1nr/ppp3pp/2n5/8/3B4/P1P2N2/2P2P1P/R3K2R w KQkq - 1 17"
    found = motifs(fen, "e1e2", subject="best", best_uci="d4g7")
    assert set(found) == {"trapped_piece"}
    assert found["trapped_piece"].moves["best"].san == "Bxg7"
    assert found["trapped_piece"].pieces[0].square == "h8"


def test_a_checking_move_does_not_trap_everything_it_attacks():
    """The artefact that was 65 % of this rule's first measurement. Under check
    only evasions are legal, so White's queen on d2 has no legal move and reads
    as having nowhere safe to go -- and the material test then happily agrees
    that a queen falls. It is a check, not a trap."""
    fen = "r1b2k2/2p5/3p1q2/p3p3/P2nPP2/3P4/2PQ1P1P/R4RK1 b - - 0 21"
    board, move = verify(fen, "d4f3")
    after = board.copy()
    after.push(move)
    assert after.is_check(), "Nf3+ is check, which is why the queen cannot move"
    assert not any(m.from_square == chess.D2 for m in after.legal_moves)

    assert "trapped_piece" not in motifs(fen, "d4f3")


def test_an_absolutely_pinned_piece_is_not_called_trapped():
    """36.2 % of findings before this guard. The e6 bishop cannot move because it
    is pinned against the e7 king by the rook on e3, not because every square is
    covered. Pin is the one mechanism this layer decided it cannot express, so
    reporting this as a trap would name the wrong thing."""
    fen = "rn5r/p3k2p/2p1b1p1/5p2/Pp2N2N/1B2R3/1PP2BPP/4K2R w - - 0 23"
    board, move = verify(fen, "e4c5")
    after = board.copy()
    after.push(move)
    assert after.is_pinned(chess.BLACK, chess.E6)

    assert "trapped_piece" not in motifs(fen, "e4c5")


def test_a_piece_that_was_already_trapped_is_not_blamed_on_this_move():
    """The newness guard, load-bearing here as it was in stage 1. The f8 bishop
    is walled in by its own pawns and was just as stuck before `Rdf7` as after,
    so the rook does not get the credit."""
    fen = "5bk1/3R2p1/2p1p2p/2PpP3/3P2pP/8/8/5RK1 w - - 0 44"
    board, move = verify(fen, "d7f7")
    passed = board.copy()
    passed.push(chess.Move.null())
    assert chess.F8 in _boxed_in(passed, chess.WHITE), "already trapped beforehand"

    assert "trapped_piece" not in motifs(fen, "d7f7")


def test_a_king_with_no_safe_square_is_mates_business_not_a_trap():
    """The geometry at unit level, on a position that makes both halves visible.

    Black is in check from `Nf6`, the king on g8 is attacked, and both squares it
    could use are covered by the g6 knight -- so it is attacked with nowhere safe
    to go, the literal definition. It is still not named, because a king with no
    square is check and mate's business and they have their own basis.

    The a8 rook *is* named, and that is the check artefact in miniature: the only
    legal move in the position is `gxf6`, so the rook has no move either. That is
    why `_trapped_candidates` throws the whole position away when the move gives
    check."""
    board = chess.Board("r5k1/5ppp/5NN1/8/8/8/8/R5K1 b - - 0 1")
    assert board.is_valid() and board.is_check() and not board.is_checkmate()
    assert [m.uci() for m in board.legal_moves] == ["g7f6"]

    king = board.king(chess.BLACK)
    assert board.is_attacked_by(chess.WHITE, king)
    assert not any(m.from_square == king for m in board.legal_moves)

    assert _boxed_in(board, chess.WHITE) == {chess.A8}


# ── the stored-ply entry point ───────────────────────────────────────────────
#
# `explain_ply` takes its engine inputs as keyword arguments with None defaults.
# That is right for a position handed over on its own and wrong for a stored ply:
# a caller that forgets one gets fewer findings and no error. Every probe written
# for this layer forgot the two mate scores, so rules 3 and 4 only ever reached
# their board branch. `explain_stored_ply` exists so there is one correct call,
# and these tests exist so dropping an argument from it fails loudly.
#
# Both rows below are real plies, pulled from the corpus by asking which findings
# appear *only* when the scores are threaded.


def stored_row(**over):
    row = {
        "fen_before": "8/3p4/2p5/p5kp/B4p2/1P3P1b/r6P/2K5 b - - 1 35",
        "played_uci": "a2h2",
        "best_uci": "g5f6",
        "classification": "excellent",
        "score_before_cp": None,
        "score_before_mate": 19,
        "score_after_cp": 1234,
        "score_after_mate": None,
    }
    row.update(over)
    return row


def test_a_stored_ply_reaches_the_engine_branch_of_the_mate_rules():
    """The regression guard for the omitted-keyword class of error.

    This ply has no mate in one, so the board branch finds nothing; the mate is
    only visible in `score_before_mate`. If `explain_stored_ply` stops threading
    that argument the finding disappears and this fails -- which is the whole
    point, because in a probe the same omission just produced a smaller number.
    """
    found = only(explain_stored_ply(stored_row()), "missed_mate")
    assert (found.basis, found.mate_in) == ("engine", 19)

    # And the same row through the raw entry point without the scores: no finding
    # at all. This is the measurement error, reproduced as an assertion.
    bare = explain_ply(
        stored_row()["fen_before"], stored_row()["played_uci"],
        best_uci=stored_row()["best_uci"],
    )
    assert "missed_mate" not in kinds(bare)


def test_a_stored_ply_reaches_the_engine_branch_for_a_mate_walked_into():
    """The other rule, the other score. `score_after_mate` is the only evidence
    that this move handed over a forced mate."""
    row = stored_row(
        fen_before="8/3p4/2p5/p4bk1/BP3p1p/5P2/7r/1K6 w - - 1 38",
        played_uci="b1c1", best_uci="b1a1",
        score_before_cp=-1149, score_before_mate=None,
        score_after_cp=None, score_after_mate=-19,
    )
    found = only(explain_stored_ply(row), "walks_into_mate")
    assert (found.basis, found.mate_in) == ("engine", 19)


# ── the refutation gate ──────────────────────────────────────────────────────
#
# SEE settles one square at full depth and is blind to a reply that ignores it.
# Rules 1, 2 and 7 rested on SEE alone until `_survives_reply` was added; the
# motifs never did. The position below is the one that found it.

QG4_ROW = {
    "fen_before": "1k4rr/3qbQ1p/p2p1p2/1pp5/4PB2/8/PPP2PPP/3RR1K1 b - - 2 19",
    "played_uci": "d7g4",
    "best_uci": "d7g4",
    "classification": "best",
    "score_before_cp": -354,
    "score_before_mate": None,
    "score_after_cp": -346,
    "score_after_mate": None,
}


def test_the_qg4_ply_does_not_report_a_bishop_that_cannot_be_taken():
    """The reported bug, as its stored row.

    Game 2864 ply 37, read out of `move_analyses` rather than transcribed — the
    scores and the classification are the engine's, so the row reaching the rules
    here is the row that reached them in the session that produced the wrong
    sentence. `review/scratch/explain_refutation_case.py` located it, and it is the
    only queen-to-g4 ply in the corpus whose named capture allows mate in one.

    `hangs_piece` said "This drops the bishop on e7" because `Qxe7` wins a bishop
    by SEE — nothing defends e7. But Black answers `Qxg2#`: the queen left g4's
    diagonal to no purpose, and with the white queen off f7 the rook on g8 backs
    the g-file up. So the bishop is not dropped, and the sentence was confidently
    wrong on a move the classifier called `best`.

    The assertion is that e7 is not named, not that the ply is silent — see below
    for why that distinction is the point of the test.
    """
    hanging = [f for f in explain_stored_ply(QG4_ROW) if f.kind == "hangs_piece"]
    assert "e7" not in {p.square for f in hanging for p in f.pieces}


def test_bxd6_check_does_not_win_the_pawn_either():
    """The same ply. This test used to pin `Bxd6+` as the *sound* capture beside the
    refuted `Qxe7`: SEE reads d6 as won (`Bxd6+ Bxd6 Rxd6` nets a pawn), and
    `_survives_reply` found no reply that ignores d6, since `Bxd6+` is check.

    It was wrong, and the tempo gate is what shows it. After `Bxd6+ Bxd6`, the
    recapture `Rxd6` walks into `Qxg2#` — the queen on g4 still threatens mate — so
    White has to spend the move on g2 and is a bishop down for a pawn. Stockfish at
    depth 20 agrees: after `Bxd6+` White stands at −1.85 (`Bxd6 g3 Be5`), against
    +3.59 for the best move, `Bg3`. So the ply drops nothing on either square, and
    `Qg4` — the engine's own first choice — gets no sentence claiming it did.
    """
    hanging = [f for f in explain_stored_ply(QG4_ROW) if f.kind == "hangs_piece"]
    assert hanging == []


def test_a_capture_refuted_by_material_is_not_a_dropped_piece():
    """The other half of the gate: no mate, just material coming back.

    `b5` looks like it drops a pawn — `Bxb5` wins it by SEE, nothing on b5 is
    defended. But taking on b5 walks the bishop off the a2-g8 diagonal it was
    guarding d5 from, so `Bxb5 Bxd5` hands the pawn straight back and the played
    move gave up nothing. Both moves are the engine's own choice here, which is why
    this is not the `PATTERN_FORCED` reframe's job: there was no loss to reframe.
    """
    assert explain_ply(
        "r3k2r/pbppbppp/1p6/3P4/2Bp4/8/PPPP1PPP/R1B2RK1 b kq - 3 11",
        "b6b5", best_uci="b6b5",
    ) == []


# ── causation on the rescue rules ────────────────────────────────────────────
#
# Rule 7 compared two positions and attributed the difference to the best move
# without ever asking whether the move was the reason. `_defence_is_caused`
# requires one of two mechanisms, and these are one position per mechanism plus
# one where neither holds.

def test_a_move_that_changes_nothing_about_the_square_defends_nothing():
    """The shape of the reported bug: "Rhg8 would have defended the pawn on c5",
    where the rook was irrelevant and c5 was defended for an unrelated reason.

    Here `f3` self-blocks the rook on h3, which was the only thing guarding d3
    along the third rank — so d3 really does hang, and the `hangs_piece` finding
    stays. What `Kf1` does about it is nothing: d3's white attackers are `{h3}`
    before the move and `{h3}` after, so the king neither arrives at a square
    bearing on d3 nor opens a line to it. The rule used to say it defended the pawn
    because `Kf1` merely declines to block the rook, which is a property of every
    move that is not `f3`.
    """
    found = explain_ply(
        "8/3p4/2p5/p2b2kp/B2r1p2/1P1P3R/P4P1P/6K1 w - - 2 30", "f2f3", best_uci="g1f1"
    )
    assert kinds(found) == {"hangs_piece"}


def test_defence_is_caused_by_arriving_on_a_square_that_bears_on_it():
    """The first mechanism. `Bxb5` abandons the a2-g8 diagonal and d5 falls;
    `Bb3` is the same bishop choosing the square that keeps guarding it, so d5's
    white attackers go from `{c4}` to `{b3}` and the defence is the move's own."""
    found = explain_ply(
        "r3k2r/pbppbppp/8/1p1P4/2Bp4/8/PPPP1PPP/R1B2RK1 w kq - 0 12",
        "c4b5", best_uci="c4b3",
    )
    defends = only(found, "best_defends_piece")
    assert [p.square for p in defends.pieces] == ["d5"]


def test_defence_is_caused_by_vacating_a_square_on_the_defenders_line():
    """The second mechanism, where the defender never moves.

    The knight on c3 needs the queen on f3, and the white pawn on d3 stands between
    them. Pushing `d4` clears the third rank and the queen defends c3 from where it
    already stood — so the causing piece is not the piece that ends up defending,
    which is the case a rule keyed on the moved piece alone would miss.
    """
    found = explain_ply(
        "r2q1rk1/p1p2ppp/1ppn1b2/4R3/8/1PNP1Q1P/P1P2PP1/R1B3K1 w - - 1 13",
        "e5e2", best_uci="d3d4",
    )
    defends = only(found, "best_defends_piece")
    assert [p.square for p in defends.pieces] == ["c3"]


@pytest.mark.parametrize("dropped", STORED_PLY_COLUMNS)
def test_a_row_missing_any_column_raises_rather_than_defaulting(dropped):
    """Silence is the failure mode being designed out.

    A caller that has not selected a column should fail where it reads it, not
    return findings computed from a default it never saw. Parametrised over every
    column so a newly added input inherits the guard automatically.
    """
    row = stored_row()
    del row[dropped]
    with pytest.raises(KeyError, match=dropped):
        explain_stored_ply(row)
