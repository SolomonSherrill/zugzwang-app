/**
 * The Games screen's pure logic (UI-BUILD-3 E; DESIGN.md fourth rulings, 7; stacked rows,
 * UI-BUILD-4 B, fifth rulings 5; mockup design/mockups/MinimalGames.html): the filters and what
 * they send, the rows' words and their two player lines, the month headers, the import count, the
 * last-sync line. Every figure is read off the stored fields the
 * games_page RPC returns.
 */
import type { GameSource, GamesItem, GamesMonth, GamesPageParams, GamesSort, GamesSpeed } from '../api'
import { shortTimeControl } from '../home/homeModel'
import { whenText } from '../settings/settingsModel'

export type ResultFilter = 'all' | 'win' | 'draw' | 'loss'
export type ColorFilter = 'all' | 'white' | 'black'
export type SourceFilter = 'all' | GameSource
export type RatedFilter = 'all' | 'rated' | 'casual'
export type DateFilter = 'all' | 'week' | 'month' | '3months' | 'custom'
export type AnalysisFilter = 'all' | 'analyzed' | 'unanalyzed'

export interface GamesFilters {
  search: string
  result: ResultFilter
  color: ColorFilter
  speeds: GamesSpeed[]
  source: SourceFilter
  rated: RatedFilter
  date: DateFilter
  /** "YYYY-MM-DD", local days, both inclusive */
  customFrom: string
  customTo: string
  analysis: AnalysisFilter
  opening: string
  sort: GamesSort
}

export const PAGE = 50

export function defaultFilters(): GamesFilters {
  return {
    search: '',
    result: 'all',
    color: 'all',
    speeds: [],
    source: 'all',
    rated: 'all',
    date: 'all',
    customFrom: '',
    customTo: '',
    analysis: 'all',
    opening: '',
    sort: 'recent',
  }
}

/** The filters inside "More filters" that are set (for the button's count). */
export function moreFiltersSet(f: GamesFilters): number {
  return [f.source !== 'all', f.rated !== 'all', f.date !== 'all', f.analysis !== 'all', f.opening.trim() !== ''].filter(Boolean)
    .length
}

/** True when any filter or the search narrows the list (the sort does not). */
export function filtersActive(f: GamesFilters): boolean {
  return (
    f.search.trim() !== '' ||
    f.result !== 'all' ||
    f.color !== 'all' ||
    f.speeds.length > 0 ||
    moreFiltersSet(f) > 0
  )
}

export function toggleSpeed(speeds: GamesSpeed[], s: GamesSpeed): GamesSpeed[] {
  return speeds.includes(s) ? speeds.filter((x) => x !== s) : [...speeds, s]
}

const DAY = 86_400_000

/** The date filter as instants: since inclusive, until exclusive. "Last week" is the last 7 days
 *  (30, 90), as the old screen counted them; a custom range is whole local days, both ends kept. */
export function dateRange(
  f: Pick<GamesFilters, 'date' | 'customFrom' | 'customTo'>,
  now: Date = new Date(),
): { since?: string; until?: string } {
  const days = { week: 7, month: 30, '3months': 90 } as Record<string, number>
  if (f.date in days) return { since: new Date(now.getTime() - days[f.date] * DAY).toISOString() }
  if (f.date !== 'custom') return {}
  const local = (s: string): Date | null => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
    return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
  }
  const from = local(f.customFrom)
  const to = local(f.customTo)
  const out: { since?: string; until?: string } = {}
  if (from) out.since = from.toISOString()
  if (to) out.until = new Date(to.getFullYear(), to.getMonth(), to.getDate() + 1).toISOString()
  return out
}

