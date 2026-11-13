"""Descriptions: board facts on the played branch against the best branch (ARCH-1).

ANALYSIS_ARCHITECTURE.md §3 defines each descriptor before any code. This module
computes them (`describe`) and renders them (`render`) through a closed template set,
into `DescriptionText`, which refuses causal or evaluative words at construction.

All nine descriptors, D1–D9, with the owner's three findings on the sample
(2026-11-08) applied to every one:

- **A, one pinned subject.** Each description is about one `Subject` (findings.py),
  minted only by a `pin_*` check that it exists unchanged on both branches. A piece the
  played or best move moved is not a subject, so "the piece that moved reaches more
  squares where it went" (D6's old case (a)) is gone by construction.
- **B, D2 needs a castled king**: on the a–c or g–h file. "Pawns in front of the king"
  on e1 was 37 % of D2's output and meant nothing.
- **C, once per state per game.** `GameMemory` drops a description whose subject's
  played-branch value is what it was when that descriptor last fired on it in this
  game: a state that persists is said once, a change is said again.

It never imports the claim renderer (`explain_text`) or the rules (`explain`): a test
enforces that, so a description cannot borrow a claim's wording or its fields.

Common to every descriptor (§3):

- B_played = `fen_before` + the played move; B_best = `fen_before` + the best move.
  Both are the position immediately after the move, with the opponent to move.
- A ply whose best move is unknown, or equals the played move, gets no description.
- "Mover" is the side that played the move.
- A descriptor fires only when its quantity differs between the branches by at least
  its θ (`config.DESCRIPTION_THETA`, set from the gradient measurement; ruling 1: a
  near-identical move shows nothing).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import chess

from zugzwang import config as C
from zugzwang.core.findings import (
    Description,
    Descriptor,
    Differential,
    Fact,
    Horizon,
    PieceOn,
    Subject,
    SubjectKind,
    pin_file,
    pin_king,
    pin_piece,
    pin_side,
    pin_square,
)

#: Bump a descriptor's version when its definition or template changes meaning.
#: D2, D3, D6 went to 2 with the pinned subject (A); D2 also with the castled king (B).
DESCRIPTOR_VERSION: dict[Descriptor, int] = {
    Descriptor.CASTLING_RIGHTS: 1,
    Descriptor.PAWN_SHIELD: 2,
    Descriptor.KING_RING_ATTACKED: 2,
    Descriptor.PAWN_STRUCTURE: 1,
    Descriptor.FILES: 1,
    Descriptor.REACH: 2,
    Descriptor.NO_FORWARD_SQUARE: 1,
    Descriptor.PAWN_COVER_GONE: 1,
    Descriptor.UNDEVELOPED: 1,
    Descriptor.ENGINE_LINE: 1,         # built by pv_reading.gate_p (stage 2)
}

#: At most this many descriptions render per ply (owner ruling 1).
MAX_DESCRIPTIONS = 2


# ── the closed lexicon ───────────────────────────────────────────────────────

#: No rendered description may contain one of these words (§2, layer 3). Causal
#: connectives, verdicts, every classification label, and eval vocabulary. The owner
#: may extend it.
BANNED_WORDS: frozenset[str] = frozenset({
    # causal
    "because", "so", "since", "therefore", "thus", "allows", "allowing", "allow",
    "allowed", "leads", "lead", "leading", "hence", "consequently", "due",
    # evaluative
    "loses", "lose", "losing", "lost", "wins", "win", "winning", "won", "drops", "drop",
    "hangs", "hanging", "hang", "threat", "threatens", "threatened", "weak", "weakness",
    "weakened", "weakens", "strong", "stronger", "better", "worse", "worst", "mistake",
    "error", "costs", "cost", "punish", "punishes", "exploit", "exploits", "exposed",
    "exposes", "safe", "unsafe", "safety", "danger", "dangerous", "vulnerable",
    "should", "bad", "good", "only", "just", "too", "fortunately", "unfortunately",
    # the classification labels
    "book", "brilliant", "great", "best", "excellent", "inaccuracy", "miss", "missed",
    "blunder", "blundered",
    # eval vocabulary
    "eval", "evaluation", "score", "scores", "centipawn", "centipawns", "advantage",
    "equal", "equality", "edge",
})

_WORD = re.compile(r"[A-Za-z']+")


class DescriptionText(str):
    """A rendered description. Not a `ClaimText`, and never compares as one's type.

    Construction runs the lexicon check, so a template edit that slips past review
    fails on its first render rather than reaching the screen."""

    __slots__ = ()

    def __new__(cls, text: str) -> "DescriptionText":
        bad = sorted({w.lower() for w in _WORD.findall(text)} & BANNED_WORDS)
        if bad:
            raise ValueError(f"description uses banned word(s) {bad}: {text!r}")
        return super().__new__(cls, text)


# ── typed template slots ─────────────────────────────────────────────────────

# Words to ten, digits above, so a sentence never mixes "21" with "sixteen".
_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight",
                 "nine", "ten")


@dataclass(frozen=True, slots=True)
class Count:
    """`{n:pawn}` → "two pawns" / "one pawn" / "no pawns"; `{n}` → "two" / "none";
    `{n:=stand}` → the verb agreeing with n: "stands" for one, "stand" otherwise."""

    n: int

    def __format__(self, spec: str) -> str:
        if spec.startswith("="):
            return spec[1:] + ("s" if self.n == 1 else "")
        word = _NUMBER_WORDS[self.n] if self.n < len(_NUMBER_WORDS) else str(self.n)
        if not spec:
            return "none" if self.n == 0 else word
        return f"{word} {spec}" + ("" if self.n == 1 else "s")


@dataclass(frozen=True, slots=True)
class Squares:
    """`{sq}` → " (f2, h2)", or nothing when empty."""

    squares: tuple[str, ...]

    def __format__(self, spec: str) -> str:
        return f" ({', '.join(self.squares)})" if self.squares else ""


_PIECE_NAMES = {chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
                chess.QUEEN: "queen", chess.KING: "king", chess.PAWN: "pawn"}

#: D1's rights, D4's pawn states, D5's file states: closed keys → fixed phrases.
#: `{white}` / `{black}` are filled with the voice's name for a colour ("you", "White").
STATE_PHRASES: Mapping[str, str] = {
    "rights:both": "on both sides", "rights:kingside": "on the kingside",
    "rights:queenside": "on the queenside", "rights:neither": "on neither side",
    "pawn:isolated": "isolated", "pawn:backward": "backward",
    "pawn:isolated+backward": "isolated and backward",
    "pawn:neither": "neither isolated nor backward",
    "file:open": "open", "file:half-open:w": "half-open for {white}",
    "file:half-open:b": "half-open for {black}", "file:closed": "closed",
}

#: Slot name → the only type it may hold. A template naming any other slot fails the
#: grammar test, so a template cannot reach for an eval, a refutation or a label.
SLOT_TYPES: Mapping[str, str] = {
    "played": "san", "best": "san",
    "subject": "subject",
    "own": "side", "opp": "side", "who": "side",
    "n_played": "count", "n_best": "count",
    "sq_played": "squares", "sq_best": "squares",
    "state_played": "state", "state_best": "state",
    "file": "file", "adj_files": "file",
    "heavy_played": "pieces", "heavy_best": "pieces",
    "queen_played": "pieces", "queen_best": "pieces",
    "line_played": "line", "line_best": "line",
}

#: One contrast template per (descriptor, case), of the form "After {played}, …; after
#: {best}, …." The subject is named once, in the first half. Data, not code: the grammar
#: test parses every one.
TEMPLATES: Mapping[tuple[Descriptor, str], str] = {
    (Descriptor.CASTLING_RIGHTS, ""):
        "After {played}, {who} can castle {state_played}; after {best}, {state_best}.",
    (Descriptor.PAWN_SHIELD, ""):
        "After {played}, {subject} has {n_played:pawn} in front of it{sq_played}; "
        "after {best}, {n_best}{sq_best}.",
    (Descriptor.KING_RING_ATTACKED, ""):
        "After {played}, {opp} pieces attack {n_played:square} next to "
        "{subject}{sq_played}; after {best}, {n_best}{sq_best}.",
    (Descriptor.PAWN_STRUCTURE, "pawn"):
        "After {played}, {subject} is {state_played}; after {best}, it is {state_best}.",
    (Descriptor.PAWN_STRUCTURE, "doubled"):
        "After {played}, the {file}-file holds {n_played} of {own} pawns{sq_played}; "
        "after {best}, {n_best}{sq_best}.",
    (Descriptor.FILES, ""):
        "After {played}, the {file}-file is {state_played}{heavy_played}; "
        "after {best}, {state_best}{heavy_best}.",
    (Descriptor.REACH, ""):
        "After {played}, {subject} reaches {n_played:square}; after {best}, {n_best}.",
    (Descriptor.NO_FORWARD_SQUARE, ""):
        "After {played}, {subject} reaches {n_played:square} ahead of it; "
        "after {best}, {n_best}{sq_best}.",
    (Descriptor.PAWN_COVER_GONE, ""):
        "After {played}, {subject} has none of {own} pawns behind it on the "
        "{adj_files}; after {best}, {n_best}{sq_best}.",
    (Descriptor.ENGINE_LINE, ""):
        "After {played}, {line_played}; after {best}, {line_best}.",
    (Descriptor.UNDEVELOPED, ""):
        "After {played}, {n_played} of {own} knights and bishops {n_played:=stand} on "
        "their starting squares{queen_played}; after {best}, {n_best}{queen_best}.",
}


def template_slots(template: str) -> list[str]:
    return [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]


# ── voice ────────────────────────────────────────────────────────────────────

_COLOUR = {chess.WHITE: "White", chess.BLACK: "Black"}


def _is_user(colour: chess.Color, mover: chess.Color, player_color: str | None) -> bool:
    """Second person for the user's side; with no game in hand (`None`) the mover is
    addressed, as the claim layer does; "unknown" (O5) addresses nobody."""
    if player_color == "unknown":
        return False
    if player_color is None:
        return colour == mover
    return player_color == ("white" if colour == chess.WHITE else "black")


def _whose(colour: chess.Color, mover: chess.Color, player_color: str | None) -> str:
    return "your" if _is_user(colour, mover, player_color) else _COLOUR[colour] + "'s"


def _who(colour: chess.Color, mover: chess.Color, player_color: str | None) -> str:
    return "you" if _is_user(colour, mover, player_color) else _COLOUR[colour]


def _possessives(mover: chess.Color, player_color: str | None) -> tuple[str, str]:
    """(mover's, opponent's)."""
    return _whose(mover, mover, player_color), _whose(not mover, mover, player_color)


# ── the measurements ─────────────────────────────────────────────────────────

def _differential_sets(played: set[str], best: set[str]) -> Differential:
    if played > best:
        return Differential.PLAYED_ONLY
    if best > played:
        return Differential.BEST_ONLY
    return Differential.BOTH_DIFFER


def _differential_counts(played: int, best: int) -> Differential:
    return Differential.PLAYED_ONLY if played > best else Differential.BEST_ONLY


def _sorted_squares(squares: Iterable[int]) -> tuple[str, ...]:
    return tuple(chess.square_name(s) for s in sorted(squares))


def _theta(d: Descriptor) -> float:
    return C.DESCRIPTION_THETA.get(d.value, 1)


def _desc(d: Descriptor, subject: Subject, played: Fact, best: Fact,
          differential: Differential, magnitude: float, case: str = "") -> Description:
    return Description(descriptor=d, subject=subject, differential=differential,
                       played=played, best=best, magnitude=float(magnitude),
                       horizon=Horizon.AFTER_MOVE, descriptor_version=DESCRIPTOR_VERSION[d],
                       case=case)


# D1 ──────────────────────────────────────────────────────────────────────────

def _rights(board: chess.Board, colour: chess.Color) -> tuple[bool, bool]:
    return (board.has_kingside_castling_rights(colour),
            board.has_queenside_castling_rights(colour))


def _rights_key(r: tuple[bool, bool]) -> str:
    return {(True, True): "rights:both", (True, False): "rights:kingside",
            (False, True): "rights:queenside", (False, False): "rights:neither"}[r]


def castling_rights(before: chess.Board, played: chess.Move, b_played: chess.Board,
                    b_best: chess.Board, mover: chess.Color) -> list[Description]:
    """D1. Subject: the mover's side. Fires when B_played has strictly fewer castling
    rights than B_best and the played move is not itself castling."""
    if before.is_castling(played):
        return []
    rp, rb = _rights(b_played, mover), _rights(b_best, mover)
    if rp == rb or any(p and not b for p, b in zip(rp, rb)):
        return []
    mag = sum(rb) - sum(rp)
    if mag < _theta(Descriptor.CASTLING_RIGHTS):
        return []
    return [_desc(Descriptor.CASTLING_RIGHTS, pin_side(mover),
                  Fact(state=_rights_key(rp), count=sum(rp)),
                  Fact(state=_rights_key(rb), count=sum(rb)),
                  Differential.BEST_ONLY, mag)]


# D2 ──────────────────────────────────────────────────────────────────────────

#: Finding B (owner, 2026-11-08): a castled king stands on one of these files.
CASTLED_FILES = frozenset({0, 1, 2, 6, 7})


def shield_squares(king: chess.Square, colour: chess.Color) -> list[chess.Square] | None:
    """D2's S: files f(k)−1..f(k)+1 (clipped), on the two ranks directly ahead of the
    king from its side. None unless the king stands on its first two ranks."""
    rank = chess.square_rank(king)
    rel = rank if colour == chess.WHITE else 7 - rank
    if rel > 1:
        return None
    step = 1 if colour == chess.WHITE else -1
    files = [f for f in (chess.square_file(king) + d for d in (-1, 0, 1)) if 0 <= f <= 7]
    return [chess.square(f, rank + step * k) for k in (1, 2) for f in files]


def _shield_pawns(board: chess.Board, king: chess.Square, colour: chess.Color) -> set[str]:
    zone = shield_squares(king, colour) or []
    return {chess.square_name(s) for s in zone
            if board.piece_at(s) == chess.Piece(chess.PAWN, colour)}


def pawn_shield(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                mover: chess.Color) -> list[Description]:
    """D2. Subject: the mover's king, pinned (the same square on both branches), on its
    first two ranks and on a castled file (a–c, g–h). Quantity: the mover's pawns on S.
    Fires when the counts differ by ≥ θ."""
    subject = pin_king(mover, before, b_played, b_best)
    if subject is None:
        return []
    king = chess.parse_square(subject.square or "")
    if chess.square_file(king) not in CASTLED_FILES or shield_squares(king, mover) is None:
        return []
    p, b = _shield_pawns(b_played, king, mover), _shield_pawns(b_best, king, mover)
    mag = abs(len(p) - len(b))
    if mag == 0 or mag < _theta(Descriptor.PAWN_SHIELD):
        return []
    return [_desc(Descriptor.PAWN_SHIELD, subject,
                  Fact(squares=tuple(sorted(p)), count=len(p)),
                  Fact(squares=tuple(sorted(b)), count=len(b)),
                  _differential_sets(p, b), mag)]


# D3 ──────────────────────────────────────────────────────────────────────────

def _ring_attacked(board: chess.Board, king: chess.Square, colour: chess.Color) -> set[str]:
    return {chess.square_name(s) for s in chess.SquareSet(chess.BB_KING_ATTACKS[king])
            if board.is_attacked_by(not colour, s)}


def king_ring_attacked(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                       mover: chess.Color) -> list[Description]:
    """D3. Subject: the mover's king, pinned. Ring = the squares adjacent to it.
    Quantity: the ring squares the opponent attacks. Fires when the counts differ by ≥ θ."""
    subject = pin_king(mover, before, b_played, b_best)
    if subject is None:
        return []
    king = chess.parse_square(subject.square or "")
    p, b = _ring_attacked(b_played, king, mover), _ring_attacked(b_best, king, mover)
    mag = abs(len(p) - len(b))
    if mag == 0 or mag < _theta(Descriptor.KING_RING_ATTACKED):
        return []
    return [_desc(Descriptor.KING_RING_ATTACKED, subject,
                  Fact(squares=tuple(sorted(p)), count=len(p)),
                  Fact(squares=tuple(sorted(b)), count=len(b)),
                  _differential_sets(p, b), mag)]


# D4 ──────────────────────────────────────────────────────────────────────────

def _pawn_files(board: chess.Board, colour: chess.Color) -> dict[int, list[chess.Square]]:
    out: dict[int, list[chess.Square]] = {}
    for sq in board.pieces(chess.PAWN, colour):
        out.setdefault(chess.square_file(sq), []).append(sq)
    return out


def pawn_state(board: chess.Board, square: chess.Square) -> str:
    """D4's per-pawn state: isolated, backward, both, or neither (§3's definitions)."""
    piece = board.piece_at(square)
    assert piece is not None and piece.piece_type == chess.PAWN
    colour, f, r = piece.color, chess.square_file(square), chess.square_rank(square)
    files_ = _pawn_files(board, colour)
    adjacent = [sq for af in (f - 1, f + 1) for sq in files_.get(af, [])]
    isolated = not adjacent
    step = 1 if colour == chess.WHITE else -1
    stop_rank = r + step
    backward = False
    if 0 <= stop_rank <= 7:
        stop = chess.square(f, stop_rank)
        attacked = bool(board.attackers(not colour, stop)
                        & board.pieces(chess.PAWN, not colour))
        behind_or_level = [sq for sq in adjacent if (chess.square_rank(sq) - r) * step <= 0]
        backward = attacked and not behind_or_level
    if isolated and backward:
        return "pawn:isolated+backward"
    return "pawn:isolated" if isolated else "pawn:backward" if backward else "pawn:neither"


def _state_parts(state: str) -> set[str]:
    return set() if state == "pawn:neither" else set(state.split(":")[1].split("+"))


def pawn_structure(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                   mover: chess.Color) -> list[Description]:
    """D4, for both colours. Case "pawn": a pawn pinned to its square on both branches
    whose isolated/backward state differs. Case "doubled": one side's pawns on a file,
    where the file is doubled (two or more) on one branch and not on the other."""
    out: list[Description] = []
    for colour in (mover, not mover):
        for sq in before.pieces(chess.PAWN, colour):
            subject = pin_piece(sq, before, b_played, b_best)
            if subject is None:
                continue
            sp, sb = pawn_state(b_played, sq), pawn_state(b_best, sq)
            if sp == sb:
                continue
            mag = len(_state_parts(sp) ^ _state_parts(sb))
            if mag < _theta(Descriptor.PAWN_STRUCTURE):
                continue
            out.append(_desc(Descriptor.PAWN_STRUCTURE, subject, Fact(state=sp),
                             Fact(state=sb), Differential.BOTH_DIFFER, mag, case="pawn"))
        fp, fb = _pawn_files(b_played, colour), _pawn_files(b_best, colour)
        for f in range(8):
            np_, nb = len(fp.get(f, [])), len(fb.get(f, []))
            if (np_ >= 2) == (nb >= 2):
                continue
            mag = abs(np_ - nb)
            if mag < _theta(Descriptor.PAWN_STRUCTURE):
                continue
            out.append(_desc(
                Descriptor.PAWN_STRUCTURE, pin_file(f, colour),
                Fact(squares=_sorted_squares(fp.get(f, [])), count=np_),
                Fact(squares=_sorted_squares(fb.get(f, [])), count=nb),
                _differential_counts(np_, nb), mag, case="doubled"))
    return out


# D5 ──────────────────────────────────────────────────────────────────────────

def file_state(board: chess.Board, f: int) -> str:
    mask = chess.BB_FILES[f]
    w = bool(board.pieces_mask(chess.PAWN, chess.WHITE) & mask)
    b = bool(board.pieces_mask(chess.PAWN, chess.BLACK) & mask)
    if not w and not b:
        return "file:open"
    if not w:
        return "file:half-open:w"
    if not b:
        return "file:half-open:b"
    return "file:closed"


def _heavy_on(board: chess.Board, f: int) -> tuple[PieceOn, ...]:
    out = []
    for sq in chess.SquareSet(chess.BB_FILES[f] & (board.rooks | board.queens)):
        piece = board.piece_at(sq)
        if piece is not None:
            out.append(PieceOn(piece.symbol(), chess.square_name(sq)))
    return tuple(out)


def files(b_played: chess.Board, b_best: chess.Board) -> list[Description]:
    """D5. Subject: a file. Fires when its open / half-open / closed state differs, or
    when a rook or queen stands on it, open or half-open, on one branch only (compared
    by which heavy pieces, not by their squares, so a rook moving along the file does
    not count)."""
    out: list[Description] = []
    for f in range(8):
        sp, sb = file_state(b_played, f), file_state(b_best, f)
        hp = _heavy_on(b_played, f) if sp != "file:closed" else ()
        hb = _heavy_on(b_best, f) if sb != "file:closed" else ()
        heavy_differs = sorted(p.piece for p in hp) != sorted(p.piece for p in hb)
        if sp == sb and not heavy_differs:
            continue
        mag = int(sp != sb) + int(heavy_differs)
        if mag < _theta(Descriptor.FILES):
            continue
        name = (chess.FILE_NAMES[f],)
        out.append(_desc(
            Descriptor.FILES, pin_file(f),
            Fact(state=sp, files=name, pieces=hp if heavy_differs else (),
                 count=len(hp) if heavy_differs else None),
            Fact(state=sb, files=name, pieces=hb if heavy_differs else (),
                 count=len(hb) if heavy_differs else None),
            Differential.BOTH_DIFFER, mag))
    return out


# D6 / D7 ─────────────────────────────────────────────────────────────────────

_REACH_TYPES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def reach_squares(board: chess.Board, square: chess.Square) -> chess.SquareSet:
    """reach(P, B): the squares P attacks that its own side does not occupy."""
    piece = board.piece_at(square)
    assert piece is not None
    return chess.SquareSet(board.attacks(square) & ~board.occupied_co[piece.color])


def reach(board: chess.Board, square: chess.Square) -> int:
    return len(reach_squares(board, square))


def _forward(board: chess.Board, square: chess.Square, colour: chess.Color) -> list[chess.Square]:
    r = chess.square_rank(square)
    step = 1 if colour == chess.WHITE else -1
    return [s for s in reach_squares(board, square) if (chess.square_rank(s) - r) * step > 0]


def _pinned_pieces(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                   mover: chess.Color) -> list[tuple[chess.Square, Subject]]:
    out = []
    for sq in chess.SquareSet(before.occupied_co[mover]):
        piece = before.piece_at(sq)
        if piece is None or piece.piece_type not in _REACH_TYPES:
            continue
        subject = pin_piece(sq, before, b_played, b_best)
        if subject is not None:
            out.append((sq, subject))
    return out


def reach_descriptions(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                       mover: chess.Color) -> list[Description]:
    """D6. Subject: one of the mover's knights, bishops, rooks and queens, pinned (moved
    by neither move). Fires when its reach differs by ≥ θ: a line one move closed or
    opened. The old case (a), the piece that moved, has no pinned subject (finding A)."""
    out: list[Description] = []
    for sq, subject in _pinned_pieces(before, b_played, b_best, mover):
        rp, rb = reach(b_played, sq), reach(b_best, sq)
        if rp == rb or abs(rp - rb) < _theta(Descriptor.REACH):
            continue
        out.append(_desc(Descriptor.REACH, subject, Fact(count=rp), Fact(count=rb),
                         _differential_counts(rp, rb), abs(rp - rb)))
    return out


def no_forward_square(before: chess.Board, b_played: chess.Board, b_best: chess.Board,
                      mover: chess.Color) -> list[Description]:
    """D7. Subject: a pinned knight, bishop, rook or queen of the mover. forward = its
    reach on ranks strictly ahead of it. Fires when forward is empty on B_played and
    holds ≥ θ squares on B_best."""
    out: list[Description] = []
    for sq, subject in _pinned_pieces(before, b_played, b_best, mover):
        fp, fb = _forward(b_played, sq, mover), _forward(b_best, sq, mover)
        if fp or not fb or len(fb) < _theta(Descriptor.NO_FORWARD_SQUARE):
            continue
        out.append(_desc(Descriptor.NO_FORWARD_SQUARE, subject, Fact(count=0),
                         Fact(count=len(fb), squares=_sorted_squares(fb)),
                         Differential.BEST_ONLY, len(fb)))
    return out


# D8 ──────────────────────────────────────────────────────────────────────────

def _covering_pawns(board: chess.Board, q: chess.Square,
                    colour: chess.Color) -> list[chess.Square]:
    """The colour's pawns on a file adjacent to q, on a rank behind q from its side."""
    f, r = chess.square_file(q), chess.square_rank(q)
    step = 1 if colour == chess.WHITE else -1
    return [sq for sq in board.pieces(chess.PAWN, colour)
            if abs(chess.square_file(sq) - f) == 1 and (r - chess.square_rank(sq)) * step > 0]


