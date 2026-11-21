"""The redesigned Insights screen's figures (UI-BUILD-2 C; DESIGN.md "Insights", ruling 14).

Every figure is an existing rule applied to stored data; nothing here is new judgement:

- **Runs:** standard (depth-14) runs only (RUNS-DEPTH, `Database.standard_run_sql`), under the
  screen's filters (`Database._insights_where`: owned games, sources, colour, speeds with
  Daily, rated, since). Games against Stockfish only with that filter on.
- **Accuracy** is each game's stored accuracy for the user's side; a month's figure is the mean
  over its analysed games, as the old screen's summary did.
- **Win rate** is `insights._wdl_record` (wins over decided-or-drawn games with a known side).
- **Blunders per game:** the user's plies labelled blunder, over analysed games.
- **Move quality:** shares of the user's and the opponents' moves by label, **book moves left
  out** (the mockup's table has no book row and its shares sum to 100).
- **By phase:** each game's own division (`core/divider.py` via `review_extras`, as Review
  does), never move numbers. A phase's accuracy is `review_extras.accuracy_by_phase` per game
  (the stored accuracy's own formula restricted to the phase's moves), averaged over the games
  that reached the phase; move quality per phase as above.
- **Openings:** families (the name before ":"), per colour the user had, with the ECO range,
  games, won / drawn / lost shares, score ((W + D/2) / games) and mean accuracy; families with
  fewer than `INSIGHTS_MIN_OPENING_GAMES` games are left out.
- **How your games end:** won / drawn / lost shares; wins and losses split by termination.
- **When you play best:** mean accuracy per local weekday and four-hour block; a block needs
  `HEAT_MIN_GAMES` analysed games to be shown or named best.
- **Castling:** `insights._shape_castling` (kingside, queenside, didn't castle), shown as the
  share of games and the win rate.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .. import config as C
from .classification import PlyScore
from .insights import _outcome, _shape_castling, _wdl, _wdl_record
from .patterns import patterns_for
from .review_extras import PHASES, accuracy_by_phase, phase_of_plies

if TYPE_CHECKING:
    from .database import Database, InsightsFilter

CLASSES = ("brilliant", "great", "best", "excellent", "good",
           "inaccuracy", "mistake", "miss", "blunder")
HOURS = ((0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HEAT_MIN_GAMES = 30     # decided (UI-BUILD-2): fewer games make a block's mean too noisy to name "best"
MONTHS = 12


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone()


def month_keys(now: datetime, n: int = MONTHS) -> list[str]:
    """The n calendar months ending with now's, oldest first, as 'YYYY-MM'."""
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def family(name: str | None) -> str | None:
    return name.split(":", 1)[0].strip() if name else None


def eco_range(ecos: set[str]) -> str | None:
    ecos = {e for e in ecos if e}
    if not ecos:
        return None
    lo, hi = min(ecos), max(ecos)
    return lo if lo == hi else f"{lo}–{hi}"


def _shares(counts: dict[str, int]) -> dict:
    total = sum(counts.get(c, 0) for c in CLASSES)
    return {"moves": total,
            "counts": {c: counts.get(c, 0) for c in CLASSES},
            "pct": {c: (round(100.0 * counts.get(c, 0) / total, 1) if total else None) for c in CLASSES}}


