"""
Structured findings about why a move was bad or good — Qt-free, and running
entirely off the board plus the analysis already stored for the ply.

This layer emits *facts*, not prose: each `Finding` names the pieces, squares
and moves involved, and carries the material at stake. Rendering them as English
is a separate, deterministic step (stage 3). No language model is involved, and
every claim here must be derivable from the board plus the engine data already
stored for the ply.

The governing rule is that a rule which cannot prove its claim emits nothing. A
move with no explanation is a fine outcome; a move with a confident wrong one is
not, because this feeds a screen meant to teach. That is why `Finding.basis`
exists: it records what the claim actually rests on, so a caller can decline to
render a whole category rather than trust everything equally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from .. import config as C
from .findings import MoveAbout, MoveRole

# 17 (CLS-V3, 2026-11-11): king-ring descriptions silent beside a forced mate on a non-error
# move (ruling 11), and classifier version 3's labels feed every label gate (ERROR_CLASSES,
# AUDIT-9, AUDIT-Q5) — one bump for both; the rendered-text changes are in
# review/CLS_V3_REPORT.md.
# 18 (CLS-V3 third round, 2026-11-12): D1/D3 descriptions silent on a move labelled an
# error (T10), and the critical-move miss's only-move sentence from the stored lines (T4).
# 19 (T-HOLD, 2026-11-14): a capture claim names a piece only where what the capture holds
# after the reply is at least that piece's value (`_capture_claims`).
# 20 (L1, owner 2026-11-14): T-HOLD replaced — a capture claim whose two-ply hold falls short
# is silenced only where the stored refutation (ply N+1's line) does not confirm the named
# loss by F1's measure; otherwise it stands (`_capture_claims`).
# 21 (MECH-NAME, owner rulings M1–M7, 2026-11-14): back rank and discovered attack/check named
# as a clause on a shown engine-line claim (`mechanisms`, `compose`).
# 22 (P1, owner 2026-11-19): pin and skewer named the same way, only at the claim's hold.
RULE_VERSION = 22

# Two mate lengths, deliberately not one (owner rulings, stage B and 2026-10-21).
#
# A missed mate and an allowed mate differ in value *at the same length* — that is the
# recorded asymmetry — so sharing a threshold would contradict it:
#
#   - MATE_CUTOFF: a *missed* mate longer than this is unactionable, because no human
#     finds it at the board, so `missed_mate` past it renders nothing
#     (`explain_text.suppressed`). It is a cut: the sentence goes.
#   - MATE_DEMOTE_FROM: a mate *against* you of this length or longer is still a
#     verdict on the move and always renders; it only gives up the lead slot to any
#     other finding on the ply (`rank_findings`, `explain_text.one_sentence_per_move`).
#     It is never dropped, so both sentences render either way and the rule cannot
#     make a ply silent — the constant only decides which one leads. A mate in 5 is a
#     better headline than a dropped pawn; a mate in 10 is not.
MATE_CUTOFF = 4
MATE_DEMOTE_FROM = 7


def is_long_mate_against(f: "Finding") -> bool:
    """A `walks_into_mate` of `MATE_DEMOTE_FROM` moves or more: rendered, but it
    leads only when nothing else on the ply renders."""
    return f.kind == "walks_into_mate" and (f.mate_in or 99) >= MATE_DEMOTE_FROM

# Material values in pawns. Knight and bishop are deliberately both 3.0: this
# table decides whether a finding may claim it won material, and a bishop-for-
# knight trade must not read as a win. The king's value only orders the
# least-valuable-attacker choice; it is never actually captured.
_VALUE = {
    chess.PAWN: 1.0,
    chess.KNIGHT: 3.0,
    chess.BISHOP: 3.0,
    chess.ROOK: 5.0,
    chess.QUEEN: 9.0,
    chess.KING: 100.0,
}

# What a claim rests on. Ordered weakest-last so callers can filter.
BASIS_BOARD = "board"    # exhaustively verified over legal moves
BASIS_SEE = "see"        # static exchange evaluation: blind to zwischenzug
BASIS_ENGINE = "engine"  # an engine score or PV, at a recorded depth


@dataclass(frozen=True)
class PieceOn:
    piece: str    # "N"
    square: str   # "f6"
    color: str    # "white" | "black"

    def to_dict(self) -> dict:
        return {"piece": self.piece, "square": self.square, "color": self.color}


@dataclass(frozen=True)
class MoveRef:
    uci: str
    san: str

    def to_dict(self) -> dict:
        return {"uci": self.uci, "san": self.san}


@dataclass(frozen=True)
class Finding:
    kind: str
    subject: str                       # "played" | "best"
    basis: str
    pieces: tuple[PieceOn, ...] = ()
    moves: dict[str, MoveRef] = field(default_factory=dict)
    material: float | None = None      # pawns, mover's POV, + = mover gains
    mate_in: int | None = None
    pattern: str | None = None         # an annotation on the finding, not a claim
    rule_version: int = RULE_VERSION
    # STAGE5-MOVE (owner, 2026-11-10; built 2026-11-19): the move this finding's sentence
    # names — UCI, SAN and whose move it is (played, best, the opponent's reply). Every rule
    # sets it explicitly; the renderer reads the move from here and from nothing else.
    # `subject` is a different question: `missed_material` is about the played move
    # (subject "played") but its sentence names the best move (about.role BEST).
    about: MoveAbout | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.about, MoveAbout):
            raise TypeError("a rule finding names the move it is about (Finding.about)")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "basis": self.basis,
            "pieces": [p.to_dict() for p in self.pieces],
            "moves": {k: v.to_dict() for k, v in self.moves.items()},
            "material": self.material,
            "mateIn": self.mate_in,
            "pattern": self.pattern,
            "ruleVersion": self.rule_version,
        }


def _piece_on(board: chess.Board, square: int) -> PieceOn | None:
    pc = board.piece_at(square)
    if pc is None:
        return None
    return PieceOn(
        piece=pc.symbol().upper(),
        square=chess.square_name(square),
        color="white" if pc.color == chess.WHITE else "black",
    )


def _ref(board: chess.Board, move: chess.Move) -> MoveRef:
    """A move with its SAN, taken in `board`'s position."""
    return MoveRef(uci=move.uci(), san=board.san(move))


def _about(role: MoveRole, ref: MoveRef | None) -> MoveAbout:
    """`Finding.about` from the move a rule names (STAGE5-MOVE)."""
    return MoveAbout(role=role, uci=ref.uci if ref else None, san=ref.san if ref else None)


# ── static exchange evaluation ───────────────────────────────────────────────

def _immediate_gain(board: chess.Board, move: chess.Move) -> float:
    """Material `move` takes off the board, plus any promotion upgrade."""
    gain = 0.0
    if board.is_en_passant(move):
        gain += _VALUE[chess.PAWN]
    else:
        victim = board.piece_at(move.to_square)
        if victim is not None:
            gain += _VALUE[victim.piece_type]
    if move.promotion:
        gain += _VALUE[move.promotion] - _VALUE[chess.PAWN]
    return gain


def see(board: chess.Board, move: chess.Move) -> float:
    """Material `move` wins, in pawns, for the side playing it.

    Both sides then recapture on the square with their least valuable piece and
    either may stop once continuing would lose material.

    Recaptures are generated as *legal* moves rather than from an attacker
    bitboard, so a defender that is absolutely pinned correctly cannot
    recapture. Pretending a pinned defender still defends is the single most
    common way a piece-counting evaluation claims material that is not there,
    and it is what sank the fork detector this layer replaces.
    """
    gain = _immediate_gain(board, move)
    board.push(move)
    try:
        square = move.to_square
        recaptures = [m for m in board.legal_moves if m.to_square == square]
        if not recaptures:
            return gain
        # Least valuable attacker; among equal ones prefer the best promotion.
        best = min(
            recaptures,
            key=lambda m: (
                _VALUE[board.piece_at(m.from_square).piece_type],
                -(_VALUE[m.promotion] if m.promotion else 0.0),
            ),
        )
        # The opponent declines the recapture if taking would lose material.
        return gain - max(0.0, see(board, best))
    finally:
        board.pop()


