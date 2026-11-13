"""
Labelling a game's plies from their stored rows — classifier version 3 (CLASSIFICATION.md).

`classify()` judges one move from numbers. Since version 3 the numbers it is given are not
all the move's own: the score of the position a move created is the **depth-14** search of
that position, which is stored as ply N+1's before-search (or the run's final lines on the
last ply), not the shallower after-move search the analysis loop runs (owner ruling 1,
2026-11-11, FIXPLAN CLS-V3-1). So a label is a function of a ply *and its neighbours*, and
it lives here, where the game is in view, rather than in the per-ply analysis loop.

Everything here reads stored data only: the rows, the run's final lines and the FEN. No
engine. The same rows always give the same labels, which is what lets the relabel
machinery re-derive the corpus and a recompute pass return 0.

The after-move search is kept, as the row's `after_search_*`: the game report's second,
conservative swing estimate reads it (owner ruling 10), and nothing else does.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

import chess

from .. import config as C
from . import pv_reading as P
from .classification import (MISS_DECIDED_MATE_MAX, MISS_MIN_MATERIAL, WPL_GREAT_GAP,
                             PlyScore, _can_be_great, classify, game_accuracy, win_prob, wpl)
from .database import MoveAnalysis
from .explain import _holds_after_reply, _immediate_gain, explain_ply, see
from .explain_text import capture_is_an_error
from .findings import ProvenClaim

def _neg(cp: int | None, mate: int | None) -> tuple[int | None, int | None]:
    return (-cp if cp is not None else None, -mate if mate is not None else None)


def _scored(cp: int | None, mate: int | None) -> bool:
    return cp is not None or mate is not None


def search_after(ma: MoveAnalysis) -> tuple[int | None, int | None]:
    """The after-move search as the analysis loop ran it (depth `max(d−4, 10)`, MultiPV 1).

    A row labelled before version 3 has it only in `score_after_*`, which is where every
    version-2 row stored it; from version 3 on it is `after_search_*`."""
    if _scored(ma.after_search_cp, ma.after_search_mate):
        return ma.after_search_cp, ma.after_search_mate
    return ma.score_after_cp, ma.score_after_mate


def after_score(
    plies: Sequence[MoveAnalysis], i: int, final_lines: Sequence[dict] | None,
) -> tuple[int | None, int | None, str]:
    """The score, from the mover's side, of the position ply *i*'s move created, and where
    it came from: `next` (ply i+1's stored before-search, negated), `final` (the run's
    final lines, last ply), `terminal` (the game ended on the board: mate 0 for a
    checkmate, 0 cp for a stalemate or a dead position), or `search` (no deeper search is
    stored — an unscored next ply, or a last ply with no final lines — so the after-move
    search stands in)."""
    ma = plies[i]
    if i + 1 < len(plies):
        nxt = plies[i + 1]
        if _scored(nxt.score_before_cp, nxt.score_before_mate):
            cp, mate = _neg(nxt.score_before_cp, nxt.score_before_mate)
            if mate != 0:   # a mated side has no next ply; guard the impossible
                return cp, mate, "next"
    else:
        lines = [ln for ln in (final_lines or ()) if ln]
        if lines and _scored(lines[0].get("cp"), lines[0].get("mate")):
            cp, mate = _neg(lines[0].get("cp"), lines[0].get("mate"))
            if mate != 0:
                return cp, mate, "final"
        board = chess.Board(ma.fen_before)
        board.push(chess.Move.from_uci(ma.played_uci))
        if board.is_checkmate():
            return None, 0, "terminal"
        if board.is_game_over():
            return 0, None, "terminal"
    cp, mate = search_after(ma)
    return cp, mate, "search"


def refutation(plies: Sequence[MoveAnalysis], i: int,
               final_lines: Sequence[dict] | None) -> list[str]:
    """The engine's line after ply *i*'s move: ply i+1's stored best line, or the final
    position's on the last ply (ARCH-0.1-N1)."""
    if i + 1 < len(plies):
        return (plies[i + 1].pv_uci or "").split()
    lines = [ln for ln in (final_lines or ()) if ln and ln.get("uci")]
    return list(lines[0]["uci"]) if lines else []


