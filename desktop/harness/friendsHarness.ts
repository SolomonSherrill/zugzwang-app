/**
 * Friends in the browser harness (FRIENDS-1 E): the friends_ methods answered from
 * `friends_fixtures.json`, which tests/make_friends_harness_fixtures.py writes with the sidecar's own
 * code over synthetic games (every name made up). Never the network, never a keychain.
 *
 *   ?screen=friends                       the friends list (signed in)
 *   ?screen=friends&state=friends-signup  not signed in: sign up (Create account shows the code)
 *   ?screen=friend&friend=<handle>        a friend's profile
 *   ?state=friends-unconfigured           no Friends server set up
 *   ?state=friends-cc-waiting             a pending Chess.com link Chess.com has not shown yet (BETA-5 K3)
 *   ?state=friends-cc-expired             … whose code expired
 *   ?state=friends-cc-code                … made, not yet checked
 *   the save dialog: window.__TAURI_INTERNALS__ (a test's init script) answers 'plugin:dialog|save'
 */
type Handler = (params: Record<string, unknown>, emit: (e: string, d: Record<string, unknown>) => void) => unknown

export interface FriendsFixtures {
  now: number
  handle: string
  me: Record<string, string>
  list: { friends: { handle: string }[]; incoming: { id: number }[]; outgoing: { id: number }[]; blocked: unknown[] }
  profiles: Record<string, { recent: unknown[]; recentTotal: number }>
  games: Record<string, unknown>
  ratingSource: { source: string; url: string; retrieved: string }
  recoveryCode: string
  me_linked: unknown[]
}

export function friendsHandlers(fx: FriendsFixtures | null, scenario: string | undefined): Record<string, Handler> {
  if (!fx) return {}
  let signedIn = scenario !== 'friends-signup'
  const state = () => ({
    enabled: true,
    configured: scenario !== 'friends-unconfigured',
    server: 'http://127.0.0.1:8799',
    keystore: { kind: 'file', label: 'the harness', available: true },
    signedIn,
    handle: signedIn ? fx.handle : null,
    settings: { shareGames: false, appearOffline: false, chatEnabled: true },
    ratingSource: fx.ratingSource,
  })
  const list = structuredClone(fx.list)
  const ccHour = Math.floor(fx.now / 3_600_000)
  const ccPending = (state: 'code' | 'waiting' | 'expired') => ({
    state,
    username: 'you_demo',
    code: 'ZZ-7K4Q2M9D',
    expires: (ccHour + 24) * 3_600_000,
    lastCheck: state === 'code' ? null : fx.now - 4 * 60_000,
    nextCheck: state === 'waiting' ? fx.now + 11 * 60_000 : null,
    error: null,
  })
  let cc: Record<string, unknown> =
    scenario === 'friends-cc-waiting' ? ccPending('waiting') : scenario === 'friends-cc-expired' ? ccPending('expired') : scenario === 'friends-cc-code' ? ccPending('code') : { state: 'none' }
  const saved: string[] = []
  const calls = (): [string, string][] => {
    const w = globalThis as unknown as { __zzFriendsCalls?: [string, string][] }
    return (w.__zzFriendsCalls ??= [])
  }
  return {
    friends_status: () => state(),
    friends_check_handle: (p) => {
      const h = String(p.handle ?? '')
      const taken = h.toLowerCase() === 'maxk'
      const reserved = /^(admin|support|zugzwang)/i.test(h)
      return { handle: h, available: !taken && !reserved, reason: taken ? 'taken' : reserved ? 'reserved' : null }
    },
    friends_signup: (p) => {
      signedIn = true
      fx.handle = String(p.handle)
      return { handle: fx.handle, recoveryCode: fx.recoveryCode }
    },
    friends_recovery_code: () => ({ code: fx.recoveryCode }),
    friends_me: () => ({
      handle: fx.handle,
      created: fx.now - 90 * 86400_000,
      appear_offline: false,
      // a pending Chess.com link: the name is on the server, not yet proven
      linked: scenario?.startsWith('friends-cc-') ? [{ site: 'chesscom', username: 'you_demo', verified: false }] : fx.me_linked,
    }),
    friends_list: () => list,
    friends_profile: (p) => {
      const prof = fx.profiles[String(p.handle)]
      if (!prof) return { error: { code: 'not_friends', message: 'You are not friends with that handle.' } }
      const n = Number(p.recentLimit ?? 10)
      return { ...prof, recent: prof.recent.slice(0, n) }
    },
    friends_game: (p) => fx.games[String(p.id)] ?? Object.values(fx.games)[0],
    friends_refresh: () => ({ started: true }),
    friends_request: (p) => ({ status: 'sent', handle: p.handle }),
    friends_answer: (p) => {
      list.incoming = list.incoming.filter((r) => r.id !== p.id)
      return { status: p.accept ? 'friends' : 'declined' }
    },
    friends_cancel: (p) => {
      list.outgoing = list.outgoing.filter((r) => r.id !== p.id)
      return { status: 'cancelled' }
    },
    friends_set_settings: () => state(),
    friends_appear_offline: (p) => ({ appear_offline: !!p.on }),
    // Remove friend and Block (BETA-5 S5): recorded in window.__zzFriendsCalls, so a test sees what was sent
    friends_remove: (p) => (calls().push(['remove', String(p.handle)]), { status: 'removed' }),
    friends_block: (p) => (calls().push(['block', String(p.handle)]), { status: 'blocked' }),
    friends_chesscom_link: () => cc,
    friends_chesscom_start: (p) => (cc = { ...ccPending('code'), username: String(p.username), site: 'chesscom', field: 'location' }),
    // the harness's Chess.com never shows the code: a check waits
    friends_chesscom_verify: () => (cc = { ...cc, state: 'waiting', lastCheck: fx.now, nextCheck: fx.now + 15 * 60_000 }),
    friends_chesscom_cancel: () => (cc = { state: 'none' }),
    friends_save_recovery: (p) => {
      const path = String(p.path ?? '')
      if (path.includes('readonly')) return { error: { code: 'save_failed', message: `The code could not be saved to ${path}: Permission denied.` } }
      saved.push(path)
      return { path }
    },
    friends_delete_account: () => {
      signedIn = false
      return { deleted: true }
    },
  }
}
