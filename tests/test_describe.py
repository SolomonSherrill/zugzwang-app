"""ARCH-1 descriptions (`core/describe.py`, `core/findings.py`).

Constructed cases are keyed by FEN + move, as the house rule asks; at least three per
descriptor (fires, does not fire, and the edge case its definition names).
"""

import ast
import dataclasses
from pathlib import Path

import chess
import pytest

import zugzwang.config as C
from zugzwang.core import describe as D
from zugzwang.core.findings import (
    Description,
    Descriptor,
    Differential,
    Fact,
    Subject,
    SubjectKind,
    pin_piece,
)

REPO = Path(__file__).resolve().parents[1]

# White castled kingside, f2 g2 h2 in front of the king; Black to have just played.
CASTLED = "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQ1RK1 w - - 0 6"
START = chess.STARTING_FEN


@pytest.fixture(autouse=True)
def theta_one(monkeypatch):
    """The definitions are tested at θ = 1; the shipped θ is provisional (config)."""
    for k in list(C.DESCRIPTION_THETA):
        monkeypatch.setitem(C.DESCRIPTION_THETA, k, 1)


def kinds(fen, played, best, **kw):
    kw.setdefault("all_descriptors", True)
    return [(d.descriptor, d.case) for d in D.describe(fen, played, best, **kw)]


def found(fen, played, best, descriptor, case="", subject=None, **kw):
    """Descriptions of one kind; `subject` filters on the subject's square or file.
    Every descriptor, the dropped ones included: these test the definitions."""
    kw.setdefault("all_descriptors", True)
    return [d for d in D.describe(fen, played, best, **kw)
            if d.descriptor == descriptor and d.case == case
            and (subject is None or subject in (d.subject.square, d.subject.file))]


def only(fen, played, best, descriptor, case="", subject=None, **kw):
    hits = found(fen, played, best, descriptor, case, subject, **kw)
    assert len(hits) == 1, hits
    return hits[0]


def text(fen, played, best, d, player_color="white"):
    b = chess.Board(fen)
    return D.render(d, fen_before=fen,
                    played_san=b.san(chess.Move.from_uci(played)),
                    best_san=b.san(chess.Move.from_uci(best)),
                    player_color=player_color)


# ── common to all ────────────────────────────────────────────────────────────

def test_no_description_when_the_best_move_was_played():
    assert D.describe(CASTLED, "g2g4", "g2g4") == []


def test_no_description_when_no_best_move_is_known():
    assert D.describe(CASTLED, "g2g4", None) == []


def test_an_illegal_stored_move_describes_nothing():
    assert D.describe(CASTLED, "e1e2", "c2c3") == []


# ── finding A: one subject, pinned on both branches ──────────────────────────

D4D5 = "rnbqkbnr/ppp1pppp/8/3p4/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2"


def test_a_subject_cannot_be_made_without_the_pin_check():
    with pytest.raises(TypeError, match="pin"):
        Subject(SubjectKind.SIDE, colour=chess.WHITE)


def test_the_pin_token_is_referenced_only_in_findings():
    for path in list((REPO / "zugzwang").rglob("*.py")) + list((REPO / "sidecar").glob("*.py")):
        if path.name != "findings.py":
            assert "_PIN" not in path.read_text(), path


def test_a_piece_either_move_moved_is_never_a_subject():
    # Nd2 against Nf3: both knights moved on one branch, so neither is described,
    # wherever it stands ("the knight on d2 … the knight on b1" was two facts).
    for d in D.describe(D4D5, "b1d2", "g1f3"):
        assert d.subject.square not in ("b1", "g1", "d2", "f3"), d


def test_pin_piece_refuses_a_square_whose_occupant_differs_between_branches():
    before = chess.Board(D4D5)
    bp, bb = before.copy(), before.copy()
    bp.push_uci("b1d2")
    bb.push_uci("g1f3")
    assert pin_piece(chess.B1, before, bp, bb) is None
    assert pin_piece(chess.C1, before, bp, bb).square == "c1"


