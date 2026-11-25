"""Rule-based tactical themes on a line of moves (COACH-1 B; COACH.md).

Modelled on how Lichess tags its puzzles: each theme is a rule over a short line in which one side (the
*attacker*) wins, read move by move. The definitions follow the themes Lichess names on its puzzle-themes page;
the code is this project's own. Lichess's tagger (github.com/ornicar/lichess-puzzler, "tagger/") is AGPL-3.0 and
was read for its definitions only: nothing here is copied from it (COACH-1 report, "Licences").

Input: a ThemeLine, the board the attacker moves from, the line (attacker first, moves alternating), and the
move that led to that board (Lichess's puzzle "setup" move: the opponent's last move), if known. A puzzle is
read as Lichess serves it: its first stored move is the setup, the rest is the solution. A game moment is the
stored engine line trimmed to its hold (coach.py).

Every detector takes keyword *variants* (its thresholds). VARIANTS lists the candidates the validation tried
(review/scratch/coach1_themes_validate.py); CHOSEN holds the one chosen per theme on the seeded tuning half
of the puzzle set, and SHIPPED the themes whose held-out precision reached 0.90 (owner, 2026-11-23, COACH-1 B).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import chess

P, N, B, R, Q, K = chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING
VALUE = {P: 1, N: 3, B: 3, R: 5, Q: 9, K: 99}
SLIDERS = (B, R, Q)

THEMES_VERSION = 1


@dataclass
class ThemeLine:
    start: chess.Board                     # the attacker to move
    moves: list[chess.Move]
    setup: chess.Move | None = None        # the move that led to start
    setup_from: chess.Board | None = None  # the board before setup
    boards: list[chess.Board] = field(default_factory=list)   # boards[i] before moves[i]; boards[-1] final

    def __post_init__(self) -> None:
        b = self.start.copy(stack=False)
        self.boards = [b.copy(stack=False)]
        for m in self.moves:
            b.push(m)
            self.boards.append(b.copy(stack=False))
        self.attacker = self.start.turn

    @classmethod
    def from_ucis(cls, fen: str, ucis: Sequence[str], setup_fen: str | None = None,
                  setup_uci: str | None = None) -> "ThemeLine":
        board = chess.Board(fen)
        moves: list[chess.Move] = []
        b = board.copy(stack=False)
        for u in ucis:
            m = chess.Move.from_uci(u)
            if m not in b.legal_moves:
                break
            moves.append(m)
            b.push(m)
        sb = chess.Board(setup_fen) if setup_fen else None
        sm = chess.Move.from_uci(setup_uci) if setup_uci else None
        return cls(board, moves, sm, sb)

    @classmethod
    def from_puzzle(cls, fen: str, moves_uci: str) -> "ThemeLine":
        ucis = moves_uci.split()
        before = chess.Board(fen)
        start = before.copy(stack=False)
        start.push(chess.Move.from_uci(ucis[0]))
        return cls.from_ucis(start.fen(), ucis[1:], before.fen(), ucis[0])

    def mine(self) -> range:                  # indices of the attacker's moves
        return range(0, len(self.moves), 2)

    def before(self, i: int) -> chess.Board:
        return self.boards[i]

    def after(self, i: int) -> chess.Board:
        return self.boards[i + 1]

    def moved_type(self, i: int) -> int:
        pt = self.after(i).piece_type_at(self.moves[i].to_square)
        assert pt is not None
        return pt

    def captured_at(self, i: int) -> chess.Piece | None:
        """The piece move i captures (en passant included)."""
        b, m = self.before(i), self.moves[i]
        if b.is_en_passant(m):
            return chess.Piece(P, not b.turn)
        return b.piece_at(m.to_square)

    def final(self) -> chess.Board:
        return self.boards[-1]

    def mated(self) -> bool:
        return bool(self.moves) and len(self.moves) % 2 == 1 and self.final().is_checkmate()


# ── board helpers ──

def defended(board: chess.Board, sq: int) -> bool:
    """Something of the piece's own side covers sq, directly or behind an enemy slider that attacks it
    (the slider's capture would open the defender's line)."""
    piece = board.piece_at(sq)
    if piece is None:
        return False
    if board.attackers(piece.color, sq):
        return True
    for a in board.attackers(not piece.color, sq):
        ap = board.piece_at(a)
        if ap is not None and ap.piece_type in SLIDERS:
            t = board.copy(stack=False)
            t.remove_piece_at(a)
            if t.attackers(piece.color, sq):
                return True
    return False


def loose(board: chess.Board, sq: int) -> bool:
    return not defended(board, sq)


def exposed_to_cheaper(board: chess.Board, sq: int) -> bool:
    piece = board.piece_at(sq)
    assert piece is not None
    for a in board.attackers(not piece.color, sq):
        ap = board.piece_at(a)
        if ap is not None and ap.piece_type != K and VALUE[ap.piece_type] < VALUE[piece.piece_type]:
            return True
    return False


def unsafe(board: chess.Board, sq: int) -> bool:
    """The piece on sq can be taken for profit: attacked and loose, or attacked by something cheaper."""
    piece = board.piece_at(sq)
    if piece is None or not board.attackers(not piece.color, sq):
        return False
    return loose(board, sq) or exposed_to_cheaper(board, sq)


def material(board: chess.Board, side: bool) -> int:
    return sum(VALUE[pt] * len(board.pieces(pt, side)) for pt in (P, N, B, R, Q))


def balance(board: chess.Board, side: bool) -> int:
    return material(board, side) - material(board, not side)


def enemies_hit(board: chess.Board, sq: int, side: bool) -> list[tuple[int, chess.Piece]]:
    out = []
    for t in board.attacks(sq):
        p = board.piece_at(t)
        if p is not None and p.color != side:
            out.append((t, p))
    return out


def between(a: int, b: int) -> chess.SquareSet:
    return chess.SquareSet.between(a, b)


def relative_rank(sq: int, side: bool) -> int:
    r = chess.square_rank(sq)
    return r if side == chess.WHITE else 7 - r


# ── detectors: each returns True (or a truthy value) when the theme applies to the line ──

def mate_in(line: ThemeLine) -> int | None:
    return (len(line.moves) + 1) // 2 if line.mated() else None


def back_rank_mate(line: ThemeLine, *, front_attacked_ok: bool = False) -> bool:
    if not line.mated():
        return False
    b = line.final()
    d = not line.attacker
    k = b.king(d)
    if k is None or relative_rank(k, d) != 0:
        return False
    step = 8 if d == chess.WHITE else -8
    front = [k + step]
    f = chess.square_file(k)
    if f > 0:
        front.append(k + step - 1)
    if f < 7:
        front.append(k + step + 1)
    for s in front:
        p = b.piece_at(s)
        own = p is not None and p.color == d
        hit = bool(b.attackers(line.attacker, s))
        if not own and not (front_attacked_ok and hit):
            return False
        if own and hit and not front_attacked_ok:
            return False
    return any(relative_rank(c, d) == 0 for c in b.checkers())


def smothered_mate(line: ThemeLine) -> bool:
    if not line.mated():
        return False
    b = line.final()
    d = not line.attacker
    k = b.king(d)
    checkers = list(b.checkers())
    if k is None or len(checkers) != 1 or b.piece_type_at(checkers[0]) != N:
        return False
    for s in chess.SquareSet(chess.BB_KING_ATTACKS[k]):
        p = b.piece_at(s)
        if p is None or p.color != d:
            return False
    return True


def bishops_mate(line: ThemeLine) -> str | None:
    """Two bishops give the mate between them: on either side of the king's file (Boden), or both on one
    side (the double-bishop mate)."""
    if not line.mated():
        return None
    b = line.final()
    d = not line.attacker
    k = b.king(d)
    checkers = list(b.checkers())
    if k is None or len(checkers) != 1 or b.piece_type_at(checkers[0]) != B:
        return None
    bishops = list(b.pieces(B, line.attacker))
    if len(bishops) < 2:
        return None
    flight = [s for s in chess.SquareSet(chess.BB_KING_ATTACKS[k])
              if b.piece_at(s) is None or b.piece_at(s).color != d]
    covering = {bs for bs in bishops if any(s in b.attacks(bs) for s in flight) or bs == checkers[0]}
    if len(covering) < 2:
        return None
    files = [chess.square_file(s) - chess.square_file(k) for s in covering]
    if any(f == 0 for f in files):
        return None
    same_side = all(f > 0 for f in files) or all(f < 0 for f in files)
    return "doubleBishopMate" if same_side else "bodenMate"


def arabian_mate(line: ThemeLine) -> bool:
    if not line.mated():
        return False
    b = line.final()
    d = not line.attacker
    k = b.king(d)
    if k is None or k not in (chess.A1, chess.H1, chess.A8, chess.H8):
        return False
    checkers = list(b.checkers())
    if len(checkers) != 1 or b.piece_type_at(checkers[0]) != R:
        return False
    rsq = checkers[0]
    if chess.square_distance(rsq, k) != 1:
        return False
    return any(b.piece_type_at(n) == N for n in b.attackers(line.attacker, rsq))


def double_check(line: ThemeLine) -> bool:
    return any(len(line.after(i).checkers()) > 1 for i in line.mine())


def fork(line: ThemeLine, *, king_forks: bool = True, need_capture: bool = False,
         last_counts: bool = False) -> int | None:
    """An attacker move whose piece, standing safely, hits two enemy pieces (pawns aside), each worth
    more than it or loose and unable to take it. Returns the forking piece's type."""
    idx = list(line.mine()) if last_counts else list(line.mine())[:-1]
    for i in idx:
        b = line.after(i)
        to = line.moves[i].to_square
        pt = line.moved_type(i)
        if pt == K and not king_forks:
            continue
        if unsafe(b, to):
            continue
        targets = []
        for s, p in enemies_hit(b, to, line.attacker):
            if p.piece_type == P:
                continue
            if VALUE[p.piece_type] > VALUE[pt] or (loose(b, s) and s not in b.attackers(not line.attacker, to)):
                targets.append(s)
        if len(targets) < 2:
            continue
        if need_capture:
            later = {line.moves[j].to_square for j in line.mine() if j > i}
            fled = {line.moves[j].from_square: line.moves[j].to_square for j in range(i + 1, len(line.moves), 2)}
            hit = set(targets) | {fled[t] for t in targets if t in fled}
            if not (hit & later) and not line.mated():
                continue
        return pt
    return None


