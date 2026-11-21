/**
 * The redesigned Insights' presentation logic (UI-BUILD-2 C), kept out of the component so it
 * can be tested. Figures come from the sidecar (core/insights_v2.py); nothing here computes a
 * statistic, it only chooses how to show one.
 */
import type { InsightsMonth, InsightsV2, QualityClassV2 } from '../api'

export type Timeframe = '7d' | '30d' | '1y' | 'all'
export const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
  { value: '1y', label: '1Y' },
  { value: 'all', label: 'All' },
]
const DAYS: Record<Timeframe, number | null> = { '7d': 7, '30d': 30, '1y': 365, all: null }

export function sinceFor(tf: Timeframe, now = Date.now()): string | undefined {
  const d = DAYS[tf]
  return d === null ? undefined : new Date(now - d * 86_400_000).toISOString()
}

/** The order the move-quality bars and table use (book left out: shares of the rest). */
export const QUALITY_ORDER: QualityClassV2[] = [
  'brilliant', 'great', 'best', 'excellent', 'good', 'inaccuracy', 'mistake', 'miss', 'blunder',
]

const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function monthLabel(key: string): string {
  return MONTH[Number(key.slice(5, 7)) - 1] ?? key
}

export type MonthKey = 'accuracy' | 'winRate' | 'blundersPerGame' | 'games'

/** The 12-month series of one figure: [index, value] for the months that have one. */
export function series(months: InsightsMonth[], key: MonthKey): [number, number][] {
  const out: [number, number][] = []
  months.forEach((m, i) => {
    const v = key === 'games' ? (m.games > 0 ? m.games : null) : m[key]
    if (v !== null && v !== undefined) out.push([i, v])
  })
  return out
}

/** A sparkline's points over the 12 months as [x, y]; none with fewer than two months of data. */
export function sparkCoords(pts: [number, number][], n = 12, w = 84, h = 26): [number, number][] {
  if (pts.length < 2) return []
  const vs = pts.map((p) => p[1])
  const lo = Math.min(...vs)
  const hi = Math.max(...vs)
  const span = hi - lo || 1
  return pts.map(([i, v]) => [+((i / (n - 1)) * w).toFixed(1), +(h - 3 - ((v - lo) / span) * (h - 6)).toFixed(1)])
}

/** A sparkline's points over the 12 months; '' with fewer than two months of data. */
export function sparkPoints(pts: [number, number][], n = 12, w = 84, h = 26): string {
  return sparkCoords(pts, n, w, h)
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ')
}

/** A stat's monthly figure as its readout shows it: "76.4", "52.1%", "1.29", "120". */
export function statValueText(key: MonthKey, v: number): string {
  if (key === 'accuracy') return v.toFixed(1)
  if (key === 'winRate') return `${v.toFixed(1)}%`
  if (key === 'blundersPerGame') return v.toFixed(2)
  return fmtInt(v)
}

/** "+4.5 over 12 months": the latest month with a figure less the earliest one in the window. */
export function changeOver(pts: [number, number][], digits = 1): { delta: number; text: string } | null {
  if (pts.length < 2) return null
  const [i0, v0] = pts[0]
  const [i1, v1] = pts[pts.length - 1]
  const delta = Number((v1 - v0).toFixed(digits))
  const months = i1 - i0
  const sign = delta > 0 ? '+' : delta < 0 ? '\u2212' : ''
  return { delta, text: `${sign}${Math.abs(delta).toFixed(digits)} over ${months} month${months === 1 ? '' : 's'}` }
}

export const fmtInt = (n: number) => n.toLocaleString('en-US')
export const fmtPct = (v: number | null, digits = 1) => (v === null ? '\u2013' : `${v.toFixed(digits)}%`)

/** The accuracy chart's points: by month (last 12) for 1Y and All, by day for 7D and 30D. */
export function chartPoints(
  data: InsightsV2,
  tf: Timeframe,
): { label: string; date: string; accuracy: number | null; games: number }[] {
  if (tf === '7d' || tf === '30d') {
    return data.daily.map((d) => ({ label: d.day.slice(5).replace('-', '/'), date: d.day, accuracy: d.accuracy, games: d.games }))
  }
  return data.monthly.map((m) => ({ label: monthLabel(m.month), date: m.month, accuracy: m.accuracy, games: m.games }))
}

/** Heat cell fill: text colour at an opacity scaled between the lowest and highest shown cell. */
export function heatOpacity(acc: number | null, lo: number, hi: number): number {
  if (acc === null) return 0
  if (hi <= lo) return 0.5
  return 0.12 + 0.7 * ((acc - lo) / (hi - lo))
}

export const PHASE_NAME = { opening: 'Opening', middlegame: 'Middlegame', endgame: 'Endgame' } as const

/** The patterns panel's titles and bar labels for the R6 sentences (PATTERNS.md §6a); the
 *  sentence itself is shown verbatim behind its link. */
export const PATTERN_TITLES: Record<string, { title: string; you: string; them: string }> = {
  punish: { title: 'Punishing errors', you: 'You, after their errors', them: 'Them, after yours' },
  decided: { title: 'Losses decided by one move', you: 'Your losses', them: 'Your wins' },
}

export function ratio(y: number, n: number): number | null {
  return n > 0 ? (100 * y) / n : null
}
