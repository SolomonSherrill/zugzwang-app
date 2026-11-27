"""
Stage 3: turning findings into English — Qt-free, deterministic, no language
model anywhere.

This module is a **lookup, not a generator**. Every sentence is four slots filled
in order from one `Finding`:

    LEAD         which move, and in which mood
    CLAIM        the mechanism — one template per `kind`
    CONSEQUENCE  what it costs, naming the piece that falls
    QUALIFIER    the policy layer — conversion and already-lost reframes

plus a GATE that can return nothing at all.

Two constraints hold the whole thing together.

**A template may only name squares and pieces the finding already carries.** It
never looks at the board to work out what to say, with one exception noted at
`cannot_mate`, which asks a question about material sufficiency rather than about
the tactic. So a template cannot assert a tactic the rule did not prove — and
where a rule proved one of two things, it says which in `pattern` and the template
reads it. A template that recomputed geometry could disagree with the rule that
proved the material, leaving the layer with two answers and no way to choose.

**Mood is decided by which move the sentence names, not by `subject`** — the move each
finding carries in `Finding.about` (STAGE5-MOVE, 2026-11-19), read through `lead_move`. A sentence
about a move that was not played is conditional throughout: "the rook would fall",
not "the rook falls". `subject` is the wrong field for this, because
`missed_material` and `missed_mate` carry `subject="played"` while the sentence
they produce names the *best* move — they are findings about the played move that
describe what a different move would have done.

**Person is decided by whose move it is**, and that is a fact about the game rather
than about the finding, so it arrives as a `Voice` from the caller — see `voice_for`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

import chess

from .classification import WPL_EXCELLENT, win_prob, wpl
from .explain import (
    _MATE_KINDS,
    MATE_CUTOFF,
    is_long_mate_against,
    MoveRef,
    PATTERN_BACK_RANK,
    PATTERN_DISCOVERED_CHECK,
    PATTERN_FORCED,
    Finding,
    deep_after,
    refutation_after,
    explain_stored_ply,
    rank_findings,
)

# ── policy constants ─────────────────────────────────────────────────────────

# MATE_CUTOFF (render `missed_mate` only at mate_in <= 4) lives in explain.py now,
# because rank_findings uses it too; imported above under the same name.
WINNING = 0.95           # at or above, the position was already won
LOST = 0.05              # at or below, it was already lost
CAP = 3                  # sentences per ply

# Labels entitled to assert the material was given up *on purpose*. Only
# `brilliant` is, because only `brilliant` has a sacrifice test behind it —
# since classifier version 3, BRILLIANT.md's B3 (the move's net on its landing square
# is negative by SEE) and B4 (taking it back fails at two plies), `labelling.brilliant`.
#
# `great` was here and is not a sacrifice detector: it is `is_best` plus a
# win-probability gap to the second line (`classification.py:303`), which proves
# the position was hard, not that anything was offered. Its findings are all
# `PATTERN_FORCED` by construction, so they keep a true sentence without it.
SACRIFICE_CLASSES = frozenset({"brilliant"})

# Above this, `win_prob` is too flat for a near-zero WPL to mean anything — see
# `compensated`. Read off the measured distribution rather than chosen: the share
# of negative-material findings with WPL < 0.02 runs 7.2 %, 4.7 %, 9.3 % across
# the 0.5–0.8 bands and then jumps to 19.5 % and 58.9 % in 0.8–0.9 and 0.9–1.0,
# while the mean material dropped for free rises from 1.14 to 2.20 pawns. A
# position where you can shed two pawns at no cost is saturated, not compensated.
COMP_MAX_DECIDED = 0.80

# Labels where the layer has nothing to add. A book move is named by the opening,
# not by what it leaves loose, and a material rule firing on one produces a
# sentence that reads as criticism of a move out of a reference book.
SILENT_CLASSES = frozenset({"book"})

# `ignored_threat` chains (owner rulings, 2026-10-22). One player leaving one piece
# loose move after move is one mistake, and saying so in full every time is nagging.
# A chain gets **one** full sentence, at its head, and the link straight after the
# head says "is still hanging"; every other link is silent. Measured over 8 945 chains
# (`review/scratch/ignored_threat_chains.out`): 91.2 % never repeat, 659 stop at two,
# 126 run to three or more.
#
# The head is where the lesson is, not where the chain happens to begin: the first
# link on a move classified as an error, else the first link. Game 285 is why —
# 11...d6 (`excellent`, costing nothing) left the knight on c5 loose first, and as
# head it pushed the blunder 12...h5 down to "still hanging".
ERROR_CLASSES = frozenset({"inaccuracy", "mistake", "miss", "blunder"})
CHAIN_REACH = 8           # links walked each way; the longest measured chain is 6
PATTERN_STILL_HANGING = "still_hanging"

# A hang on the engine's first choice that was the only legal move (owner ruling AUDIT-3,
# 2026-11-11). Stamped by `forced_clause` in place of `PATTERN_FORCED`; it says the one
# true thing about the move instead of "everything else was worse", which with no other
# move is vacuous.
PATTERN_ONLY_MOVE = "only_move"
CLAUSE_FORCED = ", but everything else was worse"
CLAUSE_ONLY_MOVE = ", but it was the only legal move"

PIECE_NAMES = {
    "P": "pawn", "N": "knight", "B": "bishop",
    "R": "rook", "Q": "queen", "K": "king",
}

# The table moved to `explain`, which needs it for `rank_findings` and cannot
# import from here. It drives the mood, the dedupe key and the rank tier, so all
# three now read one table.

# One move gets one sentence, the best one. Mate outranks a named mechanism,
# which outranks bare material, which outranks what the best move would have
# defended. Without this a single move produces "Rxf2+ was mate in 2" and
# "Rxf2+ would have won the pawn on f2" side by side, the second strictly weaker.
_SENTENCE_RANK = {
    "missed_mate": 0, "walks_into_mate": 0,
    "fork": 1, "skewer": 1, "discovered_attack": 1, "trapped_piece": 1,
    "hangs_piece": 2, "ignored_threat": 2, "missed_material": 2,
    "best_defends_piece": 3, "best_saves_piece": 3,
}


def names_move(f: Finding) -> str:
    """Whose move the sentence names: "played", "best" or "reply" (`Finding.about`,
    STAGE5-MOVE)."""
    return f.about.role.value


def lead_move(f: Finding) -> MoveRef | None:
    """The move the sentence names, read from `Finding.about` and nothing else
    (STAGE5-MOVE, owner 2026-11-10). None where the finding knows no such move."""
    a = f.about
    if a is None or a.uci is None:
        return None
    return MoveRef(uci=a.uci, san=a.san)


def is_conditional(f: Finding) -> bool:
    """A sentence about a move that was not played goes in the conditional."""
    return names_move(f) == "best"


# ── person ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Voice:
    """Who the sentence is about, in the two forms the templates need.

    `subject` opens a sentence about the played move — "This drops the…" against
    "Black drops the…". `was` appears inside the already-winning reframe, where the
    verb has to agree: "you were winning anyway" against "Black was winning anyway".
    `agent` opens a sentence about what the *player* did rather than what the move
    did — "You left the…" against "Black left the…" — for `ignored_threat`, where
    "This left the knight hanging" would credit the move with an act it failed at.

    Two fields rather than a person flag because the templates should not branch on
    person; a template that said `"you" if second else side` would have to spell the
    distinction once per sentence, and there are six sentences that need it.
    """

    subject: str
    was: str
    agent: str


# The default everywhere, so a caller with no game in hand keeps the pre-fix
# behaviour rather than silently naming the wrong side.
SECOND_PERSON = Voice("This", "you were", "You")


# A game whose user side is not known (FIXPLAN O5: `player_color` NULL). Distinct
# from `None`, which means the caller has no game at all and gets second person —
# addressing the reader on a game where their side is unknown would put "you" on
# both sides, so these are named as White and Black throughout.
UNKNOWN_SIDE = "unknown"


def voice_for(fen: str, player_color: str | None) -> Voice:
    """Second person for the user's own moves, the side's name otherwise.

    The bug this exists for: "This drops the pawn on c5" was rendered on Black's
    17…Kb8 in a game the user played as White. Every sentence about the played move
    addressed the reader, whoever had actually moved, so half the corpus blamed the
    reader for the opponent's mistakes. Roughly half — the measured share is in
    `review/EXPLANATIONS.md`.

    The side to move is read from the FEN's own turn field rather than by building a
    board, because that is the one thing a FEN states outright and this is called
    once per ply. `player_color` is the user's colour from the `games` row; `None`
    means the caller has no game, and gets second person.
    """
    mover = "white" if fen.split(" ")[1] == "w" else "black"
    if player_color == UNKNOWN_SIDE:
        side = mover.capitalize()
        return Voice(side, f"{side} was", side)
    if player_color is None or player_color == mover:
        return SECOND_PERSON
    side = mover.capitalize()
    return Voice(side, f"{side} was", side)


# ── naming pieces ────────────────────────────────────────────────────────────

def name(piece) -> str:
    """"rook on a8" — the only way a template may refer to a piece."""
    return f"{PIECE_NAMES[piece.piece]} on {piece.square}"


def joined(pieces) -> str:
    parts = [name(p) for p in pieces]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ── the claim templates ──────────────────────────────────────────────────────
#
# One per kind, each returning the mechanism clause with the verb in the mood the
# caller asks for. Indicative first, conditional second.

def _claim_fork(f: Finding, cond: bool) -> str:
    """Names the piece that falls, plus the king where the fork checks.

    The rule's definition is "every enemy piece the moved piece attacks", with the
    material test doing the judging, so `pieces` can hold six. Naming all of them
    was true and unreadable — "Qf7+ forks the knight on g8, pawn on g6, pawn on d7,
    bishop on g7 and king on e8 — the knight on g8 falls". 181 of 956 fork
    sentences named four or more.

    Two are kept rather than one. The piece that falls is `pieces[0]`, which the
    consequence clause already references, so the claim and the consequence name
    the same piece. The king earns its place because a check is *why* the defender
    cannot save the other piece — drop it and a fork reads as a double attack the
    opponent could simply answer. Both are a subset of what the finding carries, so
    no geometry is recomputed.
    """
    verb = "would fork" if cond else "forks"
    named = [f.pieces[0]]
    king = next(
        (p for p in f.pieces[1:] if p.piece == "K" and p.square != f.pieces[0].square),
        None,
    )
    if king is not None:
        named.append(king)
    return f"{verb} the {joined(named)}"


def _claim_skewer(f: Finding, cond: bool) -> str:
    # pieces[0] is the square the material is won on — the piece behind.
    verb = "would skewer" if cond else "skewers"
    rest = f.pieces[1:]
    if not rest:
        return f"{verb} the {name(f.pieces[0])}"
    return f"{verb} the {joined(rest)}, and the {name(f.pieces[0])} behind it"


def _claim_discovered(f: Finding, cond: bool) -> str:
    """Two sentences, chosen by the branch the rule recorded in `pattern`.

    On the check branch the opened line reaches the *king*, and the piece that
    falls is one the moved piece attacks — the material is just as proven, because
    the defender may only answer the check, but no opened line reaches it. Saying
    "opens a line onto the queen on a6" there would assert a geometry the rule did
    not establish. 54 of 179 findings take that branch.
    """
    if f.pattern == PATTERN_DISCOVERED_CHECK:
        verb = "would attack" if cond else "attacks"
        discovers = "discover" if cond else "discovers"
        return (
            f"{verb} the {joined(f.pieces)} and {discovers} a check, "
            "which has to be answered first"
        )
    return f"{'would open' if cond else 'opens'} a line onto the {joined(f.pieces)}"


def _claim_trapped(f: Finding, cond: bool) -> str:
    """No consequence clause follows this one — "traps" already says the piece
    falls, so naming it again would state one fact twice."""
    verb = "would trap" if cond else "traps"
    return f"{verb} the {name(f.pieces[0])} — it has nowhere safe to go"


CLAIMS = {
    "fork": _claim_fork,
    "skewer": _claim_skewer,
    "discovered_attack": _claim_discovered,
    "trapped_piece": _claim_trapped,
}

# Kinds whose claim already states what falls, so the consequence slot stays empty.
CLAIM_IS_CONSEQUENCE = frozenset({"trapped_piece"})


# ── the gate and the qualifier ───────────────────────────────────────────────

def is_mate(f: Finding) -> bool:
    """Whether the move this finding's sentence would name delivers mate.

    Reads the SAN the finding carries. That is not recomputing geometry — the
    checkmate is already stated in the notation the rule stored, and no board is
    consulted.
    """
    lead = lead_move(f)
    return lead is not None and lead.san.endswith("#")


# Kinds whose sentence itemises what a move was worth in material or in defence.
# Where that move is mate, the itemising is bookkeeping and the sentence goes.
BOOKKEEPING_KINDS = frozenset({
    "missed_material", "best_defends_piece", "best_saves_piece",
})


def suppressed(f: Finding) -> bool:
    """Two findings that must not take a render slot.

    **A mate too long to calculate.** Mate findings rank first, so without this a
    mate in 19 always displaces a finding that is actionable. Only `missed_mate` is
    cut: `walks_into_mate` is about a mate the opponent now has against *you*, and a
    long one still tells you the move lost — with the already-lost reframe below to
    say so when the position was gone anyway.

    **A mating move's merits, itemised.** "Qxc2# would have won the pawn on c2" is
    true and it is bookkeeping: the move is mate, so the pawn is not why it was
    best. The same holds for what mate happens to defend — "Ne5# would have saved
    the knight", "Qxh6# would have defended the knight on g5". Rule 3 declines to
    emit a `missed_mate` finding in these positions — `score_after_mate` is
    positive, the player still has mate, so nothing was missed — which is why rank
    order cannot solve it and the sentence has to be dropped outright.
    """
    if f.kind == "missed_mate":
        return (f.mate_in or 99) > MATE_CUTOFF
    return f.kind in BOOKKEEPING_KINDS and is_mate(f)


# Whether the sentence is about the mover gaining or the mover losing. The
# already-winning reframe is only sound on a gain, and asserting it on a loss is a
# plain falsehood: "This drops the queen on g2 — Kxg2 takes it, converting a
# position you were already winning" says the blunder converted the game, and
# "This allows Rf8#, mate in 1, converting a position you were already winning"
# says being mated did. Both were rendered before this split existed.
#
# `missed_mate` is gain-shaped and still excluded, because `p_before >= WINNING`
# is *entailed* by the finding rather than observed alongside it — a forced mate
# is a win probability of about 1 by construction, so the qualifier fires on
# essentially every one and tells the reader the mate they missed did not matter.
GAINS = frozenset({
    "fork", "skewer", "discovered_attack", "trapped_piece", "missed_material",
})

# The already-lost reframe is about the position, so it needs no person. The other
# two name whoever moved, and so are templates over `Voice.was`.
QUAL_LOST = ", though the position was lost either way"
QUAL_WON_COND = ", though {was} winning anyway"
QUAL_WON_INDICATIVE = ", converting a position {was} already winning"


def qualifier(
    f: Finding,
    p_before: float | None,
    cond: bool,
    voice: Voice = SECOND_PERSON,
) -> str:
    """The two reframes the stored scores can support, keyed on `p_before` alone.

    `p_before` is the win probability from the mover's side *before* the move, so
    it answers "was this position already decided" without reference to what the
    finding claims. That is why no material is required: a mate finding carries
    none, and a long forced mate on a move the classifier called `best` is exactly
    the case the already-lost reframe exists for.

    The already-lost reframe applies to every kind, because it is about the
    position rather than about the claim: a piece dropped, a mate allowed and a
    rook won are all equally beside the point once the game was gone. The
    already-winning reframe applies only to `GAINS`, and its wording differs by
    mood because the fact differs — a tactic you played converted the position,
    one you missed did not, and telling you it "converted" a position you never
    won would be false.

    The third case policy 4 names — material won where the result cannot change —
    is **not** here, because neither stored score answers it: the evaluation needed
    is the one *after* the material is collected. The one variant the board can
    prove on its own is `cannot_mate`.
    """
    if p_before is None:
        return ""
    if p_before <= LOST:
        return QUAL_LOST
    if p_before >= WINNING and f.kind in GAINS:
        template = QUAL_WON_COND if cond else QUAL_WON_INDICATIVE
        return template.format(was=voice.was)
    return ""


def cannot_mate(fen: str, f: Finding) -> bool:
    """Material won that cannot matter, in the one form provable from the board.

    The motivating position is `r3k3/8/8/1N6/8/8/8/4K3 w` — `Nc7+` forks king and
    rook, and after `Nxa8` White has king and knight, which cannot mate. The
    finding is true and the gain is worthless, and the reason is not an evaluation
    at all: it is insufficient material, which `python-chess` decides exactly.

    This is the one place a template consults the board, and it is allowed because
    the question is about what is left standing rather than about the tactic. It
    catches only this shape, not a drawn rook ending. Measured over the corpus it
    fires **once** — kept because it is provable and cheap, not because it earns
    its place on volume.
    """
    if f.material is None or not f.pieces:
        return False
    played = lead_move(f)
    if played is None:
        return False
    board = chess.Board(fen)
    mover = board.turn
    move = chess.Move.from_uci(played.uci)
    if move not in board.legal_moves:
        return False
    board.push(move)
    # Simulate collecting the piece the finding says falls.
    board.remove_piece_at(chess.parse_square(f.pieces[0].square))
    return board.has_insufficient_material(mover)


# What near-zero WPL proves, and all it proves: the move did not change the
# evaluation (owner ruling, 2026-10-22). It does *not* prove the material returns —
# the first wording, "the material comes back", was false on 4 of 10 hand-checked
# positions (`review/scratch/ignored_threat_spotcheck.out`): an equal rook ending a
# pawn down, two positions where the piece was simply gone, a pawn shed to trade
# queens. One claim, inflected to each template's tense.
QUAL_COST_NOTHING = ", though it costs nothing here"
QUAL_COST_NOTHING_PAST = ", though it cost nothing here"
CLAUSE_SACRIFICE = ", and that is the point"


def excuses(line: str) -> bool:
    """Whether a rendered sentence excuses the move it describes: forced ("…, but
    everything else was worse"), the only legal move, compensated ("…, though it
    costs nothing here"), or a sacrifice ("…, and that is the point"). The game report's
    pattern line does not count such a sentence as a mistake (owner ruling AUDIT-6)."""
    return any(c in line for c in (CLAUSE_FORCED, CLAUSE_ONLY_MOVE, QUAL_COST_NOTHING,
                                   QUAL_COST_NOTHING_PAST, CLAUSE_SACRIFICE))


def compensated(f: Finding, p_before: float | None, loss: float | None) -> bool:
    """Material shed at no cost to the evaluation, in the one form WPL can prove.

    The motivating case is game 167 ply 16, `9.Bxf7+` — the bishop is taken and
    the evaluation goes +3.69 to +3.55, so the rule is right that two pawns of
    material are shed and reporting that flat is still misleading.

    **The claim is about the evaluation, not about the player — or the material.**
    WPL says the move cost nothing; it says nothing about whether anyone meant it to,
    and nothing about whether the material returns. So this gates "it costs nothing
    here" (`QUAL_COST_NOTHING`) and must never gate "and that is the point" — intent
    needs `SACRIFICE_CLASSES`, which has a real sacrifice test behind it.

    Two guards, and the finding has to clear both:

    **`PATTERN_FORCED` is excluded.** It means the move played *was* the engine's
    first choice, which makes WPL zero by construction — before and after are
    scored from the same line. Measured, 85–99 % of forced findings sit under
    WPL 0.01, so without this guard the test fires on essentially all of them and
    "it costs nothing here" would be a restatement of `played == best`. Those
    findings already say "but everything else was worse", which is the true thing.

    **The position must not already be decided.** `win_prob` is a sigmoid, so near
    either end a real material loss moves it very little and WPL ≈ 0 is
    saturation rather than compensation — see `COMP_MAX_DECIDED` for the measured
    shape. The existing `WINNING`/`LOST` constants are far too loose for this:
    they sit at 0.95/0.05, and by 0.9 the curve is flat enough that 58.9 % of
    these findings cost under 0.02 while shedding 2.2 pawns on average.
    """
    if f.pattern in (PATTERN_FORCED, PATTERN_ONLY_MOVE) or p_before is None or loss is None:
        return False
    if (f.material or 0.0) >= 0:
        return False
    if max(p_before, 1.0 - p_before) > COMP_MAX_DECIDED:
        return False
    return loss <= WPL_EXCELLENT


def back_rank(f: Finding) -> str:
    """An annotation, riding on a mate already proved. It adds no claim of its
    own, so it costs no render slot."""
    if f.pattern != PATTERN_BACK_RANK or not f.pieces:
        return ""
    squares = ", ".join(p.square for p in f.pieces)
    return f" — a back-rank mate, with the king's own pawns on {squares} in the way"


# ── the sentence ─────────────────────────────────────────────────────────────

def render(
    f: Finding,
    fen: str,
    classification: str | None,
    p_before: float | None,
    qualify: bool = True,
    voice: Voice = SECOND_PERSON,
    loss: float | None = None,
) -> str | None:
    """One finding, one sentence, or None where policy says stay quiet.

    `qualify=False` renders the same sentence with the reframe clause omitted. It
    exists for `describe_ply`, which lets only the first sentence in a block carry
    one; a finding never decides this for itself, because whether the clause is a
    repeat is a property of the block.

    `voice` defaults to second person, which is what the conditional sentences want
    in every case: "Qe7 would have defended the pawn on c2" names a move nobody
    played, so it has no mover to address or to name.

    `SILENT_CLASSES` is gated here rather than in `suppressed`, which sees only the
    finding and not the label the classifier gave the move.

    `loss` is the ply's WPL. It is the mover's cost for the move actually played,
    so it belongs to the ply rather than to the finding, and `compensated` is the
    only reader. Omitting it costs that one reframe and nothing else.
    """
    if classification in SILENT_CLASSES or suppressed(f):
        return None
    cond = is_conditional(f)
    lead = lead_move(f)
    qual = qualifier(f, p_before, cond, voice) if qualify else ""

    if f.kind in CLAIMS:
        if not f.pieces or lead is None:
            return None
        claim = CLAIMS[f.kind](f, cond)
        falls = name(f.pieces[0])
        if cannot_mate(fen, f):
            verb = "would fall" if cond else "falls"
            tail = f" — the {falls} {verb}, but what is left cannot mate"
        elif f.kind in CLAIM_IS_CONSEQUENCE:
            tail = qual
        else:
            verb = "would fall" if cond else "falls"
            tail = f" — the {falls} {verb}{qual}"
        return f"{lead.san} {claim}{tail}."

    if f.kind == "hangs_piece":
        # Every piece, not just the first: the dedupe merges several pieces hanging
        # to one move into one finding, and naming `pieces[0]` alone would report a
        # move that loses two as losing one.
        lost = joined(f.pieces) if f.pieces else None
        if lost is None:
            return None
        taker = f.moves.get("refutation")
        after = f" — {taker.san} takes it" if taker else ""
        # Every verb below is third-person singular and stays so for both voices:
        # "This drops", "Black drops". That is why `Voice` carries no verb — only
        # the reframe's "you were" against "Black was" needs to inflect.
        if classification in SACRIFICE_CLASSES:
            # Checked before PATTERN_FORCED, which most brilliancies also carry:
            # a sacrifice the engine endorses is still chosen rather than endured,
            # and "that is the point" is the stronger of the two true statements.
            return f"{voice.subject} gives up the {lost}{after}{CLAUSE_SACRIFICE}."
        if f.pattern == PATTERN_ONLY_MOVE:
            return f"{voice.subject} drops the {lost}{after}{CLAUSE_ONLY_MOVE}."
        if compensated(f, p_before, loss):
            # Deliberately weaker than the clause above: the evaluation proves the
            # move cost nothing, nothing proves the mover intended it.
            return f"{voice.subject} gives up the {lost}{after}{QUAL_COST_NOTHING}."
        if f.pattern == PATTERN_FORCED:
            # The loss is real and the move was still the engine's own choice.
            # Without this clause the sentence sits under a `Best move` badge and
            # reads as the layer contradicting itself. It replaces the qualifier
            # rather than joining it: both are reframes on one sentence, and
            # "…, though the position was lost either way, but everything else was
            # worse" is two contrastive clauses saying one thing.
            return f"{voice.subject} drops the {lost}{after}{CLAUSE_FORCED}."
        return f"{voice.subject} drops the {lost}{after}{qual}."

    if f.kind == "ignored_threat":
        # Never "drops" or "hangs": the piece was already loose, so this move did
        # not lose it — it failed to rescue it, and the rule proved a rescue
        # existed. The sentence names the player, not the move, for that reason.
        lost = joined(f.pieces) if f.pieces else None
        if lost is None:
            return None
        # The compensation clause replaces the qualifier, as on `hangs_piece` — and
        # says only that the move cost nothing, never that anyone meant it or that
        # the material returns (owner rulings, 2026-10-22).
        tail = QUAL_COST_NOTHING_PAST if compensated(f, p_before, loss) else qual
        if f.pattern == PATTERN_STILL_HANGING:
            verb = "is" if len(f.pieces) == 1 else "are"
            return f"The {lost} {verb} still hanging{tail}."
        taker = f.moves.get("refutation")
        after = f" — {taker.san} wins it" if taker else ""
        return f"{voice.agent} left the {lost} hanging{after}{tail}."

    if f.kind == "missed_material":
        # An en-passant best move captures on an empty square, so the finding
        # carries no victim and there is no piece to name. 26 of 5468 findings.
        # Silence is cheaper than a second template for half a percent of a rule.
        if lead is None or not f.pieces:
            return None
        return f"{lead.san} would have won the {name(f.pieces[0])}{qual}."

    if f.kind == "missed_mate":
        if lead is None:
            return None
        return f"{lead.san} was mate in {f.mate_in}{back_rank(f)}{qual}."

    if f.kind == "walks_into_mate":
        ref = f.moves.get("refutation")
        tail = f"{back_rank(f)}{qual}"
        if ref is not None:
            return f"{voice.subject} allows {ref.san}, mate in {f.mate_in}{tail}."
        return f"{voice.subject} allows a forced mate in {f.mate_in}{tail}."

    if f.kind == "best_defends_piece":
        if lead is None or not f.pieces:
            return None
        return f"{lead.san} would have defended the {name(f.pieces[0])}."

    if f.kind == "best_saves_piece":
        # No square. This finding reads its piece off the board *after* the best
        # move, so the square it carries is where the piece went, not where it
        # stood and was in danger — "the knight on c4" for a knight that was on d6.
        # The move name already says the destination.
        if lead is None or not f.pieces:
            return None
        return f"{lead.san} would have saved the {PIECE_NAMES[f.pieces[0].piece]}."

    return None


# Kinds where losing the dropped findings would lose information rather than
# repeat it. Two pieces hanging to one move are two separate losses, so the
# dedupe merges them instead of keeping the most valuable alone — a move that
# loses two pieces must not read as losing one.
MERGED_KINDS = frozenset({"hangs_piece", "ignored_threat"})


def _merge_losses(winner: Finding, also: list[Finding]) -> Finding:
    """Fold same-kind findings about one move into a single finding.

    The result carries every piece, so the template still only names what its
    finding carries and nothing recomputes geometry.

    The refutation is dropped. Each finding carries the capture that takes *its*
    piece and there is no single move that takes both, so keeping one would name
    one capture and imply it answered everything.
    """
    pieces = winner.pieces + tuple(p for f in also for p in f.pieces)
    material = sum(f.material or 0.0 for f in (winner, *also))
    moves = {k: v for k, v in winner.moves.items() if k != "refutation"}
    return replace(winner, pieces=pieces, material=material, moves=moves)


def one_sentence_per_move(findings: list[Finding]) -> list[Finding]:
    """Keep the best-ranked finding for each move, in the order given.

    Two findings about one move produce two sentences opening with the same move
    name, and the weaker one is almost always implied by the stronger: "Qa3 was
    mate in 4" does not need "Qa3 would have defended the pawn on c3" after it.

    `MERGED_KINDS` is the exception, where the dropped finding is not implied by
    the kept one — see `_merge_losses`.

    A **suppressed** finding does not compete. It renders nothing, so letting it win
    its move's slot silences the runner-up as well and the move goes unmentioned —
    which is how a mate in 19 could delete the material sentence beside it, the
    opposite of the recorded policy that a material sentence in place of a
    suppressed unactionable mate is the right trade.

    A **long mate against the mover** does not compete either, in the other
    direction: it gets a key of its own, so it neither takes the played move's slot
    from a concrete finding nor loses its own sentence to one. `rank_findings` has
    already put it last, so it renders after whatever it used to hide.

    An **ignored threat** gets a key of its own as well. It names the played move,
    so it would otherwise share a slot with whatever that move *did* — and a move
    that drops a new piece while leaving an old one loose has lost two things, the
    case `MERGED_KINDS` exists so a reader is never told about only one. The two
    kinds cannot merge into one sentence, because "drops" and "left hanging" are
    different claims; they get one each.
    """
    best: dict[tuple[str, str], Finding] = {}
    group: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        lead = lead_move(f)
        if lead is None or suppressed(f):
            continue
        key = (lead.uci, names_move(f))
        if is_long_mate_against(f):
            key = (*key, "long mate")
        elif f.kind == "ignored_threat":
            # Keyed on the repeat form too, so a fresh threat and one "still
            # hanging" are never merged into one sentence with one verb.
            key = (*key, "ignored", f.pattern)
        group.setdefault(key, []).append(f)
        prior = best.get(key)
        rank = (_SENTENCE_RANK.get(f.kind, 9), -abs(f.material or 0.0))
        if prior is None or rank < (
            _SENTENCE_RANK.get(prior.kind, 9), -abs(prior.material or 0.0)
        ):
            best[key] = f

    merged: dict[int, Finding] = {}
    for key, winner in best.items():
        if winner.kind not in MERGED_KINDS:
            continue
        also = [f for f in group[key] if f.kind == winner.kind and f is not winner]
        if also:
            merged[id(winner)] = _merge_losses(winner, also)

    kept = set(id(f) for f in best.values())
    return [merged.get(id(f), f) for f in findings if id(f) in kept]


# ── ignored_threat repeats ───────────────────────────────────────────────────

def _ignored_keys(findings: list[Finding]) -> set[tuple[str, str]]:
    return {
        (p.square, p.piece)
        for f in findings if f.kind == "ignored_threat"
        for p in f.pieces
    }


def mate_leads(findings: list[Finding]) -> bool:
    """Whether the ply renders a mate that leads its block — one that is neither cut
    (`suppressed`) nor demoted (`is_long_mate_against`).

    Where one does, an `ignored_threat` beside it is bookkeeping: "White allows a
    forced mate in 4" followed by "White left the pawn on b2 hanging" counts a pawn
    in a position that is about the mate (owner ruling, 2026-10-22). This is not
    `BOOKKEEPING_KINDS`, which asks whether the move *a sentence names* is mate: for
    `ignored_threat` that is the played move, which leaves nothing to capture when
    it mates, so the kind in that set would never fire. A demoted long mate does not
    lead, so the hanging sentence may — and does.
    """
    return any(
        f.kind in _MATE_KINDS and not suppressed(f) and not is_long_mate_against(f)
        for f in findings
    )


@dataclass(frozen=True)
class RunPlies:
    """The rest of the game a ply sits in: `rows` is one analysis run's stored rows
    keyed by ply, and `ply` is the one being rendered. What `ignored_threat` chains
    need, in both directions — whether a link is the head depends on the links after
    it as much as before."""

    rows: Mapping
    ply: int
    # The run's `final_lines_json`: the engine's lines after the game's last move, the
    # refutation source for the last ply (STORE-FINALPLY).
    final_lines: tuple = ()
    # Whether the Review callout at a ply shows an engine-line claim in place of that
    # ply's rule sentences (reversed precedence, `compose`). Set by `compose`, which owns
    # the precedence; None means no ply's rule sentences are replaced. Read only to
    # decide whether a sentence on an earlier ply is visible (AUDIT-7).
    engine_claim: Callable[[int], bool] | None = field(default=None, compare=False)


# ── The adjacent-ply check (owner, 2026-11-09) ───────────────────────────────
#
# A rule that names a capture as the punishment of the played move ("— fxg3 takes
# it") must agree with the engine's own analysis of the next position: the best move
# stored at ply N+1 is the refutation of ply N (ARCH-0.1-N1, 176,823 adjacent pairs).
# Gate P is a two-ply minimax and cannot see a recapture that carries a further threat
# (16.fxg3 Nxg3+ forks the king and the f1 rook, in a stored game); ply
# N+1's stored analysis can. If the claimed capture is not the engine's best reply, or
# the capture was played and is itself labelled an error, the finding stays silent.

CAPTURE_CLAIM_KINDS = frozenset({"hangs_piece", "ignored_threat"})


def _lines_of(row) -> list:
    """A stored row's engine lines: `lines` (a `MoveAnalysis`) or `lines_json` (SQL)."""
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    if "lines" in keys and row["lines"]:
        return list(row["lines"])
    if "lines_json" in keys and row["lines_json"]:
        import json
        return json.loads(row["lines_json"])
    return []


def capture_is_an_error(ref_uci: str, lines) -> bool | None:
    """Whether the capture, had it been played, would itself be an error: its
    win-probability loss against the best of `lines` (stored MultiPV, side-to-move view)
    is past the non-error band (`WPL_GOOD`: best / excellent / good). None when the
    capture is not among the stored lines, so its loss cannot be read."""
    from zugzwang.core.classification import WPL_GOOD
    if not lines or not lines[0].get("uci"):
        return None
    hit = next((ln for ln in lines if ln.get("uci") and ln["uci"][0] == ref_uci), None)
    if hit is None:
        return None
    loss = win_prob(lines[0].get("cp"), lines[0].get("mate")) - win_prob(hit.get("cp"), hit.get("mate"))
    return loss > WPL_GOOD


def next_ply_contradicts(f: Finding, run: "RunPlies") -> str | None:
    """Why ply N+1's stored analysis contradicts the capture `f` names, or None.

    One rule (owner, 2026-11-09): **the claimed capture must not itself be an error.**
    Played, by its stored label; not played, by its win-probability loss against ply
    N+1's best line, from the stored MultiPV lines — in the non-error band (best,
    excellent, good) it stands, past it or not among the stored lines it is silenced."""
    if f.kind not in CAPTURE_CLAIM_KINDS:
        return None
    ref = f.moves.get("refutation")
    if ref is None:
        return None
    nxt = run.rows.get(run.ply + 1)
    if nxt is None:
        # The game's last ply: its refutation is the final position's lines. With none
        # (a partial row set, or a run older than STORE-FINALPLY) there is nothing to
        # check against, which is not a contradiction: the claim stands on gate P.
        lines = [ln for ln in (run.final_lines or ()) if ln.get("uci")]
        if not lines:
            return None
        if lines[0]["uci"][0] == ref.uci:
            return None
        err = capture_is_an_error(ref.uci, lines)
        return None if err is False else (
            "would itself be an error" if err else "not among the engine's top replies")
    if nxt["played_uci"] == ref.uci:
        return "played, and labelled an error" if nxt["classification"] in ERROR_CLASSES else None
    if not nxt["best_uci"]:
        return "no best reply stored"
    if nxt["best_uci"] == ref.uci:
        return None
    err = capture_is_an_error(ref.uci, _lines_of(nxt))
    if err is None:
        return "not among the engine's top replies"
    return "would itself be an error" if err else None


# ── The audit rulings (owner, 2026-11-11): the stored lines must not contradict ──
#
# The adjacent-ply check's class of defect, in other sentences: a claim resting on a
# static or shallow witness while a deeper stored one disagrees (`review/AUDIT_CLAIMS.md`).
# "Settled" material is `pv_reading`'s definition — the balance plus the best
# static-exchange capture the side to move then has — so a line stored mid-exchange
# does not decide anything. Every test reads the run's own stored lines: ply N's line
# (which starts with the best move) for a sentence about the best move; the played move
# plus ply N+1's line (the final lines on the last ply) for one about the played move.

def _settled(board: chess.Board, pov: bool) -> float:
    from zugzwang.core import pv_reading as P
    bal = P.balance(board, pov)
    if board.is_game_over():
        return bal
    gain = P._best_capture_gain(board)
    return bal + (gain if board.turn == pov else -gain)


@dataclass(frozen=True)
class _Walk:
    settled: dict          # half-moves replayed -> settled balance
    raw: dict              # half-moves replayed -> balance
    captured_at: int | None
    length: int
    winner: bool | None    # the colour that delivered mate at the end, or None


def _walk(fen: str, ucis, pov: bool, track_sq: str | None = None,
          track_from: int = 0) -> _Walk:
    """Replay a stored line from `fen`, stopping at the first illegal move. Tracks the
    piece standing on `track_sq` once `track_from` half-moves have been played, and
    records the half-move index at which it is captured."""
    from zugzwang.core import pv_reading as P
    board = chess.Board(fen)
    settled = {0: _settled(board, pov)}
    raw = {0: P.balance(board, pov)}
    sq = None
    cap_at = None
    n = 0
    for i, u in enumerate(ucis):
        if i == track_from and track_sq is not None:
            sq = chess.parse_square(track_sq)
        try:
            mv = chess.Move.from_uci(u)
        except ValueError:
            break
        if mv not in board.legal_moves:
            break
        if sq is not None and cap_at is None:
            victim = mv.to_square
            if board.is_en_passant(mv):
                victim = chess.square(chess.square_file(mv.to_square),
                                      chess.square_rank(mv.from_square))
            if board.is_capture(mv) and victim == sq:
                cap_at = i
            elif mv.from_square == sq:
                sq = mv.to_square
            elif board.is_castling(mv):
                rank = chess.square_rank(mv.from_square)
                ks = chess.square_file(mv.to_square) > chess.square_file(mv.from_square)
                if sq == chess.square(7 if ks else 0, rank):
                    sq = chess.square(5 if ks else 3, rank)
        board.push(mv)
        n = i + 1
        settled[n] = _settled(board, pov)
        raw[n] = P.balance(board, pov)
    winner = (not board.turn) if board.is_checkmate() else None
    return _Walk(settled, raw, cap_at, n, winner)


# The horizons a stored line is read at, in half-moves past its start, plus its end.
HORIZONS = (2, 4, 6)
# One pawn: what "won material" has to mean (`config.EXPLAIN_MIN_MATERIAL`).
PAWN = 1.0


def _horizon_gains(w: _Walk, base_idx: int) -> list[float]:
    """Settled balance at each horizon past `base_idx` and at the line's end, less the
    raw balance at `base_idx`."""
    pts = [base_idx + h for h in HORIZONS if base_idx + h <= w.length] + [w.length]
    return [w.settled[p] - w.raw[base_idx] for p in pts]


def _first_line(lines) -> list[str] | None:
    hit = next((ln for ln in lines or () if ln.get("uci")), None)
    return list(hit["uci"]) if hit is not None else None


def after_lines(run: RunPlies) -> list:
    """The stored lines of the position the ply's move created: ply N+1's, or the run's
    final lines on the last ply."""
    nxt = run.rows.get(run.ply + 1)
    if nxt is not None:
        return _lines_of(nxt)
    return [ln for ln in (run.final_lines or ()) if ln.get("uci")]


def _settled_after(fen: str, ucis, pov: bool, h: int) -> tuple[float, bool]:
    """Settled balance after min(h, len) half-moves of a line, and whether it mated."""
    board = chess.Board(fen)
    for u in list(ucis)[:h]:
        try:
            m = chess.Move.from_uci(u)
        except ValueError:
            break
        if m not in board.legal_moves:
            break
        board.push(m)
    return _settled(board, pov), board.is_checkmate()


def missed_material_contradicted(f: Finding, row, run: RunPlies | None) -> str | None:
    """Why the stored lines contradict a `missed_material` sentence ("Nxe5 would have
    won the knight on e5"), or None. Owner ruling AUDIT-1 (2026-11-11), three cases:

    - **a trade or a sacrifice**: in the engine's own line after the capture (ply N's
      stored line, which starts with it), the mover is never a pawn up, settled, at 2,
      4 or 6 half-moves or at the line's end. A line that mates for the mover is not
      this case.
    - **not a pawn ahead of the played line**: settled after 6 half-moves, the best
      line is less than a pawn ahead of the played line (the played move plus ply
      N+1's stored line, the final lines on the last ply). Not judged where either
      line mates within those 6 half-moves.
    - **taken anyway**: the player took that same piece, on that square, on their very
      next move in the game.

    The rule's own gate (`_survives_reply`) is unchanged; these read the stored lines
    the rule cannot see. With no stored line to read, a case is not tested.
    """
    if f.kind != "missed_material":
        return None
    best = lead_move(f)
    if best is None:
        return None
    fen = row["fen_before"]
    board = chess.Board(fen)
    mover = board.turn
    pv = _first_line(_lines_of(row))
    if pv and pv[0] == best.uci:
        w = _walk(fen, pv, mover)
        if w.winner != mover and max(_horizon_gains(w, 0)) < PAWN:
            return "a trade or a sacrifice in the engine's own line"
        if run is not None:
            reply = _first_line(after_lines(run))
            if reply is not None:
                b6, bm = _settled_after(fen, pv, mover, 6)
                p6, pm = _settled_after(fen, [row["played_uci"], *reply], mover, 6)
                if not bm and not pm and b6 - p6 < PAWN:
                    return "not a pawn ahead of the played line"
    if run is not None:
        n2 = run.rows.get(run.ply + 2)
        if n2 is not None and n2["played_uci"] and n2["fen_before"]:
            target = chess.parse_square(best.uci[2:4])
            victim = board.piece_at(target)
            later = chess.Board(n2["fen_before"])
            move = chess.Move.from_uci(n2["played_uci"])
            if (victim is not None and later.piece_at(target) == victim
                    and move.to_square == target and later.is_capture(move)):
                return "taken on the next move"
    return None


def forced_clause(f: Finding, row) -> Finding | None:
    """What "…, but everything else was worse" may say on this ply (owner ruling AUDIT-3,
    2026-11-11). The clause is stamped from `played == best` alone (`PATTERN_FORCED`);
    the run stores up to two alternatives, and the audit found the second scored no
    worse on 189 of 1,066 sentences and within the `excellent` band on 603.

    - **the only legal move**: the finding is re-stamped `PATTERN_ONLY_MOVE`, and says so —
      unless the capture it names is checkmate, when it is silent (AUDIT-Q4).
    - **the second stored line is worse than the played move by more than 0.05 win
      probability** (`WPL_GOOD`, the edge of the non-error band — the second-best move
      would itself have been an error): the clause stands.
    - **every other case, including no second line stored**: None — the whole sentence
      is silent, not the sentence without the clause.

    Any other finding is returned unchanged."""
    if f.kind != "hangs_piece" or f.pattern != PATTERN_FORCED:
        return f
    from zugzwang.core.classification import WPL_GOOD
    board = chess.Board(row["fen_before"])
    if board.legal_moves.count() == 1:
        # The capture it names is checkmate: itemising the material lost to a mating
        # move is bookkeeping, so the sentence is silent (owner ruling AUDIT-Q4).
        taker = f.moves.get("refutation")
        if taker is not None and taker.san.endswith("#"):
            return None
        return replace(f, pattern=PATTERN_ONLY_MOVE)
    lines = [ln for ln in _lines_of(row) if ln.get("uci")]
    if len(lines) < 2:
        return None
    gap = win_prob(lines[0].get("cp"), lines[0].get("mate")) - \
        win_prob(lines[1].get("cp"), lines[1].get("mate"))
    return f if gap > WPL_GOOD else None


MOTIF_KINDS = frozenset(CLAIMS)


def found_tactic_on_an_error(f: Finding, row) -> str | None:
    """A tactic the player *found* — a motif on the played move — as the text under an
    error badge reads backwards: "Nc7+ forks the rook on a8 and king on e8 — the rook
    on a8 falls" on a `blunder` (a stored ply). Silent on inaccuracy,
    mistake, miss and blunder (owner ruling AUDIT-9, 2026-11-11). A motif about the best
    move is unaffected: that is the tactic the player missed."""
    if f.kind in MOTIF_KINDS and f.subject == "played" and \
            row["classification"] in ERROR_CLASSES:
        return "a found tactic on a move labelled an error"
    return None


def motif_piece_does_not_fall(f: Finding, row, run: RunPlies | None) -> str | None:
    """A motif's "— the bishop on e5 falls" is silent unless the stored line that starts
    with the move captures the named piece, or leaves the mover at least a pawn up,
    settled, at 2, 4 or 6 half-moves after the move or at the line's end (owner ruling
    AUDIT-11, 2026-11-11). A line that mates for the mover stands.

    The line: for a motif on the played move, the move plus ply N+1's stored line (the
    final lines on the last ply); for one on the best move, ply N's stored line. Gate P's
    horizon is two plies, and the engine's line can show the material never arriving —
    in a stored ply, "Qf5+ forks the bishop on e5 and king on h7 — the bishop on e5
    falls", where the line is a draw by repetition.

    "Unless the stored line shows it": a run with no line to read (the stored data says
    nothing) is silent too. Only a caller with no run and a row with no `lines` at all —
    a constructed position, not the database — leaves the rule's own gate to decide."""
    if f.kind not in MOTIF_KINDS or not f.pieces:
        return None
    fen = row["fen_before"]
    mover = chess.Board(fen).turn
    if f.subject == "played":
        if run is None:
            return None
        line = _first_line(after_lines(run))
        ucis = [row["played_uci"], *line] if line is not None else None
    else:
        if "lines" not in set(row.keys()) and "lines_json" not in set(row.keys()):
            return None
        pv = _first_line(_lines_of(row))
        move = lead_move(f)
        ucis = pv if pv and move is not None and pv[0] == move.uci else None
    if ucis is None:
        return "no stored line starts with the move"
    w = _walk(fen, ucis, mover, f.pieces[0].square, 1)
    if w.winner == mover or w.captured_at is not None:
        return None
    if max(_horizon_gains(w, 1)) >= PAWN:
        return None
    return "the stored line never takes the piece and the mover is never a pawn up"


RESCUE_KINDS = frozenset({"best_defends_piece", "best_saves_piece"})


def rescue_taken_anyway(f: Finding, row) -> str | None:
    """A rescue sentence ("Qa5 would have defended the pawn on c5", "d5 would have saved
    the pawn") is silent where the engine's immediate reply in its own line — ply N's
    stored line, which starts with the best move — captures that piece, and the mover is
    a pawn down a move later: settled, after the best move, the reply and the mover's
    next move, at least a pawn below the balance before the best move (owner ruling
    AUDIT-12, 2026-11-11). A capture of it later in the line is not this case: those
    read, in the audit's sample, as voluntary give-ups."""
    if f.kind not in RESCUE_KINDS or not f.pieces:
        return None
    pv = _first_line(_lines_of(row))
    move = lead_move(f)
    if not pv or move is None or pv[0] != move.uci or len(pv) < 2:
        return None
    from zugzwang.core import pv_reading as P
    fen = row["fen_before"]
    board = chess.Board(fen)
    mover = board.turn
    start = P.balance(board, mover)
    board.push(chess.Move.from_uci(pv[0]))
    try:
        reply = chess.Move.from_uci(pv[1])
    except ValueError:
        return None
    square = chess.parse_square(f.pieces[0].square)
    if reply not in board.legal_moves or not board.is_capture(reply) or \
            reply.to_square != square:
        return None
    later, _mated = _settled_after(fen, pv, mover, 3)
    if start - later >= PAWN:
        return "the engine's own reply takes the piece"
    return None


def best_mates_on_a_non_error(row) -> bool:
    """The ply's best move is a forced mate for the mover (stored `score_before_mate` > 0,
    any length) and the played move is not labelled an error. The condition of the
    narrowed AUDIT-Q5 ruling (owner, 2026-11-11), shared with `compose` for the
    engine-line material claim."""
    mate = row["score_before_mate"]
    return mate is not None and mate > 0 and row["classification"] not in ERROR_CLASSES


def description_silenced(descriptor, row) -> bool:
    """A king-ring description (D3, `Descriptor.KING_RING_ATTACKED`) where the best move is
    a forced mate for the mover and the played move is not labelled an error: owner ruling
    11, 2026-11-11 (FIXPLAN CLS-V3-11), the question AUDIT-Q5 narrowed left open. Beside a
    mate the comparison can read backwards — "after f3+, your pieces attack two squares
    next to White's king; after Bxd8, none", Bxd8 being mate in 6 (a stored
    ply). Same condition as `best_mates_on_a_non_error`."""
    from .findings import Descriptor
    return descriptor == Descriptor.KING_RING_ATTACKED and best_mates_on_a_non_error(row)


def description_on_an_error(descriptor, row) -> bool:
    """A D1 (castling rights) or D3 (king ring) description on a move labelled an error
    (`ERROR_CLASSES`): owner ruling T10, 2026-11-12 (FIXPLAN CLS-V3-T10). Under an error
    badge a reader takes the comparison as the reason for the error, and in about 13 of 20
    read it sat beside the real one (MECHANISMS_STAGE0 C; the owner's 9.Kd1, where the
    reason is the queen pinned by 9…Bg4). They still render on non-error moves; engine-line
    descriptions are not D1/D3 and are unaffected."""
    from .findings import Descriptor
    return descriptor in (Descriptor.CASTLING_RIGHTS, Descriptor.KING_RING_ATTACKED) and \
        row["classification"] in ERROR_CLASSES


def _row_get(row, key):
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return row[key] if key in keys else None


def _first_move_san(fen: str, line) -> str | None:
    ucis = line.get("uci") if line else None
    if not ucis:
        return None
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(ucis[0])
    except ValueError:
        return None
    return board.san(move) if move in board.legal_moves else None


def only_move_lines(row) -> tuple[dict, dict] | None:
    """The stored first and second lines of a critical-move miss (owner ruling T4,
    2026-11-12; FIXPLAN CLS-V3-T4), where the sentence may be said: the ply is labelled
    `miss`, its stored `hard_only_move` property (T8) is set, the played move is not the
    best, and the stored second line is at least `WPL_GREAT_GAP` worse than the first —
    the fact the sentence states, checked here on the lines it names."""
    from .classification import WPL_GREAT_GAP
    if row["classification"] != "miss" or not _row_get(row, "hard_only_move"):
        return None
    if not row["best_uci"] or row["best_uci"] == row["played_uci"]:
        return None
    lines = [ln for ln in _lines_of(row) if ln and ln.get("uci")]
    if len(lines) < 2 or lines[0]["uci"][0] != row["best_uci"]:
        return None
    if win_prob(lines[0].get("cp"), lines[0].get("mate")) - \
            win_prob(lines[1].get("cp"), lines[1].get("mate")) < WPL_GREAT_GAP:
        return None
    return lines[0], lines[1]


def _only_move_first(line: dict) -> str:
    mate, cp = line.get("mate"), line.get("cp")
    if mate is not None and mate > 0:
        return "kept the forced mate"
    if cp is not None and cp >= 100:
        return "kept the advantage"
    return "held the balance"


def _only_move_second(line: dict) -> str:
    """What the stored second line is, from the mover's side (T4: "adapt the second clause
    to what the second stored line actually is")."""
    mate, cp = line.get("mate"), line.get("cp")
    if mate is not None:
        return "allowed a forced mate" if mate <= 0 else "still mated"
    cp = cp or 0
    if cp >= 200:     # +2.00 or more is not "a small edge" (read in the T4 sample)
        return "kept a smaller advantage"
    if cp >= 100:
        return "kept only a small edge"
    if cp > -100:
        return "was level"
    if cp > -300:
        return "was worse"
    return "was losing"


def render_only_move(row) -> ClaimText | None:
    """Owner ruling T4 (2026-11-12): a critical-move miss shows the one fact the stored
    lines prove — "X was the only move that kept the advantage; the next best, Y, was
    level." — with both clauses read off the stored first and second lines. Approved as
    built (D5, 2026-11-13), with "the move played, Y, was the next best and …" where the
    stored next best is the move played. None where
    `only_move_lines` does not hold. Whether a claim or rule sentence already explains
    the move is `compose`'s question."""
    got = only_move_lines(row)
    if got is None:
        return None
    first, second = got
    fen = row["fen_before"]
    x, y = _first_move_san(fen, first), _first_move_san(fen, second)
    if x is None or y is None:
        return None
    if second["uci"][0] == row["played_uci"]:
        # D5 (owner, 2026-11-13): where the stored next best is the move played, say so —
        # the band is still read off the stored second line, and said only where the
        # move's own depth-14 after-score falls in the same band. Where they differ (5 of 67
        # on the owner's games, review/scratch/game_report_2/s/d5_check.out) the sentence is
        # not said: firing less, never rewording.
        band = _only_move_second(second)
        if band != _only_move_second({"cp": _row_get(row, "score_after_cp"),
                                      "mate": _row_get(row, "score_after_mate")}):
            return None
        return ClaimText(f"{x} was the only move that {_only_move_first(first)}; "
                         f"the move played, {y}, was the next best and {band}.")
    return ClaimText(f"{x} was the only move that {_only_move_first(first)}; "
                     f"the next best, {y}, {_only_move_second(second)}.")


def best_move_bookkeeping_beside_mate(f: Finding, row) -> str | None:
    """A material or motif sentence about the best move — `missed_material`,
    `best_defends_piece`, `best_saves_piece`, a motif on the best move — where the best
    move is a forced mate and the played move is not an error: "Rxe7 would have won the
    pawn on e7" when Rxe7 was mate in 4 and the move played still wins. The mate is why
    the move was best; the material is bookkeeping (owner ruling AUDIT-Q5, narrowed,
    2026-11-11).

    **Not on an error label.** There a mate longer than `MATE_CUTOFF` is cut as
    unfindable, and the material or motif sentence is the actionable account of what was
    missed — `one_sentence_per_move`'s recorded trade. The first form of the ruling
    silenced those too and was withdrawn for it."""
    if not (f.kind in BOOKKEEPING_KINDS or (f.kind in MOTIF_KINDS and f.subject == "best")):
        return None
    if best_mates_on_a_non_error(row):
        return "the best move mates by force and the played move is not an error"
    return None


# ── FIX-B9 (owner, 2026-11-27; EXPLANATIONS.md "FIX-B9"): sentences that say less ──────────────────────────────
#
# EXPLAIN-0's precision read (review/scratch/explain0/precision_marks.tsv) marked these misleading or false; each
# check silences a sentence, none adds one. Keyed cases: EXPLAIN-0 n=42, 45, 48, 49, 50 (S1), n=79 (S2), n=93 and
# n=95 (S3). S4 is in the rule itself (`explain._captures_out`), S5 in `render_pv_claim`.

def rescue_not_taken_in_reply(f: Finding, row, run: RunPlies | None) -> str | None:
    """S1: "Nc3 would have defended the pawn on d5" / "Ne7+ would have saved the knight" only where the played move's
    stored reply line (ply N+1's first stored line, the final lines on the last ply) takes that same piece: the
    played move, then that line, replayed from the position before the move, tracking the piece from where it stood
    (for `best_saves_piece`, the best move's origin; the finding carries where it would have gone), and the capture
    wins it (not a trade, at once or later in the line: n=49). With no stored
    reply line it is silent: nothing shows the piece was lost. A caller with no run (a constructed position) is not
    tested."""
    if f.kind not in RESCUE_KINDS or not f.pieces or run is None:
        return None
    move = lead_move(f)
    if move is None:
        return None
    square = move.uci[:2] if f.kind == "best_saves_piece" else f.pieces[0].square
    reply = _first_line(after_lines(run))
    if reply is None:
        return "no stored reply line to show the piece is taken"
    fen = row["fen_before"]
    w = _walk(fen, [row["played_uci"], *reply], chess.Board(fen).turn, square, 0)
    if w.captured_at is None:
        return "the played move's stored reply line never takes the piece"
    # "Takes" is a loss, not a trade: settled right after the capture (the mover's best recapture counted), the mover
    # is at least a pawn below both the balance before the played move and the balance just before the capture.
    # EXPLAIN-0 n=49: the bishop goes on c5 sixteen half-moves in, in an exchange of bishop for knight (the balance
    # before 12...Qxd4 is not lost). n=48 stays: 20.Nxc8 wins the bishop (...Rxc8 Qxc8), and ...Qxb4 gets a pawn back.
    if min(w.raw[0], w.raw[w.captured_at]) - w.settled[w.captured_at + 1] < PAWN:
        return "the played move's stored reply line takes the piece in a trade"
    return None


def missed_gain_not_kept(f: Finding, row) -> str | None:
    """S2: "Bxc6 would have won the knight" only where the named gain survives the recapture in the best line: in
    ply N's stored line (which starts with the best move), settled after the capture and the reply, the mover is up
    at least the named piece's value (a pawn's tolerance below it, `PAWN` / 2). EXPLAIN-0 n=79: Bxc6 bxc6 is a trade
    that nets a pawn (Qxc6), so the knight is not what is won. A line that mates for the mover there stands; with no
    stored line starting with the move it is not tested (as AUDIT-1's cases)."""
    if f.kind != "missed_material" or not f.pieces:
        return None
    best = lead_move(f)
    if best is None:
        return None
    pv = _first_line(_lines_of(row))
    if not pv or pv[0] != best.uci:
        return None
    from zugzwang.core import pv_reading as P
    fen = row["fen_before"]
    board = chess.Board(fen)
    mover = board.turn
    piece = chess.Piece.from_symbol(f.pieces[0].piece).piece_type
    kept, mated = _settled_after(fen, pv, mover, 2)
    if mated:
        return None
    if kept - P.balance(board, mover) < P.VALUE[piece] - PAWN / 2:
        return "the named gain does not survive the recapture in the best line"
    return None


def best_move_mate_not_lost(f: Finding, row) -> str | None:
    """S3: a walks-into-mate sentence on the stored best move (played == best) only where it says the position was
    lost either way (`QUAL_LOST`: the win probability before the move at most `LOST`), n=95's shape, which the owner
    accepted; otherwise silent (n=93's shape: "h6 allows a forced mate in 11" on the engine's own move, where the
    position was not lost before). `_stored_pairs` also drops such a sentence rendered without the clause."""
    if f.kind != "walks_into_mate" or not row["best_uci"] or row["best_uci"] != row["played_uci"]:
        return None
    cp, mate = row["score_before_cp"], row["score_before_mate"]
    if cp is None and mate is None:
        return "the stored best move, with no score to show the position was lost"
    if win_prob(cp, mate) > LOST:
        return "the stored best move, and the position was not lost either way"
    return None


def stored_lines_contradict(f: Finding, row, run: RunPlies | None, fix_b9: bool = True) -> str | None:
    """Why the run's stored data contradicts `f`'s sentence, by the audit rulings of
    2026-11-11 and FIX-B9's S1–S3 (2026-11-27), or None. Applied in `_stored_pairs` after the adjacent-ply check.
    `fix_b9=False` leaves S1–S3 out, for `silenced_by_fix_b9` alone."""
    return (missed_material_contradicted(f, row, run)
            or found_tactic_on_an_error(f, row)
            or motif_piece_does_not_fall(f, row, run)
            or rescue_taken_anyway(f, row)
            or best_move_bookkeeping_beside_mate(f, row)
            or (fix_b9 and (rescue_not_taken_in_reply(f, row, run)
                            or missed_gain_not_kept(f, row)
                            or best_move_mate_not_lost(f, row)))
            or None)


def chain_forms(findings: list[Finding], run: RunPlies | None) -> dict[tuple[str, str], str]:
    """How each `ignored_threat` on this ply renders: "full", "short" or "silent".

    A chain is the same piece on the same square named on one player's consecutive
    moves (plies two apart). It is broken by a ply the run does not have, and by one
    in `SILENT_CLASSES`, where nothing was said. A link whose ply `mate_leads` stays
    in the chain but says nothing, so it cannot be the head — the short form must
    never follow a full sentence that did not render.

    The head is the first sayable link on a move in `ERROR_CLASSES`, else the first
    sayable link. It gets the full sentence; the next link gets the short form; the
    rest — links before the head included — say nothing. Before the head there is
    nothing yet for "still hanging" to refer to, and the full sentence belongs where
    the lesson is.

    Neighbouring plies are explained only when this one has an `ignored_threat`, so a
    ply without the kind costs nothing.
    """
    keys = _ignored_keys(findings)
    if not keys or run is None:
        return {}
    seen: dict[int, tuple | None] = {run.ply: (keys, mate_leads(findings))}

    def at(ply: int) -> tuple | None:
        if ply not in seen:
            row = run.rows.get(ply)
            if row is None or row["classification"] in SILENT_CLASSES:
                seen[ply] = None
            else:
                at_ply = replace(run, ply=ply)
                fs = explain_stored_ply(row, deep=deep_of(at_ply),
                                        refutation=refutation_of(at_ply))
                seen[ply] = (_ignored_keys(fs), mate_leads(fs))
        return seen[ply]

    forms: dict[tuple[str, str], str] = {}
    for key in keys:
        links = [run.ply]
        for step in (-2, 2):
            ply = run.ply + step
            while len(links) < 2 * CHAIN_REACH + 1:
                info = at(ply)
                if info is None or key not in info[0]:
                    break
                links.append(ply)
                ply += step
        links.sort()
        sayable = [p for p in links if not seen[p][1]]
        errors = [p for p in sayable if run.rows[p]["classification"] in ERROR_CLASSES]
        head = errors[0] if errors else sayable[0] if sayable else None
        if head == run.ply:
            forms[key] = "full"
        elif head is not None and head < run.ply and links[links.index(head) + 1] == run.ply:
            # The short form refers back to the head's sentence, so it needs that sentence
            # to be on screen (owner ruling AUDIT-7, 2026-11-11). Where it is not — the
            # adjacent-ply check silenced it, or the callout shows an engine-line claim in
            # its place — this link says it in full. This link's own finding has already
            # passed the adjacent-ply check, so the full sentence is one the check allows.
            forms[key] = "short" if _head_visible(run, head, key) else "full"
        else:
            forms[key] = "silent"
    return forms


def _head_visible(run: RunPlies, head: int, key: tuple[str, str]) -> bool:
    """Whether the chain head's full `ignored_threat` sentence about `key` (square, piece)
    is what the Review callout shows at `head`. It is rendered by the same path as any
    ply (adjacent-ply check, audit rulings, dedupe, cap); the head is its chain's head
    from its own ply too, so this does not recurse further."""
    if run.engine_claim is not None and run.engine_claim(head):
        return False
    _f, pairs = _stored_pairs(run.rows[head], None, CAP, replace(run, ply=head))
    return any(
        f.kind == "ignored_threat" and f.pattern != PATTERN_STILL_HANGING
        and key in {(p.square, p.piece) for p in f.pieces}
        for f, _line in pairs)


def _apply_forms(findings: list[Finding], forms) -> list[Finding]:
    """Drop the silent links and an `ignored_threat` beside a leading mate; mark the
    short ones."""
    leads = mate_leads(findings)
    out = []
    for f in findings:
        if f.kind == "ignored_threat":
            if leads:
                continue
            form = forms.get((f.pieces[0].square, f.pieces[0].piece), "full") if (
                forms and f.pieces) else "full"
            if form == "silent":
                continue
            if form == "short":
                f = replace(f, pattern=PATTERN_STILL_HANGING)
        out.append(f)
    return out


def describe_ply(
    fen: str,
    findings: list[Finding],
    classification: str | None = None,
    p_before: float | None = None,
    cap: int = CAP,
    voice: Voice = SECOND_PERSON,
    loss: float | None = None,
    forms=None,
) -> list[str]:
    """Findings for one ply, as up to `cap` sentences in display order.

    **At most one qualifier per block.** The dedupe keys on the move a sentence
    names, so two sentences about two different moves each earn the reframe
    independently and the block says "though the position was lost either way"
    twice. It is a fact about the position, not about either move, so the first
    sentence carries it and the rest are rendered without it.

    Whether a rendered line ended up carrying one is decided by asking `qualifier`
    the same question `render` asked it, rather than by matching against a list of
    qualifier strings. The strings are now templates over `Voice`, so a list of them
    would have to be re-inflected here — one distinction spelled in two places, and
    the second spelling is the one that drifts.
    """
    return [line for _f, line in describe_ply_pairs(
        fen, findings, classification, p_before, cap=cap, voice=voice, loss=loss,
        forms=forms)]


def describe_ply_pairs(
    fen: str,
    findings: list[Finding],
    classification: str | None = None,
    p_before: float | None = None,
    cap: int = CAP,
    voice: Voice = SECOND_PERSON,
    loss: float | None = None,
    forms=None,
) -> list[tuple[Finding, str]]:
    """`describe_ply`, keeping each sentence's finding: only findings that actually
    render, so a caller counting them (the game report's repeated-pattern line)
    counts what the user can see, not what the rules found and policy suppressed.

    `forms` is `chain_forms` for this ply; omitted, every `ignored_threat` renders in
    full. An `ignored_threat` beside a leading mate never renders (`mate_leads`)."""
    out: list[tuple[Finding, str]] = []
    qualified = False
    for f in one_sentence_per_move(rank_findings(_apply_forms(findings, forms))):
        line = render(
            f, fen, classification, p_before,
            qualify=not qualified, voice=voice, loss=loss,
        )
        if line is not None:
            if not qualified:
                qual = qualifier(f, p_before, is_conditional(f), voice)
                qualified = bool(qual) and qual in line
            out.append((f, line))
        if len(out) >= cap:
            break
    return out


def explain_and_describe_stored_ply(
    row, player_color: str | None, cap: int = CAP, *, run: RunPlies | None = None
) -> tuple[list[Finding], list[str]]:
    """Findings *and* sentences for a ply already in `move_analyses`. The entry point.

    Anything reading the database goes through here, so there is one call with one
    set of arguments — see `explain_stored_ply` for why that matters. A caller that
    wants both must not run the rules twice, and must not derive `p_before` itself:
    `win_prob` on the wrong score is a silent wrong reframe, not an error.

    `player_color` is positional and required for the same reason. It is the user's
    colour from the `games` row, and the row passed here carries no colour of its
    own, so a default would let a caller that has the game in hand forget to say
    whose move it is — which is exactly the bug `voice_for` exists to fix.

    `run` is the rest of the game (`RunPlies`), so a piece left loose move after move
    is named in full once — where the lesson is — then as "still hanging", then not
    at all. Omitted, each ply is read alone, which is right only for a caller that
    genuinely has one ply.
    """
    findings, pairs = _stored_pairs(row, player_color, cap, run)
    return findings, [line for _f, line in pairs]


def rendered_pairs_stored_ply(
    row, player_color: str | None, *, run: RunPlies | None = None
) -> list[tuple[Finding, str]]:
    """Each sentence a stored ply renders, with the finding behind it — what the user
    sees, by the same single path as `explain_and_describe_stored_ply`. The game report
    takes a card's sentences and its countable findings from one call of this."""
    return _stored_pairs(row, player_color, CAP, run)[1]


def refutation_of(run: RunPlies | None) -> tuple[str, ...]:
    """`explain.refutation_after` for the ply `run` is at (L1). () without a run."""
    if run is None:
        return ()
    return refutation_after(run.rows.get(run.ply + 1), run.final_lines)


def deep_of(run: RunPlies | None) -> tuple[bool, int | None]:
    """`explain.deep_after` for the ply `run` is at: ply N+1's stored row, or the run's
    final lines on the last ply. `(False, None)` without a run."""
    if run is None:
        return False, None
    return deep_after(run.rows.get(run.ply + 1), run.final_lines)


def silenced_by_fix_b9(row, player_color: str | None, cap: int = CAP, *, run: RunPlies | None = None) -> bool:
    """True where the ply would show a rule sentence but for FIX-B9's checks S1–S3. Only meaningful where the ply shows
    none: `compose` then keeps the slot empty, so nothing the fixes silenced is replaced by a description or the
    only-move line (FIX-B9: the fixes make the app say less; 10 descriptions appeared on the copy without this)."""
    return bool(_stored_pairs(row, player_color, cap, run, fix_b9=False)[1])


def _stored_pairs(
    row, player_color: str | None, cap: int, run: RunPlies | None = None, fix_b9: bool = True
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    # The mate rules read the deeper stored search after the move where there is one
    # (owner rulings AUDIT-4, -5, -13, 2026-11-11).
    findings = explain_stored_ply(row, deep=deep_of(run), refutation=refutation_of(run))
    if run is not None:
        # The adjacent-ply check: a capture claim ply N+1 contradicts stays silent.
        findings = [f for f in findings if next_ply_contradicts(f, run) is None]
    # The audit rulings (2026-11-11): what the stored lines contradict stays silent.
    findings = [f for f in findings if stored_lines_contradict(f, row, run, fix_b9) is None]
    findings = [g for g in (forced_clause(f, row) for f in findings) if g is not None]
    cp, mate = row["score_before_cp"], row["score_before_mate"]
    acp, am = row["score_after_cp"], row["score_after_mate"]
    has_before = cp is not None or mate is not None
    has_after = acp is not None or am is not None
    p_before = win_prob(cp, mate) if has_before else None
    # Both halves required: `wpl` would read a missing score as dead equal, and a
    # fabricated zero loss is exactly what `compensated` must not be handed.
    loss = wpl(cp, mate, acp, am) if has_before and has_after else None
    fen = row["fen_before"]
    pairs = describe_ply_pairs(
        fen,
        findings,
        row["classification"],
        p_before,
        cap=cap,
        voice=voice_for(fen, player_color),
        loss=loss,
        forms=chain_forms(findings, run),
    )
    if fix_b9 and row["best_uci"] and row["best_uci"] == row["played_uci"]:
        # S3 (FIX-B9): on the stored best move a walks-into-mate sentence shows only with its "lost either way" clause,
        # which `describe_ply_pairs` gives the first qualified sentence alone.
        pairs = [(f, s) for f, s in pairs if f.kind != "walks_into_mate" or QUAL_LOST in s]
    return findings, pairs


def describe_stored_ply(
    row, player_color: str | None, cap: int = CAP, *, run: RunPlies | None = None
) -> list[str]:
    """Just the sentences, for callers that do not need the findings."""
    return explain_and_describe_stored_ply(row, player_color, cap=cap, run=run)[1]


# ── Stage 2: claims from the engine's line (ProvenClaim → ClaimText) ─────────
#
# Owner rulings, 2026-11-08 (third): a forcing engine line that passed gate P is a claim
# and may say what it does; a non-forcing one is a Description (describe.py) and may not.
# The sentence stops at the move the gain is held from, or the mate.

class ClaimText(str):
    """A rendered claim. Not a `DescriptionText`, and never compares as one's type."""

    __slots__ = ()


_PIECE_WORD = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen"}
_COUNT_WORD = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def piece_list(pieces, definite: bool = False) -> str:
    """("r", "p") → "a rook and a pawn"; ("p", "p") → "two pawns"; ("b",) with
    `definite` → "the bishop". Largest first, as `pv_reading.net_pieces` orders them."""
    from collections import Counter
    counts = Counter(pieces)
    parts = []
    for letter in "qrbnp":
        n = counts.get(letter, 0)
        if not n:
            continue
        word = _PIECE_WORD[letter]
        if n == 1:
            parts.append(f"{'the' if definite and len(pieces) == 1 else 'a'} {word}")
        else:
            parts.append(f"{_COUNT_WORD.get(n, str(n))} {word}s")
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def material_phrase(took, gave) -> str:
    """"a rook and a pawn for the bishop" / "a pawn"."""
    phrase = piece_list(took)
    return f"{phrase} for {piece_list(gave, definite=True)}" if gave else phrase


def _numbered_line(fen: str, ucis) -> str:
    import chess
    board = chess.Board(fen)
    out = []
    for i, u in enumerate(ucis):
        m = chess.Move.from_uci(u)
        san = board.san(m)
        n = board.fullmove_number
        out.append(f"{n}.{san}" if board.turn == chess.WHITE else
                   (f"{n}...{san}" if i == 0 else san))
        board.push(m)
    return " ".join(out)


def _last_move_number(fen: str, ucis) -> int:
    import chess
    board = chess.Board(fen)
    n = board.fullmove_number
    for u in ucis:
        n = board.fullmove_number
        board.push_uci(u)
    return n


def render_pv_claim(claim, *, fen_before: str, best_san: str,
                    player_color: str | None) -> ClaimText:
    """One `ProvenClaim` (findings.py) as one sentence. Material is named in pieces,
    from the line's own captures; a move not played takes "would have"; a line longer than
    `config.PV_PRINT_MAX_PLIES` is summarised by the move it reaches rather than printed. No "by force" (S5, FIX-B9,
    owner 2026-11-27): the words stood for the proof and read as more than the line shows; D8's wording ("in the
    engine's line") waits for EXPLAIN-1."""
    from zugzwang import config as C
    from zugzwang.core.findings import ProvenClaim
    assert isinstance(claim, ProvenClaim)
    p = claim.proof
    short = len(p.line) <= C.PV_PRINT_MAX_PLIES
    # Long lines: "by move 40" (was "by move 40, by force", owner 2026-11-08; S5 dropped "by force", 2026-11-27).
    by = "" if short else f" by move {_last_move_number(p.start_fen, p.line)}"
    tail = f": {_numbered_line(p.start_fen, p.line)}." if short else f"{by}."
    mate_tail = f": {_numbered_line(p.start_fen, p.line)}." if short else f"{by}."
    what = material_phrase(claim.took, claim.gave)
    if claim.subject == "played":
        v = voice_for(fen_before, player_color)
        opp_white = fen_before.split(" ")[1] != "w"
        user = player_color if player_color in ("white", "black") else None
        opp = ("you" if user == ("white" if opp_white else "black")
               else ("White" if opp_white else "Black"))
        if claim.kind == "line_mates":
            return ClaimText(f"{v.subject} allows a forced mate{mate_tail}")
        return ClaimText(f"{v.subject} allows {opp} to win {what}{tail}")
    if claim.kind == "line_mates":
        return ClaimText(f"{best_san} would have forced mate{mate_tail}")
    return ClaimText(f"{best_san} would have won {what}{tail}")