def missed_win(ma: MoveAnalysis, refut: Sequence[str], a_cp: int | None,
               a_mate: int | None) -> str | None:
    """Why ply *ma* missed a win, or None — the event a `miss` needs (rulings 4 and 7).

    - "line_mates" / "line_wins_material": gate P, on the depth-14 pair, proves the best
      move mates or wins a piece or more (`MISS_MIN_MATERIAL`) by force against what the
      played move keeps — a `ProvenClaim` about the best move, the claim the callout
      states ("X would have won … by force"). Gate P declines in a decided position.
    - "decided_mate": the position was decided (`PV_DECIDED_MIN`) with a mate in
      `MISS_DECIDED_MATE_MAX` or fewer for the mover, the stored best line plays it out
      by force, and the played move has no forced mate left (AUDIT-4: a slower mate
      misses nothing).

    The other conditions — played ≠ best, the mover at least level afterwards — are
    `classify`'s."""
    if not ma.best_uci or ma.best_uci == ma.played_uci:
        return None
    rd = P.read_ply(ma.fen_before, ma.played_uci, (ma.pv_uci or "").split(), list(refut))
    if rd is None:
        return None
    g = P.gate_check(ma.fen_before, rd, score_before_cp=ma.score_before_cp,
                     score_before_mate=ma.score_before_mate, score_after_cp=a_cp,
                     score_after_mate=a_mate)
    c = g.result
    if isinstance(c, ProvenClaim) and c.subject == "best" and (
            c.kind == "line_mates" or (c.material or 0.0) >= MISS_MIN_MATERIAL):
        return c.kind
    m = ma.score_before_mate
    if (m is not None and 0 < m <= MISS_DECIDED_MATE_MAX
            and win_prob(ma.score_before_cp, m) >= C.PV_DECIDED_MIN
            and rd.mate_for and P.forcing_to_hold(rd.best)
            and not (a_mate is not None and a_mate > 0)):
        return "decided_mate"
    return None


# ── great: the obvious strata (CLASSIFICATION.md D, owner ruling 8) ──────────

def net_on_landing(board: chess.Board, move: chess.Move) -> float:
    """What *move* takes, less the opponent's best capture back on its landing square
    (`see`, if worth making): BRILLIANT.md's B3 measure. Negative is a sacrifice."""
    gain = _immediate_gain(board, move)
    after = board.copy(stack=False)
    after.push(move)
    back = [see(after, m) for m in after.legal_moves if m.to_square == move.to_square]
    return gain - max(0.0, max(back) if back else 0.0)


def _en_prise(board: chess.Board, side: bool) -> set[int]:
    """`side`'s pieces the side to move in *board* can take for a pawn or more by SEE."""
    out = set()
    for m in board.legal_moves:
        if not board.is_capture(m) or board.is_en_passant(m):
            continue
        p = board.piece_at(m.to_square)
        if p is not None and p.color == side and p.piece_type != chess.KING and see(board, m) >= 1.0:
            out.add(m.to_square)
    return out


