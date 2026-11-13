"""The types the analysis split is built on (ANALYSIS_ARCHITECTURE.md §1, ARCH-1).

A `Description` is a checkable board fact, stated differentially: the same measurement
on the board after the played move and on the board after the best move. It carries no
verdict and no cause: no material, no refutation, no mate distance, no classification.
Which board is better belongs to the `Verdict`, and only a claim that passed gate P may
say why (`ProvenClaim`, stage 1's next step, not built yet).

None of these types inherits from another, and none has a `render` method: rendering a
`Description` is `describe.py`'s job and produces a `DescriptionText`, which is not the
claim renderer's output type. `slots=True` makes an extra attribute an error rather than
a silent addition, so a causal field cannot be bolted on at a call site.

**One subject per description** (owner finding A, 2026-11-08). A description names one
`Subject` (a piece, the king, a pawn, a file, a square, or a side) and measures that same
subject on both branches. "After Rxe5, the rook on e5 reaches 13 squares; after Bxe8, the
rook on e1 reaches eight" was two facts about a rook in two different places, not a
comparison. A `Subject` can be made only by this module's `pin_*` functions, which check
that the subject exists, unchanged, on both branches, and return None when it does not:
the descriptor then does not fire. The check lives in the type, not in the templates.

This module imports nothing from the explanation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import chess


class Descriptor(Enum):
    """One per definition in ANALYSIS_ARCHITECTURE.md §3. Closed: adding one means
    writing its definition there first."""

    CASTLING_RIGHTS = "castling_rights"        # D1
    PAWN_SHIELD = "pawn_shield"                # D2
    KING_RING_ATTACKED = "king_ring_attacked"  # D3
    PAWN_STRUCTURE = "pawn_structure"          # D4
    FILES = "files"                            # D5
    REACH = "reach"                            # D6
    NO_FORWARD_SQUARE = "no_forward_square"    # D7
    PAWN_COVER_GONE = "pawn_cover_gone"        # D8
    UNDEVELOPED = "undeveloped"                # D9
    ENGINE_LINE = "engine_line"                # stage 2: a non-forcing engine line


class Differential(Enum):
    """How the two branches' measurements differ. For a set-valued quantity:
    PLAYED_ONLY when the played branch's set strictly contains the best branch's,
    BEST_ONLY the reverse, BOTH_DIFFER otherwise. For a count: PLAYED_ONLY when the
    played branch's count is higher, BEST_ONLY when the best branch's is."""

    PLAYED_ONLY = "played_only"
    BEST_ONLY = "best_only"
    BOTH_DIFFER = "both_differ"


class Horizon(Enum):
    """Where on each branch the measurement is taken."""

    AFTER_MOVE = "after_move"   # stage 1: the board immediately after the move
    PV_END = "pv_end"           # reserved for stage 2


class SubjectKind(Enum):
    PIECE = "piece"     # a knight, bishop, rook or queen, on the same square on both branches
    KING = "king"       # a king, on the same square on both branches
    PAWN = "pawn"       # a pawn, on the same square on both branches
    FILE = "file"       # a file; `colour` set when the subject is one side's pawns on it
    SQUARE = "square"   # a square, seen from `colour`'s side
    SIDE = "side"       # one side as a whole (its castling rights, its development)


# The capability token. Referenced only inside this module (a test checks), so a
# `Subject` cannot be assembled at a call site without passing through a `pin_*` check.
_PIN = object()


@dataclass(frozen=True, slots=True)
class Subject:
    """What a description is about: one thing, present and identical on both branches."""

    kind: SubjectKind
    colour: bool | None = None         # chess.WHITE / chess.BLACK
    piece: str | None = None           # python-chess symbol, for PIECE / KING / PAWN
    square: str | None = None          # for PIECE / KING / PAWN / SQUARE
    file: str | None = None            # for FILE ("a".."h")
    token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.token is not _PIN:
            raise TypeError("a Subject is made only by findings.pin_*(), which checks "
                            "that it exists on both branches")


def _same_on(square: chess.Square, *boards: chess.Board) -> chess.Piece | None:
    """The piece on `square` if every board has that same piece there, else None."""
    first = boards[0].piece_at(square)
    if first is None or any(b.piece_at(square) != first for b in boards[1:]):
        return None
    return first


def pin_piece(square: chess.Square, before: chess.Board, b_played: chess.Board,
              b_best: chess.Board) -> Subject | None:
    """The piece on `square`, if neither move moved it or replaced it: the same piece
    stands there before the move and on both branches. Kings and pawns have their own
    kinds."""
    piece = _same_on(square, before, b_played, b_best)
    if piece is None:
        return None
    kind = {chess.KING: SubjectKind.KING, chess.PAWN: SubjectKind.PAWN}.get(
        piece.piece_type, SubjectKind.PIECE)
    return Subject(kind, colour=piece.color, piece=piece.symbol(),
                   square=chess.square_name(square), token=_PIN)


def pin_king(colour: chess.Color, before: chess.Board, b_played: chess.Board,
             b_best: chess.Board) -> Subject | None:
    """`colour`'s king, if it stands on the same square before and on both branches."""
    king = before.king(colour)
    if king is None:
        return None
    return pin_piece(king, before, b_played, b_best)


