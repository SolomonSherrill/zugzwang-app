import { describe, expect, it } from 'vitest'
import type { ImportIssue } from './api'
import { importSummary } from './importReport'

const issue = (imported: boolean, index = 1): ImportIssue => ({
  index,
  label: 'a vs b',
  reason: imported ? 'stopped after 2 plies' : 'no moves',
  imported,
})

describe('importSummary', () => {
  it('says only the count when nothing went wrong', () => {
    expect(importSummary(3, [])).toBe('Imported 3 games.')
  })

  it('singularises', () => {
    expect(importSummary(1, [])).toBe('Imported 1 game.')
  })

  // The distinction the whole item exists for: a truncated game is inside
  // `count`, a skipped one is not, and calling both "failed" would misreport
  // what is now in the database.
  it('counts a truncated game as imported and still flags it', () => {
    expect(importSummary(2, [issue(true)])).toBe(
      'Imported 2 games, 1 game stored incomplete.',
    )
  })

  it('reports skipped games separately from truncated ones', () => {
    expect(importSummary(2, [issue(true, 1), issue(false, 4)])).toBe(
      'Imported 2 games, 1 game stored incomplete, 1 game skipped.',
    )
  })

  it('handles an import where every game was skipped', () => {
    expect(importSummary(0, [issue(false, 1), issue(false, 2)])).toBe(
      'Imported 0 games, 2 games skipped.',
    )
  })
})
