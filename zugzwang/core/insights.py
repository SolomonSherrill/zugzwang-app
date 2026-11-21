"""
Insights shaping — Qt-free. Takes raw aggregate rows from the Database and
produces a structured dict for the frontend to render. No DB or network here;
pure transformation so it is trivially testable and reusable by both frontends.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from .. import config as C
from .classification import move_accuracy_pct, wpl
from .divider import divide, phase_at
from .stats import benjamini_hochberg, normal_two_sided_p
from .tactics import analyze_castling

from .database import InsightsFilter
from zugzwang.core.patterns import patterns_for

if TYPE_CHECKING:
    from .database import Database

# Display order for move-classification breakdown (best → worst).
_CLASS_ORDER = [
    "brilliant",
    "great",
    "best",
    "excellent",
    "good",
    "book",
    "inaccuracy",
    "mistake",
    "miss",
    "blunder",
]


def _shape_openings(rows: list[tuple]) -> list[dict]:
    """Shape one row per opening line, most-played first. Each row carries the
    player's accuracy and W/D/L record in that opening.

    The order is frequency, not accuracy: sorting by accuracy would rank the
    openings by how well they went, and this screen is not entitled to that
    claim — the differences between openings here sit inside what a few
    thousand games can resolve. See ARCHITECTURE.md.

    No game-count gate is applied here: the frontend groups these lines into
    families and gates at the family level (INSIGHTS_MIN_OPENING_GAMES across
    all variants), so a sub-threshold variant can still surface inside a
    qualifying family."""
    out = [
        {
            "eco": eco or "",
            "name": name,
            "games": games,
            "accuracy": round(acc, 1),
            "win": win,
            "draw": draw,
            "loss": loss,
            "winRate": round(100.0 * win / games, 1) if games else 0.0,
        }
        for (eco, name, games, acc, win, draw, loss) in rows
        if acc is not None
    ]
    out.sort(key=lambda o: (-o["games"], o["name"]))
    return out


def _shape_trend(rows: list[tuple]) -> list[dict]:
    """One point per analysed game, carrying enough for a rich tooltip."""
    return [
        {
            "gameId": game_id,
            "date": played_at,
            "accuracy": round(acc, 1),
            "opening": opening_name or "Unknown opening",
            "result": result,
            "color": color,
            "outcome": _outcome(color, result) or "unknown",
        }
        for (game_id, played_at, acc, opening_name, result, color) in rows
    ]


# Move numbers past this are folded into the final bucket (long-game tail).
_MOVE_NUMBER_CAP = 40


def _shape_move_accuracy(rows: list[tuple]) -> dict:
    """Average per-move accuracy by full-move number, split by colour played.
    Returns {'all': [...], 'white': [...], 'black': [...]} where each list holds
    {move, accuracy, samples, cumulative}.

    The last bucket is not a move number: it is every move from the cap onward,
    so it holds an order of magnitude more moves than its neighbours and averages
    a different kind of position. `cumulative` marks it so the chart can label it
    `40+` rather than let it be read as the next point on the line."""
    # bucket -> {"all": [accs], "white": [accs], "black": [accs]}
    buckets: dict[int, dict[str, list[float]]] = {}
    for ply, color, sb_cp, sb_mate, sa_cp, sa_mate in rows:
        move_no = min(ply // 2 + 1, _MOVE_NUMBER_CAP)
        acc = move_accuracy_pct(wpl(sb_cp, sb_mate, sa_cp, sa_mate))
        slot = buckets.setdefault(move_no, {"all": [], "white": [], "black": []})
        slot["all"].append(acc)
        if color in ("white", "black"):
            slot[color].append(acc)

    def series(key: str) -> list[dict]:
        out = []
        for move_no in sorted(buckets):
            accs = buckets[move_no][key]
            if not accs:
                continue
            out.append(
                {
                    "move": move_no,
                    "accuracy": round(sum(accs) / len(accs), 1),
                    "samples": len(accs),
                    "cumulative": move_no == _MOVE_NUMBER_CAP,
                }
            )
        return out

    return {"all": series("all"), "white": series("white"), "black": series("black")}


_CASTLE_SIDES = ["kingside", "queenside", "none"]
_CASTLE_LABELS = {
    "kingside": "Kingside (O-O)",
    "queenside": "Queenside (O-O-O)",
    "none": "Did not castle",
}


def _shape_castling(rows: list[tuple]) -> list[dict]:
    """The player's castling choice and how they fared with each."""
    store = {side: _wdl() for side in _CASTLE_SIDES}
    for pgn, color, result in rows:
        side = analyze_castling(pgn, color)
        outcome = _outcome(color, result)
        if outcome:
            store[side][outcome] += 1
    out = []
    for side in _CASTLE_SIDES:
        rec = _wdl_record(store[side])
        out.append({"side": side, "label": _CASTLE_LABELS[side], **rec})
    return out


