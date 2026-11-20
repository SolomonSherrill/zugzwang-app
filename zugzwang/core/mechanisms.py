"""MECH-NAME (owner rulings M1–M7, 2026-11-14; ANALYSIS_ARCHITECTURE.md "MECH-NAME — the spec"):
a mechanism NAMED inside an engine-line claim the card already shows, never claimed on its own.

A name is computed from the claim's own proof (`Proof.start_fen`, `Proof.line`, `Proof.held_from`)
and nothing else — no engine, no board search outside the proof — and it renders only as a clause
after the claim's sentence (`with_name`). Two mechanisms (M1):

- **back rank** — only on `line_mates`: the line ends in checkmate; the mating move is a rook or a
  queen landing on the defender's first rank; the defender's king stands on that rank; every
  square of the next rank beside or in front of the king holds one of the defender's own pieces.
- **discovered attack** — only on `line_wins_material`, at the hold: H, the attacker's
  `held_from`-th move, captures a piece T (a knight or more, M2); D, the attacker's move before it,
  moving from f, uncovers a line through f from an attacker bishop, rook or queen S — onto T's
  square (S did not attack it before D and does after) or onto the defender's king (S gives check
  and is not the piece that moved). T stands on its square from D to H, and H is made by S or, for
  the check, by the piece D moved. The check form is named **a discovered check** (M3). The
  claim's own net gain must also be a piece (M2): the held-out read found a rook taken at the hold
  in a line that nets a pawn.

**Pin and skewer** (P1, owner 2026-11-19; ANALYSIS_ARCHITECTURE.md "MECH-NAME" §10), only on
`line_wins_material`, only at the hold (the pin or skewer must be what wins the material there), a
knight or more (M2), the claim netting a piece less a pawn:

- **pin** — H, the attacker's `held_from`-th move, captures a piece T on t; on the board before H,
  and before the defender's move that precedes H (when there is one), an attacker bishop, rook or
  queen S stands on a line with T and, directly behind T on that line, a defender piece V that is
  the king or worth more than T; nothing stands between S and T. T stays on t throughout. H is made
  by a piece other than S — the pinned piece cannot step away from another attacker — and H uncovers
  no check (a discovered check is its own reason), and T could not take S along the pin line (a
  pinned bishop, rook or queen on its own kind of line is not stuck). All three added by the held-out
  reads (2026-11-19): with S itself capturing, 22 of 30 names were a plain capture of a loose or
  overloaded piece; then 8 of 21 were a pinned piece that could have taken its pinner.
- **skewer** — H is S (a bishop, rook or queen) capturing T on t; on the board before the
  defender's move that precedes H, S attacks a defender piece V on the line to t, V is the king or
  worth more than T, nothing else stands between S and t, and that defender's move is V leaving
  its square.

Discovered attack/check is tried first, then pin, then skewer; one name per claim.

No name on a summarised claim (M5): `render_pv_claim` prints the line only up to
`config.PV_PRINT_MAX_PLIES`; past it the sentence says "by move N" and names no moves to point at.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from zugzwang import config as C

BACK_RANK = "back_rank"
DISCOVERED_ATTACK = "discovered_attack"
DISCOVERED_CHECK = "discovered_check"
PIN = "pin"
SKEWER = "skewer"
_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9,
          chess.KING: 100}
MIN_PIECE = 2.0               # M2: a piece less a pawn, net (the hold test's tolerance), to be named

_WORD = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
         chess.QUEEN: "queen", chess.KING: "king"}


@dataclass(frozen=True)
class MechanismName:
    mechanism: str            # BACK_RANK | DISCOVERED_ATTACK | DISCOVERED_CHECK | PIN | SKEWER
    clause: str               # "a back-rank mate: the king on g8 is shut in by …"


def _replay(start_fen: str, line) -> tuple[list[chess.Board], list[chess.Move], chess.Board]:
    board = chess.Board(start_fen)
    boards: list[chess.Board] = []
    moves: list[chess.Move] = []
    for uci in line:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        boards.append(board.copy(stack=False))
        moves.append(move)
        board.push(move)
    return boards, moves, board


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def back_rank(start_fen: str, line) -> MechanismName | None:
    _, moves, end = _replay(start_fen, line)
    if not moves or len(moves) != len(line) or not end.is_checkmate():
        return None
    mated = end.turn
    king = end.king(mated)
    if king is None:
        return None
    rank = 0 if mated == chess.WHITE else 7
    last = moves[-1]
    if chess.square_rank(king) != rank or chess.square_rank(last.to_square) != rank:
        return None
    if end.piece_type_at(last.to_square) not in (chess.ROOK, chess.QUEEN):
        return None
    forward = rank + (1 if mated == chess.WHITE else -1)
    kf = chess.square_file(king)
    squares = [chess.square(f, forward) for f in range(max(0, kf - 1), min(7, kf + 1) + 1)]
    if not all(end.color_at(sq) == mated for sq in squares):
        return None
    pawns = all(end.piece_type_at(sq) == chess.PAWN for sq in squares)
    names = [chess.square_name(sq) for sq in squares]
    return MechanismName(BACK_RANK, (
        f"a back-rank mate: the king on {chess.square_name(king)} is shut in by its own "
        f"{'pawns' if pawns else 'pieces'} on {_and(names)}"))


def discovered(start_fen: str, line, held_from: int | None) -> MechanismName | None:
    if not held_from or held_from < 2:
        return None
    boards, moves, _ = _replay(start_fen, line)
    if not boards or len(moves) != len(line):
        return None
    attacker = boards[0].turn
    att = [i for i, b in enumerate(boards) if b.turn == attacker]
    if len(att) < held_from:
        return None
    h, d = att[held_from - 1], att[held_from - 2]
    bh, mh = boards[h], moves[h]
    if not bh.is_capture(mh) or bh.is_en_passant(mh):
        return None
    t = mh.to_square
    victim = bh.piece_at(t)
    if victim is None or victim.piece_type in (chess.PAWN, chess.KING):
        return None                               # M2: only a piece, never a pawn
    bd, md = boards[d], moves[d]
    after_d = boards[d + 1] if d + 1 < len(boards) else None
    if after_d is None or after_d.piece_at(t) != victim:
        return None
    if any(moves[j].from_square == t or moves[j].to_square == t for j in range(d + 1, h)):
        return None                               # T stood on its square from D to H
    moved_to = md.to_square
    mover = bd.piece_at(md.from_square)
    king = after_d.king(not attacker)
    sliders = (bd.pieces(chess.BISHOP, attacker) | bd.pieces(chess.ROOK, attacker)
               | bd.pieces(chess.QUEEN, attacker))
    for s in sliders:
        if s == md.from_square:
            continue
        through = chess.BB_SQUARES[md.from_square]
        uncovered_t = bool(chess.between(s, t) & through) and t not in bd.attacks(s) \
            and t in after_d.attacks(s)
        uncovered_k = king is not None and after_d.is_check() and s in after_d.checkers() \
            and bool(chess.between(s, king) & through)
        if not (uncovered_t or uncovered_k):
            continue
        takes_s = mh.from_square == s
        takes_moved = mh.from_square == moved_to and all(
            moves[j].from_square != moved_to for j in range(d + 1, h))
        slider = bd.piece_at(s)
        assert slider is not None
        d_san = bd.san(md)
        s_name = f"the {_WORD[slider.piece_type]} on {chess.square_name(s)}"
        t_name = f"the {_WORD[victim.piece_type]} on {chess.square_name(t)}"
        if uncovered_t and (takes_s or takes_moved):
            return MechanismName(DISCOVERED_ATTACK,
                                 f"a discovered attack: {d_san} opens {s_name}'s line to {t_name}")
        if uncovered_k and takes_moved and mover is not None:
            return MechanismName(DISCOVERED_CHECK, (
                f"a discovered check: {d_san} uncovers {s_name}'s check, and the "
                f"{_WORD[mover.piece_type]} takes {t_name}"))
    return None


def _hold(start_fen: str, line, held_from: int | None):
    """(boards, moves, h, attacker) at the claim's hold: h indexes the attacker's `held_from`-th
    move, which must capture a knight or more (M2). None otherwise."""
    if not held_from or held_from < 1:
        return None
    boards, moves, _ = _replay(start_fen, line)
    if not boards or len(moves) != len(line):
        return None
    attacker = boards[0].turn
    att = [i for i, b in enumerate(boards) if b.turn == attacker]
    if len(att) < held_from:
        return None
    h = att[held_from - 1]
    bh, mh = boards[h], moves[h]
    if not bh.is_capture(mh) or bh.is_en_passant(mh):
        return None
    victim = bh.piece_at(mh.to_square)
    if victim is None or victim.piece_type in (chess.PAWN, chess.KING):
        return None
    return boards, moves, h, attacker


def _slides(piece_type: int, a: int, b: int) -> bool:
    """Whether a slider of this type moves along the line from a to b."""
    same_line = chess.square_file(a) == chess.square_file(b) or chess.square_rank(a) == chess.square_rank(b)
    diagonal = abs(chess.square_file(a) - chess.square_file(b)) == abs(chess.square_rank(a) - chess.square_rank(b))
    if piece_type == chess.ROOK:
        return same_line
    if piece_type == chess.BISHOP:
        return diagonal
    return piece_type == chess.QUEEN and (same_line or diagonal)


def _pinners(board: chess.Board, attacker: bool, t: int):
    """(S, V) pairs: an attacker slider S with a clear line to t, and directly behind t on that
    line a defender piece V that is the king or worth more than the piece on t."""
    target = board.piece_at(t)
    if target is None:
        return []
    out = []
    for s in board.pieces(chess.BISHOP, attacker) | board.pieces(chess.ROOK, attacker) \
            | board.pieces(chess.QUEEN, attacker):
        slider = board.piece_type_at(s)
        if slider is None or not _slides(slider, s, t) or chess.between(s, t) & board.occupied:
            continue
        ray = chess.ray(s, t)
        for v in chess.SquareSet(ray & board.occupied_co[not attacker]):
            if v in (s, t) or not (chess.between(s, v) & chess.BB_SQUARES[t]):
                continue
            if chess.between(t, v) & board.occupied:
                continue
            piece = board.piece_at(v)
            if piece is not None and _VALUE[piece.piece_type] > _VALUE[target.piece_type]:
                out.append((s, v))
    return out


def pin(start_fen: str, line, held_from: int | None) -> MechanismName | None:
    got = _hold(start_fen, line, held_from)
    if got is None:
        return None
    boards, moves, h, attacker = got
    bh, mh = boards[h], moves[h]
    t = mh.to_square
    victim0 = bh.piece_at(t)
    assert victim0 is not None
    found = [p for p in _pinners(bh, attacker, t) if p[0] != mh.from_square
             and not _slides(victim0.piece_type, t, p[0])]
    after = bh.copy(stack=False)
    after.push(mh)
    if after.is_check() and mh.to_square not in after.checkers():
        return None                              # H uncovers a check: not the pin's doing
    if h >= 1:
        prev = boards[h - 1]
        if prev.piece_at(t) != bh.piece_at(t):
            return None                          # T stood on t across the defender's move
        before = set(_pinners(prev, attacker, t))
        found = [p for p in found if p in before]
    if not found:
        return None
    s, v = found[0]
    victim, slider, behind = bh.piece_at(t), bh.piece_at(s), bh.piece_at(v)
    assert victim is not None and slider is not None and behind is not None
    return MechanismName(PIN, (
        f"a pin: the {_WORD[victim.piece_type]} on {chess.square_name(t)} is pinned to the "
        f"{_WORD[behind.piece_type]} on {chess.square_name(v)} by the {_WORD[slider.piece_type]} "
        f"on {chess.square_name(s)}"))


def skewer(start_fen: str, line, held_from: int | None) -> MechanismName | None:
    got = _hold(start_fen, line, held_from)
    if got is None:
        return None
    boards, moves, h, attacker = got
    if h < 1:
        return None
    bh, mh = boards[h], moves[h]
    s, t = mh.from_square, mh.to_square
    prev, mv = boards[h - 1], moves[h - 1]
    slider = prev.piece_at(s)
    victim = prev.piece_at(t)
    front = prev.piece_at(mv.from_square)
    if slider is None or slider.color != attacker or slider.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return None
    if victim is None or victim != bh.piece_at(t) or front is None or front.color == attacker:
        return None
    if not _slides(slider.piece_type, s, t):
        return None
    v = mv.from_square
    if chess.between(s, t) & prev.occupied != chess.BB_SQUARES[v]:
        return None                              # V, and only V, stood between S and T
    if _VALUE[front.piece_type] <= _VALUE[victim.piece_type]:
        return None
    return MechanismName(SKEWER, (
        f"a skewer: the {_WORD[slider.piece_type]} on {chess.square_name(s)} drives the "
        f"{_WORD[front.piece_type]} on {chess.square_name(v)} off its line and takes the "
        f"{_WORD[victim.piece_type]} on {chess.square_name(t)} behind it"))


def name_claim(claim) -> MechanismName | None:
    """The mechanism a shown `ProvenClaim` names, or None. Never on a summarised claim (M5)."""
    p = claim.proof
    if not p.line or len(p.line) > C.PV_PRINT_MAX_PLIES:
        return None
    if claim.kind == "line_mates":
        return back_rank(p.start_fen, p.line)
    if claim.kind == "line_wins_material":
        # M2, by the claim's net gain as well as the piece taken at the hold: "17.Rxf5+ gxf5
        # 18.Qxh4" takes a rook but nets a pawn, and "a discovered attack" overstates it.
        if claim.material is None or claim.material < MIN_PIECE:
            return None
        return (discovered(p.start_fen, p.line, p.held_from)
                or pin(p.start_fen, p.line, p.held_from)          # P1, 2026-11-19
                or skewer(p.start_fen, p.line, p.held_from))
    return None


def with_name(text: str, name: MechanismName | None) -> str:
    """The claim's sentence with the name as a clause after its line (M6): unchanged up to the
    dash. "… 18.Rxe8#." → "… 18.Rxe8# — a back-rank mate: …." """
    if name is None:
        return text
    body = text[:-1] if text.endswith(".") else text
    return f"{body} — {name.clause}."
