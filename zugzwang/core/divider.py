"""Game-phase division, transcribed from Lichess's scalachess `Divider.scala`.

Phases are a property of the *game*, not of a position in isolation: Divider
finds the first ply at which the middlegame has begun and the first at which the
endgame has, and everything between those points belongs to the phase they open.
Phases therefore never revert — a position cannot go back to being an opening
because pieces came back on, which is what a per-position test would allow.

Predicates are transcribed from the Scala directly; the board representation is
not, since counting FEN characters is far cheaper here than building boards.

Reference: lichess-org/scalachess, core/src/main/scala/Divider.scala.
"""

from __future__ import annotations

# The thresholds are Lichess's, not ours. Named so the predicates below read as
# the rule rather than as arithmetic.
_MIDGAME_MAJORS_AND_MINORS = 10
_ENDGAME_MAJORS_AND_MINORS = 6
_MIDGAME_MIXEDNESS = 150
_BACKRANK_SPARSE_BELOW = 4


def _score(y: int, white: int, black: int) -> int:
    """Lichess's mixedness score for one 2x2 region at rank `y`."""
    if white == 0:
        if black == 1:
            return 1 + y
        if black == 2:
            return 2 + (6 - y) if y < 6 else 0
        if black in (3, 4):
            return 3 + (7 - y) if y < 7 else 0
        return 0
    if white == 1:
        if black == 0:
            return 1 + (8 - y)
        if black == 1:
            return 5 + abs(4 - y)
        if black == 2:
            return 4 + (7 - y)
        if black == 3:
            return 5 + (7 - y)
        return 0
    if white == 2:
        if black == 0:
            return 2 + (y - 2) if y > 2 else 0
        if black == 1:
            return 4 + (y - 1)
        if black == 2:
            return 7
        return 0
    if white == 3:
        if black == 0:
            return 3 + (y - 1) if y > 1 else 0
        if black == 1:
            return 5 + (y - 1)
        return 0
    if white == 4:
        # A group of four on the home row is not mixed at all.
        return 3 + (y - 1) if black == 0 and y > 1 else 0
    return 0


# The 49 overlapping 2x2 regions are indexed y * 7 + x over files a-g and ranks
# 1-7. Each square falls in up to four of them; precomputing which turns the
# inner loop into a straight walk with no bounds tests.
_SQUARE_REGIONS: list[tuple[int, ...]] = [
    tuple(y * 7 + x
          for y in (rank - 1, rank) if 0 <= y <= 6
          for x in (file - 1, file) if 0 <= x <= 6)
    for rank in range(8) for file in range(8)
]

# A region holds four squares, so white and black counts each fit in 0-4 and
# pack into one byte as white * 5 + black. _score is pure over that tiny domain,
# so every (region, packed count) pair is scored once at import.
_REGION_SCORE: list[list[int]] = [
    [_score(i // 7 + 1, code // 5, code % 5) for code in range(25)] for i in range(49)
]


def _mixedness(placement: str) -> int:
    """Lichess's mixedness: how far the two armies have interpenetrated.

    Walks the FEN once and pushes each piece into the regions containing it,
    rather than testing all 49 regions against a bitboard. Same number. This is
    the hot path — it runs for every ply before one of the cheaper midgame tests
    fires, which is around twenty plies per game and tens of thousands across a
    synced history.
    """
    regions = bytearray(49)
    rank, file = 7, 0
    for ch in placement:
        if ch == "/":
            rank -= 1
            file = 0
            continue
        if ch <= "8":          # a digit: that many empty squares
            file += ord(ch) - 48
            continue
        delta = 5 if ch.isupper() else 1
        for i in _SQUARE_REGIONS[rank * 8 + file]:
            regions[i] += delta
        file += 1

    return sum(map(list.__getitem__, _REGION_SCORE, regions))


_DROP_MAJORS_AND_MINORS = str.maketrans("", "", "qrbnQRBN")


def majors_and_minors(placement: str) -> int:
    """Count of pieces that are neither kings nor pawns, both colours.

    Counted off the FEN text rather than through a bitboard, and in one pass
    rather than eight: this is evaluated for every ply of every game on an
    Insights load, which is six figures of positions on a synced history.
    """
    return len(placement) - len(placement.translate(_DROP_MAJORS_AND_MINORS))


def _backrank_sparse(placement: str) -> bool:
    """Whether either player's home rank has emptied out — i.e. has developed.

    A FEN's placement runs rank 8 first and rank 1 last, so black's back rank is
    the leading segment and white's is the trailing one.
    """
    ranks = placement.split("/")
    white_home, black_home = ranks[7], ranks[0]
    white_pieces = sum(1 for c in white_home if c.isupper())
    black_pieces = sum(1 for c in black_home if c.islower())
    return (white_pieces < _BACKRANK_SPARSE_BELOW
            or black_pieces < _BACKRANK_SPARSE_BELOW)


def divide(placements: list[str]) -> tuple[int | None, int | None]:
    """(middle_index, end_index) over a game's board list, per `Divider.apply`.

    Either may be None: a game can end before reaching a phase. `middle` is also
    None when the endgame began no later than the middlegame would have, which
    is Lichess's `middle.filter(m => end.forall(m < _))` — such a game goes
    straight from opening to endgame.
    """
    counts = [majors_and_minors(p) for p in placements]

    middle = None
    for i, placement in enumerate(placements):
        # Ordered by cost: mixedness walks the whole board, so it is reached
        # only for the early plies where neither cheap test has fired yet.
        if (counts[i] <= _MIDGAME_MAJORS_AND_MINORS
                or _backrank_sparse(placement)):
            middle = i
            break
        if _mixedness(placement) > _MIDGAME_MIXEDNESS:
            middle = i
            break

    end = None
    if middle is not None:
        end = next((i for i, c in enumerate(counts)
                    if c <= _ENDGAME_MAJORS_AND_MINORS), None)
        if end is not None and middle >= end:
            middle = None

    return middle, end


def phase_at(index: int, middle: int | None, end: int | None) -> str:
    """Which phase the board at `index` belongs to, given a game's division."""
    if end is not None and index >= end:
        return "endgame"
    if middle is not None and index >= middle:
        return "middlegame"
    return "opening"
