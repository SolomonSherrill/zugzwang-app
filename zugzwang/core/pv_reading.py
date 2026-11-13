"""PV reading: annotate the engine's stored line (ARCH-2, stage 2 of
ANALYSIS_ARCHITECTURE_PROMPT.md; owner approval 2026-11-08).

Every rule and descriptor so far inspects one ply. The engine's principal variation *is*
the combination it found, stored to 20 half-moves (STORE-PVCAP), and nothing read past its
first move. This module replays a stored line and records what happens along it.

**Which lines.** For a ply N with mover m, from `fen_before`:

- the **best line** is ply N's stored `pv_uci`, which starts with the best move;
- the **played line** is the played move followed by the **refutation**: the best line
  stored at ply N+1 (176,823 adjacent pairs verified, ARCH-0.1-N1), or, for the game's last
  ply, `analysis_runs.final_lines_json[0]` (STORE-FINALPLY). A game that ended in mate or
  stalemate has no final line; its last ply's played line is the played move alone.

Both lines start from the same board and are measured from m's side, so their balances
compare directly.

**Definitions (written before measurement):**

- *Balance*: m's material minus the opponent's, in pawns, with explain.py's values (P 1,
  N 3, B 3, R 5, Q 9). A promotion counts its upgrade.
- *Step*: one half-move of the line, with its SAN, mover, captured piece, check, mate, and
  the balance after it. A stored move that is illegal on the replayed board ends the
  reading there (`stopped_at`), rather than guessing.
- *Settled end*: the balance after the last step, plus the best static-exchange gain
  (`explain.see`) the side to move then has, if positive. A line stored mid-exchange
  otherwise reports a material swing that the next recapture undoes.
- *Initiator*: the side making the line's first move. For the best line, m; for the played
  line's refutation, the opponent (the played move itself is step 0).
- *Forcing prefix*: the number of the attacking side's moves, from its first, that are a
  check, a capture or a promotion, before the first that is none of these.
- *Attacker's reference*: the balance on the board the attacker starts from — the
  position before the move for the best line, the position *after the played move* for
  the played line (the played move may itself have captured). Gains, sacrifices and
  holds below are measured from it.
- *Gain held from*: when the settled end is at least `HOLD_MIN` (one pawn) in the
  attacker's favour relative to its reference, the attacker's move number (1 = its first move
  in the line) from which the balance stays at least `HOLD_MIN` in its favour to the end
  of the line (relative to the reference). A capture that is recaptured, or a pawn taken on the way to a sacrifice,
  does not count; later incidental gains do not move it. If only the settling capture
  gets there, it is the attacker's next move after the line. **Multi-move** means the
  gain is held from the attacker's second move or later: the line gains only after a move
  that does not, which is what a one-ply detector cannot see.
- *Sacrifice*: before the gain is held (or the mate lands), one of the attacker's moves
  leaves material en prise net of recapture: the balance after it, less the defender's
  best static-exchange gain on the board it then faces, is at least `HOLD_MIN` below the
  reference. (A running balance cannot tell this from an exchange, where the defender
  captures mid-sequence and is recaptured: 10.Qxg7 Rg8 11.Qxh7 Bxe3 12.fxe3.)
- *SEE-blind*: the attacker's first capture in the line has a static-exchange gain of
  zero or less (`explain.see`, which the rule layer relies on), yet the line holds a gain:
  an overloaded or deflected defender declines the recapture.
- *Mate on*: for a line ending in checkmate, the attacker's move number that mates.
- *Hanging at the end*: each piece, of either side, that the other side could capture with
  a positive static-exchange gain on the final board (for the side not to move, measured
  as if it were to move, unless it is in check).
- *Ends where*: for each of the attacking side's pieces that moved in the line, its start
  and final square (captured pieces are marked captured).

**The ply-level statement** (`PlyReading`), what "PV reading fires" means for the silent
set and the gradient:

- `material_gap` = settled end of the best line − settled end of the played line. **Fires
  (MATERIAL)** when it is at least θ (`config.PV_MATERIAL_THETA`, set on a seeded half of
  the games and judged on the other half, the project's standard since 2026-11-08).
- **Fires (MATE)** when the played line ends in checkmate of m, or the best line ends in
  checkmate of the opponent while the played line does not.

These read the engine's own line, so their text says so ("the engine's line"); they make
no claim beyond what the stored line shows at its recorded depth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import chess

from zugzwang import config as C
from zugzwang.core.explain import see
from zugzwang.core.findings import (
    _GATE_P,
    Description,
    Descriptor,
    Differential,
    Fact,
    Horizon,
    Proof,
    ProvenClaim,
    pin_side,
)

#: Material values in pawns, explain.py's table without the king.
VALUE = {chess.PAWN: 1.0, chess.KNIGHT: 3.0, chess.BISHOP: 3.0, chess.ROOK: 5.0,
         chess.QUEEN: 9.0, chess.KING: 0.0}

PV_READING_VERSION = 1

#: One pawn: the least gain that counts as held (see "Gain held from").
HOLD_MIN = 1.0


@dataclass(frozen=True, slots=True)
class Step:
    index: int                  # 0-based half-move in the line
    uci: str
    san: str
    colour: bool                # chess.WHITE / chess.BLACK: who played it
    piece: str                  # python-chess symbol of the moving piece
    from_square: str
    to_square: str
    captured: str | None        # symbol of the captured piece, if any
    check: bool
    mate: bool
    promotion: str | None
    balance: float              # after this step, from the line's point of view


@dataclass(frozen=True, slots=True)
class Hanging:
    piece: str                  # symbol (its colour is its case)
    square: str
    gain: float                 # the static-exchange gain for the side capturing it


@dataclass(frozen=True, slots=True)
class Route:
    piece: str
    start: str
    end: str | None             # None when it was captured in the line


@dataclass(frozen=True, slots=True)
class LineReading:
    pov: bool                   # whose balance is measured (the ply's mover)
    attacker: bool              # the side whose moves are counted as the attack
    attack_from: int            # index of the attacker's first move in the line
    steps: tuple[Step, ...]
    balance_start: float
    reference: float            # the balance on the board the attacker starts from
    balance_end: float
    settled_end: float
    forcing_prefix: int
    gain_held_from: int | None  # the attacker's move number from which the gain is held
    sacrifice: bool             # the attacker gave material before the gain was held
    see_blind: bool             # its first capture loses or breaks even by SEE, yet the gain holds
    mate_on: int | None         # the attacker's move number that mates, if the line mates
    mate: bool                  # the line ends in checkmate
    hanging_end: tuple[Hanging, ...]
    routes: tuple[Route, ...]
    stopped_at: int | None      # index of the first illegal stored move, if any

    @property
    def multi_move(self) -> bool:
        """Gains, or mates, only from the attacker's second move on."""
        if self.mate_on is not None:
            return self.mate_on >= 2
        return self.gain_held_from is not None and self.gain_held_from >= 2

    @property
    def mated(self) -> bool | None:
        """Which side is checkmated at the end, or None."""
        if not self.mate or not self.steps:
            return None
        return not self.steps[-1].colour


