"""
Opening book and ECO name lookup. No Qt dependencies.

OpeningsBook:
  - Reads book_mingame3.bin (Polyglot format) for book-move detection.
  - Reads lichess-org ECO TSVs to build a {epd: (eco, name)} map.
  - Degrades silently when assets are missing.
"""

from __future__ import annotations

import csv
import logging
import io
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.pgn
import chess.polyglot

import zugzwang.config as C

logger = logging.getLogger(__name__)


@dataclass
class FamilyInfo:
    """One opening family for the trainer lobby (name-prefix grouped)."""
    name: str                                   # canonical family name
    eco_lo: str
    eco_hi: str
    first_move: str                             # 'e4' | 'd4' | 'other'
    total_weight: int                           # popularity (sum of line weights)
    threshold: int                              # weight floor used (0 if limited)
    available: bool                             # trainable, or gated "limited coverage"
    line_count: int                             # curated lines at the chosen floor
    sample_moves: str                           # SAN of the top line (for move search)
    lines: list[tuple[str, str, str, str]] = field(default_factory=list)  # (eco,name,fen,pgn)


class OpeningsBook:
    def __init__(
        self,
        book_path: Path = C.OPENINGS_BOOK_PATH,
        eco_dir: Path = C.OPENINGS_ECO_DIR,
    ) -> None:
        self._reader: chess.polyglot.MemoryMappedReader | None = None
        self._eco: dict[str, tuple[str, str]] = {}
        self._entries: list[tuple[str, str, str, str]] = []   # (eco, name, starting_fen, starting_pgn)
        self._family_index: list[FamilyInfo] | None = None

        if book_path.exists():
            try:
                self._reader = chess.polyglot.open_reader(str(book_path))
                logger.info("Opening book loaded: %s", book_path)
            except Exception as exc:
                logger.warning("Could not load opening book: %s", exc)
        else:
            logger.warning("Opening book not found at %s — book classification disabled", book_path)

        if eco_dir.exists():
            self._eco, self._entries = _load_eco(eco_dir)
            logger.info(
                "ECO openings loaded: %d positions, %d entries",
                len(self._eco), len(self._entries),
            )
        else:
            logger.info("ECO directory not found at %s — opening names disabled", eco_dir)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def reader(self) -> chess.polyglot.MemoryMappedReader | None:
        """Raw Polyglot reader; None when the book file is absent."""
        return self._reader

    @property
    def has_book(self) -> bool:
        """Whether a Polyglot book actually loaded.

        Worth asking directly, because the no-book state is otherwise invisible:
        `build_family_index` falls back to weight 1 for every line, both curation
        floors then reject everything, and the trainer lobby renders a full list
        of families with nothing trainable and no stated reason. Callers that
        show that list should say *why* it is empty rather than let the user
        infer it.
        """
        return self._reader is not None

    def entries(self) -> list[tuple[str, str, str, str]]:
        """All ECO entries as (eco, name, starting_fen, starting_pgn). Used by the trainer lobby."""
        return self._entries

    def is_book_move(self, board: chess.Board, move: chess.Move) -> bool:
        """True if the move appears in the Polyglot book for this position."""
        if self._reader is None:
            return False
        try:
            for entry in self._reader.find_all(board):
                if entry.move == move:
                    return True
        except Exception:
            pass
        return False

    def book_moves(self, board: chess.Board) -> list[chess.Move]:
        """All book moves for the current position, or [] if none / no book."""
        if self._reader is None:
            return []
        try:
            return [e.move for e in self._reader.find_all(board)]
        except Exception:
            return []

    def book_moves_by_weight(self, board: chess.Board) -> list[chess.Move]:
        """Book moves for the position, most-played first. `find_all` yields in file
        order, and the Polyglot convention of weight-descending entries per key is a
        convention, not a guarantee, so the order is imposed here."""
        if self._reader is None:
            return []
        try:
            entries = sorted(self._reader.find_all(board), key=lambda e: -e.weight)
        except Exception:
            return []
        return [e.move for e in entries]

    def name_after(self, board: chess.Board) -> tuple[str, str] | None:
        """
        Returns (eco, name) if this position is a named opening node, else None.
        The caller should keep the last non-None value to show a persistent label.
        """
        if not self._eco:
            return None
        epd = _board_epd(board)
        return self._eco.get(epd)

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def curated_family_lines(
        self,
        eco_lo: str,
        eco_hi: str,
        target_lines: int = C.TRAINER_CURATION_TARGET_LINES,
    ) -> list[tuple[str, str, str, str]]:
        """
        Return curated (eco, name, fen, pgn) tuples for the ECO range.
        Uses first-occurrence (shallowest) semantics and auto-tunes the
        book-weight threshold to produce ~target_lines entries.
        """
        return curate_family(
            self._reader,
            C.OPENINGS_ECO_DIR,
            eco_lo,
            eco_hi,
            target_lines=target_lines,
        )

    def family_index(self) -> list[FamilyInfo]:
        """Full name-grouped family list for the trainer lobby (memoized).

        Every opening the book meaningfully covers, grouped by top-level family
        name, each curated with adaptive coverage thresholds. Sorted by
        popularity (total book weight) descending.
        """
        if self._family_index is None:
            self._family_index = build_family_index(self._reader, C.OPENINGS_ECO_DIR)
        return self._family_index