def test_a_king_that_moves_on_one_branch_is_not_described():
    found_ = kinds(CASTLED, "g1h1", "c2c3")
    assert Descriptor.PAWN_SHIELD not in [k for k, _ in found_]
    assert Descriptor.KING_RING_ATTACKED not in [k for k, _ in found_]


# ── D1 castling_rights ───────────────────────────────────────────────────────

RIGHTS = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"


def test_d1_fires_when_the_played_move_gives_up_rights():
    d = only(RIGHTS, "e1e2", "a1a2", Descriptor.CASTLING_RIGHTS)
    assert (d.played.state, d.best.state) == ("rights:neither", "rights:kingside")
    assert text(RIGHTS, "e1e2", "a1a2", d) == (
        "After Ke2, you can castle on neither side; after Ra2, on the kingside.")


def test_d1_does_not_fire_on_castling_itself():
    assert found(RIGHTS, "e1g1", "e1e2", Descriptor.CASTLING_RIGHTS) == []


def test_d1_edge_different_rights_lost_on_each_branch_is_not_fewer():
    # Rh2 keeps the queenside, Ra2 the kingside: neither branch has strictly fewer.
    assert found(RIGHTS, "h1h2", "a1a2", Descriptor.CASTLING_RIGHTS) == []


# ── D2 pawn_shield ───────────────────────────────────────────────────────────

def test_d2_fires_when_a_shield_pawn_leaves_the_zone():
    d = only(CASTLED, "g2g4", "c2c3", Descriptor.PAWN_SHIELD)
    assert d.subject.kind == SubjectKind.KING and d.subject.square == "g1"
    assert d.played == Fact(squares=("f2", "h2"), count=2)
    assert d.best == Fact(squares=("f2", "g2", "h2"), count=3)
    assert d.magnitude == 1.0 and d.differential == Differential.BEST_ONLY
    assert text(CASTLED, "g2g4", "c2c3", d) == (
        "After g4, your king on g1 has two pawns in front of it (f2, h2); "
        "after c3, three (f2, g2, h2).")


def test_d2_edge_a_pawn_moving_inside_the_zone_changes_nothing():
    # g3 is still one of the two ranks ahead of the king.
    assert found(CASTLED, "g2g3", "c2c3", Descriptor.PAWN_SHIELD) == []


def test_d2_does_not_fire_on_a_move_away_from_the_king():
    assert found(CASTLED, "a2a3", "c2c3", Descriptor.PAWN_SHIELD) == []


def test_d2_finding_b_an_uncastled_king_is_not_described():
    # e4 against Nf3 changes the pawns in front of e1; the king is on the e-file.
    assert found(START, "e2e4", "g1f3", Descriptor.PAWN_SHIELD) == []
    assert 4 not in D.CASTLED_FILES and 3 not in D.CASTLED_FILES and 5 not in D.CASTLED_FILES


def test_d2_is_undefined_when_the_king_has_left_its_first_two_ranks():
    assert D.shield_squares(chess.E4, chess.WHITE) is None
    fen = "8/8/8/8/6K1/5P2/8/k7 w - - 0 1"
    assert found(fen, "f3f4", "g4h4", Descriptor.PAWN_SHIELD) == []


def test_d2_zone_is_clipped_at_the_edge_and_mirrored_for_black():
    assert sorted(chess.square_name(s) for s in D.shield_squares(chess.H8, chess.BLACK)) \
        == ["g6", "g7", "h6", "h7"]


# ── D3 king_ring_attacked ────────────────────────────────────────────────────

# Black's queen on c5 is blocked from f2 by White's bishop on e3.
BLOCKED = "6k1/5ppp/8/2q5/8/4B3/5PPP/6K1 w - - 0 1"


