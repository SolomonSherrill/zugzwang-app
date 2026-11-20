"""
Pure game-analysis logic — no Qt imports.

Extracted verbatim from core/analyzer.py so that both the PyQt AnalysisWorker
and the Tauri sidecar can drive the same loop. AnalysisWorker re-exports the
helpers it previously owned, so existing imports keep working.

The main entry point is analyze_game_plies(), a generator that yields one
event tuple per step:

    ("ply", ply, total, MoveAnalysis)          per ply
    ("done", summary, final_lines)             after the final ply, and only then;
                                               final_lines are the top lines of the
                                               game's final position (STORE-FINALPLY),
                                               [] when it has no legal move
    ("cancelled",)                             when is_cancelled() turns True
    ("error", message)                         a bad PGN, or an engine error on any
                                               of a ply's searches
    ("engine_died", ply, fen, exc)             the engine died and this ply has no
                                               answer (VAL-DEATH)

Every event after the first is final except "ply". There is no empty ply: an engine
that fails on a ply ends the game there, because a ply-less hole used to be skipped
and the game still reported done, with accuracy computed from whatever survived.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import replace
from typing import Callable, Iterator, TYPE_CHECKING

import chess
import chess.engine
import chess.pgn

import zugzwang.config as C
from zugzwang.core.classification import PlyScore, classify, game_accuracy, win_prob
from zugzwang.core.database import MoveAnalysis
from zugzwang.core.labelling import forfeited_mate_in_one, label_ply
from zugzwang.core.labelling import summary as labelled_summary
from zugzwang.core.engine_supervisor import DEATH

if TYPE_CHECKING:
    from zugzwang.core.openings import OpeningsBook

logger = logging.getLogger(__name__)

# ── Score extraction helpers ─────────────────────────────────────────────────

def _extract_score(
    info: chess.engine.InfoDict | None, turn: chess.Color
) -> tuple[int | None, int | None]:
    """Return (cp, mate) from the mover's perspective."""
    if info is None:
        return None, None
    score = info.get("score")
    if score is None:
        return None, None
    pov = score.pov(turn)
    if pov.is_mate():
        return None, pov.mate()
    return pov.score(), None


def _extract_score_negated(
    info: chess.engine.InfoDict | None,
) -> tuple[int | None, int | None]:
    """
    Extract score from the *opponent's* perspective (after the move was played)
    and negate it to get the mover's perspective.
    """
    if info is None:
        return None, None
    score = info.get("score")
    if score is None:
        return None, None
    # info is from next player's POV; negate
    pov = score.relative  # relative to the side to move
    if pov.is_mate():
        mate = pov.mate()
        return None, -mate   # negate: if opponent has mate-in-3, mover has -3
    cp = pov.score()
    if cp is None:
        return None, None
    return -cp, None


def _top_move(
    info: chess.engine.InfoDict | None, board: chess.Board
) -> str | None:
    if info is None:
        return None
    pv = info.get("pv")
    if pv:
        return pv[0].uci()
    return None


def _pv_uci(info: chess.engine.InfoDict | None) -> str:
    if info is None:
        return ""
    pv = info.get("pv", [])
    return " ".join(m.uci() for m in pv[:C.ANALYSIS_PV_STORE_LEN])


def _lines_from_info(
    info_list: list[chess.engine.InfoDict],
    board: chess.Board,
    pv_len: int = C.ANALYSIS_PV_STORE_LEN,
) -> list[dict]:
    """Convert an already-fetched MultiPV info list into the same {cp, mate,
    uci, san} shape as analyze_position_multipv, so saved game analysis can
    reuse the multipv search it already ran. cp/mate are side-to-move POV."""
    lines: list[dict] = []
    for info in info_list:
        cp, mate = _extract_score(info, board.turn)
        pv = info.get("pv", []) or []
        uci: list[str] = []
        san: list[str] = []
        probe = board.copy()
        for mv in pv[:pv_len]:
            try:
                san.append(probe.san(mv))
            except Exception:
                break
            uci.append(mv.uci())
            probe.push(mv)
        lines.append({"cp": cp, "mate": mate, "uci": uci, "san": san})
    return lines