def pawn_cover_gone(before: chess.Board, played: chess.Move, best: chess.Move,
                    b_played: chess.Board, b_best: chess.Board,
                    mover: chess.Color) -> list[Description]:
    """D8. Subject: a square q on the mover's ranks 3–5, on a file adjacent to a file a
    mover's pawn left or entered by either move. Fires when a mover's pawn stands on a
    file adjacent to q, behind it, on B_best, and none does on B_played: a square the
    mover's pawns can no longer reach. One description per q."""
    changed: set[int] = set()
    for mv in (played, best):
        if before.piece_type_at(mv.from_square) == chess.PAWN:
            changed |= {chess.square_file(mv.from_square), chess.square_file(mv.to_square)}
    if not changed:
        return []
    ranks = (2, 3, 4) if mover == chess.WHITE else (5, 4, 3)
    out: list[Description] = []
    for f in sorted({af for c in changed for af in (c - 1, c + 1) if 0 <= af <= 7}):
        for r in ranks:
            q = chess.square(f, r)
            cp, cb = _covering_pawns(b_played, q, mover), _covering_pawns(b_best, q, mover)
            if cp or not cb or len(cb) < _theta(Descriptor.PAWN_COVER_GONE):
                continue
            adj = tuple(chess.FILE_NAMES[a] for a in (f - 1, f + 1) if 0 <= a <= 7)
            out.append(_desc(Descriptor.PAWN_COVER_GONE, pin_square(q, mover),
                             Fact(count=0, files=adj),
                             Fact(count=len(cb), squares=_sorted_squares(cb), files=adj),
                             Differential.BEST_ONLY, len(cb)))
    return out


