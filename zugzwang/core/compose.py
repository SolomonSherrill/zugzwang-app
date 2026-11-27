"""Layer 4 of ANALYSIS_ARCHITECTURE.md §2: the one place claims and descriptions meet.

`explain_ply_full` returns them **side by side and never joined**: today's rule sentences
(unchanged), the stage-2 engine-line claim, and the descriptions, as separate fields, so
the RPC can carry them in separate arrays and the screen render them under separate
headings. It is the only module allowed to import both renderers (a test enforces it).

First form, minimal (owner, 2026-11-08, third rulings: "wire it up minimally"):

- **claims** (`shown_claims`) = the PV claim (`pv_reading.gate_p` → `ProvenClaim`) where
  there is one — **reversed precedence, owner 2026-11-09**: it is shown instead of the
  rule sentences (provisional where the two are about different moves or kinds) — else
  the rule layer's sentences, after the adjacent-ply check. `sentences` stays the rule
  layer's own output, unchanged.
- **mechanism names** (MECH-NAME, owner 2026-11-14; P1 2026-11-19 adds pin and skewer): back rank, discovered attack/check, pin, skewer,
  appended as a clause to the engine-line claim's own sentence (`mechanisms.with_name`) where
  its printed line shows them; never on a summarised claim, never alone.
- **descriptions** = the PV description (a non-forcing engine line, same condition), then
  D1 / D3 (`describe.describe`, through `GameMemory` over the game so far), at most
  `describe.MAX_DESCRIPTIONS` — and **only on a ply where no rule sentence and no
  engine-line claim rendered** (owner, 2026-11-08, seventh round).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import chess

from zugzwang.core import describe as D
from zugzwang.core import mechanisms as M
from zugzwang.core import pv_reading as P
from zugzwang.core.explain_text import (
    ClaimText,
    RunPlies,
    best_mates_on_a_non_error,
    description_on_an_error,
    description_silenced,
    explain_and_describe_stored_ply,
    render_only_move,
    render_pv_claim,
    silenced_by_fix_b9,
)
from zugzwang.core.findings import Description, ProvenClaim
from zugzwang.core.labelling import captured_on_next_move


@dataclass(frozen=True)
class PlyExplanation:
    findings: list                                   # the rule layer's, unchanged
    sentences: list[str]                             # the rule layer's, unchanged
    pv_claims: tuple[ClaimText, ...] = ()
    # What the screen's claims list shows: the engine-line claim where there is one
    # (reversed precedence), else the rule sentences. (source, text).
    shown_claims: tuple[tuple[str, str], ...] = ()
    pv_claim_line: tuple[str, ...] = ()              # the proof's UCI line, for the wire
    descriptions: tuple[tuple[str, D.DescriptionText], ...] = ()   # (descriptor, text)
    best_san: str | None = None
    notes: dict = field(default_factory=dict)        # e.g. why the PV reading was silent


def _san(fen: str, uci: str | None) -> str | None:
    if not uci:
        return None
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    return board.san(move) if move in board.legal_moves else None


def _engine_line(rows: Mapping[int, Mapping], ply: int,
                 final_lines: list[dict] | None) -> ProvenClaim | Description | None:
    """`pv_reading.gate_p` for one stored ply."""
    row = rows[ply]
    nxt = rows.get(ply + 1)
    refutation = (nxt["pv_uci"] or "").split() if nxt is not None else \
        (final_lines[0]["uci"] if final_lines else [])
    rd = P.read_ply(row["fen_before"], row["played_uci"], (row["pv_uci"] or "").split(),
                    refutation)
    return P.gate_p(row["fen_before"], rd, score_before_cp=row["score_before_cp"],
                    score_before_mate=row["score_before_mate"],
                    score_after_cp=row["score_after_cp"],
                    score_after_mate=row["score_after_mate"])


def taken_next_move(rows: Mapping[int, Mapping], ply: int, claim: ProvenClaim) -> bool:
    """An engine-line claim about the best move ("dxc6 would have won a bishop by force:
    6...dxc6") where the player captured that same piece, on that square, on their very
    next move in the game: the material was not missed, only delayed (owner ruling
    AUDIT-Q2, 2026-11-11; the rule-layer twin is AUDIT-1 (c))."""
    if claim.subject != "best" or not claim.proof.line:
        return False
    row, later_row = rows[ply], rows.get(ply + 2)
    if later_row is None:
        return False
    # One board test for the card and the label (J1, `labelling.delayed_not_missed`).
    return captured_on_next_move(row["fen_before"], claim.proof.line[0],
                                 later_row["fen_before"], later_row["played_uci"])


def _engine_output(rows: Mapping[int, Mapping], ply: int,
                   final_lines: list[dict] | None) -> ProvenClaim | Description | None:
    """`_engine_line`, less the claims the audit rulings silence: what the screen may show
    from the engine's line at this ply. Every reader of the precedence goes through here."""
    out = _engine_line(rows, ply, final_lines)
    if isinstance(out, ProvenClaim) and taken_next_move(rows, ply, out):
        return None
    # A material claim about the best move where that move mates by force and the played
    # move is not an error: bookkeeping beside the mate (AUDIT-Q5, narrowed, 2026-11-11).
    if isinstance(out, ProvenClaim) and out.subject == "best" and \
            out.kind == "line_wins_material" and best_mates_on_a_non_error(rows[ply]):
        return None
    return out


def _diverges(row: Mapping) -> bool:
    return bool(row["best_uci"]) and row["best_uci"] != row["played_uci"] \
        and _san(row["fen_before"], row["best_uci"]) is not None


def run_plies(rows: Mapping[int, Mapping], ply: int,
              final_lines: list[dict] | None) -> RunPlies:
    """The run as the rule layer sees it, knowing which plies' rule sentences the callout
    replaces with an engine-line claim (the reversed precedence below) — so a sentence that
    refers back to an earlier one ("is still hanging") can tell whether that one was on
    screen (AUDIT-7)."""
    cache: dict[int, bool] = {}

    def engine_claim(p: int) -> bool:
        if p not in cache:
            cache[p] = p in rows and _diverges(rows[p]) and \
                isinstance(_engine_output(rows, p, final_lines), ProvenClaim)
        return cache[p]
    return RunPlies(dict(rows), ply, tuple(final_lines or ()), engine_claim=engine_claim)


def _hidden(descriptor, row) -> bool:
    """A D1/D3 description the screen does not show at its ply: ruling 11 (king ring beside a
    forced mate on a non-error move) or T10 (any D1/D3 on a move labelled an error). Not
    shown, so never committed to the game memory as said."""
    return description_silenced(descriptor, row) or description_on_an_error(descriptor, row)


def _shown_at(rows: Mapping[int, Mapping], ply: int, player_color: str | None,
              final_lines: list[dict] | None, candidates: list[Description]) -> list[Description]:
    """Which of `candidates` (D1/D3 at an earlier ply) the screen showed there: none
    beside a rule sentence or an engine-line claim, and no more than the cap leaves
    beside an engine-line description. Only computed for plies with candidates."""
    candidates = [d for d in candidates if not _hidden(d.descriptor, rows[ply])]
    if not candidates or not _diverges(rows[ply]):
        return []
    run = run_plies(rows, ply, final_lines)
    _, sentences = explain_and_describe_stored_ply(rows[ply], player_color, run=run)
    if sentences or silenced_by_fix_b9(rows[ply], player_color, run=run):
        return []
    out = _engine_output(rows, ply, final_lines)
    if isinstance(out, ProvenClaim):
        return []
    room = D.MAX_DESCRIPTIONS - (1 if isinstance(out, Description) else 0)
    return candidates[:room]


def explain_ply_full(rows: Mapping[int, Mapping], ply: int, player_color: str | None,
                     final_lines: list[dict] | None = None) -> PlyExplanation:
    """`rows`: the run's plies by ply, each a mapping with `explain.STORED_PLY_COLUMNS`
    plus `pv_uci`. `final_lines`: the run's `final_lines_json`, for the last ply."""
    row = rows[ply]
    findings, sentences = explain_and_describe_stored_ply(
        row, player_color, run=run_plies(rows, ply, final_lines))
    fen = row["fen_before"]
    played, best = row["played_uci"], row["best_uci"]
    best_san = _san(fen, best)
    played_san = _san(fen, played) or played

    pv_claims: list[ClaimText] = []
    pv_line: tuple[str, ...] = ()
    descs: list[tuple[str, D.DescriptionText]] = []
    notes: dict = {}
    if best and best != played and best_san:
        out = _engine_output(rows, ply, final_lines)
        if isinstance(out, ProvenClaim):
            # Reversed precedence (owner, 2026-11-09): where a surviving rule sentence
            # and an engine-line claim both exist, the engine-line claim is shown.
            # PROVISIONAL for the plies where they are about different moves or kinds,
            # pending the owner's reading of review/samples/precedence-complementary.md.
            text = render_pv_claim(out, fen_before=fen, best_san=best_san,
                                   player_color=player_color)
            # MECH-NAME (owner rulings M1–M7, 2026-11-14): the mechanism, named only inside
            # the claim's own printed line, as a clause after it. Never a claim of its own.
            name = M.name_claim(out)
            if name is not None:
                text = ClaimText(M.with_name(text, name))
                notes["mechanism"] = name.mechanism
            pv_claims.append(text)
            pv_line = out.proof.line
            if sentences:
                notes["precedence"] = "engine line over the rule sentences (provisional)"
        elif isinstance(out, Description):
            if sentences:
                notes["pv"] = "rules spoke"          # a description yields to a claim
            else:
                descs.append((out.descriptor.value, D.render(
                    out, fen_before=fen, played_san=played_san, best_san=best_san,
                    player_color=player_color)))

        # D1 / D3, with the game memory run over the game up to this ply.
        memory = D.GameMemory()
        kept: list[Description] = []
        for p in sorted(rows):
            if p > ply:
                break
            r = rows[p]
            got = memory.peek(D.describe(r["fen_before"], r["played_uci"], r["best_uci"]))
            if p == ply:
                # Ruling 11 (CLS-V3-11): no king-ring description beside a forced mate on
                # a non-error move. Not shown, so not committed to the game memory either.
                # T10 (CLS-V3-T10): nor any D1/D3 on a move labelled an error.
                kept = [d for d in got if not _hidden(d.descriptor, r)]
            else:
                # Only what the screen showed counts as said (owner, 2026-11-08): one
                # suppressed beside a claim stays eligible at its next firing.
                memory.commit(_shown_at(rows, p, player_color, final_lines, got))
        for d in kept:
            descs.append((d.descriptor.value, D.render(
                d, fen_before=fen, played_san=played_san, best_san=best_san,
                player_color=player_color)))
        # Owner, 2026-11-08 (seventh): descriptions render only where no rule sentence
        # and no engine-line claim did. Beside a claim they are filler; the ply is
        # covered either way, so this costs no coverage. A description suppressed here
        # is not "said": the game memory above commits only what an earlier ply showed.
        if sentences or pv_claims:
            if descs:
                notes["descriptions"] = "suppressed beside a claim"
            descs = []
        elif descs and silenced_by_fix_b9(row, player_color, run=run_plies(rows, ply, final_lines)):
            # FIX-B9 (owner, 2026-11-27): a sentence S1–S3 silenced leaves the ply as it was, not a description
            notes["descriptions"] = "suppressed where a FIX-B9 check silenced the rule sentence"
            descs = []
    shown = tuple(("engine_line", str(t)) for t in pv_claims) if pv_claims else \
        tuple(("rules", t) for t in sentences)
    if not shown:
        # T4 (CLS-V3-T4, 2026-11-12): a critical-move miss with nothing else to say shows
        # the one fact the stored lines prove — never beside a claim or a rule sentence
        # (nor where a FIX-B9 check silenced one).
        only = render_only_move(row)
        if only is not None and not silenced_by_fix_b9(row, player_color, run=run_plies(rows, ply, final_lines)):
            shown = (("only_move", str(only)),)
    return PlyExplanation(
        findings=findings, sentences=sentences, pv_claims=tuple(pv_claims),
        shown_claims=shown,
        pv_claim_line=pv_line, descriptions=tuple(descs[:D.MAX_DESCRIPTIONS]),
        best_san=best_san, notes=notes)
