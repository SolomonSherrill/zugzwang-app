"""COACH-2 C: Practice (COACH.md "COACH-2: the spec", rulings CP1, 1, 5, 6).

**Items.** Every clear-cut missed moment of the user's (core/coach.py: a chance missed, proven as gate P proves; a
threat allowed, checked against the stored next ply) that carries a coach theme becomes an item once, automatically:
"Find the move" (a missed chance: the position before the move) or "Spot the threat" (a threat allowed: the position
before the move that allowed it). A **transfer probe** is an unseen puzzle from the downloaded Lichess set with a focus
or practised theme near the user's puzzle rating, shown as "A new position, not from your games."; about one new item
in five is one (PROBE_EVERY), and none when no puzzles are downloaded.

**The attempt log is append-only** (`practice_attempts`, triggers refuse UPDATE and DELETE): item, kind, source, time,
answer, correct, time taken, hint used, answer shown. **The scheduler's state is derived from it**, never stored: each
item's FSRS card is the log's attempts replayed through the scheduler (`card_for`), so a change to the scheduler or
its parameters reschedules everything from the same record.

**Scheduling:** FSRS (py-fsrs, MIT, open-spaced-repetition), its default parameters (the 21 weights, desired retention
0.9, no fuzzing so the same log gives the same dates). Its sub-day learning steps are off: an item comes back on a later
day, as the mockups say ("Comes back tomorrow"), never minutes later in the same sitting. A rating per attempt: right
first time Good, right after a hint Hard, wrong or the answer shown Again.

**New items per day:** at most NEW_PER_DAY (decided for the owner to confirm), fed from the backlog by focus themes
first (any of the Coach page's Focus items, together), then by how recent the game is.

Times are UTC datetimes; "today" is the local day of the clock given (`now` is timezone-aware).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import chess
from fsrs import Card, Rating, Scheduler, State

from zugzwang.core import coach as CO

PRACTICE_VERSION = 1
#: New positions a day (game items and probes together). Decided for the owner to confirm: ten new positions take
#: about five minutes at the mockup's pace ("7 due today, about 5 minutes"), and the reviews they bring back stay
#: under twenty a day once the queue is running.
NEW_PER_DAY = 10
#: One new item in this many is a transfer probe (when puzzles are downloaded).
PROBE_EVERY = 5
#: A probe's puzzle is drawn from this far around the user's puzzle rating, widening once each to the next.
PROBE_RANGES = (100, 200, 400)
#: Seconds an attempt is assumed to take before the log has any ("About N minutes left").
DEFAULT_SECONDS = 30
#: "Learned, now shown less often": a card whose stability (the days until recall falls to 90 %) is at least this.
LEARNED_DAYS = 21

SCHEDULER = Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False)

#: Lichess's puzzle tag for each coach theme (the same names; a knight's fork is tagged "fork").
LICHESS_TAG = {t: t for t in CO.COACH_THEMES} | {"knightFork": "fork"}


@dataclass
class Item:
    id: int
    source: str                  # "game" | "probe"
    kind: str                    # "find" | "threat"
    theme: str                   # a coach theme
    grp: str                     # the moment's "kind:theme" (CF1's key), or "probe:<theme>"
    fen: str                     # the position the user answers from (the user to move)
    answer_uci: str              # the line's first move (find; a probe's solution), or the stored best move (threat)
    line_uci: list[str] = field(default_factory=list)
    played_uci: str | None = None    # the user's move in the game
    opp_uci: str | None = None       # the opponent's move before (Spot the threat), or a probe's setup move
    opp_label: str | None = None     # that move, numbered ("9. Nd5"), from the board before it
    threat_fen: str | None = None    # threat: the board after the user's game move (the threat's line starts there)
    game_id: int | None = None
    game_key: str | None = None
    ply: int | None = None
    played_at: str | None = None
    opponent: str | None = None
    puzzle_id: str | None = None
    puzzle_rating: int | None = None
    created_at: str = ""


@dataclass
class Attempt:
    item_id: int
    at: datetime
    correct: bool
    hint: bool = False
    revealed: bool = False
    time_ms: int | None = None
    answer_uci: str | None = None


def rating_of(a: Attempt) -> Rating:
    if a.revealed or not a.correct:
        return Rating.Again
    return Rating.Hard if a.hint else Rating.Good


def card_for(item_id: int, attempts: Sequence[Attempt]) -> Card | None:
    """The item's FSRS card: its attempts replayed in order; None for an item never attempted (new)."""
    if not attempts:
        return None
    ats = sorted(attempts, key=lambda a: a.at)
    card = Card(card_id=item_id, due=ats[0].at)
    for a in ats:
        card, _ = SCHEDULER.review_card(card, rating_of(a), a.at.astimezone(timezone.utc))
    return card