def obvious_strata(plies: Sequence[MoveAnalysis], i: int, uci: str | None = None) -> list[str]:
    """The strata in which ply *i*'s move is an obvious find, from the board alone
    (CLASSIFICATION.md D: 90.0 % of version-2 `great` fall in one): it mates, or a mate in
    two or fewer was on the board; it was forced (in check, or three legal moves or
    fewer); it recaptures on the square just captured on; it takes the piece the opponent
    just moved; it is a capture SEE alone shows wins a pawn or more; it saves a piece that
    was en prise; it promotes. D's repertoire stratum is not used: a label depends only on
    its own game (owner ruling R4, 2026-11-11 second round, FIXPLAN CLS-V3-R4).

    *uci* asks about another move from the same position (R2 asks about the best move);
    by default the played one."""
    ma = plies[i]
    board = chess.Board(ma.fen_before)
    move = chess.Move.from_uci(uci or ma.played_uci)
    after = board.copy(stack=False)
    after.push(move)
    out = []
    m = ma.score_before_mate
    if after.is_checkmate() or (m is not None and 0 < m <= 2):
        out.append("mate")
    if board.is_check() or board.legal_moves.count() <= 3:
        out.append("forced")
    capture = board.is_capture(move)
    if capture and i > 0:
        prev = plies[i - 1]
        pm = chess.Move.from_uci(prev.played_uci)
        if pm.to_square == move.to_square:
            if chess.Board(prev.fen_before).is_capture(pm):
                out.append("recapture")
            out.append("takes the piece just moved")
    if capture and see(board, move) >= 1.0:
        out.append("capture SEE wins")
    if not board.is_check():
        null = board.copy(stack=False)
        null.push(chess.Move.null())
        before = _en_prise(null, board.turn)
        now = _en_prise(after, board.turn)
        if any((move.to_square if sq == move.from_square else sq) not in now for sq in before):
            out.append("saves a piece")
    if move.promotion:
        out.append("promotion")
    return out


def only_move_gap(ma: MoveAnalysis) -> bool:
    """The best move is the only one that holds the evaluation: the stored second line is
    `WPL_GREAT_GAP` (0.15) or more worse than the first (the before-search's MultiPV)."""
    if not ma.best_uci or ma.second_best_uci is None:
        return False
    if not _scored(ma.score_before_cp, ma.score_before_mate):
        return False
    return (win_prob(ma.score_before_cp, ma.score_before_mate)
            - win_prob(ma.second_best_cp, ma.second_best_mate)) >= WPL_GREAT_GAP


def hard_only_move(plies: Sequence[MoveAnalysis], i: int) -> bool:
    """Owner ruling T8 (2026-11-12, third round; FIXPLAN CLS-V3-T8): the position's best
    move is a *hard only move* — the only one that holds (`only_move_gap`) and hard to find
    by ruling 8's predicate (`great_hard` asked of the best move: outside every old obvious
    stratum, and a quiet move or a sacrifice). An internal property, not a label (T9: stored
    data cannot measure how hard a move is to find); stored per ply as
    `move_analyses.hard_only_move` so the game report can use it. It drives the
    critical-move miss: owner, "if you find the move, it'd be great, right?" — a missed
    move that would have been ruling 8's `great`."""
    ma = plies[i]
    return only_move_gap(ma) and great_hard(plies, i, ma.best_uci)


def hangs_material(plies: Sequence[MoveAnalysis], i: int, final_lines: Sequence[dict] | None,
                   a_cp: int | None, a_mate: int | None,
                   min_material: float = MISS_MIN_MATERIAL) -> str | None:
    """Whether ply *i*'s played move gives material away — the callout's own loss sentence
    about the played move, decided from stored data without reading any label (owner ruling
    T3, 2026-11-12, third round; FIXPLAN CLS-V3-T3). *min_material* pawns' worth or more
    (`MISS_MIN_MATERIAL`, a piece, is what T3 builds; 1.0 is "any material", measured only).

    - "claim": gate P on the depth-14 pair states a `ProvenClaim` about the *played* move
      that wins material for the opponent ("This allows White to win a knight by force").
    - "hangs_piece": the rule layer's `hangs_piece` finding ("This drops the rook on d4 —
      Rxd4 takes it") for that much, where the capture it names survives the adjacent-ply
      check read from ply N+1's stored lines (the run's final lines on the last ply): it is
      ply N+1's best move, or not an error against its best line. The label-free form of
      `explain_text.next_ply_contradicts`, which reads ply N+1's *label* when the capture
      was played — a label cannot read another label being decided in the same pass."""
    ma = plies[i]
    rd = P.read_ply(ma.fen_before, ma.played_uci, (ma.pv_uci or "").split(),
                    refutation(plies, i, final_lines))
    if rd is not None:
        c = P.gate_check(ma.fen_before, rd, score_before_cp=ma.score_before_cp,
                         score_before_mate=ma.score_before_mate, score_after_cp=a_cp,
                         score_after_mate=a_mate).result
        if isinstance(c, ProvenClaim) and c.subject == "played" and \
                c.kind == "line_wins_material" and (c.material or 0.0) >= min_material:
            return "claim"
    for f in explain_ply(ma.fen_before, ma.played_uci, best_uci=ma.best_uci):
        if f.kind != "hangs_piece" or -(f.material or 0.0) < min_material:
            continue
        ref = f.moves.get("refutation")
        if ref is None:
            continue
        if i + 1 < len(plies):
            nxt = plies[i + 1]
            if nxt.best_uci == ref.uci or capture_is_an_error(ref.uci, nxt.lines) is False:
                return "hangs_piece"
        else:
            lines = [ln for ln in (final_lines or ()) if ln and ln.get("uci")]
            if lines and (lines[0]["uci"][0] == ref.uci
                          or capture_is_an_error(ref.uci, lines) is False):
                return "hangs_piece"
    return None


