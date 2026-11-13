/** Captions for the puzzle-session loader.
 *
 * The first `select_puzzles` after launch takes ~27 s: a cold page cache on the
 * 1.1 GB `puzzles` table, paid once per launch (0.3–3.5 s thereafter). Measured
 * in `review/scratch/f12_handlers.py`; the query itself is not fixed here. What
 * is fixed is that a spinner which says the same thing for 27 s reads as a hang,
 * so past a few seconds the caption says what is being waited on and that it is
 * one-off.
 */

export const PUZZLE_WAIT_EXPLAIN_MS = 2500

export function puzzleWaitCaption(elapsedMs: number): string {
  return elapsedMs < PUZZLE_WAIT_EXPLAIN_MS
    ? 'Setting up puzzle…'
    : 'Reading the puzzle database — the first search after launch is slow, later ones are not.'
}
