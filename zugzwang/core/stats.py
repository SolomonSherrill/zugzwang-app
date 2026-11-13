"""Small statistical helpers, no Qt and no numpy.

These run inside the Insights load path, so both are closed-form: nothing
resamples, and nothing allocates per ply. They are what the phase verdict needs
to decide whether it is allowed to make a claim at all — a two-sided p-value,
and a correction for having asked the question more than once.

Nothing here is safe for a small sample. Per-game accuracy is heavy-tailed, so
normal theory understates a tail p-value by orders of magnitude at small n; the
phase verdict escapes that only because it counts tens of thousands of plies.
Any new per-opening or per-segment claim has to be permutation-tested instead —
see ARCHITECTURE.md.
"""

import math


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def benjamini_hochberg(pvalues: list[float], fdr: float) -> list[bool]:
    """Which of these p-values survive at the given false-discovery rate.

    Testing many comparisons at 95 % each is expected to turn up "findings"
    from noise alone. BH controls the share of claims that are false rather
    than the chance of any false claim, which is the right trade for a screen
    whose job is to point somewhere useful.
    """
    count = len(pvalues)
    if not count:
        return []
    ranked = sorted(range(count), key=lambda i: pvalues[i])
    largest_passing = 0
    for rank, i in enumerate(ranked, start=1):
        if pvalues[i] <= rank * fdr / count:
            largest_passing = rank
    keep = [False] * count
    for rank, i in enumerate(ranked, start=1):
        if rank <= largest_passing:
            keep[i] = True
    return keep