def _shape_move_quality(rows: list[tuple]) -> dict:
    """Split per-classification counts into white/black columns with the
    display glyph, colour and percentage of that colour's total moves."""
    by_color: dict[str, dict[str, int]] = {"white": {}, "black": {}}
    for color, cls, n in rows:
        if color in by_color:
            by_color[color][cls] = by_color[color].get(cls, 0) + n

    def column(color: str) -> dict:
        counts = by_color[color]
        total = sum(counts.values())
        items = []
        for cls in _CLASS_ORDER:
            n = counts.get(cls, 0)
            if n == 0:
                continue
            items.append(
                {
                    "key": cls,
                    "glyph": C.CLASS_GLYPHS.get(cls, ""),
                    "color": C.CLASS_COLORS.get(cls, C.TEXT_MUTED),
                    "count": n,
                    "pct": round(100.0 * n / total, 1) if total else 0.0,
                }
            )
        return {"total": total, "items": items}

    return {"white": column("white"), "black": column("black")}


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Time-of-day buckets (local hour). Ordered Morning→Night for display; the
# ranges stay disjoint so bucketing is unaffected by the listing order.
_TIME_BUCKETS = [
    ("Morning", range(6, 12)),
    ("Afternoon", range(12, 18)),
    ("Evening", range(18, 24)),
    ("Night", range(0, 6)),
]

# Phases come from Lichess's Divider (see core/divider.py), which reads a whole
# game. The constants below are only reachable for games stored without FENs,
# where there are no boards to divide and a move count is all that is left.
_OPENING_MAX_PLY = 23   # first 12 full moves
_MIDDLE_MAX_PLY = 59    # through move 30

# Same fallback: both queens gone, or at most this much non-pawn material on a
# side.
_ENDGAME_MAX_NON_PAWN = 13

# Piece values in points, matching analysis.py's centipawn table so there is one
# set of numbers in the codebase rather than two that can drift apart.
_FEN_PIECE_POINTS = {"q": 9.0, "r": 5.0, "b": 3.25, "n": 3.0}


def _is_endgame(fen: str) -> bool:
    """Whether the position is an endgame by material, judged alone.

    Fallback only. Divider is the shipped rule; this stands in for games with no
    stored FENs, where there are no boards to divide.
    """
    placement = fen.split(" ", 1)[0]
    white = black = 0.0
    for ch in placement:
        points = _FEN_PIECE_POINTS.get(ch.lower())
        if points is None:
            continue
        if ch.isupper():
            white += points
        else:
            black += points
    # Both queens, not either: a one-sided queen trade leaves a sharp position
    # with a large imbalance, which is a middlegame until the material says
    # otherwise.
    if "Q" not in placement and "q" not in placement:
        return True
    return white <= _ENDGAME_MAX_NON_PAWN or black <= _ENDGAME_MAX_NON_PAWN


def _outcome(player_color: str, result: str) -> str | None:
    """'win' / 'loss' / 'draw' from the player's POV, or None if unfinished."""
    if result == "1/2-1/2":
        return "draw"
    if result == "1-0":
        return "win" if player_color == "white" else "loss"
    if result == "0-1":
        return "loss" if player_color == "white" else "win"
    return None


def _wdl() -> dict:
    return {"win": 0, "draw": 0, "loss": 0}


def _wdl_record(d: dict) -> dict:
    total = d["win"] + d["draw"] + d["loss"]
    win_rate = round(100.0 * d["win"] / total, 1) if total else 0.0
    return {**d, "total": total, "winRate": win_rate}