def _capture_candidates(
    board: chess.Board, threshold: float
) -> dict[int, list[tuple[chess.Move, float]]]:
    """Every capture the side to move can make that SEE says wins at least
    `threshold`, grouped by the square it lands on.

    Grouped rather than reduced to one capture per square because the refutation
    test in `_surviving_captures` asks something SEE cannot: two ways of taking
    the same piece are worth the same by SEE, and only one of them may survive
    the reply — *which* piece takes decides whether the mover's answer still
    works, since the capturer may block the line the answer needs.

    King captures are discarded: they are only generated in the synthetic
    null-moved baseline below, where the side that was in check has been skipped
    over, and a "hanging king" is not a finding anyone wants.
    """
    out: dict[int, list[tuple[chess.Move, float]]] = {}
    for move in list(board.legal_moves):
        if not board.is_capture(move):
            continue
        victim = board.piece_at(move.to_square)
        if victim is not None and victim.piece_type == chess.KING:
            continue
        value = see(board, move)
        if value < threshold:
            continue
        out.setdefault(move.to_square, []).append((move, value))
    return out


def _winning_captures(board: chess.Board, threshold: float) -> dict[int, tuple[chess.Move, float]]:
    """Squares where the side to move can capture and come out at least
    `threshold` pawns ahead by SEE, mapped to the best such capture.

    **SEE-only, so blind to whatever answers the capture.** This is the right
    basis inside the motif minimax, where it estimates what a defender wins back
    and the caller is already charging for it. It is the wrong basis for a rule
    that emits a finding on its own — use `_surviving_captures` there.
    """
    return {
        square: max(candidates, key=lambda c: c[1])
        for square, candidates in _capture_candidates(board, threshold).items()
    }


def _baseline_hanging(board: chess.Board, threshold: float) -> dict[int, tuple[chess.Move, float]]:
    """What the opponent could already win if the mover simply passed.

    This is what stops a piece that has been loose for five moves from being
    blamed on the move that happens to be under review.

    SEE-only, deliberately, where the set it is compared against is not. A
    refutation-aware baseline would be a *smaller* baseline and so admit more
    findings — the piece that was loose but could not actually be taken. Keeping
    the permissive one errs towards silence, which is this layer's stated bias,
    and keeps the extra minimax off every ply rather than only the ones with
    something to claim.
    """
    passed = board.copy(stack=False)
    passed.push(chess.Move.null())
    return _winning_captures(passed, threshold)


def _mate_in_one(board: chess.Board) -> chess.Move | None:
    """A mating move for the side to move, proven by playing it."""
    for move in list(board.legal_moves):
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return move
    return None


PATTERN_BACK_RANK = "back_rank"

# Which of a discovered attack's two branches the finding proved. Every
# `discovered_attack` carries one of them, and it decides the sentence:
#
#   `discovered_line`   the line this move opened is what attacks the piece that
#                       falls. "Nd3+ opens a line onto the queen on f4."
#   `discovered_check`  the opened line gives *check*, and the piece that falls is
#                       one the moved piece attacks. The material is just as
#                       proven -- the defender may only answer the check -- but no
#                       opened line reaches it, so a sentence saying otherwise
#                       would assert a geometry the rule did not establish.
#                       "Bc8+ attacks the queen on a6 and discovers a check."
#
# The distinction is recorded here rather than left to the renderer because a
# template that recomputes geometry can disagree with the rule that proved it,
# and then the layer has two answers and no way to choose. 54 of 179 findings
# measured over the stored corpus take the check branch.
PATTERN_DISCOVERED_LINE = "discovered_line"
PATTERN_DISCOVERED_CHECK = "discovered_check"

# On a `hangs_piece` finding: the move that dropped the piece was the engine's
# own first choice, so the loss was the least bad thing available. Recorded by
# the rule, which has the best move in hand, rather than inferred by the
# renderer from the classification label — `best` is a win-probability band and
# does not mean the played move *was* the engine's move.
PATTERN_FORCED = "forced"


def _back_rank_pawns(mated: chess.Board) -> tuple[PieceOn, ...]:
    """The mated king's own pawns, when they are the reason it had no square.

    This annotates a mate already proven by `_mate_in_one`; it never claims a
    mate of its own. So the only question is *why* the king was stuck, and the
    answer has to be "its own pawns" specifically — a queen or rook along the
    back rank, and every square the king could have stepped up to blocked by a
    pawn of its own colour.

    Deliberately narrow. If one of those squares is empty but covered by the
    mating side, the pawns are not the whole reason and a different sentence is
    true; widening the test to cover that case would buy volume by weakening
    the claim. Returns empty when the pattern does not hold.
    """
    them = mated.turn                       # the mated side is the one to move
    king = mated.king(them)
    if king is None:
        return ()
    home = 0 if them == chess.WHITE else 7
    if chess.square_rank(king) != home:
        return ()

    checkers = list(mated.checkers())
    if len(checkers) != 1:
        return ()                           # a double check is a different story
    checker = checkers[0]
    if mated.piece_type_at(checker) not in (chess.ROOK, chess.QUEEN):
        return ()
    if chess.square_rank(checker) != home:
        return ()

    out = []
    for df in (-1, 0, 1):
        file = chess.square_file(king) + df
        if not 0 <= file <= 7:
            continue
        square = chess.square(file, home + (1 if them == chess.WHITE else -1))
        piece = mated.piece_at(square)
        if piece is None or piece.color != them or piece.piece_type != chess.PAWN:
            return ()
        out.append(PieceOn(piece.symbol().upper(), chess.square_name(square),
                           "white" if piece.color else "black"))
    return tuple(out)


def _back_rank(board: chess.Board, mate: chess.Move) -> tuple[PieceOn, ...]:
    """`_back_rank_pawns` on the position the mating move reaches."""
    mated = board.copy(stack=False)
    mated.push(mate)
    return _back_rank_pawns(mated)


# ── motifs: geometry proposes, material disposes ─────────────────────────────
#
# Geometry alone is not a motif. Measured over stored plies, "the moved piece
# attacks two enemy pieces" is true of 21.7 % of best moves and 26.9 % of
# blunders — flat across classifications, which is the same test that removed
# two rules in stage 1. So every motif here is a geometric candidate that has
# then survived a material test, and it is credited only when the material is
# won on a square the geometry itself named.

_RAYS = {
    chess.BISHOP: (9, 7, -7, -9),
    chess.ROOK: (8, 1, -1, -8),
    chess.QUEEN: (9, 8, 7, 1, -1, -7, -8, -9),
}


def _material(board: chess.Board, pov: chess.Color) -> float:
    """Material balance in pawns from `pov`. Kings are not counted."""
    return sum(
        value * (len(board.pieces(piece, pov)) - len(board.pieces(piece, not pov)))
        for piece, value in _VALUE.items()
        if piece != chess.KING
    )


def _ray_pairs(board: chess.Board, square: int) -> list[tuple[int, int]]:
    """(front, rear) enemy pairs lined up on one ray from `square`.

    `front` must be the only piece between the slider and `rear`; a ray blocked
    by one of the mover's own pieces yields nothing.
    """
    piece = board.piece_at(square)
    if piece is None or piece.piece_type not in _RAYS:
        return []
    them = not piece.color
    pairs: list[tuple[int, int]] = []
    for step in _RAYS[piece.piece_type]:
        seen: list[int] = []
        s = square
        while True:
            prev, s = s, s + step
            if not (0 <= s < 64) or chess.square_distance(prev, s) != 1:
                break
            occupant = board.color_at(s)
            if occupant is None:
                continue
            if occupant != them:
                break
            seen.append(s)
            if len(seen) == 2:
                pairs.append((seen[0], seen[1]))
                break
    return pairs