def balance(board: chess.Board, pov: bool) -> float:
    total = 0.0
    for piece_type, v in VALUE.items():
        total += v * (len(board.pieces(piece_type, pov)) - len(board.pieces(piece_type, not pov)))
    return total


def _best_capture_gain(board: chess.Board) -> float:
    gains = [see(board, m) for m in board.legal_moves if board.is_capture(m) or m.promotion]
    return max([0.0, *gains])


def _hanging(board: chess.Board) -> tuple[Hanging, ...]:
    out: list[Hanging] = []
    sides = [board]
    if not board.is_check():
        flipped = board.copy(stack=False)
        flipped.push(chess.Move.null())
        sides.append(flipped)
    for b in sides:
        best: dict[int, float] = {}
        for m in b.legal_moves:
            if not b.is_capture(m) or b.is_en_passant(m):
                continue
            g = see(b, m)
            if g > 0 and g > best.get(m.to_square, 0.0):
                best[m.to_square] = g
        for sq, g in sorted(best.items()):
            piece = b.piece_at(sq)
            if piece is not None:
                out.append(Hanging(piece.symbol(), chess.square_name(sq), g))
    return tuple(out)


def read_line(fen: str, ucis: Sequence[str], pov: bool, attack_from: int = 0) -> LineReading:
    """Replay `ucis` from `fen` and annotate it. `pov` is the side whose balance is
    measured; `attack_from` is the index of the attacker's first move (0 for the best
    line, 1 for the played line, whose step 0 is the played move)."""
    board = chess.Board(fen)
    start = balance(board, pov)
    attacker = board.turn if attack_from % 2 == 0 else not board.turn
    steps: list[Step] = []
    stopped_at: int | None = None
    origin: dict[int, int] = {}          # current square → start square, attacker's pieces
    captured_starts: set[int] = set()
    for i, uci in enumerate(ucis):
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            stopped_at = i
            break
        if move not in board.legal_moves:
            stopped_at = i
            break
        piece = board.piece_at(move.from_square)
        assert piece is not None
        victim_sq = move.to_square
        if board.is_en_passant(move):
            victim_sq = chess.square(chess.square_file(move.to_square),
                                     chess.square_rank(move.from_square))
        victim = board.piece_at(victim_sq) if board.is_capture(move) else None
        san = board.san(move)
        mover = board.turn
        # Track the attacker's pieces (castling's rook too).
        if victim is not None and victim.color == attacker and victim_sq in origin:
            captured_starts.add(origin.pop(victim_sq))
        elif victim is not None and victim.color == attacker:
            captured_starts.add(victim_sq)
        if mover == attacker:
            moves = [(move.from_square, move.to_square)]
            if board.is_castling(move):
                rank = chess.square_rank(move.from_square)
                ks = chess.square_file(move.to_square) > chess.square_file(move.from_square)
                moves.append((chess.square(7 if ks else 0, rank), chess.square(5 if ks else 3, rank)))
            for fr, to in moves:
                origin[to] = origin.pop(fr, fr)
        board.push(move)
        steps.append(Step(
            index=i, uci=uci, san=san, colour=mover, piece=piece.symbol(),
            from_square=chess.square_name(move.from_square),
            to_square=chess.square_name(move.to_square),
            captured=victim.symbol() if victim is not None else None,
            check=board.is_check(), mate=board.is_checkmate(),
            promotion=chess.piece_symbol(move.promotion) if move.promotion else None,
            balance=balance(board, pov)))
    end = balance(board, pov)
    if board.is_checkmate() or not any(board.legal_moves):
        settled = end
    else:
        gain = _best_capture_gain(board)
        settled = end + (gain if board.turn == pov else -gain)

    sign = 1.0 if attacker == pov else -1.0
    forcing, n_attack, still_forcing = 0, 0, True
    attack_no: list[int] = []            # per step: the attacker's move count so far
    for s in steps:
        if s.colour == attacker and s.index >= attack_from:
            n_attack += 1
            if still_forcing and (s.captured or s.check or s.promotion):
                forcing += 1
            else:
                still_forcing = False
        attack_no.append(n_attack)
    # The attacker's gains are measured from the board it starts from: for the played
    # line, after the played move (which may itself have captured), not before it.
    ref = steps[attack_from - 1].balance if 0 < attack_from <= len(steps) else start
    gain_held_from: int | None = None
    if (settled - ref) * sign >= HOLD_MIN:
        held = n_attack + (1 if board.turn == attacker else 0)   # only the settling capture
        for k in range(len(steps) - 1, -1, -1):
            if (steps[k].balance - ref) * sign < HOLD_MIN:
                break
            if steps[k].colour == attacker and steps[k].index >= attack_from:
                held = attack_no[k]
        gain_held_from = held
    sacrifice = False
    if gain_held_from is not None or board.is_checkmate():
        limit = gain_held_from or n_attack + 1
        replay = chess.Board(fen)
        for k, s_ in enumerate(steps):
            replay.push_uci(s_.uci)
            if attack_no[k] >= limit:
                break
            if s_.colour != attacker or s_.index < attack_from or replay.is_game_over():
                continue
            # What the attacker's move leaves en prise, net of recapture: the
            # defender's best static-exchange gain on the board it now faces.
            net = s_.balance - sign * _best_capture_gain(replay)
            if (net - ref) * sign <= -HOLD_MIN:
                sacrifice = True
                break
    see_blind = False
    if gain_held_from is not None:
        replay = chess.Board(fen)
        for s_ in steps:
            mv = chess.Move.from_uci(s_.uci)
            if s_.colour == attacker and s_.index >= attack_from and replay.is_capture(mv):
                see_blind = see(replay, mv) <= 0
                break
            replay.push(mv)
    mate_on = n_attack if board.is_checkmate() and steps and steps[-1].colour == attacker else None
    routes = []
    for now, st in sorted(origin.items(), key=lambda kv: kv[1]):
        if now != st:
            p = board.piece_at(now)
            if p is not None:
                routes.append(Route(p.symbol(), chess.square_name(st), chess.square_name(now)))
    for st in sorted(captured_starts):
        p0 = chess.Board(fen).piece_at(st)
        if p0 is not None and p0.color == attacker:
            routes.append(Route(p0.symbol(), chess.square_name(st), None))
    return LineReading(
        pov=pov, attacker=attacker, attack_from=attack_from, steps=tuple(steps),
        balance_start=start, reference=ref, balance_end=end, settled_end=settled,
        forcing_prefix=forcing, gain_held_from=gain_held_from,
        sacrifice=sacrifice, see_blind=see_blind, mate_on=mate_on, mate=board.is_checkmate(),
        hanging_end=_hanging(board) if not board.is_game_over() else (),
        routes=tuple(routes), stopped_at=stopped_at)