def test_d3_fires_when_a_move_opens_a_line_onto_the_ring():
    d = only(BLOCKED, "e3g5", "h2h3", Descriptor.KING_RING_ATTACKED)
    assert d.played.squares == ("f2",) and d.best.squares == ()
    assert d.differential == Differential.PLAYED_ONLY
    assert text(BLOCKED, "e3g5", "h2h3", d) == (
        "After Bg5, Black's pieces attack one square next to your king on g1 (f2); "
        "after h3, none.")


def test_d3_does_not_fire_when_the_ring_is_unchanged():
    assert found(BLOCKED, "h2h3", "g2g3", Descriptor.KING_RING_ATTACKED) == []


def test_d3_edge_theta_suppresses_a_one_square_difference(monkeypatch):
    monkeypatch.setitem(C.DESCRIPTION_THETA, "king_ring_attacked", 2)
    assert found(BLOCKED, "e3g5", "h2h3", Descriptor.KING_RING_ATTACKED) == []


def test_d3_voice_names_the_user_when_the_opponent_moved():
    d = only(BLOCKED, "e3g5", "h2h3", Descriptor.KING_RING_ATTACKED)
    assert text(BLOCKED, "e3g5", "h2h3", d, player_color="black").startswith(
        "After Bg5, your pieces attack one square next to White's king on g1")


# ── D4 pawn_structure ────────────────────────────────────────────────────────

ISOLATE = "4k3/8/8/8/8/3p4/1PP5/4K3 w - - 0 1"
DOUBLE = "4k3/8/8/8/8/2p5/1PP5/4K3 w - - 0 1"


def test_d4_fires_when_a_capture_leaves_a_pinned_pawn_isolated():
    d = only(ISOLATE, "c2d3", "e1d1", Descriptor.PAWN_STRUCTURE, "pawn", subject="b2")
    assert (d.played.state, d.best.state) == ("pawn:isolated", "pawn:neither")
    assert text(ISOLATE, "c2d3", "e1d1", d) == (
        "After cxd3, your pawn on b2 is isolated; after Kd1, it is neither isolated "
        "nor backward.")


def test_d4_doubled_names_the_file_and_both_counts():
    d = only(DOUBLE, "b2c3", "e1d1", Descriptor.PAWN_STRUCTURE, "doubled")
    assert d.subject.kind == SubjectKind.FILE and d.subject.file == "c"
    assert text(DOUBLE, "b2c3", "e1d1", d) == (
        "After bxc3, the c-file holds two of your pawns (c2, c3); after Kd1, one (c2).")


def test_d4_does_not_fire_when_no_pawn_changes():
    assert found(DOUBLE, "e1d1", "e1f1", Descriptor.PAWN_STRUCTURE) == []
    assert found(DOUBLE, "e1d1", "e1f1", Descriptor.PAWN_STRUCTURE, "doubled") == []


def test_d4_edge_backward_needs_the_stop_square_attacked_by_a_pawn():
    # d3 with c- and e-pawns advanced past it, and a Black pawn on c5 hitting d4.
    board = chess.Board("4k3/8/8/2p5/2P1P3/3P4/8/4K3 w - - 0 1")
    assert D.pawn_state(board, chess.D3) == "pawn:backward"
    board.remove_piece_at(chess.C5)
    assert D.pawn_state(board, chess.D3) == "pawn:neither"


# ── D5 files ─────────────────────────────────────────────────────────────────

ROOK = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
EXD5 = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"


def test_d5_fires_when_a_rook_stands_on_an_open_file_on_one_branch_only():
    d = only(ROOK, "a1c1", "a1b1", Descriptor.FILES, subject="c")
    assert text(ROOK, "a1c1", "a1b1", d) == (
        "After Rc1, the c-file is open, with your rook on c1 on it; "
        "after Rb1, open, with no rook or queen on it.")


def test_d5_fires_when_a_capture_changes_a_file_state():
    d = only(EXD5, "e4d5", "e1d2", Descriptor.FILES, subject="d")
    assert (d.played.state, d.best.state) == ("file:half-open:b", "file:half-open:w")
    assert text(EXD5, "e4d5", "e1d2", d) == (
        "After exd5, the d-file is half-open for Black; after Kd2, half-open for you.")


