/**
 * Analyse again's depths and their measured cost (ruling 7: "time estimates measured, not
 * guessed"; RUNS-DEPTH: "measured on at least 10 games of different lengths"). Measured
 * 2026-11-20 by review/scratch/ui/runs_depth_timing.py (output beside it: the ten chess.com
 * games by platform id, 16 to 169 plies) through the real sidecar, this Mac, Stockfish 18,
 * one thread. An estimate is the least-squares line seconds = a + b * plies for that depth,
 * said with "about". Depth 24 varies most from game to game (2.7 to 12.8 s per ply).
 */
export const ANALYSE_AGAIN_FIT: Record<number, { a: number; b: number } | undefined> = {
  14: { a: 3.76, b: 0.0491 },
  18: { a: 17.82, b: 0.4165 },
  24: { a: 180.98, b: 3.5427 },
}

/** RUNS-DEPTH (owner, 2026-11-20): a deeper run is kept beside the depth-14 one, so 18 and 24 are on. */
export const DEEP_RUNS_AVAILABLE = true

export function estimateSeconds(depth: number, plies: number): number | null {
  const f = ANALYSE_AGAIN_FIT[depth]
  if (!f || plies <= 0) return null
  return f.a + f.b * plies
}

export function estimateText(depth: number, plies: number): string | null {
  const s = estimateSeconds(depth, plies)
  if (s === null) return null
  if (s < 60) return `about ${Math.max(1, Math.round(s))} s`
  return `about ${Math.round(s / 60)} min`
}
