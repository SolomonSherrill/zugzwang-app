"""
Patterns across games (R6, GR2-11; PATTERNS.md §4–§6a): the Insights card's two sentences.

P4 — punishing: after the other side's serious error (mistake, miss or blunder), how often the
next move was the engine's, the user's replies against the opponents'. P6 — how losses are
decided: of the user's decided games (the game report's `decided`, which only a game with a
winner has), how often a single move decided it, losses against wins.

Both read per-run facts stored in `pattern_facts` (PATTERNS.md §6a), never the moves or the
reports at load time: P6 needs every game's report, which costs a corpus 630 s of CPU. The
facts are written when a run completes (`write_facts_for_run`) and backfilled for existing runs
by `tools/backfill_pattern_facts.py`.

A sentence is shown only where its game-clustered interval excludes 1.0 in the measured
direction and it survives Benjamini–Hochberg over the card's sentences (owner ruling R6-4,
2026-11-13). Qt-free; engine-free.
"""

from __future__ import annotations

import io
import json
import math
import re
from typing import TYPE_CHECKING, Sequence

import chess
import chess.pgn

from .stats import benjamini_hochberg, normal_two_sided_p

if TYPE_CHECKING:
    from .database import Database, InsightsFilter, MoveAnalysis

#: Bump when what a facts row holds, or how it is computed, changes: rows of other versions
#: stop counting and the backfill (or the sidecar's refill) refills them.
#: 2 (K2, owner 2026-11-14): a reply that delivers mate counts as punishing.
FACTS_VERSION = 2

SERIOUS = ("mistake", "miss", "blunder")
FDR = 0.05
Z95 = 1.96


# ── the facts of one run ───────────────────────────────────────────────────────

def _move_label(fen: str, uci: str) -> str | None:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        return None
    n = board.fullmove_number
    return f"{n}{'.' if board.turn == chess.WHITE else '…'}{board.san(move)}"


def _mates(fen: str, uci: str) -> bool:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        return False
    board.push(move)
    return board.is_checkmate()


def p4_facts(plies: Sequence["MoveAnalysis"]) -> dict:
    """Per colour: the moves played right after the other side's serious error (`n`), how
    many punished it (`best`: the engine's move, or — K2, owner 2026-11-14 — a move that
    delivers mate), and the plies that did neither (`missed`: [ply, move label, label]).
    *plies* ordered by ply, 0..n−1."""
    out = {c: {"n": 0, "best": 0, "missed": []} for c in ("white", "black")}
    for i in range(1, len(plies)):
        if plies[i - 1].classification not in SERIOUS:
            continue
        m = plies[i]
        side = "white" if " w " in m.fen_before else "black"
        c = out[side]
        c["n"] += 1
        if (m.best_uci and m.played_uci == m.best_uci) or _mates(m.fen_before, m.played_uci):
            c["best"] += 1
        else:
            c["missed"].append([m.ply, _move_label(m.fen_before, m.played_uci),
                                m.classification])
    return out


def _headers(pgn: str) -> dict[str, str]:
    return dict(re.findall(r'^\[(\w+) "([^"]*)"\]', pgn, re.M))


def run_facts(plies: Sequence["MoveAnalysis"], *, pgn: str, result: str, termination: str,
              player_color: str | None, depth: int,
              final_lines: Sequence[dict] | None) -> dict:
    """The facts of one complete run: P4's counts and P6's `decided`, from the game report
    built as `rpc_game_report` builds it, less the book (which `decided` does not read)."""
    from .game_report import build_report   # the report imports the explanation layer

    game = chess.pgn.read_game(io.StringIO(pgn))
    nodes = list(game.mainline()) if game is not None else []
    pgn_moves = []
    board = game.board() if game is not None else None
    for n in nodes:
        pgn_moves.append((board.fen(), n.move.uci()))
        board.push(n.move)
    report = build_report(
        plies, game_plies=len(nodes), result=result, termination=termination,
        player_color=player_color, depth=depth, clocks=[n.clock() for n in nodes],
        time_control=game.headers.get("TimeControl") if game is not None else None,
        pgn_moves=pgn_moves, book=None, final_lines=final_lines,
    )
    d = report.get("decided")
    by = d.get("byPly") if d else None
    by_label = None
    if by is not None and 0 <= by < len(plies):
        by_label = _move_label(plies[by].fen_before, plies[by].played_uci)
    h = _headers(pgn)
    return {
        "p4": p4_facts(plies),
        "p6": {"decided": d is not None, "side": d["side"] if d else None,
               "byPly": by, "byMove": by_label},
        "players": {"white": h.get("White"), "black": h.get("Black")},
    }