def test_d5_edge_a_rook_moving_along_its_own_file_does_not_fire():
    assert found(ROOK, "a1a3", "a1a5", Descriptor.FILES) == []


# ── D6 reach ─────────────────────────────────────────────────────────────────

def test_d6_a_pawn_move_opens_a_pinned_bishop():
    d = only(START, "d2d3", "a2a3", Descriptor.REACH, subject="c1")
    assert (d.played.count, d.best.count) == (5, 0)
    assert text(START, "d2d3", "a2a3", d) == (
        "After d3, your bishop on c1 reaches five squares; after a3, none.")


def test_d6_theta_suppresses_a_small_reach_difference(monkeypatch):
    monkeypatch.setitem(C.DESCRIPTION_THETA, "reach", 6)
    assert found(START, "d2d3", "a2a3", Descriptor.REACH) == []


def test_d6_does_not_fire_for_kings_and_pawns():
    for d in found(START, "e2e4", "d2d4", Descriptor.REACH):
        assert d.subject.kind == SubjectKind.PIECE


def test_d6_edge_the_castling_rook_is_not_a_subject():
    fen = "r3k2r/pppqbppp/2np1n2/4p3/2B1P1b1/2NP1N2/PPPBQPPP/R3K2R w KQkq - 0 1"
    for d in found(fen, "e1g1", "a2a3", Descriptor.REACH):
        assert d.subject.square not in ("h1", "f1", "e1", "g1")


# ── D7 no_forward_square ─────────────────────────────────────────────────────

def test_d7_fires_when_a_piece_has_nothing_ahead_on_the_played_branch_only():
    d = only(START, "a2a3", "d2d3", Descriptor.NO_FORWARD_SQUARE, subject="c1")
    assert text(START, "a2a3", "d2d3", d) == (
        "After a3, your bishop on c1 reaches no squares ahead of it; "
        "after d3, five (d2, e3, f4, g5, h6).")


def test_d7_does_not_fire_when_the_played_branch_has_a_square_ahead():
    assert found(START, "d2d3", "a2a3", Descriptor.NO_FORWARD_SQUARE, subject="c1") == []


def test_d7_edge_empty_on_both_branches_does_not_fire():
    # Nf3 against Nc3: the rooks gain g1 / b1, on their own rank, not ahead.
    assert found(START, "g1f3", "b1c3", Descriptor.NO_FORWARD_SQUARE) == []


# ── D8 pawn_cover_gone ───────────────────────────────────────────────────────

def test_d8_fires_for_each_square_the_pawns_can_no_longer_reach():
    ds = found(CASTLED, "g2g4", "c2c3", Descriptor.PAWN_COVER_GONE)
    assert sorted(d.subject.square for d in ds) == ["f3", "f4", "h3", "h4"]
    d = next(d for d in ds if d.subject.square == "f3")
    assert text(CASTLED, "g2g4", "c2c3", d) == (
        "After g4, f3 has none of your pawns behind it on the e- or g-file; "
        "after c3, one (g2).")


def test_d8_does_not_fire_without_a_pawn_move():
    assert found(START, "g1f3", "b1c3", Descriptor.PAWN_COVER_GONE) == []


def test_d8_edge_a_square_the_advanced_pawn_still_stands_behind_is_covered():
    # After g4, f5 and h5 still have the g4 pawn behind them.
    squares = {d.subject.square for d in found(CASTLED, "g2g4", "c2c3",
                                               Descriptor.PAWN_COVER_GONE)}
    assert not squares & {"f5", "h5"}


# ── D9 undeveloped ───────────────────────────────────────────────────────────