/** What one page asks the sidecar for. */
export function pageParams(f: GamesFilters, offset: number, limit = PAGE, now: Date = new Date()): GamesPageParams {
  const p: GamesPageParams = { sort: f.sort, offset, limit, ...dateRange(f, now) }
  if (f.search.trim()) p.search = f.search.trim()
  if (f.result !== 'all') p.result = f.result
  if (f.color !== 'all') p.color = f.color
  if (f.speeds.length) p.speeds = [...f.speeds]
  if (f.source !== 'all') p.source = f.source
  if (f.rated !== 'all') p.rated = f.rated
  if (f.analysis !== 'all') p.analysis = f.analysis
  if (f.opening.trim()) p.opening = f.opening.trim()
  return p
}

export const SORT_LABEL: Record<GamesSort, string> = {
  recent: 'Newest first',
  oldest: 'Oldest first',
  accuracy_low: 'Lowest accuracy first',
  accuracy_high: 'Highest accuracy first',
  opening: 'By opening',
}

/** Month headers belong to a list in date order only. */
export const datedSort = (s: GamesSort) => s === 'recent' || s === 'oldest'

const fmt = (n: number) => n.toLocaleString('en-US')
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** "2026-11" → "November 2026". */
export function monthLabel(key: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(key)
  return m ? `${MONTH_NAMES[Number(m[2]) - 1]} ${m[1]}` : key
}

/** "14 won, 9 lost, 1 drawn" (the mockup's order; every part, zeros too). */
export function recordText(m: Pick<GamesMonth, 'won' | 'lost' | 'drawn'>): string {
  return `${fmt(m.won)} won, ${fmt(m.lost)} lost, ${fmt(m.drawn)} drawn`
}