def shape_games(games: list[tuple], blunders: dict[int, int], now: datetime) -> dict:
    """games: (id, played_at, color, result, termination, eco, name, accuracy, analysed)."""
    months = month_keys(now)
    per = {k: {"acc": [], "wdl": _wdl(), "games": 0, "blunders": 0, "analysed": 0} for k in months}
    days: dict[str, dict] = defaultdict(lambda: {"acc": [], "games": 0})
    heat = {(d, h): [] for d in range(7) for h in range(len(HOURS))}
    fams: dict[tuple[str, str], dict] = {}
    ends = {"win": defaultdict(int), "draw": defaultdict(int), "loss": defaultdict(int)}
    wdl_all = _wdl()
    for gid, played_at, color, result, term, eco, name, acc, analysed in games:
        t = _local(played_at)
        o = _outcome(color, result) if color in ("white", "black") else None
        if o:
            wdl_all[o] += 1
            ends[o][(term or "unknown")] += 1
        key = f"{t.year:04d}-{t.month:02d}" if t else None
        if key in per:
            p = per[key]
            p["games"] += 1
            if o:
                p["wdl"][o] += 1
            if analysed and acc is not None:
                p["acc"].append(acc)
                p["analysed"] += 1
                p["blunders"] += blunders.get(gid, 0)
        if t is not None:
            d = days[t.date().isoformat()]
            d["games"] += 1
            if analysed and acc is not None:
                d["acc"].append(acc)
                block = next(i for i, (a, b) in enumerate(HOURS) if a <= t.hour < b)
                heat[(t.weekday(), block)].append(acc)
        f = family(name)
        if f and color in ("white", "black") and analysed and acc is not None:
            r = fams.setdefault((color, f), {"name": f, "ecos": set(), "games": 0, "wdl": _wdl(), "acc": []})
            r["games"] += 1
            r["ecos"].add(eco or "")
            r["acc"].append(acc)
            if o:
                r["wdl"][o] += 1
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    monthly = []
    for k in months:
        p = per[k]
        rec = _wdl_record(p["wdl"])
        monthly.append({"month": k, "games": p["games"], "analysed": p["analysed"],
                        "accuracy": mean(p["acc"]),
                        "winRate": rec["winRate"] if rec["total"] else None,
                        "blundersPerGame": round(p["blunders"] / p["analysed"], 2) if p["analysed"] else None})
    daily = [{"day": k, "games": v["games"], "accuracy": mean(v["acc"])} for k, v in sorted(days.items())]
    cells = []
    best = None
    for (d, h), accs in heat.items():
        a = mean(accs)
        cell = {"day": d, "block": h, "games": len(accs),
                "accuracy": a if len(accs) >= HEAT_MIN_GAMES else None}
        cells.append(cell)
        if cell["accuracy"] is not None and (best is None or cell["accuracy"] > best["accuracy"]):
            best = cell
    openings = {"white": [], "black": []}
    for (color, _f), r in fams.items():
        if r["games"] < C.INSIGHTS_MIN_OPENING_GAMES:
            continue
        rec = _wdl_record(r["wdl"])
        n = rec["total"]
        openings[color].append({
            "name": r["name"], "eco": eco_range(r["ecos"]), "games": r["games"],
            "won": round(100.0 * r["wdl"]["win"] / n, 1) if n else None,
            "drawn": round(100.0 * r["wdl"]["draw"] / n, 1) if n else None,
            "lost": round(100.0 * r["wdl"]["loss"] / n, 1) if n else None,
            "score": round(100.0 * (r["wdl"]["win"] + r["wdl"]["draw"] / 2) / n, 1) if n else None,
            "accuracy": mean(r["acc"])})
    for c in openings:
        openings[c].sort(key=lambda o: (-o["games"], o["name"]))
    total = sum(wdl_all.values())

    def end_split(o: str) -> dict:
        items = ends[o]
        n = sum(items.values())
        def share(*keys):
            k = sum(items.get(x, 0) for x in keys)
            return round(100.0 * k / n, 1) if n else None
        known = ("checkmate", "resignation", "timeout")
        return {"games": n, "pct": round(100.0 * n / total, 1) if total else None,
                "mate": share("checkmate"), "resigned": share("resignation"),
                "time": share("timeout"),
                "other": share(*[k for k in items if k not in known])}
    return {
        "monthly": monthly, "daily": daily,
        "heat": {"cells": cells, "hours": [f"{a}–{b}" for a, b in HOURS], "days": list(WEEKDAYS),
                 "minGames": HEAT_MIN_GAMES,
                 "best": None if best is None else {**best, "dayName": WEEKDAYS[best["day"]],
                                                    "hours": f"{HOURS[best['block']][0]}–{HOURS[best['block']][1]}"}},
        "openings": openings,
        "ends": {"win": end_split("win"), "draw": end_split("draw"), "loss": end_split("loss")},
    }