def facts_for_run(db: "Database", run_id: int) -> tuple[dict, int | None] | None:
    """(facts, the run's classifier_version) for a complete run, or None if it is not one."""
    row = db._conn.execute(
        """SELECT r.game_id, r.depth, r.classifier_version, r.final_lines_json
           FROM analysis_runs r WHERE r.id = ? AND r.completed_at IS NOT NULL""",
        (run_id,)).fetchone()
    if row is None:
        return None
    game_id, depth, cls_version, fl = row[0], row[1], row[2], row[3]
    rec = db.get_game(game_id)
    plies = sorted(db.load_move_analyses(run_id), key=lambda m: m.ply)
    final_lines = json.loads(fl) if fl else None
    facts = run_facts(plies, pgn=rec.pgn, result=rec.result, termination=rec.termination,
                      player_color=rec.player_color, depth=depth, final_lines=final_lines)
    return facts, cls_version


def facts_row(db: "Database", run_id: int) -> tuple | None:
    """One run's `pattern_facts` row (run_id, FACTS_VERSION, classifier_version,
    RULE_VERSION, facts_json), or None if it is not a complete run. *db* may be a read-only
    connection: the backfill's workers and the sidecar's refill compute here and write
    elsewhere."""
    from .explain import RULE_VERSION
    got = facts_for_run(db, run_id)
    if got is None:
        return None
    facts, cls_version = got
    return (run_id, FACTS_VERSION, cls_version, RULE_VERSION,
            json.dumps(facts, separators=(",", ":")))


def write_facts_for_run(db: "Database", run_id: int) -> bool:
    """Compute and store one run's facts (the write at completion). True if written."""
    row = facts_row(db, run_id)
    if row is None:
        return False
    db.save_pattern_facts([row])
    return True


# ── the card ──────────────────────────────────────────────────────────────────

def clustered_rr(clusters: Sequence[tuple[int, int, int, int]]) -> dict | None:
    """The rate ratio (Yx/Nx) / (Yo/No) over per-game clusters (nx, yx, no, yo), with the
    game-clustered delta-method interval on log RR (per-game influence terms, the form
    `insights._rate_diff` and PATTERNS.md §2 use) and its two-sided p-value."""
    nx = sum(c[0] for c in clusters); yx = sum(c[1] for c in clusters)
    no = sum(c[2] for c in clusters); yo = sum(c[3] for c in clusters)
    m = len(clusters)
    if not (nx and no and yx and yo) or m < 2:
        return None
    rr = (yx / nx) / (yo / no)
    infl = [c[1] / yx - c[0] / nx - c[3] / yo + c[2] / no for c in clusters]
    se = math.sqrt(sum(v * v for v in infl) * m / (m - 1))
    lo = math.exp(math.log(rr) - Z95 * se)
    hi = math.exp(math.log(rr) + Z95 * se)
    p = normal_two_sided_p(math.log(rr) / se) if se > 0 else 0.0
    return {"rr": rr, "lo": lo, "hi": hi, "p": p, "nx": nx, "yx": yx, "no": no, "yo": yo,
            "games": m}


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f} %"


def _n(x: int) -> str:
    return f"{x:,}"