def _build_summary(
    counts: dict[str, dict[str, int]],
    ply_scores: list[PlyScore],
) -> dict:
    accuracy = game_accuracy(ply_scores)
    return {
        side: {
            "counts": counts.get(side, {}),
            "accuracy": (
                round(accuracy[side], 1) if accuracy[side] is not None else None
            ),
        }
        for side in ("white", "black")
    }


# ── Whole-game analysis loop ─────────────────────────────────────────────────

def analyze_game_plies(
    engine: chess.engine.SimpleEngine,
    pgn_str: str,
    depth: int,
    openings: "OpeningsBook | None" = None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple]:
    """Walk every ply of the PGN, analyse with Stockfish, yield event tuples."""
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        yield ("error", "Could not parse PGN.")
        return

    moves = list(game.mainline_moves())
    total = len(moves)
    if total == 0:
        yield ("done", {}, [])
        return

    board = game.board()
    # A PGN's `[FEN]` start comes from outside (an import); a legal start and legal
    # moves keep every later position legal, so this one check covers the game.
    from .positions import IllegalPosition, require_legal
    try:
        require_legal(board, "the game's starting position")
    except IllegalPosition as exc:
        yield ("error", str(exc))
        return
    plies: list[MoveAnalysis] = []      # searched, not yet labelled
    labelled: list[MoveAnalysis] = []

    def _labelled(i: int, final: list[dict] | None) -> MoveAnalysis:
        ma = label_ply(plies, i, final)
        labelled.append(ma)
        return ma

    # One identity for every search of this game, so python-chess sends
    # `ucinewgame` — clearing the hash — exactly once, at its start. Without it the
    # hash carried over from whatever the engine searched before, and a game's
    # analysis depended on which game preceded it on that engine; with several
    # engines side by side (ENG-ALLOC) that would make results depend on scheduling.
    this_game = object()

    for ply, move in enumerate(moves):
        if is_cancelled():
            yield ("cancelled",)
            return

        fen_before = board.fen()

        # Book check
        is_book = openings is not None and openings.is_book_move(board, move)

        # Book plies are analysed like any other (F4a). They used to skip the
        # engine entirely, which made the `book` label unfalsifiable and left
        # ~19 % of every game with no eval to show.
        try:
            info_list = engine.analyse(
                board,
                chess.engine.Limit(depth=depth),
                multipv=C.ANALYSIS_MULTIPV,
                game=this_game,
            )
        except DEATH as exc:
            yield ("engine_died", ply, fen_before, exc)
            return
        except Exception as exc:
            logger.error("Engine analysis error at ply %d: %s", ply, exc)
            yield ("error", f"engine error at ply {ply}: {exc}")
            return

        # info_list[0] is best, [1] second-best, [2] third-best (if available)
        best_info = info_list[0] if info_list else None
        second_info = info_list[1] if len(info_list) > 1 else None

        score_before_cp, score_before_mate = _extract_score(best_info, board.turn)
        best_uci = _top_move(best_info, board)
        pv_uci = _pv_uci(best_info)
        # capture the top lines (before the played move) for instant review
        top_lines = _lines_from_info(info_list, board)

        second_best_uci: str | None = None
        second_best_cp: int | None = None
        second_best_mate: int | None = None
        if second_info:
            second_best_uci = _top_move(second_info, board)
            second_best_cp, second_best_mate = _extract_score(second_info, board.turn)

        # The label is not decided in this loop. Since classifier version 3 it reads the
        # depth-14 score of the position a move created, which is the *next* ply's
        # before-search (CLS-V3-1), and since J1 (version 4) whether the mover's next move
        # captured the piece the best line takes — ply N+2's position and move. So ply N
        # is labelled and emitted here, two plies behind, as soon as ply N+2's row exists;
        # the last two plies after the final position's search. Ply N's row is appended now with its before-search and
        # completed below with the after-move search, which `label_ply` keeps as
        # `after_search_*`.
        plies.append(MoveAnalysis(
            ply=ply,
            fen_before=fen_before,
            played_uci=move.uci(),
            # No `or move.uci()` fallback: when the engine named no best move, saying the
            # played move was best is a claim nobody made.
            best_uci=best_uci,
            pv_uci=pv_uci,
            score_before_cp=score_before_cp,
            score_before_mate=score_before_mate,
            score_after_cp=None,
            score_after_mate=None,
            second_best_uci=second_best_uci,
            second_best_cp=second_best_cp,
            second_best_mate=second_best_mate,
            classification="",
            is_book=is_book,
            lines=top_lines,
        ))
        if ply >= 2:
            yield ("ply", ply - 2, total, _labelled(ply - 2, None))

        # Push the played move to get the resulting score
        board.push(move)

        if is_book and openings:
            openings.name_after(board)  # side-effect: warm cache

        # Analyse the position *after* the played move from the opponent's
        # perspective, then negate to get the score from the mover's perspective
        try:
            after_info = engine.analyse(
                board,
                chess.engine.Limit(depth=max(depth - 4, 10)),
                multipv=1,
                game=this_game,
            )
            score_after_cp, score_after_mate = _extract_score_negated(
                after_info[0] if after_info else None
            )
        except DEATH as exc:
            yield ("engine_died", ply, fen_before, exc)
            return
        except Exception as exc:
            # Ends the game like the main search's error does. This used to set the
            # after-score to the before-score — a measurement nobody made, which
            # `classify` reads as a loss-free move (W18).
            logger.error("Engine error after ply %d: %s", ply, exc)
            yield ("error", f"engine error after ply {ply}: {exc}")
            return

        plies[ply] = replace(plies[ply], score_after_cp=score_after_cp,
                             score_after_mate=score_after_mate,
                             after_search_cp=score_after_cp,
                             after_search_mate=score_after_mate)

    # The final position, searched like every other position before a move would be:
    # ply N+1's lines hold the refutation of ply N's move, and without this the last
    # move — most often the one a game was resigned or flagged after — had none
    # (STORE-FINALPLY; ARCH-0.1-N1 found 265 errors on final plies). Mate and
    # stalemate have no move to search. Since version 3 it is also the last move's
    # after-score.
    final_lines: list[dict] = []
    if any(board.legal_moves):
        try:
            final_lines = _lines_from_info(engine.analyse(
                board, chess.engine.Limit(depth=depth), multipv=C.ANALYSIS_MULTIPV,
                game=this_game,
            ), board)
        except DEATH as exc:
            yield ("engine_died", total, board.fen(), exc)
            return
        except Exception as exc:
            logger.error("Engine error on the final position: %s", exc)
            yield ("error", f"engine error on the final position: {exc}")
            return

    if total >= 2:
        yield ("ply", total - 2, total, _labelled(total - 2, final_lines))
    yield ("ply", total - 1, total, _labelled(total - 1, final_lines))
    yield ("done", labelled_summary(labelled), final_lines)