def local_day_end(now: datetime) -> datetime:
    loc = now.astimezone()
    end = loc.replace(hour=23, minute=59, second=59, microsecond=999999)
    return end.astimezone(timezone.utc)


def local_day_start(now: datetime) -> datetime:
    loc = now.astimezone()
    return loc.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def comes_back(due: datetime, now: datetime) -> str:
    """"Comes back tomorrow." / "Comes back in 4 days." / "in 3 weeks" / "in 2 months" (local days)."""
    days = (due.astimezone().date() - now.astimezone().date()).days
    if days <= 0:
        return "Comes back later today."
    if days == 1:
        return "Comes back tomorrow."
    if days < 14:
        return f"Comes back in {days} days."
    if days < 60:
        return f"Comes back in {round(days / 7)} weeks."
    return f"Comes back in {round(days / 30)} months."


def short_when(due: datetime, now: datetime) -> str:
    """The session list's "Tomorrow" / "In 9 days"."""
    return comes_back(due, now).removeprefix("Comes back ").rstrip(".").capitalize()


# ── items from the coach's moments ───────────────────────────────────────────

def _san(fen: str, uci: str | None) -> str | None:
    if not uci:
        return None
    try:
        return CO.move_label(fen, uci)
    except (ValueError, AssertionError):
        return None


def _move_between(fen_a: str, fen_b: str) -> str | None:
    """The move that takes the board fen_a to fen_b (placement, side, castling, en passant), if one does."""
    b = chess.Board(fen_a)
    want = fen_b.split()[:4]
    for m in b.legal_moves:
        b.push(m)
        hit = b.fen().split()[:4] == want
        b.pop()
        if hit:
            return m.uci()
    return None


def items_from_game(g: "CO.GameMoments", best_by_ply: dict[int, str]) -> list[Item]:
    """The items one game gives: each missed moment with a theme. *best_by_ply* maps a ply to its stored best move
    (move_analyses.best_uci), the answer a "Spot the threat" reveals."""
    out = []
    for m in g.moments:
        if m.outcome != "missed":
            continue
        theme = CO.moment_theme(m)
        if theme is None:
            continue
        fen_before = g.fens.get(m.ply)
        if not fen_before:
            continue
        if m.kind == "chance":
            out.append(Item(id=0, source="game", kind="find", theme=theme, grp=f"chance:{theme}", fen=fen_before,
                            answer_uci=m.key_move, line_uci=list(m.line), played_uci=m.played, game_id=g.game_id,
                            game_key=g.key, ply=m.ply, played_at=g.played_at, opponent=g.opponent))
        else:
            best = best_by_ply.get(m.ply)
            if not best or best == m.played:
                continue
            prev = g.fens.get(m.ply - 1)
            opp = _move_between(prev, fen_before) if prev else None
            out.append(Item(id=0, source="game", kind="threat", theme=theme, grp=f"threat:{theme}", fen=fen_before,
                            answer_uci=best, line_uci=list(m.line), played_uci=m.played, opp_uci=opp,
                            opp_label=_san(prev, opp) if prev and opp else None,
                            threat_fen=m.fen, game_id=g.game_id, game_key=g.key, ply=m.ply, played_at=g.played_at,
                            opponent=g.opponent))
    return out


def probe_item(puzzle: tuple, theme: str) -> Item | None:
    """A transfer probe from a Lichess puzzle (id, fen, moves, rating): the position after its setup move, the
    solution's first move the answer."""
    pid, fen, moves, rating = puzzle
    ms = moves.split() if isinstance(moves, str) else list(moves)
    if len(ms) < 2:
        return None
    b = chess.Board(fen)
    setup = chess.Move.from_uci(ms[0])
    if setup not in b.legal_moves:
        return None
    label = CO.move_label(fen, ms[0])
    b.push(setup)
    return Item(id=0, source="probe", kind="find", theme=theme, grp=f"probe:{theme}", fen=b.fen(),
                answer_uci=ms[1], line_uci=ms[1:], opp_uci=ms[0], opp_label=label, puzzle_id=str(pid),
                puzzle_rating=int(rating))


def probe_themes(items: Sequence[Item], log: dict[int, list[Attempt]], focus_keys: Sequence[str]) -> list[str]:
    """The themes a probe may take: the focus items' themes (in their order), then the practised ones (an item
    attempted at least once), the least probed first."""
    out: list[str] = []
    for k in focus_keys:
        t = k.split(":", 1)[1]
        if t not in out:
            out.append(t)
    for it in items:
        if it.source == "game" and log.get(it.id) and it.theme not in out:
            out.append(it.theme)
    probed = {t: sum(1 for it in items if it.source == "probe" and it.theme == t) for t in out}
    return sorted(out, key=lambda t: (probed[t], out.index(t)))