/** The local month of a stored time, keyed as the sidecar keys it. */
export function monthOf(iso: string): string | null {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export type ListEntry = { kind: 'month'; month: GamesMonth } | { kind: 'game'; game: GamesItem; index: number }

/** The loaded games with a header before each month's first game (date order only). A month the
 *  sidecar did not send a record for gets none (it cannot happen; nothing is guessed). */
export function withMonths(games: GamesItem[], months: GamesMonth[], sort: GamesSort): ListEntry[] {
  const out: ListEntry[] = []
  const by = new Map(months.map((m) => [m.month, m]))
  let last: string | null = null
  games.forEach((game, index) => {
    if (datedSort(sort)) {
      const k = monthOf(game.playedAt)
      if (k !== last) {
        last = k
        const m = k ? by.get(k) : undefined
        if (m) out.push({ kind: 'month', month: m })
      }
    }
    out.push({ kind: 'game', game, index })
  })
  return out
}

/** "3,620 games"; with filters, "212 of 3,620 games". */
export function countText(total: number, all: number, filtered: boolean): string {
  const word = (n: number) => (n === 1 ? 'game' : 'games')
  return filtered && total !== all ? `${fmt(total)} of ${fmt(all)} ${word(all)}` : `${fmt(total)} ${word(total)}`
}

export const RESULT_WORD = { win: 'Won', loss: 'Lost', draw: 'Drawn' } as const

/** The Result cell: Won / Lost / Drawn from the user's side; an unfinished game or one whose
 *  side is unknown shows its score instead, with no colour. */
export function resultCell(g: Pick<GamesItem, 'outcome' | 'result'>): { word: string; tone: 'win' | 'loss' | 'draw' | null } {
  if (g.outcome) return { word: RESULT_WORD[g.outcome], tone: g.outcome }
  if (g.result === '1/2-1/2') return { word: 'Drawn', tone: 'draw' }
  if (g.result === '*') return { word: 'Unfinished', tone: null }
  return { word: g.result.replace('-', '–'), tone: null }
}

/** The Opponent cell: the name and, in brackets, the rating, or Stockfish's level. */
export function opponentCell(g: Pick<GamesItem, 'source' | 'playerColor' | 'white' | 'black' | 'whiteElo' | 'blackElo' | 'skillLevel' | 'ladderVersion'>): {
  name: string
  detail: string | null
} {
  if (g.source === 'local') {
    // A level from before the ladder was recorded is not today's level of that number (F5).
    return { name: 'Stockfish', detail: g.ladderVersion === null ? `Level ${g.skillLevel}, old scale` : `Level ${g.skillLevel}` }
  }
  const side = g.playerColor === 'black' ? 'white' : 'black'
  const name = (side === 'white' ? g.white : g.black)?.trim() || 'Unknown'
  const elo = side === 'white' ? g.whiteElo : g.blackElo
  return { name, detail: elo != null ? String(elo) : null }
}

export function userAccuracy(g: Pick<GamesItem, 'analyzed' | 'playerColor' | 'whiteAccuracy' | 'blackAccuracy'>): number | null {
  if (!g.analyzed || !g.playerColor) return null
  return g.playerColor === 'white' ? g.whiteAccuracy : g.blackAccuracy
}

export function opponentAccuracy(g: Pick<GamesItem, 'analyzed' | 'playerColor' | 'whiteAccuracy' | 'blackAccuracy'>): number | null {
  if (!g.analyzed || !g.playerColor) return null
  return g.playerColor === 'white' ? g.blackAccuracy : g.whiteAccuracy
}

export const accText = (v: number | null) => (v == null ? '—' : v.toFixed(1))

export type Tone = 'bright' | 'dim' | 'off'

/** One of a row's two lines (UI-BUILD-4 B, fifth rulings 5): the colour square, the name and its
 *  rating or level, and that player's accuracy. */
export interface PlayerLine {
  color: 'white' | 'black'
  name: string
  /** "(1438)", "(Level 10)"; null when there is no rating (nothing drawn, no brackets) */
  detail: string | null
  /** the user's own line */
  you: boolean
  /** the opponent's name bright, yours dimmer */
  nameTone: 'bright' | 'dim'
  /** "90.7", or "—" when not analysed */
  accuracy: string
  /** your accuracy bright, theirs dim, "—" off */
  accTone: Tone
}

/** A row's two lines, White on top. In a game played here the engine's line is "Stockfish
 *  (Level N)" as before (F5's "old scale" kept) and the user's line is the stored name ("You").
 *  A game whose side is unknown has no "yours": both names bright, both accuracies dim. */
export function playerLines(
  g: Pick<GamesItem, 'source' | 'playerColor' | 'white' | 'black' | 'whiteElo' | 'blackElo' | 'skillLevel' | 'ladderVersion' | 'analyzed' | 'whiteAccuracy' | 'blackAccuracy'>,
): [PlayerLine, PlayerLine] {
  const line = (color: 'white' | 'black'): PlayerLine => {
    const you = g.playerColor === color
    const engine = g.source === 'local' && !!g.playerColor && !you
    const stored = (color === 'white' ? g.white : g.black)?.trim()
    const elo = color === 'white' ? g.whiteElo : g.blackElo
    const level = g.ladderVersion === null ? `Level ${g.skillLevel}, old scale` : `Level ${g.skillLevel}`
    const acc = g.analyzed ? (color === 'white' ? g.whiteAccuracy : g.blackAccuracy) : null
    return {
      color,
      name: engine ? 'Stockfish' : stored || 'Unknown',
      detail: engine ? `(${level})` : elo != null ? `(${elo})` : null,
      you,
      nameTone: you ? 'dim' : 'bright',
      accuracy: accText(acc),
      accTone: acc == null ? 'off' : you ? 'bright' : 'dim',
    }
  }
  return [line('white'), line('black')]
}

/** The line under the opening: what the row's analysis is doing, or "Not analysed" (with the
 *  row's Analyse beside it on hover or focus); null for an analysed game. */
export function analysisNote(
  g: Pick<GamesItem, 'id' | 'analyzed'>,
  run: { id: number; done: number; total: number } | null,
  queue: number[],
  error: string | undefined,
): { text: string; canAnalyse: boolean } | null {
  if (run?.id === g.id) return { text: run.total ? `Analysing ${run.done} of ${run.total}` : 'Analysing…', canAnalyse: false }
  if (queue.includes(g.id)) return { text: 'Waiting to analyse', canAnalyse: false }
  if (g.analyzed) return null
  return { text: error ? 'Analysis stopped' : 'Not analysed', canAnalyse: true }
}

/** "3+2", "10+0", "Daily"; an unusual control as stored; "—" for none. */
export function timeText(tc: string | null): string {
  if (!tc) return '—'
  return shortTimeControl(tc) ?? tc
}

export const SOURCE_LABEL: Record<GameSource, string> = {
  chesscom: 'Chess.com',
  lichess: 'Lichess',
  local: 'Played here',
  imported: 'Imported',
}

const SHORT_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Today", "Yesterday", "18 Nov"; another year's date adds the year ("18 Nov 2025"). */
export function dateText(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(now) - day(d)) / DAY)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  const base = `${d.getDate()} ${SHORT_MONTHS[d.getMonth()]}`
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`
}

/** The header's line: the latest sync this computer recorded for a connected account
 *  ("Synced today at 21:12"), null when none is recorded. The stamps are the ones Settings
 *  reads (`lastSynced`, written when a sync_done arrives); the database keeps no sync time. */
export function syncedText(
  stamps: Partial<Record<'lichess' | 'chesscom', string | null>>,
  sources: ('lichess' | 'chesscom')[],
  now: Date = new Date(),
): string | null {
  const ok = sources.map((s) => stamps[s]).filter((x): x is string => !!x && !Number.isNaN(Date.parse(x)))
  const latest = ok.sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1)
  return latest ? `Synced ${whenText(new Date(latest), now)}` : null
}

/** J / K: the next row, clamped; nothing selected yet starts at the first. */
export function step(cur: number, delta: 1 | -1, length: number): number {
  if (length === 0) return -1
  if (cur < 0) return 0
  return Math.max(0, Math.min(length - 1, cur + delta))
}

/** How many games a pasted PGN holds, as the import will count them: one per header block
 *  (lines starting "[Tag "), or one for bare movetext with no headers. Live, on every keystroke. */
export function countPgnGames(text: string): number {
  let games = 0
  let inHeaders = false
  let movetext = false
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    if (/^\[[A-Za-z0-9_]+\s+"/.test(line)) {
      if (!inHeaders) games++
      inHeaders = true
    } else {
      inHeaders = false
      movetext = true
    }
  }
  if (games === 0 && movetext && /\d+\s*\.\s*\S|^(?:[NBRQK][a-h1-8]?x?[a-h][1-8]|[a-h]x?[a-h]?[1-8]|O-O)\b/.test(text.trim())) return 1
  return games
}

export const importLabel = (n: number) => (n === 0 ? 'Import' : `Import ${fmt(n)} ${n === 1 ? 'game' : 'games'}`)

/** What a bulk run (a sync, Analyse now, or Import PGN's analysis) is doing, for its panel. */
export function runText(kind: 'sync' | 'analyse', p: { phase: 'fetching' | 'analyzing'; done: number; total: number } | null, syncLine: string): string {
  if (kind === 'sync') return syncLine
  if (!p || !p.total) return 'Analysing games at depth 14…'
  return `Analysing games at depth 14: ${fmt(p.done)} of ${fmt(p.total)}.`
}

/** The Opening column's name, shortened as the mockup draws it (UI-BUILD-3 E): "Italian Game: Two
 *  Knights Defense" → "Italian, Two Knights", "Scandinavian Defense: Valencian Variation" →
 *  "Scandinavian, Valencian". A name with no variation stays whole ("Queen's Pawn Game"). The row
 *  keeps the full name as its title. */
export function shortOpening(name: string | null): string {
  if (!name) return 'Unknown opening'
  const [family, ...rest] = name.split(/:\s*/)
  if (!rest.length) return name
  const fam = family.replace(/\s+(Defense|Defence|Game|Opening)$/, '')
  const parts = rest.join(', ').split(/,\s*/).map((p) => p.replace(/\s+(Variation|Defense|Defence)$/, '')).filter(Boolean)
  return [fam, ...parts].join(', ')
}