# D9 ──────────────────────────────────────────────────────────────────────────

_MINOR_HOMES = {
    chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT,
                  chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
    chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT,
                  chess.C8: chess.BISHOP, chess.F8: chess.BISHOP},
}
_QUEEN_HOME = {chess.WHITE: chess.D1, chess.BLACK: chess.D8}


def _undeveloped(board: chess.Board, colour: chess.Color) -> tuple[list[chess.Square], bool]:
    home = [sq for sq, pt in _MINOR_HOMES[colour].items()
            if board.piece_at(sq) == chess.Piece(pt, colour)]
    queen_home = board.piece_at(_QUEEN_HOME[colour]) == chess.Piece(chess.QUEEN, colour)
    return home, queen_home


def undeveloped(b_played: chess.Board, b_best: chess.Board,
                mover: chess.Color) -> list[Description]:
    """D9, opening phase only (the caller passes the phase). Subject: the mover's side.
    Quantity: its knights and bishops on their starting squares, and whether its queen
    is on d1/d8. Fires when either differs; magnitude = |count difference| + the queen."""
    hp, qp = _undeveloped(b_played, mover)
    hb, qb = _undeveloped(b_best, mover)
    mag = abs(len(hp) - len(hb)) + int(qp != qb)
    if mag == 0 or mag < _theta(Descriptor.UNDEVELOPED):
        return []
    queen = chess.square_name(_QUEEN_HOME[mover])
    show_q = qp != qb

    def fact(home: list[chess.Square], q: bool) -> Fact:
        return Fact(squares=_sorted_squares(home), count=len(home),
                    state=("queen:home" if q else "queen:left") if show_q else "",
                    files=(queen,) if show_q else ())
    differential = (_differential_counts(len(hp), len(hb)) if len(hp) != len(hb)
                    else Differential.BOTH_DIFFER)
    return [_desc(Descriptor.UNDEVELOPED, pin_side(mover), fact(hp, qp), fact(hb, qb),
                  differential, mag)]