def critical_missed(plies: Sequence[MoveAnalysis], i: int,
                    final_lines: Sequence[dict] | None = None,
                    a_cp: int | None = None, a_mate: int | None = None) -> bool:
    """Owner ruling R2 (2026-11-11, second round; FIXPLAN CLS-V3-R2): the critical move
    missed. Owner: "if it is even, and suddenly you have to spot an extremely ambiguous
    move, i wouldn't say it's a blunder if you don't find it." As narrowed by the third
    round (2026-11-12):

    - T8: the best move is a `hard_only_move` — the only one that holds, outside every old
      obvious stratum, and a quiet move or a sacrifice (R2 as first built asked only the
      strata). So every critical-move miss would have been ruling 8's `great` if played; a
      missed *easy* only move is labelled by cost.
    - T3: the played move does not hang a piece or more (`hangs_material`) — "if you are up
      a knight and blunder your knight, that's a blunder".
    - T2 (the played move costs more than 0.05), the floor (the mover at least
      `MISS_MIN_WP_AFTER` afterwards, R1) and the other miss conditions are `classify`'s.

    An advantage that several moves would have kept (no gap), thrown, is still a blunder by
    cost (ruling 5)."""
    ma = plies[i]
    if not ma.best_uci or ma.best_uci == ma.played_uci:
        return False
    if not hard_only_move(plies, i):
        return False
    return hangs_material(plies, i, final_lines, a_cp, a_mate) is None


def great_candidate(ma: MoveAnalysis, a_cp: int | None, a_mate: int | None) -> bool:
    """Version 2's whole `great` test on the version-3 after-score: the engine's move,
    at least `good` itself, not already lost, and the stored second line `WPL_GREAT_GAP`
    or more worse. Ruling 8 keeps it and adds `great_hard`."""
    if not ma.best_uci or ma.played_uci != ma.best_uci or ma.second_best_uci is None:
        return False
    loss = wpl(ma.score_before_cp, ma.score_before_mate, a_cp, a_mate)
    if not _can_be_great(loss, ma.score_before_cp, ma.score_before_mate):
        return False
    return (win_prob(ma.score_before_cp, ma.score_before_mate)
            - win_prob(ma.second_best_cp, ma.second_best_mate)) >= WPL_GREAT_GAP


def great_hard(plies: Sequence[MoveAnalysis], i: int, uci: str | None = None) -> bool:
    """Ruling 8's H2 test, which no longer makes a label (T7 replaced it): outside every
    obvious stratum, and a quiet move — no capture, no check — or a sacrifice
    (`net_on_landing` < 0). No repertoire stratum (R4). Kept as the "hard" half of
    `hard_only_move` (T8). *uci* asks about another move from the same position; by
    default the played one."""
    if obvious_strata(plies, i, uci):
        return False
    ma = plies[i]
    board = chess.Board(ma.fen_before)
    move = chess.Move.from_uci(uci or ma.played_uci)
    if net_on_landing(board, move) < 0:
        return True
    return not board.is_capture(move) and not board.gives_check(move)


