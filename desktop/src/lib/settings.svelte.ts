/** Connected-account usernames, persisted to localStorage (the same pattern as
 *  theme.svelte.ts / PlayScreen prefs). Core never reads this store — the synced
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

/** Trim + persist both fields. Caller is responsible for validation first. */
export function saveAccounts(lichess: string, chesscom: string): void {
  accounts.lichess = lichess.trim()
  accounts.chesscom = chesscom.trim()
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...accounts }))
}

// ── sync-analysis depth ──────────────────────────────────────────────────────
// Stockfish search depth used when a synced game has no usable Lichess evals.
// Lower = much faster bulk analysis (feasible to analyse a full back-catalog);
// higher = more reliable per-move classification. Persisted locally and passed
// to the sidecar as an explicit RPC param (the same pattern as accounts).

const DEPTH_KEY = 'zugzwang-analysis-depth'

export interface DepthPreset {
  label: string
  depth: number
  blurb: string
}

/** Presets shown in Settings. Depths must stay within the sidecar's clamp
 *  range (ANALYSIS_DEPTH_MIN..MAX = 8..18). `depth` is what gets sent. */
export const DEPTH_PRESETS: DepthPreset[] = [
  { label: 'Fast', depth: 10, blurb: '~5s/game · best for analyzing your whole history' },
  { label: 'Balanced', depth: 14, blurb: '~30s/game · the default' },
  { label: 'Deep', depth: 18, blurb: '~3min/game · most accurate' },
]

const DEFAULT_DEPTH = 14

function initialDepth(): number {
  // `Number(null)` is 0, not NaN, so an isFinite guard alone lets a missing key
  // through and clamps to the floor. Fresh installs silently analysed at 8.
  const stored = localStorage.getItem(DEPTH_KEY)
  if (stored === null) return DEFAULT_DEPTH
  const raw = Number(stored)
  if (!Number.isFinite(raw) || raw <= 0) return DEFAULT_DEPTH
  return Math.max(8, Math.min(18, Math.round(raw)))
}

export const analysisDepth = $state<{ value: number }>({ value: initialDepth() })

/** Persist the chosen sync-analysis depth (clamped to the supported range). */
export function saveAnalysisDepth(depth: number): void {
  analysisDepth.value = Math.max(8, Math.min(18, Math.round(depth)))
  localStorage.setItem(DEPTH_KEY, String(analysisDepth.value))
}
