/** Which tone the eval-bar's score label needs, given how tall the white half is.
 *
 * The label always sits at the white end of the bar, a few px in from the edge,
 * so the only question is whether the white half has grown tall enough to be
 * underneath it. That is a pixel comparison, and the bar is 450–680 px tall
 * depending on the window — which is why the percentage threshold this replaces
 * could not have been right at any single value.
 */

/** Distance from the bar's white end to the middle of the label's glyph ink.
 *
 * `bottom: 3px` plus roughly 8 px of ink for digits at 8.5 px / 700 weight, so
 * the ink spans about 5–11 px and its middle sits near 8. Switching on the
 * middle rather than either edge is deliberate: when the white half ends
 * somewhere inside the ink no single colour is right, and the midpoint splits
 * the error evenly instead of favouring one side.
 */
export const LABEL_INK_MID_PX = 8

/**
 * @param whitePct white's share of the bar, 0..100
 * @param barHeightPx measured height of the bar; 0 before first layout
 */
export function labelOnWhite(whitePct: number, barHeightPx: number): boolean {
  if (barHeightPx <= 0) return false
  return (whitePct / 100) * barHeightPx >= LABEL_INK_MID_PX
}