@dataclass(frozen=True, slots=True)
class PlyReading:
    played: LineReading
    best: LineReading
    material_gap: float          # best.settled_end − played.settled_end, mover's side
    mate_against: bool           # the played line ends with the mover checkmated
    mate_for: bool               # the best line mates the opponent; the played line does not

    @property
    def fires_material(self) -> bool:
        return self.material_gap >= C.PV_MATERIAL_THETA

    @property
    def fires(self) -> bool:
        return self.fires_material or self.mate_against or self.mate_for

    @property
    def multi_move(self) -> bool:
        """The line that carries the statement wins only after a quiet move."""
        if self.mate_against or (self.fires_material and self.played.settled_end < self.played.balance_start):
            return self.played.multi_move
        return self.best.multi_move


def read_ply(fen_before: str, played_uci: str, best_line: Sequence[str],
             refutation: Sequence[str]) -> PlyReading | None:
    """Both lines for one ply. None when there is no best line or the played move is
    the best line's first move (played = best: nothing to compare)."""
    if not best_line or best_line[0] == played_uci:
        return None
    mover = chess.Board(fen_before).turn
    played = read_line(fen_before, [played_uci, *refutation], mover, attack_from=1)
    best = read_line(fen_before, list(best_line), mover, attack_from=0)
    if played.stopped_at == 0 or best.stopped_at == 0:
        return None
    return PlyReading(
        played=played, best=best,
        material_gap=best.settled_end - played.settled_end,
        mate_against=played.mate and played.mated == mover,
        mate_for=best.mate and best.mated == (not mover) and not played.mate)