def lines_after(plies: list[MoveAnalysis], final_lines: list[dict], ply: int) -> list[dict]:
    """The engine's lines for the position *ply*'s move created — the refutation of
    that move, when it was a mistake. Ply N+1's stored lines, or the final position's
    for the last move (ARCH-0.1-N1). `plies` is a run's, ordered by ply."""
    return plies[ply + 1].lines if ply + 1 < len(plies) else final_lines


# ── Engine resource configuration ─────────────────────────────────────────────

def configure_engine_for_analysis(engine: chess.engine.SimpleEngine) -> None:
    """Apply Threads / Hash from config, best-effort; skips options the engine
    lacks. Called on every analysis engine (Re-analyse, the FEN path, each sync
    worker) so they all run one configuration — see `ANALYSIS_THREADS` for why that
    configuration is one thread. Not on live play, which sets its own strength."""
    opts: dict = {}
    available = getattr(engine, "options", {}) or {}
    if "Threads" in available:
        opts["Threads"] = C.ANALYSIS_THREADS
    if "Hash" in available:
        opts["Hash"] = C.ANALYSIS_HASH_MB
    if opts:
        try:
            engine.configure(opts)
        except Exception as exc:
            logger.warning("Could not configure engine resources: %s", exc)


# ── Embedded-eval (Lichess [%eval]) classification ────────────────────────────