# ── the queue ────────────────────────────────────────────────────────────────

@dataclass
class Queue:
    due: list[Item]            # attempted items due by the end of today, the most overdue first
    new: list[Item]            # new items for today (the cap left), probes in their slots
    probe_slots: list[int]     # indexes in *new* where a probe belongs but none was available yet
    introduced_today: int
    cap_left: int


def _matches(it: Item, grp: str | None) -> bool:
    if grp is None:
        return True
    if it.source == "probe":
        return it.theme == grp.split(":", 1)[1] or (grp.endswith(":knightFork") and it.theme == "fork")
    return it.grp == grp


def build_queue(items: Sequence[Item], log: dict[int, list[Attempt]], now: datetime, *,
                focus_keys: Sequence[str] = (), grp: str | None = None, probes: bool = False,
                new_per_day: int = NEW_PER_DAY) -> Queue:
    """Today's queue: the attempted items due by the end of the local day, then new ones up to the day's cap left
    (the backlog by focus first, then the newest game), every PROBE_EVERY-th new item overall a probe when *probes*
    (an unattempted probe item is reused before a new one is drawn: the caller fills probe_slots). *grp* narrows it
    to one focus item (a focus card's Practise)."""
    end = local_day_end(now)
    start = local_day_start(now)
    due: list[tuple[datetime, Item]] = []
    introduced_today = 0
    introduced = 0
    fresh: list[Item] = []
    fresh_probes: list[Item] = []
    for it in items:
        ats = log.get(it.id, [])
        if ats:
            introduced += 1
            if min(a.at for a in ats) >= start:
                introduced_today += 1
            card = card_for(it.id, ats)
            if card is not None and card.due <= end and _matches(it, grp):
                due.append((card.due, it))
        elif _matches(it, grp):
            (fresh_probes if it.source == "probe" else fresh).append(it)
    # the focus items first (any of them, mixed by recency: ranking by focus order would show one theme's
    # hundreds of items before the next one's), then the newest game first
    focus = set(focus_keys)
    fresh.sort(key=lambda it: (0 if it.grp in focus else 1, _neg_date(it.played_at), -(it.ply or 0), it.id))
    cap_left = max(0, new_per_day - introduced_today)
    new: list[Item] = []
    slots: list[int] = []
    gi = pi = 0
    for j in range(cap_left):
        if probes and (introduced + j + 1) % PROBE_EVERY == 0:
            if pi < len(fresh_probes):
                new.append(fresh_probes[pi])
                pi += 1
            else:
                slots.append(len(new))
                new.append(None)          # type: ignore[arg-type]  (filled by the caller, or dropped)
            continue
        if gi < len(fresh):
            new.append(fresh[gi])
            gi += 1
    due.sort(key=lambda d: (d[0], d[1].id))
    return Queue(due=[it for _, it in due], new=new, probe_slots=slots, introduced_today=introduced_today,
                 cap_left=cap_left)


def _neg_date(s: str | None) -> str:
    """Sorts newest first as a key: the date's characters inverted."""
    return "".join(chr(0x10FFFF - ord(c)) for c in (s or ""))


# ── what the Coach page's Practice panel says ────────────────────────────────

def panel(items: Sequence[Item], log: dict[int, list[Attempt]], now: datetime, queue: Queue,
          seconds_each: float) -> dict:
    """Due today (reviews and the new ones today allows), by form; right first time this week; learned."""
    today = [it for it in queue.due] + [it for it in queue.new if it is not None]
    week_ago = now - timedelta(days=7)
    week = [a for ats in log.values() for a in ats if a.at >= week_ago]
    right = sum(1 for a in week if a.correct and not a.hint and not a.revealed)
    learned = 0
    nxt: datetime | None = None
    for it in items:
        card = card_for(it.id, log.get(it.id, []))
        if card is None:
            continue
        if card.state == State.Review and (card.stability or 0) >= LEARNED_DAYS:
            learned += 1
        if card.due > local_day_end(now) and (nxt is None or card.due < nxt):
            nxt = card.due
    n = len(today) + len(queue.probe_slots)
    return {
        "due": n,
        "reviews": len(queue.due),
        "new": n - len(queue.due),
        "find": sum(1 for it in today if it.kind == "find") + len(queue.probe_slots),
        "threat": sum(1 for it in today if it.kind == "threat"),
        "minutes": max(1, round(n * seconds_each / 60)) if n else 0,
        "rightWeek": round(right / len(week), 3) if week else None,
        "weekAttempts": len(week),
        "learned": learned,
        "items": len(items),
        "next": nxt.isoformat() if nxt else None,
        "nextText": short_when(nxt, now) if nxt else None,
    }