def obvious_recapture(plies: Sequence[MoveAnalysis], i: int) -> bool:
    """Owner ruling T7 (2026-11-12, third round): ply *i*'s move captures on the square the
    opponent just captured on, and no other legal move captured on that square. Where two
    or more pieces could take back, the recapture is a choice and stays eligible for
    `great` — the gap test already says only this one works."""
    if i == 0:
        return False
    ma, prev = plies[i], plies[i - 1]
    board = chess.Board(ma.fen_before)
    move = chess.Move.from_uci(ma.played_uci)
    pm = chess.Move.from_uci(prev.played_uci)
    if not board.is_capture(move) or pm.to_square != move.to_square:
        return False
    if not chess.Board(prev.fen_before).is_capture(pm):
        return False
    takers = [m for m in board.legal_moves
              if m.to_square == move.to_square and board.is_capture(m)]
    # Promotions to different pieces are one recapture, not a choice of capturers.
    return len({m.from_square for m in takers}) <= 1


def great_eligible(plies: Sequence[MoveAnalysis], i: int) -> bool:
    """Owner ruling T7 (2026-11-12, third round; FIXPLAN CLS-V3-T7), replacing ruling 8:
    `great` needs the move not to be an obvious recapture and more than one legal move.
    Owner: "i think the ONLY thing that needed to be removed was obvious recaptures. i
    don't think the move NECESSARILY has to be hard to find" — "two or three legal moves
    where ONLY one is good can be great. saving an attacked piece is good. checks can be
    brought back, but still, if it is the only move." The gap and `_can_be_great` are
    `classify`'s."""
    ma = plies[i]
    if chess.Board(ma.fen_before).legal_moves.count() <= 1:
        return False
    return not obvious_recapture(plies, i)


# ── brilliant: BRILLIANT.md B1–B5 (owner ruling 9) ───────────────────────────

def offers_a_piece(board: chess.Board, move: chess.Move) -> bool:
    """B3, as refined by owner ruling R6 (2026-11-11, second round; FIXPLAN CLS-V3-R6): the
    unit offered on the landing square is a piece, not a pawn. Owner: "it is not really
    'brilliant' to just sacrifice a pawn". A promotion offers the promoted piece."""
    if move.promotion:
        return True
    piece = board.piece_at(move.from_square)
    return piece is not None and piece.piece_type != chess.PAWN


def brilliant(ma: MoveAnalysis) -> bool:
    """BRILLIANT.md's rule, from the stored row and its FEN only (no engine):

    - B1 the engine's own move; the mover had no forced mate already; win probability
      before at most `BRILLIANT_MAX_WP_BEFORE` (0.90). *No book exclusion* (ruling 9).
    - B2 not forced: at least `BRILLIANT_MIN_LEGAL` (5) legal moves.
    - B3 a real sacrifice: `net_on_landing` < 0 — what the move took, less the
      opponent's best SEE back on its square — of a piece, not a pawn (`offers_a_piece`,
      ruling R6).
    - B4 taking it fails: the opponent's best capture there does not hold under gate P's
      two-ply minimax (`_holds_after_reply`).
    - B5 hard: the stored 2nd and 3rd lines are each `BRILLIANT_MIN_GAP_2ND` / `_3RD`
      (0.15) worse.

    Checking sacrifices are included (ruling 9: "keep checking sacrifices, even if it's a
    book move it's still brilliant"); B4's minimax answers checks."""
    if not ma.best_uci or ma.played_uci != ma.best_uci:
        return False
    if ma.score_before_mate is not None and ma.score_before_mate > 0:
        return False
    if win_prob(ma.score_before_cp, ma.score_before_mate) > C.BRILLIANT_MAX_WP_BEFORE:
        return False
    board = chess.Board(ma.fen_before)
    if board.legal_moves.count() < C.BRILLIANT_MIN_LEGAL:
        return False
    move = chess.Move.from_uci(ma.played_uci)
    if not net_on_landing(board, move) < 0 or not offers_a_piece(board, move):
        return False
    after = board.copy(stack=False)
    after.push(move)
    takes = [m for m in after.legal_moves if m.to_square == move.to_square]
    if takes and _holds_after_reply(after, max(takes, key=lambda m: see(after, m)),
                                    1.0) is not None:
        return False
    lines = [ln for ln in ma.lines or () if ln.get("uci")]
    if len(lines) < 3:
        return False
    w = [win_prob(ln.get("cp"), ln.get("mate")) for ln in lines[:3]]
    return w[0] - w[1] >= C.BRILLIANT_MIN_GAP_2ND and w[0] - w[2] >= C.BRILLIANT_MIN_GAP_3RD