def _motif_candidates(
    after: chess.Board, square: int
) -> list[tuple[str, frozenset[int]]]:
    """Each motif the geometry proposes, with the squares it names as targets.

    No value comparison decides a fork: "worth more than the forker, or equal
    and undefended" is what made a queen unable to fork anything but another
    queen, and left the commonest double attack in chess invisible. Two enemy
    pieces attacked is the whole condition; the material test does the judging.

    One entry per ray, not one per motif. `Rxc1` in a real game lines up a
    knight against a rook on one side and a bishop against the king on the
    other; merged, that is a single finding naming four pieces and pinning
    nothing in particular.

    Pin-shaped rays are recognised and then discarded — see EXPLANATIONS.md.
    A pin pays off by constraint rather than by material within two plies, so
    the minimax below cannot measure it; the shape is still matched here so
    that a pin does not fall through and get reported as a skewer.
    """
    mover = after.color_at(square)
    if mover is None:
        return []
    them = not mover
    out: list[tuple[str, frozenset[int]]] = []

    hit = {s for s in after.attacks(square) if after.color_at(s) == them}
    if len(hit) >= 2:
        out.append(("fork", frozenset(hit)))

    for front, rear in _ray_pairs(after, square):
        rear_type = after.piece_type_at(rear)
        front_type = after.piece_type_at(front)
        if rear_type == chess.KING or _VALUE[rear_type] > _VALUE[front_type]:
            continue  # pin
        if _VALUE[front_type] > _VALUE[rear_type] or front_type == chess.KING:
            out.append(("skewer", frozenset({front, rear})))
    return out


_SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)


def _discovered_candidate(
    board: chess.Board, move: chess.Move
) -> tuple[frozenset[int], frozenset[int]] | None:
    """Targets of a line this move opened, when the threatening piece is not
    the piece that moved.

    Returns `(targets, on_the_line)`. `on_the_line` is the subset the opened line
    itself reaches; the rest, if any, are squares the *moved* piece attacks, lent
    to the motif by the discovered-check branch below. The caller needs the split
    because the two deserve different sentences and a renderer may not work out
    which is which for itself — see `PATTERN_DISCOVERED_CHECK`.

    The vacated square must lie on the ray between the unmasking slider and its
    new target, which is what makes the attribution exact: nothing else on the
    board moved, so a line that is open now and was shut before was opened by
    this move and no other.

    **A discovered check also lends its targets to the moved piece.** The point
    of the motif is that the opponent cannot deal with both threats, and when
    the discovery is check that is not a heuristic — the defender's legal moves
    really are only check evasions, so whatever the moved piece then collects is
    the discovery's doing. When the discovery is *not* check the opponent is
    free to answer it directly, so only the unmasked line's own targets count
    and material won elsewhere is not credited here.
    """
    mover = board.turn
    after = board.copy(stack=False)
    after.push(move)
    them = not mover

    discovered: set[int] = set()
    for target in chess.SquareSet(after.occupied_co[them]):
        for source in after.attackers(mover, target) - board.attackers(mover, target):
            if source == move.to_square:
                continue  # the moved piece threatening something is not a discovery
            piece = after.piece_at(source)
            if piece is None or piece.piece_type not in _SLIDERS:
                continue
            if chess.BB_SQUARES[move.from_square] & chess.between(source, target):
                discovered.add(target)
                break
    if not discovered:
        return None

    king = after.king(them)
    on_the_line = frozenset(discovered - {king})
    targets = set(on_the_line)
    if king in discovered:
        targets |= {
            s for s in after.attacks(move.to_square) if after.color_at(s) == them
        } - {king}
    if not targets:
        return None
    return frozenset(targets), on_the_line


_TRAPPABLE = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def _boxed_in(board: chess.Board, pov: chess.Color) -> set[int]:
    """Enemy pieces `pov` attacks that have no safe square to run to.

    `board` must have the enemy to move, so their legal moves are available.
    Pawns and the king are not trappable here: a pawn cannot be worth the motif
    material floor, and a king with no safe square is check and mate's business.
    """
    them = not pov
    escapes: dict[int, bool] = {}
    for move in board.legal_moves:
        origin = move.from_square
        if board.piece_type_at(origin) not in _TRAPPABLE:
            continue
        safe = not board.is_attacked_by(pov, move.to_square)
        escapes[origin] = escapes.get(origin, False) or safe

    return {
        square for square in chess.SquareSet(board.occupied_co[them])
        if board.piece_type_at(square) in _TRAPPABLE
        and board.is_attacked_by(pov, square)
        and not escapes.get(square, False)
    }


def _trapped_candidates(
    board: chess.Board, move: chess.Move
) -> list[tuple[int, frozenset[int]]]:
    """Enemy pieces this move traps, each with the squares it can be cashed on.

    A trapped piece is attacked and has nowhere safe to go, so it is collected
    either where it stands or wherever it runs to — which is why the targets are
    its square *and* every square it can flee to. Anything narrower would let the
    piece dodge the material test simply by moving.

    One candidate per piece rather than one union of all of them: a finding then
    proves that a *named* piece falls, and the square it is anchored to is never
    in doubt.

    Three exclusions, each of which was producing wrong findings before it was
    added — see EXPLANATIONS.md for the measurements:

    * **Checking moves.** Under check only evasions are legal, so every other
      enemy piece has no legal move at all and so reads as having nowhere to go.
      That is a check, not a trap; it was 65 % of findings.
    * **Absolutely pinned pieces.** A pinned piece has no legal moves either, for
      a reason this layer has already decided it cannot express soundly. Calling
      it trapped names the wrong mechanism; it was 36.2 % of findings.
    * **Pieces that were already trapped**, tested with a null move so that the
      opponent gets the turn without anything else changing. Without it the rule
      credits this move for a piece that had been stuck for ten plies.
    """
    pov = board.turn
    after = board.copy(stack=False)
    after.push(move)
    if after.is_check():
        return []

    them = not pov
    now = {s for s in _boxed_in(after, pov) if not after.is_pinned(them, s)}
    if not now:
        return []
    if not board.is_check():
        # A null move is illegal under check, and a move that answers a check
        # changes too much for "was it already trapped" to have a clean answer.
        # Treating every piece as newly trapped there is the permissive branch,
        # and the material test still has to agree before anything is claimed.
        probe = board.copy(stack=False)
        probe.push(chess.Move.null())
        now -= _boxed_in(probe, pov)
    if not now:
        return []

    out = []
    for square in sorted(now):
        flights = {r.to_square for r in after.legal_moves if r.from_square == square}
        out.append((square, frozenset(flights | {square})))
    return out


def _choose_cash(
    board: chess.Board, pov: chess.Color, targets: set[int]
) -> tuple[float, chess.Move | None]:
    """The best exchange on a named target the mover can safely take.

    Cashing must prove itself safe. Greedily grabbing the most valuable forked
    piece is not a strategy: checked against an engine's own defence, the mover
    won a bishop and was mated next move (`Nxf6+ Kf7 Nxd7 Rxe1#`). Every
    candidate is therefore charged for whatever the defender wins straight
    back, and taking nothing is always allowed.
    """
    if board.turn != pov:
        return 0.0, None
    best, best_move = 0.0, None
    for move in list(board.legal_moves):
        if not board.is_capture(move) or move.to_square not in targets:
            continue
        gain = see(board, move)
        if gain <= 0.0:
            continue
        cashed = board.copy(stack=False)
        cashed.push(move)
        if _mate_in_one(cashed) is not None:
            continue
        recovery = max((v for _, v in _winning_captures(cashed, 0.0).values()), default=0.0)
        value = gain - max(0.0, recovery)
        if value > best:
            best, best_move = value, move
    return best, best_move


