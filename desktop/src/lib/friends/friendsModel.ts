/** Pure helpers for the Friends screens (FRIENDS-1 C): words and figures from the API's data. */
import type { Friend, ListRating, Rating, Record3, Split } from './friendsApi'

export const HANDLE_RE = /^[A-Za-z0-9_-]{3,20}$/
export const HANDLE_RULE = '3 to 20 characters: letters, numbers, _ and -.'

/** The client's first check of a handle (the server's rules, server/src/handles.ts, decide). */
export function handleShape(h: string): string | null {
  if (!h) return null
  if (h.length < 3) return 'Too short: at least 3 characters.'
  if (h.length > 20) return 'Too long: at most 20 characters.'
  if (!HANDLE_RE.test(h)) return 'Only letters, numbers, _ and -.'
  return null
}

export function initial(handle: string): string {
  return (handle.match(/[A-Za-z0-9]/)?.[0] ?? '?').toUpperCase()
}

const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR

/** "just now", "12 min ago", "2 h ago", "Yesterday", "3 days ago", "2 weeks ago", "3 months ago" */
export function ago(ms: number, now: number): string {
  const d = Math.max(0, now - ms)
  if (d < MIN) return 'just now'
  if (d < HOUR) return `${Math.floor(d / MIN)} min ago`
  if (d < DAY) return `${Math.floor(d / HOUR)} h ago`
  if (d < 2 * DAY) return 'Yesterday'
  if (d < 14 * DAY) return `${Math.floor(d / DAY)} days ago`
  if (d < 60 * DAY) return `${Math.floor(d / (7 * DAY))} weeks ago`
  if (d < 365 * DAY) return `${Math.floor(d / (30 * DAY))} months ago`
  return `${Math.floor(d / (365 * DAY))} years ago`
}

/** The friend's line under their name: Online, Last seen …, or Offline (appearing offline). */
export function presence(f: Pick<Friend, 'online' | 'last_seen'>, now: number): { text: string; online: boolean } {
  if (f.online) return { text: 'Online', online: true }
  if (f.last_seen == null) return { text: 'Offline', online: false }
  return { text: `Last seen ${ago(f.last_seen, now)}`, online: false }
}

/** Online first, then the most recently seen, then by handle (the list's "Online first"). */
export function onlineFirst<T extends Pick<Friend, 'online' | 'last_seen' | 'handle'>>(fs: T[]): T[] {
  return [...fs].sort(
    (a, b) =>
      Number(b.online) - Number(a.online) ||
      (b.last_seen ?? 0) - (a.last_seen ?? 0) ||
      a.handle.localeCompare(b.handle),
  )
}

/** Today, Yesterday, 3 Nov, or 3 Nov 2024 for another year. */
export function dayLabel(iso: string | null | undefined, now: Date): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, now)) return 'Today'
  const y = new Date(now)
  y.setDate(now.getDate() - 1)
  if (same(d, y)) return 'Yesterday'
  const opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }
  if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric'
  return d.toLocaleDateString('en-GB', opts)
}

export function speedLabel(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

export function siteLabel(s: string): string {
  return s === 'chesscom' ? 'Chess.com' : s === 'lichess' ? 'Lichess' : s
}

/** "5 / 1 / 3" */
export function recordLabel(r: Record3 | null | undefined): string {
  return r && r.games ? `${r.won} / ${r.drawn} / ${r.lost}` : ''
}

/** A ratings-column entry: its text and its tooltip (R2: the source of an ≈). */
export function ratingCell(r: ListRating, source: string): { label: string; value: string; title: string } {
  const label = speedLabel(r.speed)
  if (r.approx) {
    return {
      label,
      value: `≈${r.rating}`,
      title: `Lichess ${r.speed} ${r.lichess ?? ''}, about ${r.rating} on Chess.com (${source})`.replace('  ', ' '),
    }
  }
  return { label, value: String(r.rating), title: `Chess.com ${r.speed}` }
}

/** "+12 over 30 days" / "−18 over 30 days" / "No change over 30 days" / null */
export function deltaLabel(d: number | null): { text: string; tone: 'up' | 'down' | 'flat' } | null {
  if (d == null) return null
  if (d > 0) return { text: `+${d} over 30 days`, tone: 'up' }
  if (d < 0) return { text: `−${-d} over 30 days`, tone: 'down' }
  return { text: 'No change over 30 days', tone: 'flat' }
}

/** The ratings strip: the friend's three most-played modes, Chess.com first (R1), each with its ≈
 *  for a Lichess-only friend (R2). */
export function strip(ratings: Rating[], n = 3): Rating[] {
  return ratings.slice(0, n)
}

/** "Sicilian Defense: Najdorf Variation" → "Sicilian, Najdorf" (the mockups' short names). */
export function shortOpening(name: string | null | undefined): string {
  if (!name) return ''
  const [fam, rest] = name.split(':').map((s) => s.trim())
  const f = fam.replace(/ (Defense|Defence|Opening|Variation)$/, '')
  if (!rest) return fam
  const v = rest.split(',')[0].replace(/ (Variation|Attack|Line|System)$/, '').trim()
  return v ? `${f}, ${v}` : fam
}

/** Percentages of a W/D/L bar, summing to 100. */
export function wdlWidths(r: Record3): [number, number, number] {
  if (!r.games) return [0, 0, 0]
  const w = (100 * r.won) / r.games
  const d = (100 * r.drawn) / r.games
  return [w, d, Math.max(0, 100 - w - d)]
}

export function splitLine(s: Split): string {
  const parts = [`Mate ${s.by.mate}%`, `Resigned ${s.by.resigned}%`, `Time ${s.by.time}%`]
  if (s.by.other) parts.push(`Other ${s.by.other}%`)
  return parts.join('  ')
}

/** "From maxk's 312 Chess.com games in the last 12 months. No engine involved." */
export function scoutingNote(handle: string, sites: Record<string, number>, oldest: string | null, now: Date): string {
  const parts = Object.entries(sites)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${n} ${siteLabel(s)}`)
  if (!parts.length) return 'No games yet. No engine involved.'
  const total = Object.values(sites).reduce((a, b) => a + b, 0)
  const what = parts.length === 1 ? `${parts[0]} games` : `${total} games (${parts.join(', ')})`
  const year = oldest && now.getTime() - new Date(oldest).getTime() <= 367 * DAY
  const since = year ? 'in the last 12 months' : oldest ? `since ${new Date(oldest).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}` : ''
  return `From ${handle}'s ${what} ${since}. No engine involved.`.replace(' .', '.')
}

/** The time control as the mockups print it: "180+2" → "3+2", "600" → "10+0". */
export function tcLabel(tc: string | null | undefined): string {
  if (!tc) return ''
  const [b, i] = tc.split('+')
  const base = Number(b)
  if (!Number.isFinite(base)) return tc
  const m = base >= 60 ? (base % 60 === 0 ? String(base / 60) : (base / 60).toFixed(1)) : `${base}s`
  return `${m}+${i ?? 0}`
}

export function outcomeWord(o: string | null): string {
  return o === 'won' ? 'Won' : o === 'lost' ? 'Lost' : o === 'drawn' ? 'Drawn' : ''
}
