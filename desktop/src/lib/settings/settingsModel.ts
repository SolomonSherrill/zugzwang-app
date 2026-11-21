/**
 * Settings, rebuilt (UI-BUILD-2 E1; DESIGN.md "Settings", rulings 17 and 20): the words and
 * figures the screen shows, from stored data only (sync_status, engine_status, books_status,
 * the last-sync stamps the Games screen already keeps). Pure, so it is tested in Node.
 */
import type { BookInfo, EngineStatus, SyncProgressEvent, SyncSourceCounts, SyncStatus, UsernameCheck, UsernameChecks } from '../api'

export type Source = 'lichess' | 'chesscom'

export const SOURCE_NAME: Record<Source, string> = { chesscom: 'Chess.com', lichess: 'Lichess' }

/** Ruling 17's line, word for word. */
export const DEPTH_LINE =
  'Every game is analysed at depth 14, so all your games compare. To look deeper at one game, use Analyse again in its review.'

/** Ruling 20's sentence under the books, word for word from the mockup. */
export const BOOK_SWITCH_LINE = 'Switching books relabels book moves in your games.'

const fmt = (n: number) => n.toLocaleString('en-US')
const plural = (n: number, one: string, many = one + 's') => (n === 1 ? one : many)

/** The sources with a saved username, in the mockup's order (Chess.com first). */
export function connected(accounts: { lichess: string; chesscom: string }): Source[] {
  return (['chesscom', 'lichess'] as Source[]).filter((s) => accounts[s].trim().length > 0)
}

/** Game sync's first line: the synced games still waiting for their depth-14 analysis.
 *  Named by platform when only one has any. Null with no account. */
export function waitingLine(status: SyncStatus, sources: Source[]): string | null {
  if (sources.length === 0) return null
  const by = sources.map((s) => [s, status[s]?.pending ?? 0] as const)
  const total = by.reduce((n, [, p]) => n + p, 0)
  if (total === 0) return 'Every synced game is analysed'
  const withAny = by.filter(([, p]) => p > 0)
  const where = withAny.length === 1 ? ` from ${SOURCE_NAME[withAny[0][0]]}` : ''
  return `${fmt(total)} ${plural(total, 'game')}${where} waiting for analysis`
}

/** "3,615 imported, last synced today at 21:12": the games synced from the connected
 *  accounts, and the latest sync this computer recorded (none recorded: the count alone). */
export function importedLine(
  status: SyncStatus,
  sources: Source[],
  lastSynced: Partial<Record<Source, string | null>>,
  now: Date = new Date(),
): string | null {
  if (sources.length === 0) return null
  const n = sources.reduce((acc, s) => acc + (status[s]?.synced ?? 0), 0)
  const stamps = sources.map((s) => lastSynced[s]).filter((x): x is string => !!x && !Number.isNaN(Date.parse(x)))
  const latest = stamps.sort().at(-1) ?? null
  const when = latest ? whenText(new Date(latest), now) : null
  return `${fmt(n)} imported${when ? `, last synced ${when}` : ''}`
}

/** Games that a sync stopped retrying (VAL-DEATH-2): said, never hidden. */
export function attentionLine(status: SyncStatus, sources: Source[]): string | null {
  const n = sources.reduce((acc, s) => acc + ((status[s] as SyncSourceCounts | undefined)?.needsAttention ?? 0), 0)
  return n > 0 ? `${fmt(n)} ${plural(n, 'game')} could not be analysed and are left out; Games lists them.` : null
}

const pad = (n: number) => String(n).padStart(2, '0')
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "today at 21:12", "yesterday at 09:03", "on 18 Nov at 21:12" (local time). */
export function whenText(t: Date, now: Date = new Date()): string {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diff = Math.round((day(now) - day(t)) / 86_400_000)
  const hm = `${pad(t.getHours())}:${pad(t.getMinutes())}`
  if (diff === 0) return `today at ${hm}`
  if (diff === 1) return `yesterday at ${hm}`
  const year = t.getFullYear() !== now.getFullYear() ? ` ${t.getFullYear()}` : ''
  return `on ${t.getDate()} ${MONTHS[t.getMonth()]}${year} at ${hm}`
}

