/**
 * Handle rules (FRIENDS.md ruling A3): 3 to 20 characters of [a-z0-9_-] (capitals allowed and kept as
 * typed; uniqueness ignores case, by the column's NOCASE collation), not on the reserved list, and not
 * changeable in stage 1 (there is no endpoint that changes one).
 */
export const HANDLE_RE = /^[A-Za-z0-9_-]{3,20}$/

/** Compared after lower-casing and dropping _ and - ("Ad_Min" is "admin"). */
export const RESERVED: ReadonlySet<string> = new Set([
  'admin', 'administrator', 'admins', 'root', 'sysadmin', 'system', 'superuser',
  'support', 'help', 'helpdesk', 'helpcenter', 'service', 'customerservice',
  'zugzwang', 'zugzwangapp', 'official', 'staff', 'team', 'moderator', 'mod', 'mods', 'owner',
  'security', 'privacy', 'legal', 'terms', 'abuse', 'report', 'reports', 'safety', 'trust',
  'contact', 'info', 'mail', 'email', 'noreply', 'postmaster', 'webmaster', 'hostmaster',
  'api', 'www', 'server', 'status', 'bot', 'robot',
  'null', 'undefined', 'nobody', 'anonymous', 'guest', 'unknown', 'deleted', 'removed',
  'me', 'you', 'friend', 'friends', 'account', 'accounts', 'settings', 'signup', 'signin',
  'login', 'logout', 'register', 'delete',
  'lichess', 'chesscom', 'chess', 'stockfish', 'fide', 'uscf', 'ncmec',
])

/** Reserved as a prefix too: "zugzwang_team", "admin2" */
export const RESERVED_PREFIXES: readonly string[] = ['zugzwang', 'admin', 'support', 'official', 'moderator']

export type HandleProblem = 'invalid' | 'reserved'

export function handleProblem(handle: string): HandleProblem | null {
  if (!HANDLE_RE.test(handle)) return 'invalid'
  const k = handle.toLowerCase().replace(/[_-]/g, '')
  if (RESERVED.has(k) || RESERVED_PREFIXES.some((p) => k.startsWith(p))) return 'reserved'
  return null
}
