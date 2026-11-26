"""The coach's moments, focus and report lines (COACH-1; COACH.md rulings 1, 5, 9; COACH-2 ruling CF1).

A **moment** is a ply of the user's where a theme was at stake, read from the stored analysis only (no engine),
except the parried threat, which needs one search of the position with the user's turn passed (below):

- **chance** (the user to move): the stored best line wins by force, proven as gate P proves (pv_reading): it
  mates, or holds a gain of at least PV_MATERIAL_THETA, every attacker move up to the hold a check, capture or
  promotion; the position was not already decided (max(p, 1 - p) < PV_DECIDED_MIN before the move); and the
  stored second line is at least PV_CONSISTENCY_MIN_CP worse (there was something to find). **Caught** when the
  user played the best move, or another move that costs under PV_CONSISTENCY_MIN_CP; **missed** when gate P fires
  on the ply (the eval charged at least PV_CONSISTENCY_MIN_CP and the played line falls PV_MATERIAL_THETA or a
  mate short of the best line).
- **threat** (against the user, the user to move): **missed** when gate P fires on the ply with the played line as
  its carrier and forcing to the hold: the user's move allowed the opponent's forcing win, and the line is ply
  N+1's stored line, so the claim is the stored next ply's (CLAUDE.md: claims about the opponent are validated
  against it). **Caught** (parried) when a search of the position with the user's turn passed (the null move:
  the same board, the opponent to move) finds the opponent a forcing win, proven the same way, and the played
  line (the user's move and ply N+1's stored line) holds no forcing win for the opponent.

Themes are themes.tag over the proven line trimmed to its hold (the mate, or the attacker's move the gain is held
from), the board it starts from, and the move before it; only themes.SHIPPED are used.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import chess

from zugzwang import config as C
from zugzwang.core import themes as T
from zugzwang.core.classification import win_prob
from zugzwang.core.pv_reading import (
    LineReading, _attacker_gain, _hold_index, carrier, consistent, decided, forcing_to_hold,
    read_line, read_ply)
from zugzwang.core.stats import benjamini_hochberg, normal_two_sided_p

#: 2 (FIX-B8, ruling D9a, 2026-11-25): a threat parried only by moving the attacked piece away is no longer a catch.
COACH_VERSION = 2

#: The themes the coach counts: tactical motifs, of those that shipped (themes.SHIPPED).
#: Mate lengths, the descriptive tags (castling, en passant, quiet or defensive moves) and the
#: themes a forcing line cannot show are left out.
COACH_THEMES: tuple[str, ...] = (
    "fork", "pin", "skewer", "discoveredAttack", "doubleCheck", "hangingPiece", "trappedPiece",
    "sacrifice", "xRayAttack", "deflection", "attraction", "capturingDefender", "clearance",
    "backRankMate", "smotheredMate", "mateIn1", "mateIn2", "promotion", "attackingF2F7",
)

#: The name shown for a theme; a knight's fork has its own name (the mockups' "Knight forks").
THEME_NAMES = {
    "fork": "Fork", "knightFork": "Knight fork", "pin": "Pin", "skewer": "Skewer",
    "discoveredAttack": "Discovered attack", "doubleCheck": "Double check", "hangingPiece": "Loose piece",
    "trappedPiece": "Trapped piece", "sacrifice": "Sacrifice", "xRayAttack": "X-ray",
    "deflection": "Deflection", "attraction": "Attraction", "capturingDefender": "Removing the defender",
    "clearance": "Clearance", "backRankMate": "Back-rank mate", "smotheredMate": "Smothered mate",
    "mateIn1": "Mate in one", "mateIn2": "Mate in two", "promotion": "Promotion",
    "attackingF2F7": "Attack on f2/f7",
}
#: The threat side's own names (FIX-B8, ruling D9b, 2026-11-25): "Loose piece" against the user reads "Hanging piece";
#: the chance side keeps "Loose piece". theme_name / theme_phrase / theme_plural pick by side.
THREAT_NAMES = {"hangingPiece": "Hanging piece"}
THREAT_PHRASES = {"hangingPiece": "a hanging piece"}
THREAT_PLURALS = {"hangingPiece": "hanging pieces"}

#: The phrase a sentence uses ("was a knight fork", "allowed a back-rank mate").
THEME_PHRASES = {
    "fork": "a fork", "knightFork": "a knight fork", "pin": "a pin", "skewer": "a skewer",
    "discoveredAttack": "a discovered attack", "doubleCheck": "a double check",
    "hangingPiece": "a loose piece", "trappedPiece": "a trapped piece", "sacrifice": "a sacrifice",
    "xRayAttack": "an x-ray", "deflection": "a deflection", "attraction": "an attraction",
    "capturingDefender": "removing the defender", "clearance": "a clearance",
    "backRankMate": "a back-rank mate", "smotheredMate": "a smothered mate", "mateIn1": "mate in one",
    "mateIn2": "mate in two", "promotion": "a promotion", "attackingF2F7": "an attack on f2/f7",
}

#: How many earlier moments a history line counts at most (COACH.md ruling 5).
HISTORY_MAX = 20


@dataclass
class Moment:
    ply: int                    # move_analyses.ply (0-based: ply 0 is White's first move)
    kind: str                   # "chance" | "threat"
    outcome: str                # "caught" | "missed"
    themes: list[str]           # coach themes, primary first (a knight fork as "knightFork")
    fen: str                    # the board the proven line starts from
    line: list[str]             # the proven line, trimmed to its hold (UCI)
    played: str                 # the user's move (UCI)
    key_move: str               # the line's first move: the best move (chance) or the opponent's (threat)
    move_type: str              # the key move's type: "check" | "capture" | "pawn" | "other"
    mate: bool                  # the line mates
    gain: float                 # material the line wins, in pawns (0 for a mate)
    via: str = ""               # chance caught by another move: "other"; threat caught: "parried"

    def to_dict(self) -> dict:
        return asdict(self)


def move_type(fen: str, uci: str) -> str:
    b = chess.Board(fen)
    m = chess.Move.from_uci(uci)
    if b.gives_check(m):
        return "check"
    if b.is_capture(m):
        return "capture"
    if b.piece_type_at(m.from_square) == chess.PAWN:
        return "pawn"
    return "other"


def _cp(cp: int | None, mate: int | None) -> int:
    if mate is not None:
        return 10_000 if mate > 0 else -10_000
    return cp or 0


def proven(lr: LineReading) -> bool:
    """The line's attacker wins by force: mates or holds at least PV_MATERIAL_THETA, forcing to the hold."""
    if lr.stopped_at == 0 or not lr.steps:
        return False
    if lr.mate and lr.mated is not None and lr.mated != lr.attacker and lr.mate_on is not None:
        return forcing_to_hold(lr)
    return (lr.gain_held_from is not None and _attacker_gain(lr) >= C.PV_MATERIAL_THETA
            and forcing_to_hold(lr))