# ── gate P for a line (owner, 2026-11-08, third rulings) ─────────────────────

def _cp(cp: int | None, mate: int | None) -> int:
    if mate is not None:
        return 10_000 if mate > 0 else -10_000
    return cp or 0


def _attacker_gain(line: LineReading) -> float:
    sign = 1.0 if line.attacker == line.pov else -1.0
    return (line.settled_end - line.reference) * sign


def _hold_index(line: LineReading) -> int:
    """Index of the attacker's move the gain is held from (or that mates)."""
    target = line.mate_on or line.gain_held_from
    n = 0
    for s in line.steps:
        if s.colour == line.attacker and s.index >= line.attack_from:
            n += 1
            if n == target:
                return s.index
    return len(line.steps) - 1


def carrier(rd: PlyReading) -> LineReading | None:
    """The line the statement is about: the played line when the opponent mates or
    holds a gain in it, else the best line; None when neither holds anything."""
    if rd.mate_against:
        return rd.played
    if rd.mate_for:
        return rd.best
    gp = _attacker_gain(rd.played) if rd.played.gain_held_from else 0.0
    gb = _attacker_gain(rd.best) if rd.best.gain_held_from else 0.0
    if max(gp, gb) < HOLD_MIN:
        return None
    return rd.played if gp >= gb else rd.best


