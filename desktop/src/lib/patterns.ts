// R6 (PATTERNS.md §6a): the Insights patterns card's text, kept out of the component so it
// can be tested. The sentences themselves come from the sidecar (core/patterns.py).
import type { InsightsPatternItem, InsightsPatterns } from './api'

/** How many games the card covers. Games without stored pattern facts are left out, and
 *  the card says so rather than implying it read them. */
export function coverageText(p: InsightsPatterns): string {
  const n = (x: number) => x.toLocaleString('en-US')
  const games = (x: number) => `${n(x)} analysed game${x === 1 ? '' : 's'}`
  if (p.covered === p.analysed) return `Across ${games(p.covered)}.`
  return `Across ${n(p.covered)} of ${games(p.analysed)}; the other ${n(p.analysed - p.covered)} have no pattern facts stored yet.`
}

/** What the card says when no sentence passes: nothing about the player, only that nothing
 *  cleared the bar on these games. */
export function emptyText(p: InsightsPatterns): string {
  return p.covered === 0
    ? 'No games with pattern facts under these filters.'
    : 'No pattern clears the bar on these games.'
}

/** One linked ply, as the list shows it: date, opponent, the move and its label. */
export function itemText(it: InsightsPatternItem): string {
  const date = it.date ? it.date.slice(0, 10) : ''
  const parts = [date, it.opponent ? `vs ${it.opponent}` : null, it.move, it.label ? `(${it.label})` : null]
  return parts.filter((x): x is string => !!x).join(' · ').replace(/ · \(/, ' (')
}

/** The link under a sentence. */
export function linkText(label: string, count: number): string {
  return `${label} → (${count.toLocaleString('en-US')})`
}

export const PAGE = 50
