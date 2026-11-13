// The Games screen's search: jump to one game by its id, or narrow by text.
//
// The owner is cited games by id — the chess.com / Lichess game id, or the app's own
// id — and the screen had no way to find one (2026-11-11). An id query matches the id
// exactly, never as a substring: "483" must not pull in every game whose opponent's
// name contains 483. Text (opponent, opening, ECO, date) still matches as a substring,
// so a bare number finds the game with that id *and* any text containing it.

export interface SearchableGame {
  id: number
  /** The platform's game id (chess.com numeric, Lichess 8 characters); null for local games. */
  externalId: string | null
}

/** Whether `query` names `g` by id. "#483" is the app id only; a bare token is either id. */
export function matchesId(query: string, g: SearchableGame): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return false
  if (q.startsWith('#')) return q.slice(1) === String(g.id)
  return q === String(g.id) || (g.externalId !== null && q === g.externalId.toLowerCase())
}

/** The search box's test: an exact id, or a substring of the game's text fields. */
export function matchesSearch(query: string, g: SearchableGame, text: string[]): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (matchesId(q, g)) return true
  if (q.startsWith('#')) return false
  return text.join(' ').toLowerCase().includes(q)
}
