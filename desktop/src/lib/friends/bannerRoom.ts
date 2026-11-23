/**
 * S8 (FIX-B6, owner 2026-11-23): the challenge banner never covers a control on any screen; where floating can't
 * avoid that, the screen makes room for it. What counts as a control, and which ones a set of banner cards covers.
 * Shared by ChallengeBanners.svelte (which decides float or make room from it) and the harness's DOM check
 * (harness/beta6Checks.ts, controlsUnder), so the app and the check agree on the rule.
 */

/** A control: a button, link, form field, an element with a widget role or a tab stop, or a board. */
export const CONTROL_SELECTOR =
  'button, a[href], input, select, textarea, [role=button], [role=tab], [role=switch], [role=checkbox], [role=radio], ' +
  '[role=option], [role=menuitem], [role=slider], [tabindex]:not([tabindex="-1"]), cg-board, .cg-wrap'

/** Layers drawn over the banners (z-index above 45): dialogs and the command menu. A control in one is not covered. */
export const ABOVE_BANNERS = '[role=dialog][aria-modal=true], [aria-label="Command menu"]'

export interface Box {
  left: number
  top: number
  right: number
  bottom: number
}

export function overlap(a: Box, b: Box): { w: number; h: number } | null {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return w > 0 && h > 0 ? { w, h } : null
}

/** The controls (outside the banners and the layers above them) whose boxes meet any of *cards*. */
export function controlsUnder(cards: Box[], doc: Document = document): Element[] {
  if (!cards.length) return []
  const out: Element[] = []
  for (const el of doc.querySelectorAll(CONTROL_SELECTOR)) {
    if (el.closest('.banners') || el.closest(ABOVE_BANNERS)) continue
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) continue
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none') continue
    if (cards.some((c) => overlap(c, r))) out.push(el)
  }
  return out
}
