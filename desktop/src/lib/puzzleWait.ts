/** Captions for the puzzle-session loader.
 *
 * The first `select_puzzles` after launch takes ~27 s: a cold page cache on the
 * 1.1 GB `puzzles` table, paid once per launch (0.3–3.5 s thereafter). Measured
 * in `review/scratch/f12_handlers.py`; the query itself is not fixed here. What
 * is fixed is that a spinner which says the same thing for 27 s reads as a hang,
 * so past a few seconds the loader says plainly what is being waited on, how long
 * the first search can take, and that it is one-off (UI-BUILD-2 E2: a panel with
 * the sentence and a muted line, no silent spinner).
 */

export const PUZZLE_WAIT_EXPLAIN_MS = 2500

export interface WaitCaption {
  sentence: string
  sub: string | null
}

export function puzzleWaitCaption(elapsedMs: number): WaitCaption {
  if (elapsedMs < PUZZLE_WAIT_EXPLAIN_MS) return { sentence: 'Finding a puzzle…', sub: null }
  return {
    sentence: 'Reading the puzzle database…',
    sub: 'The first search after the app starts can take about half a minute. Later ones take a few seconds at most.',
  }
}