def _won_after_defence(
    board: chess.Board, move: chess.Move, targets: set[int], threshold: float
) -> tuple[float, chess.Move | None]:
    """Material the mover is up once the defender has answered, worst case.

    Counted from *after* the move, never from before it. Counting from before
    makes every recapture a win: measured that way over stored plies, 54.6 % of
    firings had the evaluation fall while the rule claimed material, and the
    samples were plain recaptures — `Qxf6` restoring the balance read as
    winning a bishop. A motif claims the move creates something new, so only
    what it wins afterwards counts.

    Returns the material and the square it is won on, so a caller can say which
    piece falls rather than only how much it was worth.
    """
    pov = board.turn
    after = board.copy(stack=False)
    after.push(move)
    start = _material(after, pov)

    replies = list(after.legal_moves)
    if not replies:
        # Mate and stalemate are not material claims; `missed_mate` owns mate.
        return 0.0, None

    worst: float | None = None
    won_square: int | None = None
    for reply in replies:
        nb = after.copy(stack=False)
        nb.push(reply)
        gain, cash = _choose_cash(nb, pov, targets)
        value = (_material(nb, pov) - start) + gain
        if worst is None or value < worst:
            worst = value
            won_square = cash.to_square if cash is not None else None
            if worst < threshold:
                return worst, None
    return (worst if worst is not None else 0.0), won_square


# ── refutation: what the capture is worth once it has been answered ──────────
#
# The motifs were built against the minimax above and the cheap rules were not,
# which left rules 1, 2 and 7 resting on SEE alone. SEE settles the exchange on
# one square and asks nothing about the rest of the board, so a capture it calls
# favourable can be answered by mate or by a bigger capture elsewhere — and the
# rule then reports a piece dropped that nobody can actually take. The case that
# found this is game 2864 ply 37, a required case in `tests/test_explain.py`.

def _survives_reply(
    board: chess.Board, capture: chess.Move, threshold: float
) -> float | None:
    """What `capture` still wins once the other side has replied, or None when it
    is refuted — by mate, or by enough material coming back.

    The SEE value is the starting point and the ceiling, because SEE already
    settles the contested square at full depth: both sides recapture there until
    one declines. What it cannot see is a reply that *ignores* the square, so
    that is all this adds. Every legal answer except a recapture on the square
    SEE accounted for is tried, and one that captures is credited at its own SEE
    — the counter-capture has to be sound too, or an even trade would read as
    material coming back.

    Only lowering the value, never raising it, is what keeps this from becoming a
    second opinion that disagrees with SEE about plain exchanges. A finding that
    survives here is one both measurements support.

    **A counter-capture only counts for what this capture added to it**, tested
    with a null move the way `_baseline_hanging` tests a loose piece. Crediting
    every counter-capture was measured first and it suppressed plain truths:
    "Qxg4 would have won the pawn on g4" was dropped because the opponent then
    takes a pawn on e5 — a pawn that was loose beforehand and stays loose
    whichever move is played. What refutes a capture is material the capture
    itself hands back, and that is what `Bxb5 Bxd5` is: taking on b5 walks the
    bishop off the diagonal that was guarding d5.

    The mate branch carries no such test. A mate available regardless is not a
    reason to credit the capture — it is a reason the material was never the
    story, and the mate rules say so first.
    """
    net = see(board, capture)
    won = _immediate_gain(board, capture)

    taken = board.copy(stack=False)
    taken.push(capture)
    if taken.is_checkmate():
        return net              # the capture is mate; nothing answers it
    already: dict[int, tuple[chess.Move, float]] | None = None

    for reply in list(taken.legal_moves):
        if reply.to_square == capture.to_square:
            continue            # SEE settled this square already
        taken.push(reply)
        mate = taken.is_checkmate()
        taken.pop()
        if mate:
            return None         # refuted by mate
        if not taken.is_capture(reply):
            continue
        if already is None:
            passed = board.copy(stack=False)
            passed.push(chess.Move.null())
            already = _winning_captures(passed, threshold)
        prior = already.get(reply.to_square)
        back = see(taken, reply) - (prior[1] if prior is not None else 0.0)
        if back <= 0.0:
            continue
        net = min(net, won - back)
        if net < threshold:
            return None         # refuted by material coming back
    return net


def _holds_after_reply(
    board: chess.Board, capture: chess.Move, threshold: float
) -> float | None:
    """What `capture` still wins once the other side has made its best reply — any
    reply, counter-captures of material that was already loose included — or None
    when that leaves it short of `threshold` or the reply mates.

    This is the test for a claim that a capture **works**: "Bxf3 takes it", "dxc5
    wins it". `_survives_reply` discounts a counter-capture of anything loose before
    the capture, and that is a tempo blind spot for such a claim (EX-IT-T): in game
    285, 11...d6 attacks the rook on e5, so "dxc5 wins it" is false — White has to
    save the rook — yet the rook counts as "already loose" and is discounted.
    Measured, 26.2 % of `ignored_threat` findings were tempo-refuted, and those were
    taken on the next ply about half as often as the rest.

    The two-ply minimax `_won_after_defence` gives the motifs, with **one deliberate
    difference**: after the reply the capturer may recapture on the square the reply
    landed on, as well as on the capture square. Cashing only on the capture square —
    the motifs' rule, applied literally — means a reply that grabs a *defended* pawn
    anywhere else cannot be answered and counts in full, and with
    `EXPLAIN_MIN_MATERIAL` at one pawn, a single loose pawn then refutes any pawn
    claim. Measured that way it removed 46.9 % of `hangs_piece`, and 40.7 % of the
    pieces it removed were still captured on the next ply: deleting real claims
    (owner ruling 2026-10-22, EXPLANATIONS.md).

    Never worth more than SEE, as with `_survives_reply`, so it only ever lowers a
    claim. **Not** used where a rule claims a piece is *safe* — see
    `_capture_claims`.
    """
    net = see(board, capture)
    pov = board.turn
    start = _material(board, pov)
    taken = board.copy(stack=False)
    taken.push(capture)
    if taken.is_checkmate():
        return net
    replies = list(taken.legal_moves)
    if not replies:
        return None             # stalemate: not a material claim
    worst: float | None = None
    for reply in replies:
        answered = taken.copy(stack=False)
        answered.push(reply)
        if answered.is_checkmate():
            return None         # refuted by mate
        targets = {capture.to_square}
        if taken.is_capture(reply):
            targets.add(reply.to_square)
        gain, _ = _choose_cash(answered, pov, targets)
        value = _material(answered, pov) - start + gain
        worst = value if worst is None else min(worst, value)
        if worst < threshold:
            return None
    return min(net, worst)


def _surviving_captures(
    board: chess.Board, threshold: float, *, gate=None
) -> dict[int, tuple[chess.Move, float]]:
    """`_winning_captures`, less the captures the other side refutes in reply.

    The value carried is the minimax net rather than the SEE value, so a caller
    reporting material reports what survived the reply.

    `gate` judges each capture; `_survives_reply` by default. That default is the
    **safety** side — "is this piece still winnable after the best move?" — and it
    stays permissive on purpose; `_capture_claims` is the claim side.
    """
    gate = _survives_reply if gate is None else gate
    out: dict[int, tuple[chess.Move, float]] = {}
    for square, candidates in _capture_candidates(board, threshold).items():
        best: tuple[chess.Move, float] | None = None
        for move, _see_value in candidates:
            net = gate(board, move, threshold)
            if net is None:
                continue
            if best is None or net > best[1]:
                best = (move, net)
        if best is not None:
            out[square] = best
    return out


def _takes_on(board: chess.Board, line, square: int) -> bool:
    """Whether `line` (UCI from `board`, the capturer to move) captures the piece on `square`
    with one of the side-to-move's moves before that piece moves away."""
    capturer = board.turn
    b = board.copy(stack=False)
    for uci in line:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if move not in b.legal_moves:
            return False
        if b.turn == capturer and move.to_square == square and b.is_capture(move):
            return True
        if b.turn != capturer and move.from_square == square:
            return False                      # the piece ran (or took something)
        b.push(move)
    return False


