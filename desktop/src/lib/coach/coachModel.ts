/** COACH-1 C: the Coach page's words (fixed templates over the overview's figures). */
import type { CoachFocusItem, CoachOverview, CoachRow } from '../api'

/** "Missed <b>9</b> of 14" (COACH-2 ruling CF1; the count is trusted HTML: numbers only) */
export function countText(f: Pick<CoachFocusItem, 'missed' | 'total'>): string {
  return `Missed <b>${Math.round(f.missed).toLocaleString('en-GB')}</b> of ${Math.round(f.total).toLocaleString('en-GB')}`
}

/** The window in words: "last 12 months" for 365 days, else "last N days" (CF1: the header names it). */
export function windowText(days: number | undefined): string {
  if (!days || days === 365) return 'last 12 months'
  return `last ${days} days`
}

export function focusSub(f: CoachFocusItem): string {
  return f.kind === 'chance' ? 'Chances you had' : 'Threats against you'
}

/** "Caught 4 of your last 5" */
export function recentText(f: Pick<CoachFocusItem, 'recentCaught' | 'recentTotal'>): string {
  if (f.recentTotal === 0) return ''
  if (f.recentTotal === 1) return f.recentCaught ? 'Caught the last one' : 'Missed the last one'
  return `Caught ${f.recentCaught} of your last ${f.recentTotal}`
}

/** The rows behind one focus item, or behind all of them, newest first. */
export function rowsFor(o: Extract<CoachOverview, { status: 'ready' }>, key: string | null): CoachRow[] {
  if (!key) return o.behind
  return o.focus.find((f) => f.key === key)?.rows ?? []
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "19 Nov", "19 Nov 2025" outside this year; "Today", "Yesterday" */
export function coachDate(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(now) - day(d)) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`
}
