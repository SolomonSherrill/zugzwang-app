// Layer 5 (ANALYSIS_ARCHITECTURE.md §2): ClaimText and DescriptionText are distinct
// branded types, so `npm run check` rejects a description where a claim belongs and
// the reverse. The `@ts-expect-error` lines fail the type check if that ever stops
// being an error.
import { describe, expect, it } from 'vitest'
import type { ClaimText, DescriptionText } from './api'

function showClaims(lines: ClaimText[]): number {
  return lines.length
}
function showDescriptions(lines: DescriptionText[]): number {
  return lines.length
}

describe('claim and description texts', () => {
  it('cannot be swapped', () => {
    const d = 'After e4, the engine line runs 1.e4.' as DescriptionText
    const c = 'Bxf7+ won seven points of material by force.' as ClaimText
    // @ts-expect-error a description is not a claim
    showClaims([d])
    // @ts-expect-error a claim is not a description
    showDescriptions([c])
    expect(showClaims([c]) + showDescriptions([d])).toBe(2)
  })
})
