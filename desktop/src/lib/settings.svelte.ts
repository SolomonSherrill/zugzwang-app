/** Connected-account usernames, persisted to localStorage (the same pattern as
 *  theme.svelte.ts / Play prefs). Core never reads this store — the synced
 *  usernames are passed to the sidecar as explicit RPC params. */

const STORAGE_KEY = 'zugzwang-accounts'

export interface Accounts {
  lichess: string
  chesscom: string
}

function initial(): Accounts {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    return {
      lichess: typeof saved.lichess === 'string' ? saved.lichess : '',
      chesscom: typeof saved.chesscom === 'string' ? saved.chesscom : '',
    }
  } catch {
    return { lichess: '', chesscom: '' }
  }
}

export const accounts = $state<Accounts>(initial())

/** True when at least one account is connected. */
export function hasAnyAccount(): boolean {
  return accounts.lichess.length > 0 || accounts.chesscom.length > 0
}

/** Validate a username: trimmed, no internal whitespace. Empty is allowed
 *  (an empty field means "no account"). Returns an error string or null. */
export function validateUsername(raw: string): string | null {
  const value = raw.trim()
  if (value.length === 0) return null
  if (/\s/.test(value)) return 'No spaces allowed'
  return null
}

/** CR1 (FIX-B6, owner 2026-11-23): a save that adds or changes a username, not one that only removes one. */
export function namesAddedOrChanged(before: Accounts, after: Accounts): boolean {
  return (['lichess', 'chesscom'] as const).some((k) => after[k] !== '' && after[k] !== before[k])
}

/** The colour repair the app runs by itself (CR1; "Fix game colours" left Settings): re-reads which side the
 *  user played in each synced game from its players' names, with the names just saved. */
function repairColors(names: Accounts): void {
  void import('./api')
    .then(({ api }) => api.repairColors(names.lichess, names.chesscom))
    .then((r) => {
      if (r.changed) console.info(`colour repair after a username change: ${r.changed} games`)
    })
    .catch((e) => console.warn('colour repair after a username change failed', e))
}

/** Trim + persist both fields. Caller is responsible for validation first. When a username was added or changed,
 *  the colour repair runs once with the saved names (CR1); *repair* is for tests. Returns whether it ran. */
export function saveAccounts(lichess: string, chesscom: string, repair: (names: Accounts) => void = repairColors): boolean {
  const before = { ...accounts }
  accounts.lichess = lichess.trim()
  accounts.chesscom = chesscom.trim()
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...accounts }))
  const after = { ...accounts }
  if (!namesAddedOrChanged(before, after)) return false
  repair(after)
  return true
}

// ── no sync depth (ruling 17, 2026-11-20) ─────────────────────────────────────
// Settings once offered Fast / Balanced / Deep presets (depth 10 / 14 / 18), stored under this
// key and sent with every sync. Every game is now analysed at depth 14 so all games compare;
// one game goes deeper only through Analyse again. The old choice is cleared on load.

export const LEGACY_DEPTH_KEY = 'zugzwang-analysis-depth'

try {
  globalThis.localStorage?.removeItem(LEGACY_DEPTH_KEY)
} catch {
  /* private mode or no storage: nothing stored to clear */
}