# ── ECO loading ───────────────────────────────────────────────────────────────

def _board_epd(board: chess.Board) -> str:
    """Position identifier without move-counters so transpositions match."""
    return board.epd()


def _load_eco(
    eco_dir: Path,
) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str, str, str]]]:
    eco_map: dict[str, tuple[str, str]] = {}
    # (eco, name) → (starting_fen, starting_pgn); dedup by (eco, name) keeping last-seen
    entries_map: dict[tuple[str, str], tuple[str, str]] = {}
    for tsv_path in sorted(eco_dir.glob("*.tsv")):
        try:
            _parse_tsv(tsv_path, eco_map, entries_map)
        except Exception as exc:
            logger.warning("Could not parse ECO file %s: %s", tsv_path, exc)
    entries = [(eco, name, fen, pgn) for (eco, name), (fen, pgn) in entries_map.items()]
    return eco_map, entries


def _parse_tsv(
    path: Path,
    out: dict[str, tuple[str, str]],
    entries_map: dict[tuple[str, str], tuple[str, str]],
) -> None:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            eco = row.get("eco", "").strip()
            name = row.get("name", "").strip()
            pgn_text = row.get("pgn", "").strip()
            if not (eco and name and pgn_text):
                continue
            board = _replay_pgn(pgn_text)
            if board is None:
                continue
            epd = _board_epd(board)
            # Later rows (more specific lines) override earlier ones
            out[epd] = (eco, name)
            entries_map[(eco, name)] = (board.fen(), pgn_text)


def _replay_pgn(pgn_text: str) -> chess.Board | None:
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return None
        board = game.board()
        for move in game.mainline_moves():
            board.push(move)
        return board
    except Exception:
        return None