def trimmed(lr: LineReading) -> list[str]:
    """The attacker's part of a proven line: from its first move to the hold (or the mate)."""
    h = _hold_index(lr)
    return [s.uci for s in lr.steps[lr.attack_from:h + 1]]


def line_themes(fen: str, line: Sequence[str], setup_fen: str | None, setup_uci: str | None) -> list[str]:
    tl = T.ThemeLine.from_ucis(fen, line, setup_fen, setup_uci)
    got = [t for t in T.tag(tl) if t in COACH_THEMES]
    if "fork" in got and T.fork(tl, **T.VARIANTS["fork"][1][T.CHOSEN.get("fork", 0)]) == chess.KNIGHT:
        got.insert(got.index("fork"), "knightFork")      # a knight fork is a fork too: it counts under both
    return got


def _already_decided(m) -> bool:
    if m.score_before_cp is None and m.score_before_mate is None:
        return True
    p = win_prob(m.score_before_cp, m.score_before_mate)
    return max(p, 1 - p) >= C.PV_DECIDED_MIN


def null_fen(fen: str) -> str | None:
    """The same board with the other side to move, or None when the side to move is in check."""
    b = chess.Board(fen)
    if b.is_check():
        return None
    b.turn = not b.turn
    b.ep_square = None
    if not b.is_valid():
        return None
    return b.fen()


def _pv(m) -> list[str]:
    return [u for u in (m.pv_uci or "").split() if u]


def _refutation(plies: Sequence, final_lines: Sequence[dict], i: int) -> list[str] | None:
    lines = plies[i + 1].lines if i + 1 < len(plies) else list(final_lines or [])
    if not lines:
        return None
    u = lines[0].get("uci")
    return list(u) if isinstance(u, list) else (u.split() if u else None)