def _confirmed_by_line(board: chess.Board, line, square: int, named: float) -> bool:
    """L1: whether the stored refutation `line` (UCI moves from `board`, the position after the
    played move, the opponent to move) confirms the named loss: it **takes the piece on
    `square`** (a check or another capture may come first) and the opponent keeps at least
    `named` less a pawn by F1's measure (`pv_reading.kept_first`; a line that mates keeps
    everything). A line that wins material some other way — the piece runs, or the engine mates
    without taking it — does not confirm "— X wins it". No line, or one that does not start
    legally, confirms nothing."""
    if not line or not _takes_on(board, line, square):
        return False
    from zugzwang.core import pv_reading as P     # pv_reading imports this module
    try:
        lr = P.read_line(board.fen(), list(line), not board.turn, attack_from=0)
    except (ValueError, AssertionError):
        return False
    if lr.stopped_at == 0 or not lr.steps:
        return False
    return P.kept_first(lr) >= named - _VALUE[chess.PAWN] - 1e-9


def _capture_claims(board: chess.Board, threshold: float, *,
                    hold_names_piece: bool = True,
                    refutation=None) -> dict[int, tuple[chess.Move, float]]:
    """The captures a rule may claim *work*, judged by `_holds_after_reply`.

    This is `exposed` — what rules 1, 7 and 12 say the opponent wins. The safety side
    (`still`, "is it safe after the best move") keeps `_surviving_captures`' default
    gate, and the asymmetry is deliberate (owner ruling 2026-10-22): the strict gate
    there *adds* findings, because a smaller `still` makes more pieces look rescued —
    1 717 more `ignored_threat` findings, taken on the next ply 41.6 % of the time
    against 56.7 % for those kept. "Does this capture work" and "is this piece safe"
    are different questions, and a shared test would be tidiness, not correctness.

    `missed_material` (rule 2) does not come here either. It is the one comparative
    rule — the best move *against* the played move — so material loose under both
    branches belongs to the position, and `_survives_reply`'s discount is right for it.
    Its own differential test is specified, unbuilt: EX-MM-DIFF.

    **T-HOLD (2026-11-14; EXPLANATIONS.md "T-HOLD").** A claim names the piece on its
    square. "You left the queen on c8 hanging — Rxc8 wins it." was false where Nc4 attacked
    the other queen: Rxc8 Nxb6 Bxb6 holds a knight (3.0), not the queen (SEE 9). So a claim
    is kept only where the hold is within a pawn of what the capture was said to win — the
    piece, or SEE's exchange on its square where that is less: the reply may take back a
    pawn, not the piece. Silent otherwise; the engine-line claim may speak instead. (As
    written, "the hold at least the piece's value", the decision also silenced SEE's own
    exchanges — game 285's knight for a pawn, `ignored_threat`'s required case, and GR2-2's
    queen for a rook; measured, not built: EXPLANATIONS.md "T-HOLD as built".)
    `hold_names_piece=False` keeps the pre-T-HOLD set: labelling's T3
    (`labelling.hangs_material`) reads the material lost, not the name, and labels must not
    move with a wording fix.

    **L1 (owner, 2026-11-14; EXPLANATIONS.md "L1") replaces T-HOLD's silence.** The two-ply
    hold is a static witness; the engine's stored refutation is the deeper one. A claim whose
    hold falls short is silenced **only where the stored line from this position does not
    confirm the named loss**: `refutation`, ply N+1's stored line (the engine's best reply to
    the played move), must take the named piece and win the opponent at least what the claim
    names — by F1's measure, within the same pawn as the hold test. T-HOLD's case stays silent (20.Nc4: the
    refutation keeps a knight, not the queen); a piece the line does win comes back. Without a
    refutation (a caller holding one ply alone) nothing confirms, so it stays silent.
    """
    claims = _surviving_captures(board, threshold, gate=_holds_after_reply)
    if not hold_names_piece:
        return claims
    def named(sq: int) -> float:     # en passant lands on an empty square: a pawn
        pc = board.piece_at(sq)
        return _VALUE[pc.piece_type] if pc is not None else _VALUE[chess.PAWN]
    out = {}
    for sq, (move, net) in claims.items():
        said = min(named(sq), see(board, move))
        if net >= said - _VALUE[chess.PAWN] - 1e-9 or \
                _confirmed_by_line(board, refutation, sq, said):
            out[sq] = (move, net)
    return out


# ── rules ────────────────────────────────────────────────────────────────────

def explain_ply(
    fen_before: str,
    played_uci: str,
    *,
    best_uci: str | None = None,
    score_before_mate: int | None = None,
    score_after_mate: int | None = None,
    threshold: float | None = None,
    deep_after_stored: bool = False,
    deep_after_mate: int | None = None,
    hold_names_piece: bool = True,
    refutation=None,
) -> list[Finding]:
    """Every finding this layer can prove about one ply.

    Takes no engine. Stage 1 shipped without a live-search rule because the one
    proposed could not be shown to measure anything — see EXPLANATIONS.md — so
    the whole layer runs on the board plus the scores already stored for the
    ply. That also settles the no-engine case the fresh-install audit raised:
    there is no degraded mode here, because there is nothing to degrade.

    Returns findings unordered; `rank_findings` imposes the display order.

    `deep_after_stored` / `deep_after_mate`: the deeper stored search of the position
    after the move — ply N+1's before-search, or the run's final lines on the last ply
    (owner rulings AUDIT-4, AUDIT-5, AUDIT-13, 2026-11-11). `deep_after_mate` is from
    the mover's side, `None` meaning no forced mate; it is read only when
    `deep_after_stored` says one exists. `score_after_mate` (the depth-10 after-search)
    is read only where none is.

    `hold_names_piece` (T-HOLD, `_capture_claims`): False only for labelling's T3, which
    must not move with the wording.

    `refutation` (L1): ply N+1's stored line, UCI moves from the position after the played
    move (the run's final lines on the last ply) — what confirms a capture claim whose
    two-ply hold falls short (`_capture_claims`).
    """
    threshold = C.EXPLAIN_MIN_MATERIAL if threshold is None else threshold

    try:
        board = chess.Board(fen_before)
        played = chess.Move.from_uci(played_uci)
    except ValueError:
        return []
    if played not in board.legal_moves:
        return []

    played_ref = _ref(board, played)
    best: chess.Move | None = None
    if best_uci:
        try:
            candidate = chess.Move.from_uci(best_uci)
        except ValueError:
            candidate = None
        if candidate is not None and candidate in board.legal_moves:
            best = candidate

    baseline = _baseline_hanging(board, threshold)
    played_see = see(board, played) if board.is_capture(played) else None

    after = board.copy(stack=False)
    after.push(played)
    exposed = _capture_claims(after, threshold, hold_names_piece=hold_names_piece,
                              refutation=refutation)

    findings: list[Finding] = []
    findings += _rule_hangs_piece(
        board, played, played_ref, played_see, baseline, exposed, after, best
    )
    findings += _rule_missed_material(board, played, played_ref, played_see, best, threshold)
    findings += _rule_missed_mate(
        board, played, played_ref, after, best, score_before_mate,
        deep_after_mate if deep_after_stored else score_after_mate,
    )
    findings += _rule_walks_into_mate(
        after, played_ref, score_before_mate, score_after_mate,
        deep_after_stored, deep_after_mate,
    )
    findings += _rule_best_saves(board, played, best, baseline, exposed, threshold)
    findings += _rule_ignored_threat(
        board, played, played_ref, best, baseline, exposed, after, threshold
    )

    motif_min = C.EXPLAIN_MIN_MOTIF_MATERIAL
    findings += _rule_motifs(board, played, played_ref, "played", motif_min)
    if best is not None and best != played:
        findings += _rule_motifs(board, best, _ref(board, best), "best", motif_min)
    return findings


