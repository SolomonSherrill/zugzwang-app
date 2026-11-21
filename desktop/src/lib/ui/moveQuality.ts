/**
 * The ten move-quality classes as the redesign draws them (DESIGN.md, owner ruling 1;
 * design/design-system-README.md, "Move-quality icons"): every class a filled circle in its
 * `--q-*` colour, its mark in `--q-ink`. Marks (!!, !, ?!, ?, ??) are 800-weight text;
 * symbols (book, star, thumbs-up, check, cross) are SVG paths on a 24 viewBox so they look
 * the same on every platform. Excellent is a thumbs-up, never "+" ("+" means check).
 */

export type QualityClass =
  | 'brilliant'
  | 'great'
  | 'book'
  | 'best'
  | 'excellent'
  | 'good'
  | 'inaccuracy'
  | 'mistake'
  | 'miss'
  | 'blunder'

export interface SymbolPath {
  d: string
  /** filled shape, or a stroke of this width */
  mode: 'fill' | 'stroke'
  strokeWidth?: number
}

export interface Quality {
  cls: QualityClass
  /** the accessible name, sentence case */
  name: string
  /** CSS variable holding the fill */
  fill: string
  /** text mark, for the five marked classes */
  mark?: string
  /** SVG symbol, for the five symbol classes */
  symbol?: SymbolPath
}

const STAR = 'M12 3.2l2.7 5.5 6 .9-4.35 4.25 1.03 6L12 17l-5.38 2.85 1.03-6L3.3 9.6l6-.9z'
const THUMBS_UP =
  'M3.5 10h3.5v10H3.5zM9 20h8.4a2 2 0 0 0 2-1.65l1.15-6.2A1.8 1.8 0 0 0 18.8 10H14.2l.75-3.4a1.9 1.9 0 0 0-1.86-2.3L9 10z'
const CHECK = 'M5 12.5l4.5 4.5L19.5 7'
const CROSS = 'M6.5 6.5l11 11M17.5 6.5l-11 11'
const BOOK = 'M3 5.5c3-1.2 6-1 9 .8 3-1.8 6-2 9-.8v13c-3-1.2-6-1-9 .8-3-1.8-6-2-9-.8z'

/** In the design system's table order. */
export const QUALITIES: Quality[] = [
  { cls: 'brilliant', name: 'Brilliant', fill: '--q-brilliant', mark: '!!' },
  { cls: 'great', name: 'Great', fill: '--q-great', mark: '!' },
  { cls: 'book', name: 'Book', fill: '--q-book', symbol: { d: BOOK, mode: 'fill' } },
  { cls: 'best', name: 'Best', fill: '--q-best', symbol: { d: STAR, mode: 'fill' } },
  { cls: 'excellent', name: 'Excellent', fill: '--q-excellent', symbol: { d: THUMBS_UP, mode: 'fill' } },
  { cls: 'good', name: 'Good', fill: '--q-good', symbol: { d: CHECK, mode: 'stroke', strokeWidth: 3.6 } },
  { cls: 'inaccuracy', name: 'Inaccuracy', fill: '--q-inaccuracy', mark: '?!' },
  { cls: 'mistake', name: 'Mistake', fill: '--q-mistake', mark: '?' },
  { cls: 'miss', name: 'Miss', fill: '--q-miss', symbol: { d: CROSS, mode: 'stroke', strokeWidth: 3.6 } },
  { cls: 'blunder', name: 'Blunder', fill: '--q-blunder', mark: '??' },
]

export const QUALITY: Record<QualityClass, Quality> = Object.fromEntries(
  QUALITIES.map((q) => [q.cls, q]),
) as Record<QualityClass, Quality>

export function isQualityClass(s: string | null | undefined): s is QualityClass {
  return !!s && s in QUALITY
}

/** The three drawn sizes: 16 in lists, 18 in tables, 20 as the badge on a board square. */
export type IconSize = 16 | 18 | 20

/** Mark font size and symbol box for a circle size (16 → 9px / 10px, as the mockups). */
export function iconMetrics(size: IconSize): { font: number; symbol: number } {
  return { 16: { font: 9, symbol: 10 }, 18: { font: 10, symbol: 11 }, 20: { font: 11, symbol: 12 } }[size]
}

/** The classes the Moves graph marks with a dot (ruling 5); never inaccuracies. */
export const GRAPH_DOT_QUALITIES: ReadonlySet<QualityClass> = new Set<QualityClass>([
  'brilliant',
  'great',
  'miss',
  'mistake',
  'blunder',
])