def _parse_pgn_to_moves_and_fen(pgn_text: str) -> tuple[list[str], str] | None:
    """Return (list of UCI strings, final FEN) or None on parse error."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return None
        board = game.board()
        moves: list[str] = []
        for mv in game.mainline_moves():
            moves.append(mv.uci())
            board.push(mv)
        return moves, board.fen()
    except Exception:
        return None


def curate_family(
    reader: "chess.polyglot.MemoryMappedReader | None",
    eco_dir: Path,
    eco_lo: str,
    eco_hi: str,
    target_lines: int = C.TRAINER_CURATION_TARGET_LINES,
    depth_min: int = C.TRAINER_CURATION_DEPTH_MIN,
    depth_max: int = C.TRAINER_CURATION_DEPTH_MAX,
) -> list[tuple[str, str, str, str]]:
    """
    Build a curated list of opening lines for the ECO range [eco_lo, eco_hi].

    Returns (eco, name, fen, pgn) sorted by book weight descending.

    Algorithm:
      1. Load TSV rows with first-occurrence semantics (shallowest position per
         (eco, name) — better training entry points than last-wins).
      2. Parse + compute book weight at the terminal position.
      3. Same-name dedup: keep the highest-weight entry per name.
      4. Depth filter: keep depth_min <= len(moves) <= depth_max.
      5. Auto-tune a weight threshold via binary search toward target_lines,
         then apply prefix-dedup (drop an entry if a higher-weight entry's
         move sequence is a strict extension of it).
    """
    # Step 1: first-occurrence per (eco, name) for the ECO range
    seen: dict[tuple[str, str], str] = {}
    for tsv_path in sorted(eco_dir.glob("*.tsv")):
        try:
            with tsv_path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    eco  = row.get("eco",  "").strip()
                    name = row.get("name", "").strip()
                    pgn  = row.get("pgn",  "").strip()
                    if not (eco and name and pgn):
                        continue
                    if not (eco_lo <= eco <= eco_hi):
                        continue
                    if (eco, name) not in seen:
                        seen[(eco, name)] = pgn
        except Exception as exc:
            logger.warning("curate_family: could not read %s: %s", tsv_path, exc)

    # Step 2: parse + compute weights
    _Entry = tuple  # (eco, name, pgn, fen, weight, depth, uci_moves)
    raw: list[_Entry] = []
    for (eco, name), pgn in seen.items():
        result = _parse_pgn_to_moves_and_fen(pgn)
        if result is None:
            continue
        moves, fen = result
        depth = len(moves)
        if not (depth_min <= depth <= depth_max):
            continue
        if reader is not None:
            try:
                board = chess.Board(fen)
                w = sum(e.weight for e in reader.find_all(board))
            except Exception:
                w = 0
        else:
            w = 1
        raw.append((eco, name, pgn, fen, w, depth, moves))

    if not raw:
        return []

    # Step 3: same-name dedup — keep the highest-weight entry per name
    by_name: dict[str, _Entry] = {}
    for rec in raw:
        n = rec[1]
        if n not in by_name or rec[4] > by_name[n][4]:
            by_name[n] = rec
    raw = list(by_name.values())

    if reader is None:
        # No book: return depth-filtered entries sorted by name
        return [
            (eco, name, fen, pgn)
            for eco, name, pgn, fen, _, _, _ in sorted(raw, key=lambda r: r[1])
        ][:target_lines]

    def _apply_dedup(min_w: int) -> list[_Entry]:
        cands = [r for r in raw if r[4] >= min_w]
        cands.sort(key=lambda r: -r[4])
        to_remove: set[str] = set()
        for ri in cands:
            for rj in cands:
                if rj[4] > ri[4] and len(ri[6]) < len(rj[6]) and rj[6][: len(ri[6])] == ri[6]:
                    to_remove.add(ri[1])
                    break
        return [r for r in cands if r[1] not in to_remove]

    # Step 5: binary-search threshold to hit target_lines
    all_weights = sorted({r[4] for r in raw if r[4] > 0}, reverse=True)
    if not all_weights:
        return []

    lo_w, hi_w = 1, all_weights[0] + 1
    for _ in range(30):
        if hi_w - lo_w <= 1:
            break
        mid_w = (lo_w + hi_w) // 2
        if len(_apply_dedup(mid_w)) > target_lines:
            lo_w = mid_w
        else:
            hi_w = mid_w

    # Pick the threshold (lo or hi) whose result is closest to target
    result_lo = _apply_dedup(lo_w)
    result_hi = _apply_dedup(hi_w)
    final = result_lo if abs(len(result_lo) - target_lines) <= abs(len(result_hi) - target_lines) else result_hi

    return [(eco, name, fen, pgn) for eco, name, pgn, fen, _, _, _ in final]


# ── Name-grouped family index (full-encyclopedia lobby) ─────────────────────────

def family_key(name: str, aliases: dict[str, tuple[str, ...]]) -> str:
    """Canonical family name for an ECO opening name.

    Alias patterns win first (so e.g. 'Queen's Pawn Game: London System' maps to
    'London System'); otherwise the family is the prefix before the earliest ':'
    or ',' — the lichess ECO data uses both as top-level separators.
    """
    low = name.lower()
    for canon, patterns in aliases.items():
        if any(p in low for p in patterns):
            return canon
    cut = len(name)
    for sep in (":", ","):
        i = name.find(sep)
        if i != -1:
            cut = min(cut, i)
    return name[:cut].strip()


def _san_line(uci_moves: list[str]) -> str:
    """Render a UCI move list as a numbered SAN string ('1. e4 e5 2. Nf3 ...')."""
    board = chess.Board()
    parts: list[str] = []
    try:
        for i, uci in enumerate(uci_moves):
            mv = chess.Move.from_uci(uci)
            san = board.san(mv)
            if i % 2 == 0:
                parts.append(f"{i // 2 + 1}. {san}")
            else:
                parts.append(san)
            board.push(mv)
    except Exception:
        pass
    return " ".join(parts)


def _first_move_bucket(uci_moves: list[str]) -> str:
    if not uci_moves:
        return "other"
    try:
        san = chess.Board().san(chess.Move.from_uci(uci_moves[0]))
    except Exception:
        return "other"
    if san == "e4":
        return "e4"
    if san == "d4":
        return "d4"
    return "other"


def _curate_entries(entries: list[tuple], min_w: int) -> list[tuple]:
    """Same-name dedup (highest weight per name), weight floor, then prefix-dedup.

    Mirrors curate_family's curation, parametrised by an explicit weight floor.
    Entry tuple: (eco, name, pgn, fen, weight, depth, uci_moves).
    """
    by_name: dict[str, tuple] = {}
    for rec in entries:
        n = rec[1]
        if n not in by_name or rec[4] > by_name[n][4]:
            by_name[n] = rec
    cands = [r for r in by_name.values() if r[4] >= min_w]
    cands.sort(key=lambda r: -r[4])
    to_remove: set[str] = set()
    for ri in cands:
        for rj in cands:
            if rj[4] > ri[4] and len(ri[6]) < len(rj[6]) and rj[6][: len(ri[6])] == ri[6]:
                to_remove.add(ri[1])
                break
    return [r for r in cands if r[1] not in to_remove]


def build_family_index(
    reader: "chess.polyglot.MemoryMappedReader | None",
    eco_dir: Path,
    aliases: dict[str, tuple[str, ...]] = C.TRAINER_FAMILY_ALIASES,
    depth_min: int = C.TRAINER_FAMILY_DEPTH_MIN,
    depth_max: int = C.TRAINER_CURATION_DEPTH_MAX,
) -> list[FamilyInfo]:
    """Group every ECO entry by family name and curate each with adaptive
    thresholds. Returns FamilyInfo list sorted by popularity (total weight) desc.
    """
    # Step 1: first-occurrence per (eco, name) across all TSVs.
    seen: dict[tuple[str, str], str] = {}
    for tsv_path in sorted(eco_dir.glob("*.tsv")):
        try:
            with tsv_path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    eco  = row.get("eco",  "").strip()
                    name = row.get("name", "").strip()
                    pgn  = row.get("pgn",  "").strip()
                    if not (eco and name and pgn):
                        continue
                    if (eco, name) not in seen:
                        seen[(eco, name)] = pgn
        except Exception as exc:
            logger.warning("build_family_index: could not read %s: %s", tsv_path, exc)

    # Step 2: parse + depth-filter + weight.
    grouped: dict[str, list[tuple]] = {}
    for (eco, name), pgn in seen.items():
        result = _parse_pgn_to_moves_and_fen(pgn)
        if result is None:
            continue
        moves, fen = result
        depth = len(moves)
        if not (depth_min <= depth <= depth_max):
            continue
        if reader is not None:
            try:
                w = sum(e.weight for e in reader.find_all(chess.Board(fen)))
            except Exception:
                w = 0
        else:
            w = 1
        grouped.setdefault(family_key(name, aliases), []).append(
            (eco, name, pgn, fen, w, depth, moves)
        )

    primary_w, primary_min = C.TRAINER_FAMILY_PRIMARY_WEIGHT, C.TRAINER_FAMILY_PRIMARY_MIN_LINES
    fallback_w, fallback_min = C.TRAINER_FAMILY_FALLBACK_WEIGHT, C.TRAINER_FAMILY_FALLBACK_MIN_LINES

    families: list[FamilyInfo] = []
    for fam_name, entries in grouped.items():
        primary = _curate_entries(entries, primary_w)
        if len(primary) >= primary_min:
            curated, threshold, available = primary, primary_w, True
        else:
            fallback = _curate_entries(entries, fallback_w)
            if len(fallback) >= fallback_min:
                curated, threshold, available = fallback, fallback_w, True
            else:
                curated, threshold, available = fallback, 0, False

        # ECO range + first move from curated lines if present, else all entries.
        basis = curated if curated else entries
        ecos = sorted(r[0] for r in basis)
        top = max(basis, key=lambda r: r[4]) if basis else None
        total_weight = sum(r[4] for r in entries)
        families.append(FamilyInfo(
            name=fam_name,
            eco_lo=ecos[0] if ecos else "",
            eco_hi=ecos[-1] if ecos else "",
            first_move=_first_move_bucket(top[6]) if top else "other",
            total_weight=total_weight,
            threshold=threshold,
            available=available,
            line_count=len(curated),
            sample_moves=_san_line(top[6]) if top else "",
            lines=[(eco, name, fen, pgn) for eco, name, pgn, fen, _, _, _ in curated],
        ))

    families.sort(key=lambda fi: -fi.total_weight)
    return families