def hanging_piece(line: ThemeLine, *, max_moves: int = 99) -> bool:
    if not line.moves or (len(line.moves) + 1) // 2 > max_moves:
        return False
    b0 = line.before(0)
    to = line.moves[0].to_square
    victim = b0.piece_at(to)
    if b0.is_check() and (victim is None or victim.piece_type == P):
        return False
    if victim is None or victim.piece_type == P or victim.color == line.attacker:
        return False
    if not loose(b0, to):
        return False
    if line.setup is not None and line.setup_from is not None and line.setup.to_square == to:
        took = line.setup_from.piece_at(to)
        if took is not None and VALUE[took.piece_type] >= VALUE[victim.piece_type]:
            return False          # a trade in progress, not a piece left hanging
    if len(line.moves) >= 3:
        return balance(line.after(2), line.attacker) >= balance(line.after(0), line.attacker)
    return True


def _trapped(board: chess.Board, sq: int) -> bool:
    """The side to move's piece on sq cannot get out of danger."""
    if board.is_check() or board.is_pinned(board.turn, sq):
        return False
    p = board.piece_at(sq)
    if p is None or p.piece_type in (P, K) or not unsafe(board, sq):
        return False
    for m in board.legal_moves:
        if m.from_square != sq:
            continue
        cap = board.piece_at(m.to_square)
        if cap is not None and VALUE[cap.piece_type] >= VALUE[p.piece_type]:
            return False
        t = board.copy(stack=False)
        t.push(m)
        if not unsafe(t, m.to_square):
            return False
    return True