def shape_plies(plies: list[tuple]) -> tuple[dict, dict, dict[int, int]]:
    """plies: (game_id, color, ply, classification, fen_before, sb_cp, sb_mate, sa_cp, sa_mate),
    ordered by game then ply. Returns (move quality, by phase, blunders per game id)."""
    mq = {"you": defaultdict(int), "opponents": defaultdict(int)}
    ph_cls = {p: {"you": defaultdict(int), "opponents": defaultdict(int)} for p in PHASES}
    ph_acc = {p: {"you": [], "opponents": []} for p in PHASES}
    blunders: dict[int, int] = defaultdict(int)

    def flush(gid, color, rows):
        if not rows or color not in ("white", "black"):
            return
        fens = [r[4] for r in rows]
        phases = phase_of_plies(fens)
        scores = [PlyScore("white" if " w " in r[4] else "black", r[5], r[6], r[7], r[8]) for r in rows]
        for r, ph, sc in zip(rows, phases, scores):
            who = "you" if sc.mover == color else "opponents"
            cls = r[3]
            if cls in CLASSES:
                mq[who][cls] += 1
                ph_cls[ph][who][cls] += 1
            if who == "you" and cls == "blunder":
                blunders[gid] += 1
        by = accuracy_by_phase(scores, phases)
        opp = "black" if color == "white" else "white"
        for ph in PHASES:
            if by[color][ph] is not None:
                ph_acc[ph]["you"].append(by[color][ph])
            if by[opp][ph] is not None:
                ph_acc[ph]["opponents"].append(by[opp][ph])

    cur, color, rows = None, None, []
    for r in plies:
        if r[0] != cur:
            flush(cur, color, rows)
            cur, color, rows = r[0], r[1], []
        rows.append(r)
    flush(cur, color, rows)
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    move_quality = {k: _shares(v) for k, v in mq.items()}
    by_phase = [{"phase": p,
                 "games": len(ph_acc[p]["you"]),
                 "accuracy": {"you": mean(ph_acc[p]["you"]), "opponents": mean(ph_acc[p]["opponents"])},
                 "quality": {k: _shares(v) for k, v in ph_cls[p].items()}}
                for p in PHASES]
    return move_quality, {"phases": by_phase}, dict(blunders)


def build_insights_v2(db: "Database", flt: "InsightsFilter", now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone()
    overview = db.insights_overview(flt)
    games = db.insights_game_rows(flt)
    move_quality, by_phase, blunders = shape_plies(db.insights_plies(flt))
    g = shape_games(games, blunders, now)
    analysed = [r for r in games if r[8] and r[7] is not None]
    wdl = _wdl()
    for r in games:
        o = _outcome(r[2], r[3]) if r[2] in ("white", "black") else None
        if o:
            wdl[o] += 1
    rec = _wdl_record(wdl)
    castling = _shape_castling(db.insights_castling_rows(flt))
    castled = sum(c["total"] for c in castling)
    return {
        "view": "v2",
        "overview": overview,
        "ready": overview["analyzed"] > 0,
        "summary": {
            "accuracy": round(sum(r[7] for r in analysed) / len(analysed), 1) if analysed else None,
            "winRate": rec["winRate"] if rec["total"] else None,
            "games": overview["total"], "analysed": overview["analyzed"],
            "blundersPerGame": round(sum(blunders.values()) / len(analysed), 2) if analysed else None,
        },
        **g,
        "moveQuality": move_quality,
        "byPhase": by_phase,
        "castling": [{"side": c["side"], "label": c["label"], "games": c["total"],
                      "share": round(100.0 * c["total"] / castled, 1) if castled else None,
                      "winRate": c["winRate"] if c["total"] else None} for c in castling],
        "patterns": patterns_for(db, flt, overview["analyzed"]),
    }