def consistent(rd: PlyReading, score_before_cp: int | None, score_before_mate: int | None,
               score_after_cp: int | None, score_after_mate: int | None) -> bool:
    """The approved eval consistency check: the stored eval charges what the line
    shows. MATERIAL: the eval loss (mover's view) is at least `PV_CONSISTENCY_MIN_CP`.
    A mate against the mover: the stored score after the move is a mate against it. A
    missed mate: the score before is a mate for the mover and the score after is not."""
    if rd.mate_against:
        # The move must have caused it: a position already lost to mate is not this
        # move's mate (#-8 → #-8 is not news).
        already = score_before_mate is not None and score_before_mate < 0
        return score_after_mate is not None and score_after_mate < 0 and not already
    if rd.mate_for:
        return (score_before_mate is not None and score_before_mate > 0
                and not (score_after_mate is not None and score_after_mate > 0))
    loss = _cp(score_before_cp, score_before_mate) - _cp(score_after_cp, score_after_mate)
    return loss >= C.PV_CONSISTENCY_MIN_CP


def forcing_to_hold(line: LineReading) -> bool:
    """Every attacker move up to the hold (or the mate) is a check, capture or promotion."""
    target = line.mate_on or line.gain_held_from
    return target is not None and line.forcing_prefix >= target


def _material_state(points: int) -> str:
    return "material:ahead" if points > 0 else "material:behind" if points < 0 else "material:level"


_ORDER = "qrbnp"