def seconds_each(log: dict[int, list[Attempt]]) -> float:
    """The median time an attempt took, in seconds, or DEFAULT_SECONDS before there are any."""
    ts = sorted(a.time_ms / 1000 for ats in log.values() for a in ats if a.time_ms)
    if not ts:
        return float(DEFAULT_SECONDS)
    return ts[len(ts) // 2]


# ── what an item shows ───────────────────────────────────────────────────────

def side(fen: str) -> str:
    return "white" if chess.Board(fen).turn == chess.WHITE else "black"


def view(it: Item) -> dict:
    """An item before it is answered: no theme (ruling 6: the theme shows after the answer). The hint is a square:
    the piece the answer moves (Find the move), or the opponent's piece the threat starts with (Spot the threat)."""
    if it.kind == "threat" and it.line_uci:
        hint_sq = chess.square_name(chess.Move.from_uci(it.line_uci[0]).from_square)
    else:
        hint_sq = chess.square_name(chess.Move.from_uci(it.answer_uci).from_square)
    return {"id": it.id, "kind": it.kind, "source": it.source, "fen": it.fen, "side": side(it.fen),
            "hintSquare": hint_sq, "gameId": it.game_id, "ply": it.ply, "date": it.played_at,
            "opponent": it.opponent, "played": _san(it.fen, it.played_uci) if it.played_uci else None,
            "oppMove": it.opp_label, "puzzleRating": it.puzzle_rating}


def reveal(it: Item, answer_uci: str | None, correct: bool, revealed: bool, focus_keys: Iterable[str],
           due: datetime, now: datetime) -> dict:
    """After the answer: Right / Not quite, one sentence from a fixed template over the item's checked facts, the
    theme, "One of your focus themes" where it is one, and when it comes back."""
    fk = set(focus_keys)
    best = CO.move_label(it.fen, it.answer_uci)
    mine = CO.move_label(it.fen, answer_uci) if answer_uci else None
    phrase = CO.theme_phrase("chance" if it.kind == "find" else "threat", it.theme)
    multi = len(it.line_uci) > 1
    if it.source == "probe":
        sentence = (f"You found it: {best}." if correct and answer_uci == it.answer_uci
                    else f"{mine} works too; the puzzle's move is {best}." if correct
                    else f"The move is {best}.")
    elif it.kind == "find":
        line = f"{best} starts {phrase}" if multi else f"{best} is {phrase}"
        if correct and answer_uci == it.answer_uci:
            sentence = f"You found it: {line}."
        elif correct:
            sentence = f"{mine} works too. In the game, {line}."
        else:
            sentence = f"{line[0].upper()}{line[1:]}." if not mine else f"Not {mine}: {line}."
    else:
        theirs = CO.move_label(it.threat_fen, it.line_uci[0]) if it.threat_fen and it.line_uci else None
        played = CO.move_label(it.fen, it.played_uci) if it.played_uci else None
        allowed = (f"{played} allowed {phrase}, starting with {theirs}" if multi else f"{played} allowed {phrase}: {theirs}") \
            if theirs and played else f"{played} allowed {phrase}"
        if correct:
            sentence = f"{mine} keeps you safe. In the game, {allowed}."
        else:
            sentence = f"In the game, {allowed}. A move that deals with it: {best}."
    key = f"{'chance' if it.kind == 'find' else 'threat'}:{it.theme}"
    return {
        "verdict": "right" if correct else "notQuite",
        "sentence": sentence,
        "theme": CO.theme_name("chance" if it.kind == "find" else "threat", it.theme),
        "focus": it.source == "game" and key in fk,
        "comesBack": comes_back(due, now),
        "due": due.isoformat(),
        "answerUci": it.answer_uci,
        "line": it.line_uci,
        "revealed": revealed,
    }


def item_from_row(r) -> Item:
    return Item(id=r["id"], source=r["source"], kind=r["kind"], theme=r["theme"], grp=r["grp"], fen=r["fen"],
                answer_uci=r["answer_uci"], line_uci=json.loads(r["line_json"] or "[]"), played_uci=r["played_uci"],
                opp_uci=r["opp_uci"], opp_label=r["opp_label"], threat_fen=r["threat_fen"], game_id=r["game_id"], game_key=r["game_key"],
                ply=r["ply"], played_at=r["played_at"], opponent=r["opponent"], puzzle_id=r["puzzle_id"],
                puzzle_rating=r["puzzle_rating"], created_at=r["created_at"])


def attempt_from_row(r) -> Attempt:
    return Attempt(item_id=r["item_id"], at=datetime.fromisoformat(r["at"]), correct=bool(r["correct"]),
                   hint=bool(r["hint"]), revealed=bool(r["revealed"]), time_ms=r["time_ms"],
                   answer_uci=r["answer_uci"])