def test_d9_fires_in_the_opening_on_the_count_of_undeveloped_minors():
    d = only(START, "e2e4", "g1f3", Descriptor.UNDEVELOPED, opening=True)
    assert text(START, "e2e4", "g1f3", d) == (
        "After e4, four of your knights and bishops stand on their starting squares; "
        "after Nf3, three.")


def test_d9_names_the_queen_when_it_differs():
    d = only(D4D5, "d1d3", "g1f3", Descriptor.UNDEVELOPED, opening=True)
    assert d.magnitude == 2.0
    assert text(D4D5, "d1d3", "g1f3", d) == (
        "After Qd3, four of your knights and bishops stand on their starting squares, "
        "and your queen has left d1; after Nf3, three, and your queen is on d1.")


def test_d9_edge_is_defined_in_the_opening_only():
    assert found(START, "e2e4", "g1f3", Descriptor.UNDEVELOPED, opening=False) == []


# ── finding C: a state is said once per game ─────────────────────────────────

def test_game_memory_drops_a_repeat_and_says_a_change_again():
    first = only(BLOCKED, "e3g5", "h2h3", Descriptor.KING_RING_ATTACKED)
    again = only(BLOCKED, "e3g5", "g2g3", Descriptor.KING_RING_ATTACKED)
    assert first.played == again.played and first.subject == again.subject
    m = D.GameMemory()
    assert m.filter([first]) == [first]
    assert m.filter([again]) == []          # same subject, same played value
    changed = dataclasses.replace(first, played=Fact(squares=("f2", "g2"), count=2))
    assert m.filter([changed]) == [changed]
    assert m.filter([first]) == [first]     # changed back: said again


def test_game_memory_keys_on_the_subject():
    a = only(START, "d2d3", "a2a3", Descriptor.REACH, subject="c1")
    b = only(START, "d2d3", "a2a3", Descriptor.REACH, subject="d1")
    m = D.GameMemory()
    assert m.filter([a, b]) == [a, b]


def test_dropped_descriptors_are_left_out_by_default():
    # Owner, 2026-11-08, under the corrected bar: only D1 and D3 ship.
    # engine_line is built by pv_reading.gate_p, not by describe().
    kept = {d.value for d in Descriptor} - C.DESCRIPTION_DROPPED - {"engine_line"}
    assert kept == {"castling_rights", "king_ring_attacked"}
    cases = [(START, "a2a3", "d2d3"), (START, "e2e4", "g1f3")]
    shipped = {d.descriptor.value for c in cases for d in D.describe(*c, opening=True)}
    measured = {d.descriptor.value for c in cases
                for d in D.describe(*c, opening=True, all_descriptors=True)}
    assert not shipped & C.DESCRIPTION_DROPPED
    assert {"reach", "no_forward_square", "undeveloped"} <= measured


# ── ranking and the cap ──────────────────────────────────────────────────────

def test_ranked_keeps_the_top_two_by_percentile():
    ds = (D.describe(START, "d2d3", "a2a3", all_descriptors=True)
          + D.describe(CASTLED, "g2g4", "c2c3", all_descriptors=True))
    top = D.ranked(ds, percentile=lambda d: d.magnitude)
    assert len(top) == 2 and top[0].magnitude >= top[1].magnitude


# ── the type split (§1) ──────────────────────────────────────────────────────

def test_a_description_has_no_field_a_causal_sentence_could_be_built_from():
    names = {f.name for f in dataclasses.fields(Description)}
    assert names == {"descriptor", "subject", "differential", "played", "best",
                     "magnitude", "horizon", "descriptor_version", "case"}
    for banned in ("material", "refutation", "mate_in", "basis", "classification",
                   "wpl", "score", "eval"):
        assert banned not in names


def test_a_description_cannot_grow_an_attribute():
    d = only(START, "d2d3", "a2a3", Descriptor.REACH, subject="c1")
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        d.material = 3  # type: ignore[attr-defined]


# ── layer 3: the closed grammar ──────────────────────────────────────────────