def _shape_results(rows: list[tuple]) -> dict:
    """W/D/L overall and split by the colour the player had."""
    overall = _wdl()
    by_color = {"white": _wdl(), "black": _wdl()}
    for played_at, color, result, _term, _acc in rows:
        outcome = _outcome(color, result)
        if outcome is None:
            continue
        overall[outcome] += 1
        if color in by_color:
            by_color[color][outcome] += 1
    return {
        "overall": _wdl_record(overall),
        "white": _wdl_record(by_color["white"]),
        "black": _wdl_record(by_color["black"]),
    }


def _shape_terminations(rows: list[tuple]) -> dict:
    """How the player's wins and losses end, by termination type."""
    buckets = {"win": {}, "loss": {}}
    for _played_at, color, result, term, _acc in rows:
        outcome = _outcome(color, result)
        if outcome not in ("win", "loss"):
            continue
        label = (term or "unknown").replace("_", " ")
        buckets[outcome][label] = buckets[outcome].get(label, 0) + 1

    def column(kind: str) -> list[dict]:
        items = buckets[kind]
        total = sum(items.values())
        out = [
            {"label": k, "count": n, "pct": round(100.0 * n / total, 1) if total else 0.0}
            for k, n in items.items()
        ]
        out.sort(key=lambda x: x["count"], reverse=True)
        return out

    return {"win": column("win"), "loss": column("loss")}


def _parse_hour_weekday(iso: str) -> tuple[int, int] | None:
    """Local-time (hour, weekday) for the day-of-week / time-of-day heatmap.
    Stored timestamps are UTC-aware; convert to the machine's local zone so the
    buckets reflect the user's actual clock rather than UTC."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.hour, dt.weekday()


def _shape_by_time(rows: list[tuple]) -> dict:
    """Accuracy + W/D/L grouped by day of week and by time-of-day bucket."""
    dow = {d: {"wdl": _wdl(), "acc": []} for d in _WEEKDAYS}
    tod = {label: {"wdl": _wdl(), "acc": []} for label, _ in _TIME_BUCKETS}

    for played_at, color, result, _term, acc in rows:
        hw = _parse_hour_weekday(played_at)
        if hw is None:
            continue
        hour, weekday = hw
        day_label = _WEEKDAYS[weekday]
        tod_label = next((lbl for lbl, rng in _TIME_BUCKETS if hour in rng), None)

        outcome = _outcome(color, result)
        if outcome:
            dow[day_label]["wdl"][outcome] += 1
            if tod_label:
                tod[tod_label]["wdl"][outcome] += 1
        if acc is not None:
            dow[day_label]["acc"].append(acc)
            if tod_label:
                tod[tod_label]["acc"].append(acc)

    def shape(store: dict, order: list[str]) -> list[dict]:
        out = []
        for key in order:
            cell = store[key]
            accs = cell["acc"]
            rec = _wdl_record(cell["wdl"])
            out.append(
                {
                    "label": key,
                    "games": rec["total"],
                    "winRate": rec["winRate"],
                    "accuracy": round(sum(accs) / len(accs), 1) if accs else None,
                }
            )
        return out

    return {
        "dayOfWeek": shape(dow, _WEEKDAYS),
        "timeOfDay": shape(tod, [lbl for lbl, _ in _TIME_BUCKETS]),
    }


_PHASES = ("opening", "middlegame", "endgame")


def _phase_of(ply: int, fen: str | None) -> str:
    """Fallback phase for a position judged alone, with no game to divide.

    Reached only for games stored without FENs. Divider is the shipped rule; see
    `_phase_buckets`.
    """
    if fen and _is_endgame(fen):
        return "endgame"
    if ply <= _OPENING_MAX_PLY:
        return "opening"
    if fen is None and ply > _MIDDLE_MAX_PLY:
        return "endgame"
    return "middlegame"


def _phase_buckets(rows: list[tuple]) -> list[dict[str, dict[str, int]]]:
    """One `{phase: {classification: count}}` per game, for the player's moves.

    Takes *every* ply of each game, in order, because Divider reads a whole game
    to find where the phases turn over; only the player's own moves are counted
    into the buckets. Keeping the per-game shape is also what lets the verdict
    below compute a standard error that respects the clustering — plies within
    one game are not independent draws.
    """
    games: dict[object, list[tuple]] = {}
    for key, ply, cls, fen, color in rows:
        games.setdefault(key, []).append((ply, cls, fen, color))

    out = []
    for plies in games.values():
        plies.sort(key=lambda r: r[0])
        placements = [fen.split(" ", 1)[0] for _, _, fen, _ in plies if fen]
        divided = len(placements) == len(plies)
        middle, end = divide(placements) if divided else (None, None)

        buckets: dict[str, dict[str, int]] = {p: {} for p in _PHASES}
        for i, (ply, cls, fen, color) in enumerate(plies):
            if (color == "white") != (ply % 2 == 0):
                continue
            phase = phase_at(i, middle, end) if divided else _phase_of(ply, fen)
            buckets[phase][cls] = buckets[phase].get(cls, 0) + 1
        out.append(buckets)
    return out


def _shape_phase_quality(per_game: list[dict[str, dict[str, int]]]) -> list[dict]:
    """Player's move-quality breakdown bucketed into opening/middlegame/endgame."""
    phases: dict[str, dict[str, int]] = {p: {} for p in _PHASES}
    for game in per_game:
        for name, counts in game.items():
            bucket = phases[name]
            for cls, n in counts.items():
                bucket[cls] = bucket.get(cls, 0) + n

    out = []
    for name in _PHASES:
        counts = phases[name]
        total = sum(counts.values())
        items = []
        for cls in _CLASS_ORDER:
            n = counts.get(cls, 0)
            if n == 0:
                continue
            items.append(
                {
                    "key": cls,
                    "glyph": C.CLASS_GLYPHS.get(cls, ""),
                    "color": C.CLASS_COLORS.get(cls, C.TEXT_MUTED),
                    "count": n,
                    "pct": round(100.0 * n / total, 1) if total else 0.0,
                }
            )
        out.append({"phase": name, "total": total, "items": items})
    return out


