import { describe, expect, it } from 'vitest'
import { LABEL_INK_MID_PX, labelOnWhite } from './evalBar'

// The bar is `min(calc(100vh - 150px), 680px)` tall (ReviewScreen.svelte), so
// these are the two ends of the range it actually takes on.
const SHORT = 450
const TALL = 680

describe('labelOnWhite', () => {
  it('is false before the bar has been measured', () => {
    // A `bind:clientHeight` reads 0 until first layout. Light-on-dark is the
    // safe guess for one frame: at that point the halves have no height either.
    expect(labelOnWhite(50, 0)).toBe(false)
    expect(labelOnWhite(100, 0)).toBe(false)
  })

  it('is false when white has no share of the bar', () => {
    expect(labelOnWhite(0, TALL)).toBe(false)
  })

  it('is true when white owns the whole bar', () => {
    expect(labelOnWhite(100, SHORT)).toBe(true)
  })

  it('switches where the white half reaches the middle of the glyph ink', () => {
    const atMid = (100 * LABEL_INK_MID_PX) / TALL
    expect(labelOnWhite(atMid, TALL)).toBe(true)
    expect(labelOnWhite(atMid - 0.01, TALL)).toBe(false)
  })

  it('switches lower on a taller bar, because a percent is more pixels', () => {
    const justUnderOnShort = (100 * (LABEL_INK_MID_PX - 0.5)) / SHORT
    expect(labelOnWhite(justUnderOnShort, SHORT)).toBe(false)
    expect(labelOnWhite(justUnderOnShort, TALL)).toBe(true)
  })

  // The bug this replaces: `whitePct > 12` drew the label in #e8e2d4 on the
  // #e8e2d4 white half for every white share between ~2 % and 12 % — 15,246 of
  // the 85,390 scored plies in the live database, not the single boundary ply
  // the review described.
  it('is on-white across the band the percentage threshold got wrong', () => {
    for (const pct of [2.5, 5, 8, 11, 11.99, 12]) {
      expect(labelOnWhite(pct, SHORT), `${pct}% of ${SHORT}px`).toBe(true)
      expect(labelOnWhite(pct, TALL), `${pct}% of ${TALL}px`).toBe(true)
    }
  })
})