def chance_at(plies: Sequence, final_lines: Sequence[dict], i: int) -> Moment | None:
    m = plies[i]
    if m.is_book or not m.best_uci or _already_decided(m):
        return None
    best = _pv(m)
    if not best or best[0] != m.best_uci:
        return None
    mover = chess.Board(m.fen_before).turn
    lr = read_line(m.fen_before, best, mover, 0)
    if not proven(lr):
        return None
    lines = m.lines or []
    if len(lines) >= 2:
        gap = _cp(lines[0].get("cp"), lines[0].get("mate")) - _cp(lines[1].get("cp"), lines[1].get("mate"))
        if gap < C.PV_CONSISTENCY_MIN_CP:
            return None
    setup = (plies[i - 1].fen_before, plies[i - 1].played_uci) if i > 0 else (None, None)
    line = trimmed(lr)
    base = dict(ply=m.ply, kind="chance", fen=m.fen_before, line=line, played=m.played_uci,
                key_move=best[0], move_type=move_type(m.fen_before, best[0]), mate=lr.mate,
                gain=0.0 if lr.mate else round(_attacker_gain(lr), 1),
                themes=line_themes(m.fen_before, line, *setup))
    loss = _cp(m.score_before_cp, m.score_before_mate) - _cp(m.score_after_cp, m.score_after_mate)
    if m.played_uci == best[0]:
        return Moment(outcome="caught", **base)
    if loss < C.PV_CONSISTENCY_MIN_CP:
        return Moment(outcome="caught", via="other", **base)
    ref = _refutation(plies, final_lines, i)
    if ref is None:
        return None
    rd = read_ply(m.fen_before, m.played_uci, best, ref)
    if rd is None or not rd.fires:
        return None
    if not consistent(rd, m.score_before_cp, m.score_before_mate, m.score_after_cp, m.score_after_mate):
        return None
    return Moment(outcome="missed", **base)


def allowed_threat_at(plies: Sequence, final_lines: Sequence[dict], i: int) -> Moment | None:
    """Gate P with the played line as carrier: the user's move allowed the opponent's forcing win, read from
    ply N+1's stored line (the refutation)."""
    m = plies[i]
    if m.is_book or not m.best_uci or _already_decided(m):
        return None
    best = _pv(m)
    ref = _refutation(plies, final_lines, i)
    if not best or not ref or m.played_uci == best[0]:
        return None
    after = chess.Board(m.fen_before)
    after.push_uci(m.played_uci)
    if i + 1 < len(plies) and plies[i + 1].fen_before.split()[:4] != after.fen().split()[:4]:
        return None                                  # the stored next ply is not this position
    rd = read_ply(m.fen_before, m.played_uci, best, ref)
    if rd is None or not rd.fires:
        return None
    sc = (m.score_before_cp, m.score_before_mate, m.score_after_cp, m.score_after_mate)
    if not consistent(rd, *sc) or decided(*sc):
        return None
    if carrier(rd) is not rd.played or not proven(rd.played):
        return None
    line = trimmed(rd.played)
    return Moment(ply=m.ply, kind="threat", outcome="missed", fen=after.fen(), line=line,
                  played=m.played_uci, key_move=line[0], move_type=move_type(after.fen(), line[0]),
                  mate=rd.played.mate, gain=0.0 if rd.played.mate else round(_attacker_gain(rd.played), 1),
                  themes=line_themes(after.fen(), line, m.fen_before, m.played_uci))


def parried_threat_at(plies: Sequence, final_lines: Sequence[dict], i: int,
                      null_line: Sequence[str] | None) -> Moment | None:
    """The opponent threatened a forcing win (found by the null-move search, null_line), and the user's move
    left none: the played line, ply N+1's stored line after the user's move, holds no forcing win for the
    opponent."""
    m = plies[i]
    if not null_line or m.is_book or _already_decided(m):
        return None
    nf = null_fen(m.fen_before)
    if nf is None:
        return None
    opp = chess.Board(nf).turn
    nl = read_line(nf, list(null_line), opp, 0)
    if not proven(nl):
        return None
    ref = _refutation(plies, final_lines, i)
    if ref is None:
        return None
    mover = not opp
    played = read_line(m.fen_before, [m.played_uci, *ref], mover, 1)
    if played.stopped_at == 0 or proven(played):
        return None
    if i + 1 < len(plies):
        after = chess.Board(m.fen_before)
        after.push_uci(m.played_uci)
        if plies[i + 1].fen_before.split()[:4] != after.fen().split()[:4]:
            return None
    line = trimmed(nl)
    if moved_away(nf, line, m.played_uci):
        return None                                  # ruling D9a: moving the attacked piece away is not a catch
    setup = (plies[i - 1].fen_before, plies[i - 1].played_uci) if i > 0 else (None, None)
    return Moment(ply=m.ply, kind="threat", outcome="caught", via="parried", fen=nf, line=line,
                  played=m.played_uci, key_move=line[0], move_type=move_type(nf, line[0]), mate=nl.mate,
                  gain=0.0 if nl.mate else round(_attacker_gain(nl), 1),
                  themes=line_themes(nf, line, *setup))