/** What a running sync is doing, for its panel. */
export function progressText(p: SyncProgressEvent | null): string {
  const name = p?.source ? SOURCE_NAME[p.source as Source] ?? '' : ''
  if (!p || p.phase === 'fetching') return `Syncing: fetching your games${name ? ` from ${name}` : ''}…`
  if (!p.total) return `Syncing: analysing${name ? ` ${name}` : ''} games at depth 14…`
  return `Syncing: analysing${name ? ` ${name}` : ''} games at depth 14, ${fmt(p.done)} of ${fmt(p.total)}.`
}

export function progressFraction(p: SyncProgressEvent | null): number | null {
  return p && p.phase === 'analyzing' && p.total ? Math.min(1, p.done / p.total) : null
}

/** The finished panel's sentence, from the run's sync_done events. */
export function finishedText(done: { new: number; analyzed: number }[]): string {
  const added = done.reduce((n, d) => n + d.new, 0)
  const analysed = done.reduce((n, d) => n + d.analyzed, 0)
  if (added === 0 && analysed === 0) return 'Sync finished: no new games.'
  return `Sync finished: ${fmt(added)} new ${plural(added, 'game')}, ${fmt(analysed)} analysed.`
}

/** The engine row: its name, and how it was found. */
export function engineTitle(e: EngineStatus): string {
  if (e.name) return e.name
  const file = e.path?.split(/[\\/]/).at(-1)
  return file || 'Stockfish'
}

export function engineSource(e: EngineStatus): string {
  switch (e.source) {
    case 'bundled':
      return 'Bundled with the app'
    case 'chosen':
      return 'The binary you chose'
    case 'path':
      return 'Found on your PATH'
    case 'env':
      return 'Set by ZUGZWANG_STOCKFISH'
    default:
      return e.path ?? ''
  }
}

/** "151 MB", "1.32 GB": decimal units, three figures (the mockup's sizes). */
export function bookSize(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`
  return `${Math.round(bytes / 1e6)} MB`
}

/** A book's floor, as the book was built (opening-index `book --min-games N`: a move enters
 *  when it was played in N games or more). */
export function bookFloor(b: BookInfo): string {
  return `moves played in ${b.minGames}+ games`
}

// ── the username check on Save (UI-BUILD-3 G, ruling 5) ─────────────────────────

/** A field's check: asked and waiting, or the site's answer. */
export type CheckState = { status: 'checking' } | UsernameCheck

/** What a Save starts: each non-empty saved name is being checked; an empty one is not. */
export function checksStarted(saved: { chesscom: string; lichess: string }): Record<Source, CheckState | null> {
  return {
    chesscom: saved.chesscom.trim() ? { status: 'checking' } : null,
    lichess: saved.lichess.trim() ? { status: 'checking' } : null,
  }
}

/** The reply laid over what was asked; a site the reply leaves out stays unanswered. */
export function checksAnswered(
  started: Record<Source, CheckState | null>,
  reply: UsernameChecks,
): Record<Source, CheckState | null> {
  const one = (s: Source): CheckState | null =>
    started[s] === null ? null : (reply[s] ?? { status: 'unreachable', message: 'No answer' })
  return { chesscom: one('chesscom'), lichess: one('lichess') }
}

/** The check could not be made at all (the sidecar failed or is older than the check): each
 *  name that was being checked reads as a site that could not be reached. */
export function checksFailed(started: Record<Source, CheckState | null>, message: string): Record<Source, CheckState | null> {
  const one = (s: Source): CheckState | null => (started[s] === null ? null : { status: 'unreachable', message })
  return { chesscom: one('chesscom'), lichess: one('lichess') }
}

/** The line beside a username field: "Found", "No Chess.com player named X", "Couldn't reach
 *  Chess.com to check; saved anyway." (the reason in `detail`, for a tooltip), "Checking…". */
export function checkLine(
  source: Source,
  name: string,
  c: CheckState | null,
): { text: string; tone: 'checking' | 'found' | 'missing' | 'unreachable'; detail: string | null } | null {
  if (!c) return null
  const site = SOURCE_NAME[source]
  switch (c.status) {
    case 'checking':
      return { text: 'Checking…', tone: 'checking', detail: null }
    case 'found':
      return { text: 'Found', tone: 'found', detail: null }
    case 'not_found':
      return { text: `No ${site} player named ${name.trim()}`, tone: 'missing', detail: null }
    default:
      return { text: `Couldn't reach ${site} to check; saved anyway.`, tone: 'unreachable', detail: c.message ?? null }
  }
}