def trapped_piece(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        victim = line.captured_at(i)
        if victim is None or victim.piece_type == P:
            continue
        sq = line.moves[i].to_square
        if line.moves[i - 1].to_square == sq:
            sq = line.moves[i - 1].from_square
        if _trapped(line.before(i - 1), sq):
            return True
    return False


def sacrifice(line: ThemeLine, *, drop: int = 2, from_first: bool = False) -> bool:
    if any(line.moves[j].promotion for j in range(1, len(line.moves), 2)):
        return False
    start = balance(line.before(0), line.attacker)
    for i in line.mine():
        if i == 0 and not from_first:
            continue
        if balance(line.after(i), line.attacker) - start <= -drop:
            return True
    return False


def x_ray(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        if line.captured_at(i) is None:
            continue
        reply, mine_before = line.moves[i - 1], line.moves[i - 2]
        if reply.to_square != m.to_square or line.moved_type(i - 1) == K:
            continue
        if mine_before.to_square != reply.to_square:
            continue
        if reply.from_square in between(m.from_square, m.to_square):
            return True
    return False


def discovered_attack(line: ThemeLine, *, checks: bool = True) -> bool:
    if checks:
        for i in line.mine():
            c = line.after(i).checkers()
            if c and line.moves[i].to_square not in c:
                return True
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        if line.captured_at(i) is None:
            continue
        if line.moves[i - 1].to_square == m.to_square:
            return False
        prev = line.moves[i - 2]
        if line.before(i - 2).is_castling(prev):
            continue
        if (prev.from_square in between(m.from_square, m.to_square)
                and m.to_square != prev.to_square and m.from_square != prev.to_square):
            return True
    return False


def skewer(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        victim = line.captured_at(i)
        if victim is None or line.moved_type(i) not in SLIDERS or line.after(i).is_checkmate():
            continue
        reply = line.moves[i - 1]
        if reply.to_square == m.to_square or reply.from_square not in between(m.from_square, m.to_square):
            continue
        if VALUE[line.moved_type(i - 1)] > VALUE[victim.piece_type] and unsafe(line.before(i), m.to_square):
            return True
    return False


def pin(line: ThemeLine, *, prevents_attack: bool = True, prevents_escape: bool = True) -> bool:
    me = line.attacker
    for i in line.mine():
        b = line.after(i)
        for sq, p in b.piece_map().items():
            if p.color == me or not b.is_pinned(p.color, sq):
                continue
            ray = b.pin(p.color, sq)
            if prevents_attack:
                for t in b.attacks(sq):
                    tp = b.piece_at(t)
                    if tp is None or tp.color != me or t in ray:
                        continue
                    if VALUE[tp.piece_type] > VALUE[p.piece_type] or loose(b, t):
                        return True
            if prevents_escape:
                for a in b.attackers(me, sq):
                    if a not in ray:
                        continue
                    ap = b.piece_at(a)
                    if VALUE[p.piece_type] > VALUE[ap.piece_type]:
                        return True
                    if loose(b, sq) and sq not in b.attackers(not me, a):
                        if any(mv.from_square == sq and mv.to_square not in ray for mv in b.pseudo_legal_moves):
                            return True
    return False


def deflection(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        victim = line.captured_at(i)
        if victim is None and not m.promotion:
            continue
        if victim is not None and VALUE[victim.piece_type] > VALUE[line.moved_type(i)]:
            continue
        mine_prev, reply = line.moves[i - 2], line.moves[i - 1]
        took = line.before(i - 2).piece_at(mine_prev.to_square)
        if took is not None and VALUE[took.piece_type] >= VALUE[line.moved_type(i - 2)]:
            continue
        sq = m.to_square
        if sq in (reply.to_square, mine_prev.to_square):
            continue
        if not (reply.to_square == mine_prev.to_square or line.after(i - 2).is_check()):
            continue
        guarded = sq in line.after(i - 2).attacks(reply.from_square)
        promo_path = (m.promotion is not None and chess.square_file(sq) == chess.square_file(reply.from_square)
                      and m.from_square in line.after(i - 2).attacks(reply.from_square))
        if (guarded or promo_path) and sq not in line.after(i - 1).attacks(reply.to_square):
            return True
    return False


def attraction(line: ThemeLine) -> bool:
    for i in line.mine():
        if i + 2 >= len(line.moves):
            break
        to = line.moves[i].to_square
        reply = line.moves[i + 1]
        if reply.to_square != to:
            continue
        lured = line.moved_type(i + 1)
        if lured not in (K, Q, R):
            continue
        nxt = line.moves[i + 2]
        if nxt.to_square not in line.after(i + 2).attackers(line.attacker, to):
            continue
        if lured == K:
            return True
        if i + 4 < len(line.moves) and line.moves[i + 4].to_square == to:
            return True
    return False


def capturing_defender(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        victim = line.captured_at(i)
        mover = line.moved_type(i)
        hit = line.after(i).is_checkmate() or (
            victim is not None and mover != K and VALUE[victim.piece_type] <= VALUE[mover]
            and loose(line.before(i), m.to_square) and line.moves[i - 1].to_square != m.to_square)
        if not hit:
            continue
        prev = line.moves[i - 2]
        if line.after(i - 2).is_check() or prev.to_square == m.from_square:
            continue
        init = line.before(i - 2)
        d = init.piece_at(prev.to_square)
        if d is not None and prev.to_square in init.attackers(d.color, m.to_square) and not init.is_check():
            return True
    return False


def intermezzo(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        if line.captured_at(i) is None:
            continue
        sq = m.to_square
        if line.moves[i - 1].from_square in line.before(i - 2).attackers(not line.attacker, sq):
            continue
        if line.moves[i - 2].to_square == sq or i < 3:
            continue
        their = line.moves[i - 3]
        return (their.to_square == sq and line.captured_at(i - 3) is not None
                and m in line.before(i - 2).legal_moves)
    return False


def interference(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        victim = line.captured_at(i)
        sq = m.to_square
        if victim is None or not loose(line.before(i), sq):
            continue
        for j, base in ((i - 1, i - 2), (i - 2, i - 3)):
            if base < 0:
                continue
            if j == i - 2 and sq == line.moves[i - 1].to_square:
                continue
            init = line.before(base)
            ds = list(init.attackers(victim.color, sq))
            if not ds:
                continue
            dp = init.piece_at(ds[0])
            if dp is not None and dp.piece_type in SLIDERS and line.moves[j].to_square in between(sq, ds[0]):
                return True
    return False


def clearance(line: ThemeLine) -> bool:
    for i in list(line.mine())[1:]:
        m = line.moves[i]
        if line.before(i).piece_at(m.to_square) is not None:
            continue
        piece = line.after(i).piece_at(m.to_square)
        if piece is None or piece.piece_type not in SLIDERS:
            continue
        prev = line.moves[i - 2]
        if prev.promotion or prev.to_square in (m.from_square, m.to_square) or line.before(i).is_check():
            continue
        if line.after(i).is_check() and line.moved_type(i - 1) == K:
            continue
        if prev.from_square == m.to_square or prev.from_square in between(m.from_square, m.to_square):
            if line.before(i - 2).piece_at(prev.to_square) is None or unsafe(line.after(i - 2), prev.to_square):
                return True
    return False


def exposed_king(line: ThemeLine) -> bool:
    b = line.before(0)
    d = not line.attacker
    k = b.king(d)
    if k is None or relative_rank(k, d) > 2:
        return False
    fwd = 8 if d == chess.WHITE else -8
    f = chess.square_file(k)
    shield = [k + fwd] + ([k + fwd - 1] if f > 0 else []) + ([k + fwd + 1] if f < 7 else [])
    if any(0 <= s < 64 and b.piece_at(s) == chess.Piece(P, d) for s in shield):
        return False
    return any(line.after(i).is_check() for i in list(line.mine())[1:-1])


def wing_attack(line: ThemeLine, corner_file: int, king_files: tuple[int, ...], min_pieces: int) -> bool:
    d = not line.attacker
    b0 = line.before(0)
    k = b0.king(d)
    if (k is None or relative_rank(k, d) != 0 or chess.square_file(k) not in king_files
            or len(b0.piece_map()) < min_pieces or not any(line.after(i).is_check() for i in line.mine())):
        return False
    corner = chess.square(corner_file, 0 if d == chess.WHITE else 7)
    score = 0
    for i in line.mine():
        dist = chess.square_distance(corner, line.moves[i].to_square)
        if line.after(i).is_check():
            score += 1
        if line.captured_at(i) is not None and dist <= 3:
            score += 1
        elif dist >= 5:
            score -= 1
    return score >= 2


def advanced_pawn(line: ThemeLine) -> bool:
    for i in line.mine():
        m = line.moves[i]
        if m.promotion or (line.moved_type(i) == P and relative_rank(m.to_square, line.attacker) >= 6):
            return True
    return False


def promotion(line: ThemeLine) -> bool:
    return any(line.moves[i].promotion for i in line.mine())


def under_promotion(line: ThemeLine) -> bool:
    for i in line.mine():
        m = line.moves[i]
        if line.after(i).is_checkmate():
            return m.promotion == N
        if m.promotion and m.promotion != Q:
            return True
    return False


def en_passant(line: ThemeLine) -> bool:
    return any(line.before(i).is_en_passant(line.moves[i]) for i in line.mine())


def castling(line: ThemeLine) -> bool:
    return any(line.before(i).is_castling(line.moves[i]) for i in line.mine())


def attacking_f2f7(line: ThemeLine) -> bool:
    for i in line.mine():
        m = line.moves[i]
        if m.to_square in (chess.F2, chess.F7) and line.captured_at(i) is not None:
            home = chess.E8 if m.to_square == chess.F7 else chess.E1
            kp = line.after(i).piece_at(home)
            return kp is not None and kp.piece_type == K and kp.color != line.attacker
    return False


def _quiet(line: ThemeLine, i: int) -> bool:
    b, m, a = line.before(i), line.moves[i], line.after(i)
    push = m.promotion or (line.moved_type(i) == P and relative_rank(m.to_square, line.attacker) >= 5)
    return (not a.is_check() and not b.is_check() and not b.is_capture(m)
            and not enemies_hit(a, m.to_square, line.attacker) and not push and line.moved_type(i) != K)


def quiet_move(line: ThemeLine) -> bool:
    return any(_quiet(line, i) for i in list(line.mine())[:-1])


def defensive_move(line: ThemeLine) -> bool:
    if not line.moves or len(line.moves) % 2 == 0:
        return False
    i = len(line.moves) - 1
    if line.before(i).legal_moves.count() < 3:
        return False
    a, m = line.after(i), line.moves[i]
    if a.is_check() or line.before(i).is_capture(m) or enemies_hit(a, m.to_square, line.attacker):
        return False
    return not (m.promotion or (line.moved_type(i) == P and relative_rank(m.to_square, line.attacker) >= 5))


# ── the table ──

#: name -> (detector, the variants tried). A variant is a dict of keyword arguments.
VARIANTS: dict[str, tuple[Callable[..., object], list[dict]]] = {
    "mate": (lambda l: mate_in(l) is not None, [{}]),
    "mateIn1": (lambda l: mate_in(l) == 1, [{}]),
    "mateIn2": (lambda l: mate_in(l) == 2, [{}]),
    "mateIn3": (lambda l: mate_in(l) == 3, [{}]),
    "backRankMate": (back_rank_mate, [{}, {"front_attacked_ok": True}]),
    "smotheredMate": (smothered_mate, [{}]),
    "bodenMate": (lambda l: bishops_mate(l) == "bodenMate", [{}]),
    "doubleBishopMate": (lambda l: bishops_mate(l) == "doubleBishopMate", [{}]),
    "arabianMate": (arabian_mate, [{}]),
    "doubleCheck": (double_check, [{}]),
    "fork": (lambda l, **k: fork(l, **k) is not None,
             [{}, {"need_capture": True}, {"king_forks": False}, {"king_forks": False, "need_capture": True}]),
    "hangingPiece": (hanging_piece, [{}, {"max_moves": 1}, {"max_moves": 2}]),
    "trappedPiece": (trapped_piece, [{}]),
    "sacrifice": (sacrifice, [{}, {"drop": 3}, {"from_first": True}, {"drop": 3, "from_first": True}]),
    "xRayAttack": (x_ray, [{}]),
    "discoveredAttack": (discovered_attack, [{}, {"checks": False}]),
    "skewer": (skewer, [{}]),
    "pin": (pin, [{}, {"prevents_escape": False}, {"prevents_attack": False}]),
    "deflection": (deflection, [{}]),
    "attraction": (attraction, [{}]),
    "capturingDefender": (capturing_defender, [{}]),
    "intermezzo": (intermezzo, [{}]),
    "interference": (interference, [{}]),
    "clearance": (clearance, [{}]),
    "exposedKing": (exposed_king, [{}]),
    "kingsideAttack": (lambda l: wing_attack(l, 7, (6, 7), 20), [{}]),
    "queensideAttack": (lambda l: wing_attack(l, 0, (0, 1, 2), 18), [{}]),
    "advancedPawn": (advanced_pawn, [{}]),
    "promotion": (promotion, [{}]),
    "underPromotion": (under_promotion, [{}]),
    "enPassant": (en_passant, [{}]),
    "castling": (castling, [{}]),
    "attackingF2F7": (attacking_f2f7, [{}]),
    "quietMove": (quiet_move, [{}]),
    "defensiveMove": (defensive_move, [{}]),
}

#: Chosen on the seeded tuning half (an index into VARIANTS[name][1]), measured 2026-11-23 on the app's puzzle set
#: (review/scratch/coach1_themes_validate.out): every theme's first variant won on the tuning half.
CHOSEN: dict[str, int] = {}

#: Themes whose held-out precision reached 0.90 (COACH-1 B, measured 2026-11-23 on Lichess's file of 2026-11-01 as
#: imported, 5,531,622 puzzles, held-out half 2,765,925; review/scratch/coach1_themes_validate.out). Left out, under the
#: bar: bodenMate, doubleBishopMate, arabianMate, intermezzo, interference, exposedKing, kingsideAttack, queensideAttack.
SHIPPED: tuple[str, ...] = (
    "mate",
    "mateIn1",
    "mateIn2",
    "mateIn3",
    "backRankMate",
    "smotheredMate",
    "doubleCheck",
    "fork",
    "hangingPiece",
    "trappedPiece",
    "sacrifice",
    "xRayAttack",
    "discoveredAttack",
    "skewer",
    "pin",
    "deflection",
    "attraction",
    "capturingDefender",
    "clearance",
    "advancedPawn",
    "promotion",
    "underPromotion",
    "enPassant",
    "castling",
    "attackingF2F7",
    "quietMove",
    "defensiveMove",
)


def variant_flags(line: ThemeLine) -> dict[str, list[bool]]:
    """Every variant of every theme, for the validation."""
    out: dict[str, list[bool]] = {}
    for name, (fn, vs) in VARIANTS.items():
        res = []
        for v in vs:
            try:
                res.append(bool(fn(line, **v)))
            except (AssertionError, IndexError, ValueError):
                res.append(False)
        out[name] = res
    return out


def tag(line: ThemeLine, names: Sequence[str] | None = None) -> list[str]:
    """The shipped themes (or the given names) the line shows, each with its chosen variant."""
    out = []
    for name in (SHIPPED if names is None else names):
        fn, vs = VARIANTS[name]
        try:
            if fn(line, **vs[CHOSEN.get(name, 0)]):
                out.append(name)
        except (AssertionError, IndexError, ValueError):
            pass
    return out
