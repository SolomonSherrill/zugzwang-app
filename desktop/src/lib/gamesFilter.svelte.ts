/** Past Games filter / search / sort state, kept at module scope so it survives
 *  navigating into a game's detail view and back (the list component may unmount,
 *  but this state persists for the session). Plus a small localStorage record of
 *  the last successful sync per source — there is no backend timestamp, so the
 *  frontend stamps it when a sync finishes (same pattern as settings.svelte.ts).
 */

export type ResultFilter = 'all' | 'win' | 'draw' | 'loss'
export type ColorFilter = 'all' | 'white' | 'black'
export type SourceFilter = 'all' | 'local' | 'chesscom' | 'lichess' | 'imported'
export type SpeedFilter = 'all' | 'bullet' | 'blitz' | 'rapid' | 'classical'
export type RatedFilter = 'all' | 'rated' | 'casual'
export type DateFilter = 'all' | 'week' | 'month' | '3months' | 'custom'
export type AnalysisFilter = 'all' | 'analyzed' | 'unanalyzed'
export type SortOrder = 'recent' | 'accuracy_low' | 'accuracy_high' | 'opening'

export interface GamesFilterState {
  search: string
  result: ResultFilter
  color: ColorFilter
  source: SourceFilter
  speed: SpeedFilter
  rated: RatedFilter
  opening: string
  date: DateFilter
  customFrom: string
  customTo: string
  analysis: AnalysisFilter
  sort: SortOrder
  moreOpen: boolean
  scrollTop: number
}

export function defaultFilters(): GamesFilterState {
  return {
    search: '',
    result: 'all',
    color: 'all',
    source: 'all',
    speed: 'all',
    rated: 'all',
    opening: '',
    date: 'all',
    customFrom: '',
    customTo: '',
    analysis: 'all',
    sort: 'recent',
    moreOpen: false,
    scrollTop: 0,
  }
}

export const gamesFilter = $state<GamesFilterState>(defaultFilters())

/** Reset every filter/search/sort to its default (the "Clear filters" action).
 *  Leaves moreOpen + scrollTop alone — those are view state, not filters. */
export function clearFilters(): void {
  const d = defaultFilters()
  gamesFilter.search = d.search
  gamesFilter.result = d.result
  gamesFilter.color = d.color
  gamesFilter.source = d.source
  gamesFilter.speed = d.speed
  gamesFilter.rated = d.rated
  gamesFilter.opening = d.opening
  gamesFilter.date = d.date
  gamesFilter.customFrom = d.customFrom
  gamesFilter.customTo = d.customTo
  gamesFilter.analysis = d.analysis
}

/** True when any filter/search narrows the list (sort + view state excluded). */
export function filtersActive(): boolean {
  return (
    gamesFilter.search.trim() !== '' ||
    gamesFilter.result !== 'all' ||
    gamesFilter.color !== 'all' ||
    gamesFilter.source !== 'all' ||
    gamesFilter.speed !== 'all' ||
    gamesFilter.rated !== 'all' ||
    gamesFilter.opening.trim() !== '' ||
    gamesFilter.date !== 'all' ||
    gamesFilter.analysis !== 'all'
  )
}

// ── last-synced timestamps (frontend-only; no backend stores this) ────────────

const LAST_SYNCED_KEY = 'zugzwang-last-synced'

export interface LastSynced {
  lichess: string | null
  chesscom: string | null
}

function initialLastSynced(): LastSynced {
  try {
    const saved = JSON.parse(localStorage.getItem(LAST_SYNCED_KEY) ?? '{}')
    return {
      lichess: typeof saved.lichess === 'string' ? saved.lichess : null,
      chesscom: typeof saved.chesscom === 'string' ? saved.chesscom : null,
    }
  } catch {
    return { lichess: null, chesscom: null }
  }
}

export const lastSynced = $state<LastSynced>(initialLastSynced())

/** Stamp a source as just-synced (ISO now) and persist. */
export function markSynced(source: 'lichess' | 'chesscom'): void {
  lastSynced[source] = new Date().toISOString()
  localStorage.setItem(LAST_SYNCED_KEY, JSON.stringify({ ...lastSynced }))
}

/** "2h ago" / "just now" / "3d ago" — compact relative time, or null. */
export function relativeTime(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 45) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.round(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  const months = Math.round(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.round(days / 365)}y ago`
}
