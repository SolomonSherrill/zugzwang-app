/** Home's pure wording and shaping (UI-BUILD C). Every sentence is read off stored fields. */
import { describeTermination, type HomeRecent, type ReportMoment } from '../api'

export function dayWord(iso: string, now = new Date()): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, now)) return 'Today'
  const y = new Date(now)
  y.setDate(now.getDate() - 1)
  if (same(d, y)) return 'Yesterday'
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** "You beat X by checkmate", "You lost to X on time", "You drew with X (stalemate)". */
export function resultSentence(g: Pick<HomeRecent, 'outcome' | 'opponent' | 'termination'>): string | null {
  const opp = g.opponent ?? 'your opponent'
  const t = g.termination
  const how = t === 'checkmate' || t === 'resignation' ? ` by ${t}` : t === 'timeout' ? ' on time' : ''
  if (g.outcome === 'win') return `You beat ${opp}${how}`
  if (g.outcome === 'loss') return `You lost to ${opp}${how}`
  if (g.outcome === 'draw') return `You drew with ${opp}${t ? ` (${describeTermination(t)})` : ''}`
  return null
}

/** The family before the colon: "Scandinavian Defense: Valencian Variation" → "Scandinavian Defense". */
export function openingFamily(name: string | null): string | null {
  return name ? name.split(':')[0].trim() : null
}

/** "180+2" → "3+2", "600" → "10+0", "1/86400" → "Daily"; null for "-" or "?". */
export function shortTimeControl(tc: string | null): string | null {
  if (!tc) return null
  if (/^1\/\d+$/.test(tc)) return 'Daily'
  const m = /^(\d+)(?:\+(\d+))?$/.exec(tc.trim())
  if (!m) return null
  const base = Number(m[1])
  const b = base % 60 === 0 ? String(base / 60) : `${base}s`
  return `${b}+${m[2] ?? 0}`
}

/** The moment Home offers to retry: the user's own moment with the largest swing. */
export function retryMoment(moments: ReportMoment[]): ReportMoment | null {
  const mine = moments.filter((m) => m.yours === true && m.bestUci)
  return mine.sort((a, b) => b.swing - a.swing)[0] ?? null
}

export const SPEED_NAME: Record<string, string> = {
  bullet: 'Bullet',
  blitz: 'Blitz',
  rapid: 'Rapid',
  classical: 'Classical',
  daily: 'Daily',
  puzzles: 'Puzzles',
}

/** "+18", "−6", "0"; null when there is no change to show. */
export function changeText(c: number | null): string | null {
  if (c === null) return null
  if (c === 0) return '0'
  return c > 0 ? `+${c}` : `\u2212${-c}`
}

/** A 96 × 24 sparkline's points as [x, y]; none with fewer than two values. */
export function sparkCoords(values: number[], w = 96, h = 24): [number, number][] {
  if (values.length < 2) return []
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 1
  return values.map((v, i) => [+((i / (values.length - 1)) * w).toFixed(1), +(h - 2 - ((v - lo) / span) * (h - 4)).toFixed(1)])
}

/** Polyline points for a 96 × 24 sparkline. */
export function sparkline(values: number[], w = 96, h = 24): string {
  return sparkCoords(values, w, h)
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ')
}