# ── per ply, per game ────────────────────────────────────────────────────────

def describe(fen_before: str, played_uci: str, best_uci: str | None, *,
             opening: bool = False, all_descriptors: bool = False) -> list[Description]:
    """Every description that fires for one ply, unranked and not yet deduplicated
    against the game (`GameMemory`). Empty when there is no best move, or the played
    move is the best move. `opening`: whether the ply is in the opening phase
    (`divider.py`), the only phase D9 is defined on. Descriptors that failed the kill
    criterion (`config.DESCRIPTION_DROPPED`) are left out unless `all_descriptors`,
    which only the gradient measurement passes."""
    if not best_uci or best_uci == played_uci:
        return []
    before = chess.Board(fen_before)
    played, best = chess.Move.from_uci(played_uci), chess.Move.from_uci(best_uci)
    if played not in before.legal_moves or best not in before.legal_moves:
        return []
    mover = before.turn
    b_played, b_best = before.copy(stack=False), before.copy(stack=False)
    b_played.push(played)
    b_best.push(best)
    def on(d: Descriptor) -> bool:
        return all_descriptors or d.value not in C.DESCRIPTION_DROPPED
    out: list[Description] = []
    if on(Descriptor.CASTLING_RIGHTS):
        out += castling_rights(before, played, b_played, b_best, mover)
    if on(Descriptor.PAWN_SHIELD):
        out += pawn_shield(before, b_played, b_best, mover)
    if on(Descriptor.KING_RING_ATTACKED):
        out += king_ring_attacked(before, b_played, b_best, mover)
    if on(Descriptor.PAWN_STRUCTURE):
        out += pawn_structure(before, b_played, b_best, mover)
    if on(Descriptor.FILES):
        out += files(b_played, b_best)
    if on(Descriptor.REACH):
        out += reach_descriptions(before, b_played, b_best, mover)
    if on(Descriptor.NO_FORWARD_SQUARE):
        out += no_forward_square(before, b_played, b_best, mover)
    if on(Descriptor.PAWN_COVER_GONE):
        out += pawn_cover_gone(before, played, best, b_played, b_best, mover)
    if on(Descriptor.UNDEVELOPED) and opening:
        out += undeveloped(b_played, b_best, mover)
    return out


