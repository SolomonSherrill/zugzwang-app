/** The last successful sync per source, stamped by the frontend when a sync_done arrives (the
 *  database keeps no sync time) and kept in localStorage. Settings' "last synced" line and the
 *  Games header's "Synced today at 21:12" read it. (The old Games screen's filter state that also
 *  lived here moved to games/gamesState.svelte.ts with the rebuild, UI-BUILD-3 E.)
 */

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