# False-discovery rate for every family of comparisons the screen makes.
_FDR = 0.05


def _rate_diff(
    per_game: list[dict[str, dict[str, int]]], a: str, b: str
) -> tuple[float, float]:
    """(difference in blunder rate, its standard error) between two phases,
    in percentage points.

    Both rates are ratios of sums across games, so the error has to treat the
    *game* as the sampling unit: plies inside one game share an opponent, a time
    control and a mood, and a binomial error over 52 000 plies would be far too
    small. This linearises each ratio and sums the per-game influence terms —
    the standard cluster-robust form — which gives the same answer as resampling
    games without resampling anything at load time.
    """
    def counts(game: dict[str, dict[str, int]], phase: str) -> tuple[int, int]:
        c = game[phase]
        return c.get("blunder", 0), sum(c.values())

    na = sum(counts(g, a)[1] for g in per_game)
    nb = sum(counts(g, b)[1] for g in per_game)
    if not na or not nb or len(per_game) < 2:
        return 0.0, float("inf")

    pa = sum(counts(g, a)[0] for g in per_game) / na
    pb = sum(counts(g, b)[0] for g in per_game) / nb

    variance = 0.0
    for g in per_game:
        ba, ta = counts(g, a)
        bb, tb = counts(g, b)
        influence = (ba - pa * ta) / na - (bb - pb * tb) / nb
        variance += influence * influence
    m = len(per_game)
    se = math.sqrt(variance * m / (m - 1))
    return 100.0 * (pa - pb), 100.0 * se


