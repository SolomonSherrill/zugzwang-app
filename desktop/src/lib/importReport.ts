import type { ImportIssue } from './api'

/** How an import went, in one sentence.
 *
 * Split out of the component because the branching is the part that can be
 * wrong: "imported" and "came through whole" are different counts whenever a
 * game was truncated, and conflating them is the bug this whole item is about.
 */
export function importSummary(count: number, issues: ImportIssue[]): string {
  const truncated = issues.filter((i) => i.imported).length
  const skipped = issues.length - truncated
  const games = (n: number) => `${n} game${n === 1 ? '' : 's'}`

  const parts = [`Imported ${games(count)}`]
  if (truncated > 0) parts.push(`${games(truncated)} stored incomplete`)
  if (skipped > 0) parts.push(`${games(skipped)} skipped`)
  return parts.join(', ') + '.'
}