def forfeited_mate_in_one(board: chess.Board, played: chess.Move) -> bool:
    """Whether mate was available in one and the move played was not it (a rule fact; see
    `classify`'s mate-in-one gate)."""
    board.push(played)
    played_mates = board.is_checkmate()
    board.pop()
    if played_mates:
        return False
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def label_ply(
    plies: Sequence[MoveAnalysis],
    i: int,
    final_lines: Sequence[dict] | None,
) -> MoveAnalysis:
    """Ply *i* with its version-3 after-score and label.

    *plies* must hold ply i+1 when there is one (the analysis loop calls this one ply
    behind); *final_lines* matters only on the last ply. The label reads this game only
    (R4)."""
    ma = plies[i]
    s_cp, s_mate = search_after(ma)
    a_cp, a_mate, _src = after_score(plies, i, final_lines)
    board = chess.Board(ma.fen_before)
    move = chess.Move.from_uci(ma.played_uci)
    hard = hard_only_move(plies, i)
    label = classify(
        played_uci=ma.played_uci,
        best_uci=ma.best_uci,
        score_before_cp=ma.score_before_cp,
        score_before_mate=ma.score_before_mate,
        score_after_cp=a_cp,
        score_after_mate=a_mate,
        second_best_uci=ma.second_best_uci,
        second_best_cp=ma.second_best_cp,
        second_best_mate=ma.second_best_mate,
        is_book=ma.is_book,
        only_legal_move=board.legal_moves.count() == 1,
        forfeited_mate_in_one=forfeited_mate_in_one(board, move),
        brilliant=brilliant(ma),
        missed_win=missed_win(ma, refutation(plies, i, final_lines), a_cp, a_mate) is not None,
        critical_missed=critical_missed(plies, i, final_lines, a_cp, a_mate),
        great_eligible=great_eligible(plies, i),
    )
    return replace(ma, score_after_cp=a_cp, score_after_mate=a_mate,
                   after_search_cp=s_cp, after_search_mate=s_mate, classification=label,
                   hard_only_move=hard)


def label_game(
    plies: Sequence[MoveAnalysis],
    final_lines: Sequence[dict] | None,
) -> list[MoveAnalysis]:
    """Every ply of a run, labelled. *plies* ordered by ply, 0..n−1."""
    return [label_ply(plies, i, final_lines) for i in range(len(plies))]


def summary(plies: Sequence[MoveAnalysis]) -> dict:
    """The run summary `complete_analysis_run` stores: label counts and accuracy per side,
    from the labelled plies (so accuracy reads the same after-score the labels do)."""
    counts: dict[str, dict[str, int]] = {"white": {}, "black": {}}
    scores: list[PlyScore] = []
    for ma in plies:
        mover = "white" if " w " in ma.fen_before else "black"
        counts[mover][ma.classification] = counts[mover].get(ma.classification, 0) + 1
        scores.append(PlyScore(mover, ma.score_before_cp, ma.score_before_mate,
                               ma.score_after_cp, ma.score_after_mate))
    accuracy = game_accuracy(scores)
    return {
        side: {
            "counts": counts[side],
            "accuracy": round(accuracy[side], 1) if accuracy[side] is not None else None,
        }
        for side in ("white", "black")
    }