def _rule_hangs_piece(
    board, played, played_ref, played_see, baseline, exposed, after, best=None
):
    """Rule 1. A piece of the mover's became capturable *because of this move*.

    The "because of this move" half is the entire rule. Without it, a piece that
    has been hanging for five moves gets blamed on whichever move is on screen.

    `best` is taken only to stamp `PATTERN_FORCED`. A hang on the engine's own
    first choice is still a hang, so the finding is unchanged — but "this drops a
    knight" under a `Best move` badge reads as the layer contradicting itself, and
    the fact that resolves it is one the rule can see and the renderer cannot.
    """
    forced = best is not None and best == played
    out = []
    for square, (capture, value) in exposed.items():
        if square == played.to_square:
            # The piece that just moved. A capture that comes out even or ahead
            # is a sound trade, and the recapture is part of it, not a hang.
            if played_see is not None:
                if played_see >= 0:
                    continue
                material = played_see
            else:
                if played.from_square in baseline:
                    continue  # it was already loose where it stood
                material = -value
        else:
            if square in baseline:
                continue  # already winnable before this move
            material = -value

        victim = _piece_on(after, square)
        if victim is None:
            continue
        out.append(Finding(
            kind="hangs_piece",
            subject="played",
            basis=BASIS_SEE,
            pieces=(victim,),
            moves={"played": played_ref, "refutation": _ref(after, capture)},
            material=round(material, 2),
            pattern=PATTERN_FORCED if forced else None,
            about=_about(MoveRole.PLAYED, played_ref),
        ))
    return out


def _rule_missed_material(board, played, played_ref, played_see, best, threshold):
    """Rule 2. The best move wins material the played move does not.

    The best move's capture goes through the refutation gate as well: SEE is the
    same blind witness here, and "Nxe4 would have won the knight on e4" is not
    worth saying if taking on e4 opens a line onto the queen.

    The played move's own capture is *not* re-measured, so the played move is
    charged at its SEE value. That only ever makes `delta` smaller, and a smaller
    delta claims less.
    """
    if best is None or best == played or not board.is_capture(best):
        return []
    best_gain = _survives_reply(board, best, threshold)
    if best_gain is None:
        return []
    played_gain = max(played_see or 0.0, 0.0)
    delta = best_gain - played_gain
    if delta < threshold:
        return []
    victim = _piece_on(board, best.to_square)
    best_ref = _ref(board, best)
    return [Finding(
        kind="missed_material",
        subject="played",
        basis=BASIS_SEE,
        pieces=(victim,) if victim else (),
        moves={"played": played_ref, "best": best_ref},
        material=round(delta, 2),
        about=_about(MoveRole.BEST, best_ref),
    )]


def _rule_missed_mate(
    board, played, played_ref, after, best, score_before_mate, score_after_mate
):
    """Rule 3. Mate was available and this move gave it up.

    "Gave it up" is the whole rule. Playing a different mating move, or a
    slower one, misses nothing, and that is the common case rather than the
    exception: of the stored plies where mate was available, 2524 of 3478
    classified `excellent` still had a forced mate after the move was played.
    Without these two guards the rule told the reader they had missed a mate
    they were in fact still delivering.

    **The guard reads the deeper score** (owner ruling AUDIT-4, 2026-11-11): the
    caller passes ply N+1's depth-14 search of the position after the move as
    `score_after_mate` where one is stored, and the depth-10 after-search only where
    none is. On the depth-10 score alone the guard let 280 of 956 sentences through
    on moves after which the deeper search still had the mover mating
    (`review/AUDIT_CLAIMS.md`, finding 4).
    """
    if after.is_checkmate():
        return []
    if best is not None and played == best:
        return []
    if score_after_mate is not None and score_after_mate > 0:
        return []
    mate_move = _mate_in_one(board)
    if mate_move is not None:
        pawns = _back_rank(board, mate_move)
        mate_ref = _ref(board, mate_move)
        return [Finding(
            kind="missed_mate",
            subject="played",
            basis=BASIS_BOARD,
            pieces=pawns,
            moves={"played": played_ref, "best": mate_ref},
            mate_in=1,
            pattern=PATTERN_BACK_RANK if pawns else None,
            about=_about(MoveRole.BEST, mate_ref),
        )]
    if score_before_mate is not None and score_before_mate > 0:
        moves = {"played": played_ref}
        if best is not None:
            moves["best"] = _ref(board, best)
        return [Finding(
            kind="missed_mate",
            subject="played",
            basis=BASIS_ENGINE,
            moves=moves,
            mate_in=score_before_mate,
            about=_about(MoveRole.BEST, moves.get("best")),
        )]
    return []


def _rule_walks_into_mate(after, played_ref, score_before_mate, score_after_mate,
                          deep_after_stored=False, deep_after_mate=None):
    """Rule 4. This move handed the opponent a forced mate.

    A mover who was already being mated before they moved has not walked into
    anything, and blaming the move on screen would point the reader at the
    wrong one -- the same trap rule 1 avoids for a loose piece. On the stored
    plies this was nearly the whole signal: 2517 of the 2644 `best` moves with
    mate against them afterwards were already lost beforehand.

    **Where a deeper search of the position after the move is stored** (ply N+1's
    before-search, or the run's final lines), the engine branch takes its length from
    it (owner ruling AUDIT-5) and is silent if it sees no forced mate against the
    mover (AUDIT-13). It still fires only where the depth-10 after-search saw a mate:
    the rulings set the length and the silence, not new firings. The board branch is
    a mate in one, proved exactly, and is unchanged.
    """
    if after.is_checkmate():
        return []  # the mover just delivered mate, not walked into one
    if score_before_mate is not None and score_before_mate < 0:
        return []
    mate_move = _mate_in_one(after)
    if mate_move is not None:
        pawns = _back_rank(after, mate_move)
        return [Finding(
            kind="walks_into_mate",
            subject="played",
            basis=BASIS_BOARD,
            pieces=pawns,
            moves={"played": played_ref, "refutation": _ref(after, mate_move)},
            mate_in=1,
            pattern=PATTERN_BACK_RANK if pawns else None,
            about=_about(MoveRole.PLAYED, played_ref),
        )]
    if score_after_mate is not None and score_after_mate < 0:
        mate_in = abs(score_after_mate)
        if deep_after_stored:
            if deep_after_mate is None or deep_after_mate >= 0:
                return []
            mate_in = abs(deep_after_mate)
        return [Finding(
            kind="walks_into_mate",
            subject="played",
            basis=BASIS_ENGINE,
            moves={"played": played_ref},
            mate_in=mate_in,
            about=_about(MoveRole.PLAYED, played_ref),
        )]
    return []


def _defence_is_caused(
    board: chess.Board, after_best: chess.Board, best: chess.Move, square: int
) -> bool:
    """Whether `best` is *why* `square` is defended, rather than merely a move
    played in a position where it happens to be.

    `still` establishes that the square is no longer winnable; it does not
    establish that this move is the reason, and the rule used to claim the one
    from the other. The case that found it: "Rhg8 would have defended the pawn on
    c5", where Rhg8 has nothing to do with c5 — the pawn stays defended because
    the king never steps to b8 and unpins the d6 pawn. The claim was about a
    *different* move's side-effect, and no wording of the sentence makes that
    true.

    Two mechanisms are accepted, both of which the board proves outright:

    * a piece this move put somewhere now attacks the square. Read off the
      squares the mover newly occupies rather than off `best.to_square`, so
      castling is covered by the rook it moves as well as by the king.
    * the move vacated a square on the line between a defender and the piece,
      which is the discovered-attack test run in the mover's own favour.

    A third real mechanism is deliberately not here: the best move can make a
    piece safe by capturing or blocking its attacker, with no new defender
    involved. That is a true rescue and "would have defended" is the wrong
    sentence for it, so it stays silent until it has a rule and a verb of its
    own.
    """
    mover = board.turn
    fresh = after_best.attackers(mover, square) - board.attackers(mover, square)
    if not fresh:
        return False
    arrived = after_best.occupied_co[mover] & ~board.occupied_co[mover]
    vacated = chess.SquareSet(board.occupied_co[mover] & ~after_best.occupied_co[mover])
    for source in fresh:
        if chess.BB_SQUARES[source] & arrived:
            return True
        if any(chess.BB_SQUARES[s] & chess.between(source, square) for s in vacated):
            return True
    return False