class GameMemory:
    """Finding C (owner, 2026-11-08): a descriptor does not fire again in a game unless
    its value has changed since it last fired. Feed it each ply's descriptions in game
    order. The key is (descriptor, case, subject); the value is the played-branch fact,
    the state the game actually carried forward. A suppressed description does not
    update the memory, so a value that changes and changes back is said again."""

    def __init__(self) -> None:
        self._last: dict[tuple[Descriptor, str, Subject], Fact] = {}

    def peek(self, descriptions: Iterable[Description]) -> list[Description]:
        """The descriptions that would fire, without spending anything: a description
        is "said" only when it is shown, and the caller decides that (owner,
        2026-11-08: one suppressed beside a claim must stay eligible later)."""
        return [d for d in descriptions
                if self._last.get((d.descriptor, d.case, d.subject)) != d.played]

    def commit(self, shown: Iterable[Description]) -> None:
        """Record descriptions that were actually shown."""
        for d in shown:
            self._last[(d.descriptor, d.case, d.subject)] = d.played

    def filter(self, descriptions: Iterable[Description]) -> list[Description]:
        """`peek` then `commit` everything that fires: for a caller that shows every
        description it is given (the measurements)."""
        out = self.peek(descriptions)
        self.commit(out)
        return out


def ranked(descriptions: Iterable[Description],
           percentile: Callable[[Description], float],
           limit: int = MAX_DESCRIPTIONS) -> list[Description]:
    """The top `limit` by `percentile` (§3: each descriptor's magnitude as a
    percentile over the corpus plies where it fires, so different units compare).
    Ties keep the order `describe` produced."""
    items = list(descriptions)
    order = sorted(range(len(items)), key=lambda i: (-percentile(items[i]), i))
    return [items[i] for i in order[:limit]]