def net_pieces(steps: Sequence[Step], side: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What `side` took and gave in `steps`, as piece letters ("r", "p"), with the same
    kind on both sides cancelled (a knight for a knight is no news), largest first. A
    promotion counts as taking the new piece and giving the pawn."""
    from collections import Counter
    took: Counter[str] = Counter()
    gave: Counter[str] = Counter()
    for st in steps:
        if st.captured:
            (took if st.colour == side else gave)[st.captured.lower()] += 1
        if st.promotion:
            (took if st.colour == side else gave)[st.promotion.lower()] += 1
            (gave if st.colour == side else took)["p"] += 1
    common = took & gave
    took, gave = took - common, gave - common
    return (tuple(sorted(took.elements(), key=_ORDER.index)),
            tuple(sorted(gave.elements(), key=_ORDER.index)))


def _value(pieces: Sequence[str]) -> float:
    return sum(VALUE[chess.Piece.from_symbol(p).piece_type] for p in pieces)


def decided(score_before_cp: int | None, score_before_mate: int | None,
            score_after_cp: int | None, score_after_mate: int | None) -> bool:
    """The October decided-position rule (`review/scratch/explain_decided.py`,
    `decided_v11.out`, measured 2026-10-21, never shipped until now): the position was
    already settled before the move — max(p, 1 − p) ≥ `PV_DECIDED_MIN` (0.95, the
    layer's `WINNING` / `LOST` line) — and the verdict held (the mover's win probability
    is on the same side of 0.5 before and after)."""
    from zugzwang.core.classification import win_prob
    if (score_before_cp is None and score_before_mate is None) or \
            (score_after_cp is None and score_after_mate is None):
        return False
    pb = win_prob(score_before_cp, score_before_mate)
    pa = win_prob(score_after_cp, score_after_mate)
    return max(pb, 1 - pb) >= C.PV_DECIDED_MIN and (pb - 0.5) * (pa - 0.5) > 0


_WHY: dict[str, str] = {}    # the last reason _claim / _description declined (measurement)


def _claim(fen_before: str, rd: PlyReading, line: LineReading) -> ProvenClaim | None:
    """The claim for a forcing carrier: its line from the attacker's start up to the
    point where what it has taken equals what it keeps, named in pieces."""
    k = _hold_index(line)
    sign = 1.0 if line.attacker == line.pov else -1.0
    subject = "played" if line is rd.played else "best"
    took: tuple[str, ...] = ()
    gave: tuple[str, ...] = ()
    if not line.mate_on:
        kept = min([(st.balance - line.reference) * sign for st in line.steps[k:]]
                   + [(line.settled_end - line.reference) * sign])
        # Extend past the hold to where the running balance is exactly what is kept, so
        # every piece the sentence names is taken (and not retaken) within the line shown.
        j = next((i for i in range(k, len(line.steps))
                  if abs((line.steps[i].balance - line.reference) * sign - kept) < 1e-9), None)
        if j is None:
            _WHY["why"] = "claim: what is kept arrives only by the settling capture"
            return None
        k = j
        took, gave = net_pieces(line.steps[line.attack_from:k + 1], line.attacker)
        if not took or abs(_value(took) - _value(gave) - kept) > 1e-9:
            _WHY["why"] = "claim: pieces do not add up to what is kept"
            return None
    if subject == "played":
        start = chess.Board(fen_before)
        start.push_uci(rd.played.steps[0].uci)
        start_fen, ucis = start.fen(), tuple(s.uci for s in line.steps[1:k + 1])
    else:
        start_fen, ucis = fen_before, tuple(s.uci for s in line.steps[:k + 1])
    proof = Proof(basis="engine", start_fen=start_fen, line=ucis,
                  forcing_moves=line.forcing_prefix, held_from=line.gain_held_from,
                  mate_on=line.mate_on, token=_GATE_P)
    return ProvenClaim(kind="line_mates" if line.mate_on else "line_wins_material",
                       subject=subject, proof=proof,
                       material=None if line.mate_on else _value(took) - _value(gave),
                       took=took, gave=gave)


_SETTLE_PLIES = 6


def _description(fen_before: str, rd: PlyReading, line: LineReading) -> Description | None:
    """Not forcing: both lines up to the same half-move, followed on through any exchange
    still open there (at most six half-moves), and where each stands, named in pieces. Emitted only
    if the gap is still at least θ at that point: a gap that exists only further down
    the lines is not what the lines shown say."""
    mover = rd.played.pov
    n = _hold_index(line) + 1

    def stand(lr: LineReading) -> tuple[Fact, float] | None:
        # Follow the stored line on while an exchange is still open — a capture is
        # next, or the side to move has a winning capture — for at most
        # `_SETTLE_PLIES` more half-moves, so the pieces named are pieces taken in it.
        m = min(n, len(lr.steps))
        board = chess.Board(fen_before)
        for st in lr.steps[:m]:
            board.push_uci(st.uci)
        extra = 0
        while m < len(lr.steps) and extra < _SETTLE_PLIES and (
                lr.steps[m].captured or (not board.is_game_over()
                                         and _best_capture_gain(board) > 0)):
            board.push_uci(lr.steps[m].uci)
            m += 1
            extra += 1
        steps = lr.steps[:m]
        if not steps:
            return Fact(state="material:level"), 0.0
        moves = tuple(numbered(fen_before, steps).split())
        board = chess.Board(fen_before)
        for st in steps:
            board.push_uci(st.uci)
        by = board.fullmove_number - (1 if board.turn == chess.WHITE else 0)
        if board.is_checkmate():
            mated_mover = board.turn == mover
            return Fact(moves=moves, state="line:mated" if mated_mover else "line:mates",
                        count=by), (-1000.0 if mated_mover else 1000.0)
        if not board.is_game_over() and _best_capture_gain(board) > 0:
            return None                 # still an exchange open at the end: unnamed
        took, gave = net_pieces(steps, mover)
        pts = _value(took) - _value(gave)
        return Fact(moves=moves, state=_material_state(int(pts)), count=by,
                    took=took, gave=gave), pts
    sp, sb = stand(rd.played), stand(rd.best)
    # Owner, 2026-11-08 (sixth): an unforced line is not trustworthy at any length, so
    # a description exists only in the short form, where the gap shows within the
    # moves printed. (Claims keep their long form: a forced line is forced however long.)
    if any(x is not None and len(x[0].moves) > C.PV_PRINT_MAX_PLIES for x in (sp, sb)):
        _WHY["why"] = "description: a line too long to print (unforced, so not summarised)"
        return None
    if sp is None or sb is None:
        _WHY["why"] = "description: an exchange still open where the lines stop"
        return None
    if sb[1] - sp[1] < C.PV_MATERIAL_THETA:
        _WHY["why"] = "description: the gap is under θ where the lines stop"
        return None
    return Description(descriptor=Descriptor.ENGINE_LINE, subject=pin_side(mover),
                       differential=Differential.BOTH_DIFFER, played=sp[0], best=sb[0],
                       magnitude=float(min(sb[1] - sp[1], 99.0)), horizon=Horizon.PV_END,
                       descriptor_version=PV_READING_VERSION)


@dataclass(frozen=True, slots=True)
class GateCheck:
    """Each condition of the gate, evaluated independently, so the cost of each can be
    measured (owner, 2026-11-08: how the gate's cost splits). `result` is what
    `gate_p` emits: all conditions applied."""

    fires: bool
    consistent: bool
    decided: bool
    has_carrier: bool
    forcing: bool | None
    shown: bool | None          # the claim or description could be built and stated
    result: ProvenClaim | Description | None
    why: str = ""               # when not shown: which part of the cut declined


def gate_check(fen_before: str, rd: PlyReading | None, *, score_before_cp: int | None,
               score_before_mate: int | None, score_after_cp: int | None,
               score_after_mate: int | None) -> GateCheck:
    scores = (score_before_cp, score_before_mate, score_after_cp, score_after_mate)
    if rd is None or not rd.fires:
        return GateCheck(False, False, False, False, None, None, None)
    ok = consistent(rd, *scores)
    dec = decided(*scores)
    line = carrier(rd)
    if line is None:
        return GateCheck(True, ok, dec, False, None, None, None)
    forcing = forcing_to_hold(line)
    _WHY.clear()
    built = _claim(fen_before, rd, line) if forcing else _description(fen_before, rd, line)
    result = built if ok and not dec else None
    return GateCheck(True, ok, dec, True, forcing, built is not None, result,
                     _WHY.get("why", "") if built is None else "")


def gate_p(fen_before: str, rd: PlyReading | None, *, score_before_cp: int | None,
           score_before_mate: int | None, score_after_cp: int | None,
           score_after_mate: int | None) -> ProvenClaim | Description | None:
    """What a ply's PV reading may emit: nothing unless it fires, the eval is
    consistent with it, the position was not already decided (with the verdict
    holding), and one line carries a gain or a mate. Forcing up to the hold → a
    `ProvenClaim` (this module holds the only token that mints its `Proof`); not forcing
    → a `Description` of where the two engine lines stand, with no causation."""
    return gate_check(fen_before, rd, score_before_cp=score_before_cp,
                      score_before_mate=score_before_mate, score_after_cp=score_after_cp,
                      score_after_mate=score_after_mate).result


# ── rendering (for the sample; not wired into the app) ───────────────────────

_NAMES = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}


def numbered(fen: str, steps: Sequence[Step]) -> str:
    """'12.Nxe5 Bxe5 13.Qh5+' style text for the steps."""
    board = chess.Board(fen)
    out = []
    for s in steps:
        n = board.fullmove_number
        if s.colour == chess.WHITE:
            out.append(f"{n}.{s.san}")
        elif not out:
            out.append(f"{n}...{s.san}")
        else:
            out.append(s.san)
        board.push_uci(s.uci)
    return " ".join(out)


def _points(x: float) -> str:
    x = round(x)
    if x == 0:
        return "level in material"
    n = abs(x)
    return f"{n} point{'s' if n != 1 else ''} {'ahead' if x > 0 else 'behind'} in material"


def describe_line(fen: str, line: LineReading, who: str) -> str:
    """One line in words: the moves, the captures, the checks, the end."""
    if not line.steps:
        return "no line is stored"
    takes = [f"{s.san}" for s in line.steps if s.captured]
    checks = [s.san for s in line.steps if s.check and not s.mate]
    parts = [numbered(fen, line.steps)]
    if takes:
        parts.append("captures " + ", ".join(takes))
    if checks:
        parts.append("checks " + ", ".join(checks))
    end = "ends in checkmate" if line.mate else \
        f"ends with {who} {_points(line.settled_end - line.balance_start)}"
    parts.append(end)
    return "; ".join(parts)


def render_ply(fen_before: str, reading: PlyReading, played_san: str, best_san: str,
               who: str = "you") -> str:
    """The sample's text. 'Points' are relative to the position before the move."""
    return (f"Engine's line after {played_san}: {describe_line(fen_before, reading.played, who)}. "
            f"After {best_san}: {describe_line(fen_before, reading.best, who)}.")