def moved_away(threat_fen: str, line: Sequence[str], played_uci: str) -> bool:
    """FIX-B8, ruling D9a (2026-11-25): the threat is one move, a capture, and the user's move took the attacked
    piece off that square. Such a parry is not counted as caught (ARCH-AUDIT-1 §8 (e): 73.3 % of the caught
    "Loose piece" threats were this). A parry by any other move (defending the piece, blocking, a counter-threat,
    moving another piece) still counts, and so does moving away from a threat longer than one move."""
    if len(line) != 1:
        return False
    key = chess.Move.from_uci(line[0])
    if not chess.Board(threat_fen).is_capture(key):
        return False
    return chess.Move.from_uci(played_uci).from_square == key.to_square


def user_plies(plies: Sequence, player_color: str) -> Iterable[int]:
    want = chess.WHITE if player_color == "white" else chess.BLACK
    for i, m in enumerate(plies):
        if chess.Board(m.fen_before).turn == want:
            yield i


def needs_null_search(plies: Sequence, i: int) -> str | None:
    """The FEN to search for a parried threat at ply i, or None when there is nothing to search."""
    m = plies[i]
    if m.is_book or _already_decided(m):
        return None
    return null_fen(m.fen_before)


def _continues(plies: Sequence, follow: tuple[int, list[str]], i: int) -> bool:
    """Ply i's best move is the next move of the line a caught chance began at ply s, every move since as the
    line had it (the fork's capture after the fork is the fork, not a second chance)."""
    s, line = follow
    k = i - s
    if k <= 0 or k >= len(line):
        return False
    if any(plies[s + j].played_uci != line[j] for j in range(k)):
        return False
    return plies[i].best_uci == line[k]


def moments_for_run(plies: Sequence, final_lines: Sequence[dict], player_color: str,
                    null_lines: dict[int, list[str]] | None = None) -> list[Moment]:
    """Every moment of the user's in one run. null_lines maps a ply index to the null-move search's line;
    without it no threat is found caught."""
    out: list[Moment] = []
    if player_color not in ("white", "black"):
        return out
    follow: tuple[int, list[str]] | None = None     # the last caught chance's line: its later moves are the same
    for i in user_plies(plies, player_color):        # combination played on, not new chances
        c = chance_at(plies, final_lines, i)
        if c is not None and follow is not None and _continues(plies, follow, i):
            c = None
        if c is not None:
            out.append(c)
            if c.outcome == "caught" and c.via != "other":
                follow = (i, c.line)
        t = allowed_threat_at(plies, final_lines, i)
        if t is None and null_lines is not None:
            t = parried_threat_at(plies, final_lines, i, null_lines.get(i))
        if t is not None:
            out.append(t)
    return out


# ── ruling 9's bar (COACH-1) ──
# No longer what Focus shows: ruling CF1 (cost_focus, below) replaced it on 2026-11-24 (COACH-1 decided items 6,
# 7 and 8). Kept so COACH-1's measurement scripts (review/scratch/coach1_*.py) re-run exactly.

def half_of(key: str) -> int:
    """The seeded half a game belongs to: 0 = the half the bar is found on, 1 = the half it is judged on."""
    return hashlib.sha1(("coach-focus:" + key).encode()).digest()[0] & 1


Z95 = 1.959963984540054
FDR = 0.05                # the Insights bar's (patterns.FDR)
STRATUM_MIN = 5          # a stratum counts toward "holds within strata" with at least this many on each side
#: A theme is tested only with at least this many of its moments in each half: below it the clustered
#: interval is not to be trusted (COACH-1 B: 9 moments passed before it; decided, for the owner to confirm).
FOCUS_MIN = 20