# ── rendering ────────────────────────────────────────────────────────────────

def _piece_text(p: PieceOn, mover: chess.Color, player_color: str | None) -> str:
    piece = chess.Piece.from_symbol(p.piece)
    return (f"{_whose(piece.color, mover, player_color)} "
            f"{_PIECE_NAMES[piece.piece_type]} on {p.square}")


def _subject_text(s: Subject, mover: chess.Color, player_color: str | None) -> str:
    if s.kind in (SubjectKind.PIECE, SubjectKind.KING, SubjectKind.PAWN):
        return _piece_text(PieceOn(s.piece or "", s.square or ""), mover, player_color)
    if s.kind == SubjectKind.FILE:
        return f"the {s.file}-file"
    if s.kind == SubjectKind.SQUARE:
        return s.square or ""
    return _whose(bool(s.colour), mover, player_color)


def _state_text(state: str, mover: chess.Color, player_color: str | None) -> str:
    if state not in STATE_PHRASES:
        return ""
    return STATE_PHRASES[state].format(white=_who(chess.WHITE, mover, player_color),
                                       black=_who(chess.BLACK, mover, player_color))


def _heavy_text(f: Fact, mover: chess.Color, player_color: str | None) -> str:
    if f.count is None:
        return ""
    if not f.pieces:
        return ", with no rook or queen on it"
    names = [_piece_text(p, mover, player_color) for p in f.pieces]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f", with {joined} on it"