def _rule_best_saves(board, played, best, baseline, exposed, threshold):
    """Rule 7. What the best move does about the piece the played move loses —
    the "Bd2 defends it" half of an explanation.

    `exposed` is read off the board *after* the played move, but the piece this
    names is read off the board *before* it, so the played move's destination
    square would name whatever stood there first — the opponent's piece, when the
    played move was a capture. In the best move's line that piece is still on the
    board and belongs to the other side, so "Bc4 would have defended the queen on
    e7" was about the queen Qxe7 had just taken. Measured over all 157 178 stored
    plies: 6727 of 15 282 `best_defends_piece` findings, 44.0 %, and the set was
    exactly the destination squares — no correct finding sits on one, because a
    non-capturing destination has no piece before the move and is skipped below.

    `baseline` applies rule 1's "because of this move" test, which this rule read
    `exposed` without. A piece loose before the played move was not dropped by it,
    so rule 1 stays silent — and the rescue then had nothing to rescue from, which
    rendered as "O-O would have defended the pawn on f3" with no sentence saying
    f3 was in trouble. Measured on the emitted sentences: 6284 of 25 607 blocks,
    24.5 %, were a rescue with no danger named.

    Both sets it reads are refutation-aware, and the two corrections pull in
    opposite directions: a danger that was never real drops a finding, while a
    piece still nominally capturable after the best move keeps one, because a
    capture the mover refutes is not a capture. `_defence_is_caused` then asks the
    question neither set answers, which is whether this move is the reason.
    """
    if best is None or not exposed:
        return []
    after_best = board.copy(stack=False)
    after_best.push(best)
    still = _surviving_captures(after_best, threshold)
    out = []
    for square in exposed:
        if square in still:
            continue
        if square == played.to_square:
            continue
        if square in baseline:
            continue
        piece_before = _piece_on(board, square)
        moved_away = best.from_square == square
        if piece_before is None and not moved_away:
            continue
        if moved_away:
            # The piece ran, so causation is that it is safe where it landed —
            # which `still` is keyed on the vacated square to answer, and does
            # not. Nothing else about the move needs proving.
            if best.to_square in still:
                continue
            piece_before = _piece_on(after_best, best.to_square)
            if piece_before is None:
                continue
        elif not _defence_is_caused(board, after_best, best, square):
            continue
        best_ref = _ref(board, best)
        out.append(Finding(
            kind="best_saves_piece" if moved_away else "best_defends_piece",
            subject="best",
            basis=BASIS_SEE,
            pieces=(piece_before,),
            moves={"best": best_ref},
            about=_about(MoveRole.BEST, best_ref),
        ))
    return out


def _rule_ignored_threat(
    board, played, played_ref, best, baseline, exposed, after, threshold
):
    """Rule 12. The piece was already loose, this move did nothing about it, and the
    engine's move would have — "you left the knight on c5 hanging".

    This is the shape rule 1 declines by design: its `square in baseline` test
    keeps a piece loose for five moves from being blamed on the move on screen, as
    *dropping* it. What the move on screen can still be blamed for is not rescuing
    it, and that needs a proof rule 1 never asks for: that a rescue existed. So the
    square has to be in `baseline` (loose before), in `exposed` (still loose after
    the played move) and **not** winnable after the best move. Without the third
    clause this would blame a move for a piece no move could save.

    The third clause is read on the square, as specified, and deliberately not
    moved with the piece the way `_rule_best_saves` follows a piece that runs. The
    required case is why: in game 285 the best move is 12...Nxb3, the knight
    trading itself for the bishop, and b3 is "still winnable" afterwards only in
    the sense that axb3 recaptures. A piece that leaves by an even trade has been
    rescued, and reading the clause on its landing square would call that a loss.

    The played move's own piece is excluded: rule 1 owns `played.to_square`, and a
    piece that moved from one loose square to another was not left anywhere.

    Disjoint from rule 1 by construction: rule 1 requires the square absent from
    `baseline` and this rule requires it present. Disjoint from rule 7 the same
    way, which skips `baseline` squares — so the rescue rule 7 would have named
    stays unnamed here too, and the sentence carries the capture instead.

    The material is what the opponent wins: the surviving-capture net `exposed`
    carries, the counting rule 1 reports.
    """
    if best is None or best == played:
        return []
    carried = [
        s for s in exposed
        if s in baseline and s != played.to_square
    ]
    if not carried:
        return []
    after_best = board.copy(stack=False)
    after_best.push(best)
    still = _surviving_captures(after_best, threshold)
    out = []
    for square in carried:
        victim = _piece_on(after, square)
        if victim is None or victim != _piece_on(board, square):
            continue
        if square in still:
            continue
        capture, value = exposed[square]
        out.append(Finding(
            kind="ignored_threat",
            subject="played",
            basis=BASIS_SEE,
            pieces=(victim,),
            moves={"played": played_ref, "refutation": _ref(after, capture)},
            material=round(-value, 2),
            about=_about(MoveRole.PLAYED, played_ref),
        ))
    return out


# When several motifs win the same piece, more material wins and this breaks the
# tie -- towards the motif naming the *mechanism*. A discovery explains why the
# opponent could not answer (two pieces threaten at once and only one moved),
# which a bare "fork" does not. `trapped_piece` ranks last because its measured
# value is the 70 % of its findings that no other rule produces at all, so where
# another motif already explains the same piece falling it should defer. Measured
# over all 157 178 stored plies, adding it changed no other rule's count.
_MOTIF_RANK = {"discovered_attack": 0, "fork": 1, "skewer": 2, "trapped_piece": 3}


def _rule_motifs(board, move, move_ref, subject, threshold):
    """Rules 8–11. Fork, skewer, discovered attack and trapped piece — a named
    geometry that has been shown to win material against every legal defence.

    Fires for a move the player made and for one they did not; `subject` says
    which, and stage 3 phrases a found tactic differently from a missed one.
    """
    if move is None:
        return []
    after = board.copy(stack=False)
    after.push(move)

    # (kind, targets, anchor, on_the_line). `anchor` is the square the finding is
    # *about*, or None to mean "whichever square the material is won on". Fork and
    # skewer win the piece they name, so they need no anchor; a trapped piece can
    # be cashed on a square it flees to, which is empty now and names no piece at
    # all. `on_the_line` is only used by discovered attack, to record which branch
    # the finding proved once the material test has said where the material falls.
    proposed: list[tuple[str, frozenset[int], int | None, frozenset[int]]] = [
        (kind, targets, None, frozenset())
        for kind, targets in _motif_candidates(after, move.to_square)
    ]
    discovered = _discovered_candidate(board, move)
    if discovered is not None:
        targets, on_the_line = discovered
        proposed.append(("discovered_attack", targets, None, on_the_line))
    proposed += [
        ("trapped_piece", targets, square, frozenset())
        for square, targets in _trapped_candidates(board, move)
    ]

    best: dict[int, tuple[str, frozenset[int], int | None, float, frozenset[int]]] = {}
    candidates = sorted(proposed, key=lambda c: (c[0], sorted(c[1])))
    for kind, targets, anchor, on_the_line in candidates:
        material, won_square = _won_after_defence(board, move, set(targets), threshold)
        if material < threshold or won_square is None:
            continue
        # One piece falls once. `Qc7+` in a real game attacks the king and the
        # e7 bishop, and also lines the bishop up in front of the f7 pawn along
        # the rank — fork and skewer, both true, both winning the same bishop.
        # Emitting both spends two of three render slots describing one tactic,
        # so the square keeps a single finding. `_MOTIF_RANK` breaks the tie
        # towards the double attack, which is why the defender cannot answer.
        key = won_square if anchor is None else anchor
        prior = best.get(key)
        if prior is not None and (prior[3], -_MOTIF_RANK[prior[0]]) >= (
            material, -_MOTIF_RANK[kind]
        ):
            continue
        best[key] = (kind, targets, anchor, material, on_the_line)

    out = []
    for key, (kind, targets, anchor, material, on_the_line) in sorted(best.items()):
        # The piece that actually falls leads, so a renderer naming one piece
        # names the right one. For a trapped piece that is the piece itself and
        # nothing else: its other targets are the squares it could run to, which
        # hold either nothing or one of the *mover's* own pieces.
        ordered = [key] if anchor is not None else [key] + sorted(targets - {key})
        pieces = tuple(
            piece for piece in (_piece_on(after, square) for square in ordered)
            if piece is not None
        )
        if not pieces:
            continue
        pattern = None
        if kind == "discovered_attack":
            # `key` is the square the material was proved on, so this asks the
            # exact question the sentence needs: is the piece that falls one the
            # opened line reaches, or one the moved piece took under cover of the
            # discovered check?
            pattern = (
                PATTERN_DISCOVERED_LINE if key in on_the_line
                else PATTERN_DISCOVERED_CHECK
            )
        out.append(Finding(
            kind=kind,
            subject=subject,
            basis=BASIS_SEE,
            pieces=pieces,
            moves={subject: move_ref},
            material=material,
            pattern=pattern,
            about=_about(MoveRole(subject), move_ref),
        ))
    return out


