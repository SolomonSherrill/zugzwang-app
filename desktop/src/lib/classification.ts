/** Move classification display constants — mirrors CLASS_COLORS / CLASS_GLYPHS
 *  in zugzwang/config.py. */

export const CLASS_COLORS: Record<string, string> = {
  book: '#c4a57a',
  brilliant: '#34d3d3',
  great: '#60a5fa',
  best: '#4ade80',
  excellent: '#4ade80',
  good: '#86b89a',
  inaccuracy: '#facc15',
  mistake: '#fb923c',
  miss: '#f472b6',
  blunder: '#f87171',
}

export const CLASS_GLYPHS: Record<string, string> = {
  book: '☰',
  brilliant: '!!',
  great: '!',
  best: '★',
  excellent: 'Excellent', // no emoji (ruling 7, 2026-11-20 third): text contexts say the word; the redesign draws the SVG thumbs-up
  good: '✓',
  inaccuracy: '?!',
  mistake: '?',
  miss: '✗',
  blunder: '??',
}

export const CLASS_LABELS: Record<string, string> = {
  book: 'Book move',
  brilliant: 'Brilliant',
  great: 'Great move',
  best: 'Best move',
  excellent: 'Excellent',
  good: 'Good',
  inaccuracy: 'Inaccuracy',
  mistake: 'Mistake',
  miss: 'Miss',
  blunder: 'Blunder',
}

/** Categories worth a dot on the eval graph (signal, not noise). */
export const GRAPH_DOT_CLASSES = new Set([
  'brilliant',
  'great',
  'inaccuracy',
  'mistake',
  'miss',
  'blunder',
])

// ── eval helpers (Lichess sigmoid, k from core/classification.py) ───────────

const WP_K = 0.00368208

/** Win probability for white, 0..1, from a white-POV centipawn score. */
export function wpFromCp(cpWhite: number): number {
  return 1 / (1 + Math.exp(-WP_K * cpWhite))
}

/**
 * Convert a mover-POV score (as stored in move_analyses) at a given ply to
 * white POV. Ply is 0-based; even plies are white's moves. mate=0 means the
 * mover delivered checkmate.
 */
export function whitePovScore(
  ply: number,
  cp: number | null,
  mate: number | null,
): { cp: number | null; mate: number | null; whiteWins: boolean | null } {
  const whiteMoved = ply % 2 === 0
  if (mate !== null) {
    // mate >= 0 means the mover wins (0 = mate delivered)
    const moverWins = mate >= 0
    const whiteWins = whiteMoved ? moverWins : !moverWins
    return { cp: null, mate: whiteMoved ? mate : -mate, whiteWins }
  }
  if (cp !== null) return { cp: whiteMoved ? cp : -cp, mate: null, whiteWins: null }
  return { cp: null, mate: null, whiteWins: null }
}

/** White win probability 0..1 for a ply's score; null when no score. */
export function whiteWp(ply: number, cp: number | null, mate: number | null): number | null {
  const s = whitePovScore(ply, cp, mate)
  if (s.whiteWins !== null) return s.whiteWins ? 1 : 0
  if (s.cp !== null) return wpFromCp(s.cp)
  return null
}

/** Short eval label like "+1.4", "−0.3", "#5", "#−3". */
export function evalLabel(ply: number, cp: number | null, mate: number | null): string {
  const s = whitePovScore(ply, cp, mate)
  if (s.whiteWins !== null) {
    if (s.mate === 0 || s.mate === null) return s.whiteWins ? '1-0' : '0-1'
    return s.mate > 0 ? `#${s.mate}` : `#−${Math.abs(s.mate)}`
  }
  if (s.cp === null) return ''
  const pawns = s.cp / 100
  const txt = Math.abs(pawns) >= 10 ? pawns.toFixed(0) : pawns.toFixed(1)
  return pawns >= 0 ? `+${txt}` : `−${Math.abs(pawns).toFixed(Math.abs(pawns) >= 10 ? 0 : 1)}`
}