def _queen_text(f: Fact, own: str) -> str:
    if not f.state.startswith("queen:"):
        return ""
    verb = "is on" if f.state == "queen:home" else "has left"
    return f", and {own} queen {verb} {f.files[0]}"


def _files_text(names: tuple[str, ...]) -> str:
    """("e", "g") → "e- or g-file"; ("b",) → "b-file"."""
    if not names:
        return ""
    return "".join(f"{x}- or " for x in names[:-1]) + f"{names[-1]}-file"


_LETTER = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen"}


def _pieces_text(pieces: tuple[str, ...], definite: bool = False) -> str:
    """("r", "p") → "a rook and a pawn"; ("p", "p") → "two pawns"."""
    counts = {x: pieces.count(x) for x in "qrbnp" if x in pieces}
    parts = []
    for x, n in counts.items():
        if n == 1:
            parts.append(f"{'the' if definite and len(pieces) == 1 else 'a'} {_LETTER[x]}")
        else:
            parts.append(f"{_NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else n} {_LETTER[x]}s")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _line_text(f: Fact, mover: chess.Color, player_color: str | None, first: bool) -> str:
    """One engine line (stage 2) in words, material named in pieces. Both lines are the
    engine's, so neither is called "the engine's line": the first is "the line", the
    second is named by its moves. Always the short form: a description of an unforced
    line is never summarised (owner, 2026-11-08, sixth round), so a line too long to
    print has no description at all (`pv_reading._description`)."""
    if len(f.moves) > C.PV_PRINT_MAX_PLIES:
        raise ValueError("an engine-line description is never summarised")
    who = _who(mover, mover, player_color)
    if f.state in ("line:mated", "line:mates"):
        king = _whose(mover if f.state == "line:mated" else not mover, mover, player_color)
        short_end, then = f"mating {king} king", f"mates {king} king"
    elif f.state == "material:level":
        short_end, then = "level in material", "leaves material level"
    else:
        up = bool(f.took) and (not f.gave or f.state == "material:ahead")
        main, other = (f.took, f.gave) if up else (f.gave, f.took)
        standing = f"{_pieces_text(main)} {'up' if up else 'down'}"
        if other:
            standing += f" for {_pieces_text(other, definite=True)}"
        short_end, then = f"with {who} {standing}", f"leaves {who} {standing}"
    moves = " ".join(f.moves)
    return f"the line runs {moves}, {short_end}" if first else f"{moves} {then}"