def _phase_verdict(per_game: list[dict[str, dict[str, int]]]) -> dict | None:
    """The one phase claim the screen is allowed to make, or None.

    Names a weakest phase only when its blunder rate is separated from the
    *next* worst — the strictest of the available comparisons, and what stops a
    pair the data cannot tell apart from being ranked anyway. All three pairs
    are tested and corrected together: three comparisons barely need it, but a
    claim that survives here and a claim that survives on the openings card
    should have had to clear the same bar.
    """
    rates = []
    for phase in _PHASES:
        blunders = sum(g[phase].get("blunder", 0) for g in per_game)
        total = sum(sum(g[phase].values()) for g in per_game)
        if total:
            rates.append((100.0 * blunders / total, phase, blunders, total))
    if len(rates) < 2:
        return None

    populated = [r[1] for r in rates]
    pairs = [(a, b) for i, a in enumerate(populated) for b in populated[i + 1:]]
    pvalues = []
    for a, b in pairs:
        diff, se = _rate_diff(per_game, a, b)
        if se > 0.0:
            pvalues.append(normal_two_sided_p(diff / se))
        else:
            # Every game gave the same pair of rates, so there is no
            # between-game variance left to doubt the difference with.
            pvalues.append(0.0 if diff else 1.0)
    survives = dict(zip(pairs, benjamini_hochberg(pvalues, _FDR)))

    rates.sort(reverse=True)
    (worst_rate, worst, _, worst_n), (next_rate, nxt, _, next_n) = rates[0], rates[1]
    if not survives.get((worst, nxt), survives.get((nxt, worst), False)):
        return None

    return {
        "phase": worst,
        "comparedTo": nxt,
        "rate": round(worst_rate, 1),
        "comparedRate": round(next_rate, 1),
        "total": worst_n,
        "comparedTotal": next_n,
    }


def _shape_summary(overview: dict, trend: list[dict], results: dict) -> dict:
    """Headline numbers for the page's stat strip."""
    accs = [p["accuracy"] for p in trend]
    avg_accuracy = round(sum(accs) / len(accs), 1) if accs else None

    return {
        "avgAccuracy": avg_accuracy,
        "gamesAnalyzed": overview["analyzed"],
        "winRate": results["overall"]["winRate"],
        "totalGames": overview["total"],
    }


_VALID_SPEEDS = ("bullet", "blitz", "rapid", "classical")


def build_insights(
    db: "Database",
    *,
    color: str = "all",
    speeds: list[str] | tuple[str, ...] | None = None,
    since: str | None = None,
    rated: str = "all",
    include_local: bool = False,
    view: str = "full",
) -> dict:
    """Assemble the full insights payload from the database, optionally filtered
    to one colour, a set of time-control speed buckets, a start date, and/or
    rated vs. casual games. `include_local` adds games played here against
    Stockfish, which are left out by default."""
    color = color if color in ("white", "black") else "all"
    # Daily is the redesign's (ruling 14); the old payload's speeds stay the four buckets.
    valid = (*_VALID_SPEEDS, "daily") if view == "v2" else _VALID_SPEEDS
    speeds = tuple(s for s in (speeds or ()) if s in valid)
    since = since if (since and isinstance(since, str)) else None
    rated = rated if rated in ("rated", "casual") else "all"
    flt = InsightsFilter(
        color=color, speeds=speeds, since=since, rated=rated,
        include_local=bool(include_local),
    )

    if view == "v2":     # the redesigned screen (UI-BUILD-2 C)
        from .insights_v2 import build_insights_v2
        return build_insights_v2(db, flt)
    overview = db.insights_overview(flt)
    ready = overview["analyzed"] > 0
    details = db.insights_game_details(flt)
    opening_rows = db.insights_opening_performance(flt)
    trend = _shape_trend(db.insights_accuracy_trend(flt))
    results = _shape_results(details)
    phase_games = _phase_buckets(db.insights_phase_quality(flt))
    return {
        "overview": overview,
        "ready": ready,
        "summary": _shape_summary(overview, trend, results),
        "openings": _shape_openings(opening_rows),
        "trend": trend,
        "move_quality": _shape_move_quality(db.insights_move_quality(flt)),
        "move_accuracy": _shape_move_accuracy(db.insights_move_scores(flt)),
        "results": results,
        "terminations": _shape_terminations(details),
        "by_time": _shape_by_time(details),
        "phase_quality": _shape_phase_quality(phase_games),
        "phase_verdict": _phase_verdict(phase_games),
        "castling": _shape_castling(db.insights_castling_rows(flt)),
        # R6 (PATTERNS.md §6a): from the stored per-run facts only.
        "patterns": patterns_for(db, flt, overview["analyzed"]),
    }