_EVAL_RE = re.compile(r"\[%eval\s+(#?-?\d+(?:\.\d+)?)\]")


def _parse_eval_comment(comment: str) -> tuple[int | None, int | None]:
    """Parse a python-chess node comment containing a Lichess ``[%eval ...]``
    annotation. Returns ``(cp, mate)`` from **White's** perspective, the
    convention Lichess uses. ``[%eval 0.24]`` → (24, None);
    ``[%eval #-3]`` → (None, -3). Returns (None, None) when absent."""
    if not comment:
        return None, None
    m = _EVAL_RE.search(comment)
    if not m:
        return None, None
    token = m.group(1)
    if token.startswith("#"):
        try:
            return None, int(token[1:])
        except ValueError:
            return None, None
    try:
        return int(round(float(token) * 100)), None
    except ValueError:
        return None, None


def _pov(cp: int | None, mate: int | None, color: chess.Color
         ) -> tuple[int | None, int | None]:
    """Flip a White-POV (cp, mate) pair to *color*'s perspective."""
    if color == chess.WHITE:
        return cp, mate
    return (None if cp is None else -cp), (None if mate is None else -mate)


def eval_coverage(pgn_str: str) -> float:
    """Fraction of plies that carry an ``[%eval]`` annotation. Used to decide
    whether a game can be classified from embedded evals or needs local
    Stockfish. Returns 0.0 for an unparseable / moveless game."""
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        return 0.0
    total = 0
    have = 0
    node = game
    while node.variations:
        node = node.variations[0]
        total += 1
        cp, mate = _parse_eval_comment(node.comment)
        if cp is not None or mate is not None:
            have += 1
    return have / total if total else 0.0


def analyze_game_from_evals(
    pgn_str: str,
    openings: "OpeningsBook | None" = None,
) -> tuple[list[MoveAnalysis], dict] | None:
    """Classify every ply of a game using only the embedded ``[%eval]``
    annotations — no engine. Returns ``(analyses, summary)`` or None if the PGN
    is unparseable / moveless.

    Embedded evals give the position score but no engine best move, so we cannot
    distinguish best/great/brilliant. A move whose win-probability loss is at or
    below ``SYNC_EVAL_BEST_WPL`` is treated as 'best' (passed as its own
    best_uci); otherwise best_uci is None and the WPL ladder assigns the
    category. None rather than the played move, so the label never rests on an
    agreement the engine was never asked about."""
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        return None

    board = game.board()
    analyses: list[MoveAnalysis] = []
    counts: dict[str, dict[str, int]] = {"white": {}, "black": {}}
    ply_scores: list[PlyScore] = []

    # White-POV eval of the starting position (before any move). Lichess seeds
    # its eval chain with Cp.initial = +15 rather than dead level, so White's
    # first move is not scored as having thrown away a nonexistent equality.
    prev_cp: int | None = 15
    prev_mate: int | None = None

    node = game
    ply = 0
    while node.variations:
        nxt = node.variations[0]
        move = nxt.move
        if move is None:
            break

        fen_before = board.fen()
        mover = "white" if board.turn == chess.WHITE else "black"
        color = board.turn

        is_book = openings is not None and openings.is_book_move(board, move)

        # White-POV eval after this move, taken from the child node's comment.
        cur_cp, cur_mate = _parse_eval_comment(nxt.comment)

        if is_book and openings:
            # Warm the opening-name cache. The rest of the book short-circuit is
            # gone (F4a): the PGN already carries evals for these plies, so the
            # label can be gated here at no engine cost.
            board.push(move)
            openings.name_after(board)
            board.pop()

        sb_cp, sb_mate = _pov(prev_cp, prev_mate, color)
        sa_cp, sa_mate = _pov(cur_cp, cur_mate, color)

        only_legal = board.legal_moves.count() == 1
        forfeited_mate = forfeited_mate_in_one(board, move)

        ply_scores.append(PlyScore(mover, sb_cp, sb_mate, sa_cp, sa_mate))

        loss = max(0.0, win_prob(sb_cp, sb_mate) - win_prob(sa_cp, sa_mate))
        treat_as_best = loss <= C.SYNC_EVAL_BEST_WPL

        cls = classify(
            played_uci=move.uci(),
            best_uci=move.uci() if treat_as_best else None,
            score_before_cp=sb_cp,
            score_before_mate=sb_mate,
            score_after_cp=sa_cp,
            score_after_mate=sa_mate,
            second_best_uci=None,
            second_best_cp=None,
            second_best_mate=None,
            is_book=is_book,
            only_legal_move=only_legal,
            forfeited_mate_in_one=forfeited_mate,
        )

        ma = MoveAnalysis(
            ply=ply,
            fen_before=fen_before,
            played_uci=move.uci(),
            best_uci=move.uci() if treat_as_best else None,
            pv_uci="",
            score_before_cp=sb_cp,
            score_before_mate=sb_mate,
            score_after_cp=sa_cp,
            score_after_mate=sa_mate,
            second_best_uci=None,
            second_best_cp=None,
            second_best_mate=None,
            classification=cls,
            is_book=is_book,
        )
        counts[mover][cls] = counts[mover].get(cls, 0) + 1
        analyses.append(ma)

        board.push(move)
        prev_cp, prev_mate = cur_cp, cur_mate
        node = nxt
        ply += 1

    if not analyses:
        return None
    return analyses, _build_summary(counts, ply_scores)