def render(d: Description, *, fen_before: str, played_san: str, best_san: str,
           player_color: str | None) -> DescriptionText:
    """One description as one sentence, through its template only."""
    mover = chess.WHITE if fen_before.split(" ")[1] == "w" else chess.BLACK
    colour = mover if d.subject.colour is None else bool(d.subject.colour)
    own = _whose(colour, mover, player_color)
    slots: dict[str, object] = {
        "played": played_san, "best": best_san,
        "subject": _subject_text(d.subject, mover, player_color),
        "own": own,
        "opp": _whose(not colour, mover, player_color),
        "who": _who(colour, mover, player_color),
        "n_played": Count(d.played.count or 0), "n_best": Count(d.best.count or 0),
        "sq_played": Squares(d.played.squares), "sq_best": Squares(d.best.squares),
        "state_played": _state_text(d.played.state, mover, player_color),
        "state_best": _state_text(d.best.state, mover, player_color),
        "file": d.subject.file or "",
        "adj_files": _files_text(d.best.files),
        "heavy_played": _heavy_text(d.played, mover, player_color),
        "heavy_best": _heavy_text(d.best, mover, player_color),
        "queen_played": _queen_text(d.played, own),
        "queen_best": _queen_text(d.best, own),
        "line_played": _line_text(d.played, mover, player_color, first=True)
        if d.descriptor == Descriptor.ENGINE_LINE else "",
        "line_best": _line_text(d.best, mover, player_color, first=False)
        if d.descriptor == Descriptor.ENGINE_LINE else "",
    }
    template = TEMPLATES[(d.descriptor, d.case)]
    return DescriptionText(template.format(**slots))