def pin_file(file_index: int, colour: chess.Color | None = None) -> Subject:
    """A file exists on every board. With `colour`, the subject is that side's pawns on it."""
    return Subject(SubjectKind.FILE, colour=colour, file=chess.FILE_NAMES[file_index],
                   token=_PIN)


def pin_square(square: chess.Square, colour: chess.Color) -> Subject:
    return Subject(SubjectKind.SQUARE, colour=colour, square=chess.square_name(square),
                   token=_PIN)


def pin_side(colour: chess.Color) -> Subject:
    return Subject(SubjectKind.SIDE, colour=colour, token=_PIN)


@dataclass(frozen=True, slots=True)
class PieceOn:
    """A piece a sentence will name. `piece` is the python-chess symbol, upper case
    for White ("N" = White knight, "q" = Black queen)."""

    piece: str
    square: str


@dataclass(frozen=True, slots=True)
class Fact:
    """One branch's measurement of the description's subject. Every square and piece a
    sentence names is here, so a sentence can be checked against the board it
    describes. `state` is a closed key for a categorical measurement (a pawn's
    "isolated", a file's "open"), rendered through a fixed table, never free text."""

    squares: tuple[str, ...] = ()
    pieces: tuple[PieceOn, ...] = ()
    count: int | None = None
    files: tuple[str, ...] = ()
    state: str = ""
    # For `engine_line`: the line's moves as numbered SAN ("12.Nxe5", "Bxe5", …), up to
    # where the description stops. Replayable from the ply's position.
    moves: tuple[str, ...] = ()
    # For `engine_line`: the pieces the mover took and gave along the line shown
    # (letters, same kinds cancelled); `count` is then the move number it stops at.
    took: tuple[str, ...] = ()
    gave: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Description:
    """A checkable board fact about one subject, stated differentially. No verdict, no
    causation.

    `played == best` produces no description of any kind, so a `best` move cannot
    carry one."""

    descriptor: Descriptor
    subject: Subject
    differential: Differential
    played: Fact
    best: Fact
    magnitude: float            # |played − best| in the descriptor's own unit
    horizon: Horizon
    descriptor_version: int
    # Which variant of the descriptor's template applies, where a definition has more
    # than one case (D4: a pawn's state, or a doubled file). A key into
    # describe.TEMPLATES, never free text.
    case: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.subject, Subject):
            raise TypeError("a Description needs a pinned Subject")


@dataclass(frozen=True, slots=True)
class Score:
    """An engine score, mover's point of view, as stored: exactly one is not None."""

    cp: int | None
    mate: int | None


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the eval says. The only type allowed to say a move was worse."""

    classification: str
    wpl: float | None
    before: Score
    after: Score
    depth: int


# ── Layer 1: a claim needs a proof that only gate P can mint ─────────────────

# The capability token for gate P on an engine line. Referenced only here and in
# `pv_reading.gate_p` (a test checks), so a `Proof` cannot be built at a call site.
_GATE_P = object()


@dataclass(frozen=True, slots=True)
class Proof:
    """What a claim rests on. `basis` "engine": the stored engine line, every one of the
    attacker's moves up to `held_from` (or the mate) a check, capture or promotion, and
    the stored eval charging what the line shows (ANALYSIS_ARCHITECTURE.md, third
    rulings of 2026-11-08)."""

    basis: str
    start_fen: str                      # the board the line is replayed from
    line: tuple[str, ...]               # UCI, up to and including the hold (or mate)
    forcing_moves: int
    held_from: int | None
    mate_on: int | None
    token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.token is not _GATE_P:
            raise TypeError("a Proof is minted only by gate P")


@dataclass(frozen=True, slots=True)
class ProvenClaim:
    """A claim that passed gate P. `kind`: "line_wins_material" or "line_mates";
    `subject`: "played" (the opponent's line after the played move) or "best"."""

    kind: str
    subject: str
    proof: Proof
    material: float | None              # pawns' worth won for the attacker, kept
    took: tuple[str, ...] = ()          # piece letters the attacker takes in the line
    gave: tuple[str, ...] = ()          # … and gives, same kinds cancelled

    def __post_init__(self) -> None:
        if not isinstance(self.proof, Proof):
            raise TypeError("a ProvenClaim needs a Proof")