def analyze_position(
    engine: chess.engine.SimpleEngine, fen: str, depth: int = C.ANALYSIS_DEPTH
) -> tuple[str, int | None, int | None]:
    """Analyse a single position; returns (best_uci, cp, mate) from the
    side-to-move's perspective. Identical to the old analyze_single_fen body."""
    board = chess.Board(fen)
    info_list = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=1)
    info = info_list[0] if info_list else None
    best_uci = _top_move(info, board)
    cp: int | None = None
    mate: int | None = None
    if info is not None:
        score = info.get("score")
        if score is not None:
            pov = score.pov(board.turn)
            if pov.is_mate():
                mate = pov.mate()
            else:
                cp = pov.score()
    return best_uci, cp, mate


def analyze_position_multipv(
    engine: chess.engine.SimpleEngine,
    fen: str,
    depth: int = C.ANALYSIS_DEPTH,
    multipv: int = 3,
    pv_len: int = 6,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[dict]:
    """Analyse a position with MultiPV; return up to *multipv* lines ordered
    best-first. Each line is {cp, mate, uci, san} where cp/mate are from the
    side-to-move's perspective and san is the principal variation rendered in
    SAN, truncated to *pv_len* half-moves.

    With `is_cancelled`, the search streams instead of blocking, the predicate is
    consulted on every info line the engine sends, and a cancelled search returns
    `[]` — telling the caller there is no answer, rather than a partial one that
    would read as a shallower eval of the same position. Without it the engine is
    left to run to the depth limit, which is the cheaper path and the one bulk
    analysis wants.
    """
    board = chess.Board(fen)
    if is_cancelled is None:
        info_list = engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv
        )
    else:
        with engine.analysis(
            board, chess.engine.Limit(depth=depth), multipv=multipv
        ) as stream:
            for _ in stream:
                if is_cancelled():
                    stream.stop()
                    return []
            if is_cancelled():
                return []
            info_list = [info for info in stream.multipv if info.get("pv")]
    lines: list[dict] = []
    for info in info_list:
        cp, mate = _extract_score(info, board.turn)
        pv = info.get("pv", []) or []
        uci: list[str] = []
        san: list[str] = []
        probe = board.copy()
        for mv in pv[:pv_len]:
            try:
                san.append(probe.san(mv))
            except Exception:
                break
            uci.append(mv.uci())
            probe.push(mv)
        lines.append({"cp": cp, "mate": mate, "uci": uci, "san": san})
    return lines