def _rr(clusters: Sequence[tuple[int, int, int, int]]) -> dict | None:
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
    return {"rr": rr, "lo": lo, "hi": hi, "p": p, "nx": nx, "yx": yx, "no": no, "yo": yo, "games": m}


def group_key(kind: str, theme: str) -> str:
    return f"{kind}:{theme}"


def _test(games: Sequence[tuple[str, list[Moment]]], kind: str, theme: str) -> dict | None:
    """Theme vs the user's other tactical themes of the same kind: per-game clusters (theme moments, theme
    misses, other moments, other misses); with the per-stratum rate ratios by the key move's type."""
    clusters = []
    strata: dict[str, list[int]] = {}
    for _, ms in games:
        nx = yx = no = yo = 0
        for mo in ms:
            if mo.kind != kind or not mo.themes:
                continue
            miss = mo.outcome == "missed"
            s = strata.setdefault(mo.move_type, [0, 0, 0, 0])
            if theme in mo.themes:
                nx += 1; yx += miss; s[0] += 1; s[1] += miss
            else:
                no += 1; yo += miss; s[2] += 1; s[3] += miss
        if nx or no:
            clusters.append((nx, yx, no, yo))
    res = _rr(clusters)
    if res is None:
        return None
    rows = {}
    holds = True
    for k, (nx, yx, no, yo) in sorted(strata.items()):
        rr = (yx / nx) / (yo / no) if nx and no and yo else None
        rows[k] = {"nx": nx, "yx": yx, "no": no, "yo": yo, "rr": rr}
        if nx >= STRATUM_MIN and no >= STRATUM_MIN and (rr is None or rr <= 1.0) and yx * no <= yo * nx:
            holds = False
    res["strata"] = rows
    res["strata_hold"] = holds
    return res


def focus(games: Sequence[tuple[str, list[Moment]]], *, limit: int = 3) -> dict:
    """Ruling 9's bar over the user's games, each (platform key, moments), oldest first. A (kind, theme) is a
    focus when, on the seeded finding half, its miss rate is above the user's own on the other tactical themes
    of that kind with a game-clustered 95 % interval above 1 after Benjamini-Hochberg at FDR, holding within
    the key move's type strata, with at least FOCUS_MIN of its moments in each half; and on the judging half the
    ratio is above 1 as well."""
    halves = [[g for g in games if half_of(g[0]) == h] for h in (0, 1)]
    cands = []
    for kind in ("chance", "threat"):
        seen = {t for _, ms in games for mo in ms if mo.kind == kind for t in mo.themes}
        for theme in sorted(seen):
            a = _test(halves[0], kind, theme)
            b = _test(halves[1], kind, theme)
            whole = _test(games, kind, theme)
            if a is not None:
                cands.append({"kind": kind, "theme": theme, "find": a, "judge": b, "all": whole})
    keep = benjamini_hochberg([c["find"]["p"] for c in cands], FDR) if cands else []
    passed = []
    for c, k in zip(cands, keep):
        c["passes"] = bool(k and c["find"]["lo"] > 1.0 and c["find"]["strata_hold"]
                           and c["find"]["nx"] >= FOCUS_MIN
                           and c["judge"] is not None and c["judge"]["nx"] >= FOCUS_MIN
                           and c["judge"]["rr"] > 1.0)
        if c["passes"]:
            passed.append(c)
    passed.sort(key=lambda c: (-(c["all"] or c["find"])["rr"], c["theme"]))
    return {"tested": cands, "focus": passed[:limit], "games": len(games)}


# ── Focus by cost (COACH-2, ruling CF1, 2026-11-24): what costs the user most ──
#
# Replaces ruling 9's bar as what Focus shows (COACH-1 decided items 6, 7 and 8). Each moment counts under one
# theme, its primary (PRIORITY: the most specific first), so a moment's cost is never counted twice and the
# report's history lines, Practice's filter and the card's "Missed X of Y" all count the same moments.

#: The window Focus reads: the user's games of the last 12 months (by the game's date).
FOCUS_WINDOW_DAYS = 365
#: The bootstrap that decides whether an item's place in the top three holds (decided for the owner to confirm):
#: games resampled with replacement BOOT_N times (a seed drawn from the games' keys, so the same games give the
#: same Focus); an item is shown when it is in the top three in at least BOOT_SHARE of the resamples.
BOOT_N = 400
BOOT_SHARE = 0.80