_MATE_KINDS = ("missed_mate", "walks_into_mate")

# Which move each sentence opens with is carried by each finding (`Finding.about`,
# STAGE5-MOVE, built 2026-11-19); the table that implied it from the kind (`NAMES_MOVE`)
# is gone. **It is not the same question as `subject`.** `missed_material` and
# `missed_mate` carry `subject="played"` because they are findings *about* the played
# move, yet the sentence they produce names the best move. Ordering on `subject` therefore
# mixed "what this move cost" with "what a different move offered" into one tier, which is
# how a 5-pawn rook the player never won came to outrank the 3-pawn knight they actually
# dropped.


# The columns `explain_stored_ply` reads. Exported so a caller builds its SELECT
# from this list instead of guessing, and so adding an input to the layer is one
# edit rather than one edit per probe.
STORED_PLY_COLUMNS = (
    "fen_before",
    "played_uci",
    "best_uci",
    "classification",
    "score_before_cp",
    "score_before_mate",
    "score_after_cp",
    "score_after_mate",
)


def stored_ply_row(obj) -> dict:
    """Adapt a `MoveAnalysis` to the mapping `explain_stored_ply` expects.

    Driven by the column tuple, so it cannot omit one — which is the whole reason
    this exists rather than each caller writing the dict out.
    """
    return {c: getattr(obj, c) for c in STORED_PLY_COLUMNS}


def deep_after(after_row=None, after_lines=None) -> tuple[bool, int | None]:
    """The deeper stored search of the position a move created, from the MOVER's side:
    `(stored, mate)`. `after_row` is ply N+1's stored row (its before-search is that
    position at the run's full depth, MultiPV 3); `after_lines` the run's final lines,
    for the last ply. Both are from the side to move after the move — the opponent —
    so the mate is negated. `(False, None)` where nothing deeper is stored."""
    if after_row is not None:
        cp, mate = after_row["score_before_cp"], after_row["score_before_mate"]
        if cp is not None or mate is not None:
            return True, (-mate if mate is not None else None)
        return False, None      # the final lines belong to the last ply only
    lines = [ln for ln in (after_lines or ()) if ln.get("uci")]
    if lines and (lines[0].get("cp") is not None or lines[0].get("mate") is not None):
        mate = lines[0].get("mate")
        return True, (-mate if mate is not None else None)
    return False, None


def refutation_after(after_row=None, after_lines=None) -> tuple[str, ...]:
    """The engine's stored refutation of a move: ply N+1's best line (`pv_uci`, the line
    `compose` reads as the refutation), or the run's final lines on the last ply. UCI moves
    from the position after the move; () where nothing is stored."""
    if after_row is not None:
        return tuple((after_row["pv_uci"] or "").split()) if "pv_uci" in set(after_row.keys()) \
            else ()
    lines = [ln for ln in (after_lines or ()) if ln.get("uci")]
    return tuple(lines[0]["uci"]) if lines else ()


def explain_stored_ply(row, *, deep: tuple[bool, int | None] = (False, None),
                       refutation=None) -> list[Finding]:
    """Explain one ply that is already in `move_analyses`. Use this, not
    `explain_ply`, for anything reading the database.

    `explain_ply` takes its engine inputs as keyword arguments with `None`
    defaults, which is right for a position handed over in isolation and wrong
    for a stored ply, because omitting one is silent. Omitting the two mate scores
    leaves rules 3 and 4 on their board branch, which proves mate in one and
    nothing longer: measured over the corpus that hid 1261 long `missed_mate`
    findings *and* admitted mate-in-one findings the rules' own guards decline —
    wrong in both directions, with nothing in the output to suggest it.

    Every probe written for this layer made that mistake, which is the fourth time
    a caller assembling its own inputs has produced a quietly wrong measurement.
    So this function raises on a row missing any column rather than defaulting:
    a caller that has not supplied the data fails where it reads it.

    `row` is any mapping with the `STORED_PLY_COLUMNS` keys — `sqlite3.Row`, a
    dict, or anything else with `.keys()`.

    `deep` is `deep_after(...)` for this ply: the deeper stored search of the position
    after the move, which the mate rules read in place of the depth-10 after-search
    where it exists (AUDIT-4, -5, -13). A caller with the rest of the run passes it;
    `explain_text._stored_pairs` does.

    `refutation` is `refutation_after(...)` for this ply (L1): what confirms a capture claim
    whose two-ply hold falls short. Passed by the same callers as `deep`.
    """
    missing = [c for c in STORED_PLY_COLUMNS if c not in set(row.keys())]
    if missing:
        raise KeyError(
            f"explain_stored_ply needs {', '.join(missing)}; select "
            f"explain.STORED_PLY_COLUMNS rather than naming columns by hand"
        )
    return explain_ply(
        row["fen_before"],
        row["played_uci"],
        best_uci=row["best_uci"],
        score_before_mate=row["score_before_mate"],
        score_after_mate=row["score_after_mate"],
        deep_after_stored=deep[0],
        deep_after_mate=deep[1],
        refutation=refutation,
    )


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Display order: mate first, then what this move cost, then what another
    move offered.

    Four tiers, because "whose move is this about" and "what did it cost" are
    different questions and `subject` only answers the first — plus a last place
    for a long mate against the mover:

      0. mate, shortest first
      1. `subject="played"` and the sentence names the **played** move — what the
         move on screen actually did
      2. `subject="played"` and the sentence names the **best** move — what a
         different move would have done. Still a finding about the played move,
         which is why it outranks tier 3, but it is not something that happened.
      3. `subject="best"` — what the best move defends or saves
      4. a `walks_into_mate` of `MATE_DEMOTE_FROM` or more. It still leads a ply
         with nothing else to say; it only stops displacing something concrete. See
         the constants for why a missed mate is cut and this one is only demoted.

    Tiers 1 and 2 were one tier, sorted by material across both. A player who
    dropped a knight and also missed a rook was told about the rook first, which
    inverts the thing they need: the loss is on the board, the gain is
    hypothetical. See `Finding.about` for why `subject` cannot express this.

    Material still breaks ties *within* a tier, so two real losses order by size.
    """
    def key(f: Finding) -> tuple:
        if is_long_mate_against(f):
            return (4, f.mate_in or 99, 0.0)
        if f.kind in _MATE_KINDS:
            return (0, f.mate_in if f.mate_in is not None else 99, 0.0)
        names = f.about.role.value
        if f.subject == "played":
            return (1 if names == "played" else 2, 0, -abs(f.material or 0.0))
        return (3, 0, -abs(f.material or 0.0))

    return sorted(findings, key=key)