def build_patterns(rows: Sequence[tuple], analysed: int) -> dict:
    """The card from the filtered games' facts rows: (game id, played_at, player_color,
    facts_json), one per game with counting facts. *analysed* is how many analysed games the
    filters select, so the card can say how many it covers."""
    p4_clusters: list[tuple[int, int, int, int]] = []
    p6_clusters: list[tuple[int, int, int, int]] = []
    missed: list[dict] = []
    deciding: list[dict] = []
    for game_id, played_at, you, fj in rows:
        if you not in ("white", "black"):
            continue
        f = json.loads(fj)
        opp = "black" if you == "white" else "white"
        mine, theirs = f["p4"][you], f["p4"][opp]
        p4_clusters.append((mine["n"], mine["best"], theirs["n"], theirs["best"]))
        opponent = (f.get("players") or {}).get(opp)
        for ply, move, label in mine["missed"]:
            missed.append({"gameId": game_id, "ply": ply, "move": move, "label": label,
                           "date": played_at, "opponent": opponent})
        d = f["p6"]
        if d["decided"]:
            single = d["byPly"] is not None
            if d["side"] != you:
                p6_clusters.append((1, int(single), 0, 0))
                if single:
                    deciding.append({"gameId": game_id, "ply": d["byPly"], "move": d["byMove"],
                                     "label": None, "date": played_at, "opponent": opponent})
            else:
                p6_clusters.append((0, 0, 1, int(single)))
    newest = lambda it: (it["date"] or "", it["ply"])  # noqa: E731
    missed.sort(key=newest, reverse=True)
    deciding.sort(key=newest, reverse=True)

    p4 = clustered_rr(p4_clusters)
    p6 = clustered_rr(p6_clusters)
    tests = [t for t in (p4, p6) if t is not None]
    keep = iter(benjamini_hochberg([t["p"] for t in tests], FDR))
    passes = {id(t): next(keep) and t["lo"] > 1.0 for t in tests}

    sentences = []
    if p4 is not None:
        sentences.append({
            "key": "punish",
            "text": ("When your opponent makes a serious error, you punish it more often than "
                     f"they punish yours: you played the engine's move or mated after "
                     f"{_n(p4['yx'])} of "
                     f"their {_n(p4['nx'])} ({_pct(p4['yx'], p4['nx'])}); they did after "
                     f"{_n(p4['yo'])} of your {_n(p4['no'])} ({_pct(p4['yo'], p4['no'])})."),
            "shown": passes[id(p4)],
            "stats": p4,
            "link": {"label": "Your answers that weren't the engine's move, newest first",
                     "count": len(missed), "items": missed},
        })
    if p6 is not None:
        sentences.append({
            "key": "decided",
            "text": ("Your losses are settled by one move more often than your wins: "
                     f"{_n(p6['yx'])} of {_n(p6['nx'])} decided losses had a single deciding "
                     f"move ({_pct(p6['yx'], p6['nx'])}), against {_n(p6['yo'])} of "
                     f"{_n(p6['no'])} decided wins ({_pct(p6['yo'], p6['no'])})."),
            "shown": passes[id(p6)],
            "stats": p6,
            "link": {"label": "Your losses at the move that decided them, newest first",
                     "count": len(deciding), "items": deciding},
        })
    # What the screen may show: nothing of a sentence that does not pass — not its text,
    # not its link (a link under no sentence would be a claim without its evidence).
    shown = [s for s in sentences if s["shown"]]
    return {
        "covered": len(rows),
        "analysed": analysed,
        "sentences": shown,
        "tested": [{"key": s["key"], "shown": s["shown"],
                    **{k: s["stats"][k] for k in ("rr", "lo", "hi", "p", "nx", "yx", "no", "yo",
                                                  "games")}} for s in sentences],
    }


def patterns_for(db: "Database", flt: "InsightsFilter", analysed: int) -> dict:
    """The card under Insights' filters (`build_insights`)."""
    from .explain import RULE_VERSION
    return build_patterns(db.insights_pattern_facts(flt, FACTS_VERSION, rule_version=RULE_VERSION),
                          analysed)