def moment_theme(m: Moment) -> str | None:
    """The one theme a moment counts under (its primary, by PRIORITY)."""
    return primary(m.themes)


def moment_key(m: Moment) -> str | None:
    t = moment_theme(m)
    return f"{m.kind}:{t}" if t else None


def window_start(now: datetime, days: int = FOCUS_WINDOW_DAYS) -> str:
    """The ISO date-time the window starts at (played_at strings compare as text)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - timedelta(days=days)).astimezone(timezone.utc).isoformat()


def _in_window(played_at: str, start: str) -> bool:
    if not played_at:
        return False
    try:
        d = datetime.fromisoformat(played_at.replace("Z", "+00:00"))
    except ValueError:
        return played_at >= start
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat() >= start


def cost_focus(games: Sequence["GameMoments"], *, now: datetime, limit: int = 3, n_boot: int = BOOT_N,
               share: float = BOOT_SHARE, days: int = FOCUS_WINDOW_DAYS) -> dict:
    """Ruling CF1 over the user's games: per (kind, theme), the sum of the win probability lost on its missed
    moments in the window (GameMoments.losses: the ply's stored loss, mover's view, classification.wpl). The
    top *limit* by that sum, each kept only when it is in the top *limit* in at least *share* of *n_boot*
    game-clustered bootstrap resamples. Returns every group's figures ("groups", by cost) and the shown items
    ("focus")."""
    start = window_start(now, days)
    win = [g for g in games if _in_window(g.played_at, start)]
    per_game: list[dict[str, float]] = []
    groups: dict[str, dict] = {}
    for g in win:
        costs: dict[str, float] = {}
        for mo in g.moments:
            k = moment_key(mo)
            if k is None:
                continue
            gr = groups.setdefault(k, {"key": k, "kind": mo.kind, "theme": moment_theme(mo), "cost": 0.0,
                                       "missed": 0, "total": 0, "games": set()})
            gr["total"] += 1
            if mo.outcome == "missed":
                loss = float(g.losses.get(mo.ply, 0.0))
                gr["missed"] += 1
                gr["cost"] += loss
                gr["games"].add(g.key)
                costs[k] = costs.get(k, 0.0) + loss
        per_game.append(costs)
    ranked = sorted((gr for gr in groups.values() if gr["cost"] > 0),
                    key=lambda gr: (-gr["cost"], gr["key"]))
    top = [gr["key"] for gr in ranked[:limit]]
    hold = {k: 0 for k in top}
    n = len(per_game)
    if n and top:
        seed = int.from_bytes(hashlib.sha1("|".join(sorted(g.key for g in win)).encode()).digest()[:8], "big")
        rng = random.Random(seed)
        for _ in range(n_boot):
            sums: dict[str, float] = {}
            for i in rng.choices(range(n), k=n):
                for k, v in per_game[i].items():
                    sums[k] = sums.get(k, 0.0) + v
            best = sorted(sums.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
            for k, _ in best:
                if k in hold:
                    hold[k] += 1
    out_groups = []
    for gr in ranked:
        held = hold.get(gr["key"])
        out_groups.append({**{k: v for k, v in gr.items() if k != "games"}, "cost": round(gr["cost"], 4),
                           "missedGames": len(gr["games"]),
                           "held": None if held is None else held / n_boot})
    shown = [g for g in out_groups if g["held"] is not None and g["held"] >= share]
    return {"groups": out_groups, "focus": shown, "games": len(win), "start": start,
            "boot": {"n": n_boot, "share": share}}


# ── what the screens show (COACH-1 C): fixed templates over the moments' checked facts ──

#: The order a moment's themes are named in when none is a focus: the most specific first.
PRIORITY = ("smotheredMate", "backRankMate", "mateIn1", "mateIn2", "knightFork", "fork", "discoveredAttack",
            "doubleCheck", "skewer", "pin", "hangingPiece", "trappedPiece", "deflection", "attraction",
            "capturingDefender", "clearance", "xRayAttack", "sacrifice", "promotion", "attackingF2F7")
#: Plural names for a focus item's title ("Knight forks against you", "Your own discovered attacks").
THEME_PLURALS = {
    "fork": "forks", "knightFork": "knight forks", "pin": "pins", "skewer": "skewers",
    "discoveredAttack": "discovered attacks", "doubleCheck": "double checks", "hangingPiece": "loose pieces",
    "trappedPiece": "trapped pieces", "sacrifice": "sacrifices", "xRayAttack": "x-rays",
    "deflection": "deflections", "attraction": "attractions", "capturingDefender": "removing the defender",
    "clearance": "clearances", "backRankMate": "back-rank mates", "smotheredMate": "smothered mates",
    "mateIn1": "mates in one", "mateIn2": "mates in two", "promotion": "promotions",
    "attackingF2F7": "attacks on f2/f7",
}
FOUND_PHRASES = {k: ("the " + v.split(" ", 1)[1] if v.startswith(("a ", "an ")) else v)
                 for k, v in THEME_PHRASES.items()}
FOUND_PHRASES["capturingDefender"] = "the capture of the defender"


def move_label(fen: str, uci: str, numbered: bool = True) -> str:
    """"21... Nd5" / "17. Qe2" (numbered), or the bare SAN."""
    b = chess.Board(fen)
    san = b.san(chess.Move.from_uci(uci))
    if not numbered:
        return san
    return f"{b.fullmove_number}{'.' if b.turn == chess.WHITE else '...'} {san}"


def theme_name(kind: str, theme: str) -> str:
    """The name a screen shows for a theme on one side (ruling D9b): "Hanging piece" against the user."""
    return (THREAT_NAMES.get(theme) if kind == "threat" else None) or THEME_NAMES.get(theme, theme)


def theme_phrase(kind: str, theme: str) -> str:
    return (THREAT_PHRASES.get(theme) if kind == "threat" else None) or THEME_PHRASES[theme]


def theme_plural(kind: str, theme: str) -> str:
    return (THREAT_PLURALS.get(theme) if kind == "threat" else None) or THEME_PLURALS[theme]


def primary(themes: Sequence[str], focus: Iterable[str] = ()) -> str | None:
    f = set(focus)
    for t in themes:
        if t in f:
            return t
    for t in PRIORITY:
        if t in themes:
            return t
    return themes[0] if themes else None


def sentence(m: Moment, theme: str, fen_before: str) -> str:
    """The one sentence a moment shows, from a fixed template; every part is a checked fact: the move
    played, the proven line's first move, the theme's rule, and for a threat the stored next ply (missed)
    or the null-move search with the stored next ply holding no forcing win for the opponent (caught). A
    line longer than its first move is said to start with it (the theme may come later in it)."""
    played = move_label(fen_before, m.played)
    multi = len(m.line) > 1
    if m.kind == "chance":
        first = move_label(fen_before, m.key_move)
        if theme == "hangingPiece":
            if m.outcome == "caught" and m.via != "other":
                return f"You took the loose piece: {first}."
            if m.outcome == "caught":
                return f"{played} was nearly as good as taking the loose piece with {first}."
            return f"{first} took a loose piece; you played {played}."
        phrase = THEME_PHRASES[theme]
        if m.outcome == "caught" and m.via != "other":
            return f"You found {FOUND_PHRASES[theme]} that starts with {first}." if multi \
                else f"You found {FOUND_PHRASES[theme]}: {first}."
        if m.outcome == "caught":
            return f"{played} was nearly as good as {phrase} starting with {first}." if multi \
                else f"{played} was nearly as good as {first}, {phrase}."
        return f"{first} started {phrase}; you played {played}." if multi \
            else f"{first} was {phrase}; you played {played}."
    if m.outcome == "missed":
        theirs = move_label(m.fen, m.key_move)
        if theme == "hangingPiece":
            return f"{played} left a piece hanging: {theirs} takes it."
        phrase = THEME_PHRASES[theme]
        return f"{played} allowed {phrase}, starting with {theirs}." if multi else f"{played} allowed {phrase}: {theirs}."
    theirs = move_label(m.fen, m.key_move, numbered=False)
    if theme == "hangingPiece":
        return f"{played} dealt with a hanging piece ({theirs} would have taken it)."
    return f"{played} dealt with the threat of {THEME_PHRASES[theme]} ({theirs})."


def history_line(earlier: Sequence[str]) -> str | None:
    """"You had missed this 6 of the last 9 times." over the outcomes of the same (kind, theme) before this
    game, newest last, at most HISTORY_MAX of them."""
    last = list(earlier)[-HISTORY_MAX:]
    if not last:
        return None
    missed = sum(1 for o in last if o == "missed")
    if len(last) == 1:
        return ("You missed this the last time it came up." if missed
                else "You caught this the last time it came up.")
    return f"You had missed this {missed} of the last {len(last)} times."


def item_title(kind: str, theme: str) -> str:
    plural = theme_plural(kind, theme)
    if kind == "threat":
        return f"{plural[0].upper()}{plural[1:]} against you"
    return f"Your own {plural}"


def moments_from_json(text: str) -> list[Moment]:
    return [Moment(**d) for d in json.loads(text)] if text else []


@dataclass
class GameMoments:
    game_id: int
    key: str                  # platform game id, or local-<id>
    played_at: str
    colour: str
    opponent: str | None
    fens: dict[int, str]      # ply -> fen before (for labels)
    moments: list[Moment]
    losses: dict[int, float] = field(default_factory=dict)   # ply -> the move's win-probability loss (CF1)
    run_id: int = 0           # the standard run the moments were read from


def build_overview(games: Sequence[GameMoments], *, pending: int = 0, behind_max: int = 200,
                   now: datetime | None = None) -> dict:
    """The Coach page: Focus (ruling CF1: at most three items, what cost the user most in the last 12 months,
    each only if its place holds in the bootstrap) and "Behind your focus" (each focus item's moments in the
    window, newest first, linking to the game's report)."""
    now = now or datetime.now(timezone.utc)
    games = sorted(games, key=lambda g: (g.played_at or "", g.game_id))
    fc = cost_focus(games, now=now)
    start = fc["start"]
    items = []
    for c in fc["focus"]:
        kind, theme, key = c["kind"], c["theme"], c["key"]
        outcomes = []
        rows = []
        for g in games:
            if not _in_window(g.played_at, start):
                continue
            for mo in g.moments:
                if moment_key(mo) == key:
                    outcomes.append(mo.outcome)
                    rows.append({"gameId": g.game_id, "ply": mo.ply, "date": g.played_at,
                                 "opponent": g.opponent, "move": move_label(g.fens[mo.ply], mo.played),
                                 "theme": theme_name(kind, theme), "kind": kind, "outcome": mo.outcome,
                                 "key": key})
        recent = outcomes[-5:]
        items.append({
            "key": key, "kind": kind, "theme": theme, "title": item_title(kind, theme),
            "name": theme_name(kind, theme), "missed": c["missed"], "total": c["total"],
            "cost": c["cost"], "held": c["held"],
            "recentCaught": recent.count("caught"), "recentTotal": len(recent),
            "rows": list(reversed(rows))[:behind_max], "rowCount": len(rows),
        })
    behind = sorted((r for it in items for r in it["rows"]), key=lambda r: (r["date"] or "", r["ply"]),
                    reverse=True)[:behind_max]
    return {"games": len(games), "windowGames": fc["games"], "windowStart": start,
            "windowDays": FOCUS_WINDOW_DAYS, "pending": pending, "focus": items, "behind": behind,
            "moments": sum(len(g.moments) for g in games),
            "groups": [{k: g[k] for k in ("key", "cost", "missed", "total", "held")} for g in fc["groups"][:12]],
            "boot": fc["boot"]}


def report_patterns(game: GameMoments, earlier: dict[str, list[str]], focus_keys: Iterable[str]) -> dict:
    """"Your patterns in this game" and each moment's theme, for the game report. *earlier* maps a
    "kind:theme" key to the outcomes of that group in the user's games before this one (oldest first);
    a history line is shown only for a focus item (ruling 5)."""
    fk = set(focus_keys)
    out = []
    for mo in sorted(game.moments, key=lambda m: m.ply):
        theme = moment_theme(mo)          # the theme it counts under (CF1), focus or not
        if theme is None:
            continue
        key = f"{mo.kind}:{theme}"
        is_focus = key in fk
        out.append({
            "ply": mo.ply, "kind": mo.kind, "outcome": mo.outcome, "theme": theme,
            "name": theme_name(mo.kind, theme), "focus": is_focus,
            "sentence": sentence(mo, theme, game.fens[mo.ply]),
            "history": history_line(earlier.get(key, [])) if is_focus else None,
            "move": move_label(game.fens[mo.ply], mo.played),
        })
    return {"items": out, "version": COACH_VERSION}