@pytest.mark.parametrize("key", list(D.TEMPLATES))
def test_every_template_is_a_contrast_with_typed_slots_only(key):
    t = D.TEMPLATES[key]
    assert t.startswith("After {played}, ") and "; after {best}, " in t and t.endswith(".")
    for slot in D.template_slots(t):
        assert slot in D.SLOT_TYPES, f"{key}: slot {slot!r} is not a typed slot"


@pytest.mark.parametrize("key", list(D.TEMPLATES))
def test_no_template_uses_a_banned_word(key):
    literal = "".join(lit for lit, *_ in __import__("string").Formatter().parse(D.TEMPLATES[key]))
    words = {w.lower() for w in D._WORD.findall(literal)}
    assert not words & D.BANNED_WORDS


def test_counts_are_words_to_ten_and_digits_above():
    assert (f"{D.Count(0):square}", f"{D.Count(1):square}", f"{D.Count(10):square}",
            f"{D.Count(11):square}", f"{D.Count(0)}", f"{D.Count(16)}") == (
        "no squares", "one square", "ten squares", "11 squares", "none", "16")
    assert (f"{D.Count(1):=stand}", f"{D.Count(3):=stand}") == ("stands", "stand")


def test_description_text_refuses_a_causal_word_at_runtime():
    with pytest.raises(ValueError, match="because"):
        D.DescriptionText("After g4, the king has two pawns because of it.")
    with pytest.raises(ValueError, match="blunder"):
        D.DescriptionText("After g4, a blunder.")


def test_every_template_renders_through_the_lexicon_check():
    seen = set()
    for fen, played, best in [(CASTLED, "g2g4", "c2c3"), (BLOCKED, "e3g5", "h2h3"),
                              (START, "d2d3", "a2a3"), (D4D5, "d1d3", "g1f3"),
                              (RIGHTS, "e1e2", "a1a2"), (ISOLATE, "c2d3", "e1d1"),
                              (DOUBLE, "b2c3", "e1d1"), (ROOK, "a1c1", "a1b1"),
                              (EXD5, "e4d5", "e1d2"), (START, "a2a3", "d2d3")]:
        for d in D.describe(fen, played, best, opening=True, all_descriptors=True):
            for pc in ("white", "black", "unknown", None):
                assert isinstance(text(fen, played, best, d, pc), D.DescriptionText)
            seen.add((d.descriptor, d.case))
    # engine_line is built by pv_reading.gate_p; tests/test_pv_reading.py renders it.
    assert seen == set(D.TEMPLATES) - {(Descriptor.ENGINE_LINE, "")}, set(D.TEMPLATES) - seen


def test_description_text_is_not_a_claim_text_type():
    assert D.DescriptionText.__mro__ == (D.DescriptionText, str, object)


# ── layer 2: the import graph ────────────────────────────────────────────────

def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_describe_never_imports_the_claim_layer():
    for mod in ("describe.py", "findings.py"):
        imported = _imports(REPO / "zugzwang" / "core" / mod)
        assert not {m for m in imported if "explain" in m}, (mod, imported)


def test_no_module_imports_both_renderers():
    """Only layer 4's composition function (core/compose.py) may import both."""
    for path in list((REPO / "zugzwang").rglob("*.py")) + list((REPO / "sidecar").glob("*.py")):
        if path.name == "compose.py":
            continue
        imported = _imports(path)
        both = (any(m.endswith("explain_text") or ".explain_text." in m for m in imported)
                and any(m.endswith("core.describe") or m == "zugzwang.core.describe"
                        or m.startswith("zugzwang.core.describe.") for m in imported))
        assert not both, path


# ── the approved type checker, on these two modules only ─────────────────────

def test_the_two_modules_type_check():
    mypy = pytest.importorskip("mypy.api")
    out, err, status = mypy.run(["--config-file", str(REPO / "mypy.ini"),
                                 str(REPO / "zugzwang/core/findings.py"),
                                 str(REPO / "zugzwang/core/describe.py")])
    assert status == 0, out + err
