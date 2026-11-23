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
 *
 * FRIENDS-2 D (games against friends; the positions and lines of the stage-2 mockups):
 *   ?state=friends-challenge              maxk challenges you (5+0, you play Black): the banner on any screen
 *   ?challenge=1|3                        BETA-6: one or three challenges with any scenario (a game screen too)
 *   ?friends=one|many                     BETA-6: the first friend only, or 24 friends
 *   ?names=long                           BETA-6: every name the longest allowed (main.ts, longNames.ts)
 *   ?screen=play&state=fgame              a game in progress (MinimalPlayGame-friend.html), your move
 *   ?screen=play&state=fgame-draw         … maxk offers a draw
 *   ?screen=play&state=fgame-left         … maxk disconnected: the claim in 0:24
 *   ?screen=play&state=fgame-over         … over: you won, maxk resigned
 *   ?screen=play&state=fgame-collapsed    … a chat line from maxk arrives 2.5 s after the game opens
 *   window.__zzFriendsCalls records the game messages and challenges sent
 */
import { Chess } from 'chess.js'
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
  // BETA-6 layout checks: ?friends=one keeps the first friend only (online); ?friends=many repeats the list to 24
  const howMany = typeof location === 'undefined' ? null : new URLSearchParams(location.search).get('friends')
  if (howMany === 'one') list.friends = list.friends.slice(0, 1)
  if (howMany === 'many') {
    const base = list.friends
    list.friends = Array.from({ length: 24 }, (_, i) => ({ ...structuredClone(base[i % base.length]), handle: i < base.length ? base[i].handle : `${base[i % base.length].handle}${Math.floor(i / base.length)}` }))
  }
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
  // ── FRIENDS-2: challenges and a live game ───────────────────────────────────
  const GID = 'g'.repeat(16)
  const NEW_GID = 'h'.repeat(16)
  const NAJDORF = ['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'a6', 'Be3', 'e5']
  const fgame = scenario?.startsWith('fgame') ?? false
  const t0 = Date.now()
  function position(sans: string[]) {
    const c = new Chess()
    const moves: string[] = []
    for (const s of sans) moves.push(c.move(s).lan)
    return { moves, sans, fen: c.fen(), turn: (c.turn() === 'w' ? 'white' : 'black') as 'white' | 'black' }
  }
  let game: Record<string, unknown> | null = null
  const me = () => fx!.handle
  function baseGame(id: string, sans: string[], over: Record<string, unknown> = {}): Record<string, unknown> {
    const p = position(sans)
    return {
      t: 'state', id, you: 'white', tc: id === GID ? '10+0' : '5+0', speed: id === GID ? 'rapid' : 'blitz', created: t0 - 160_000, ended: null,
      white: { handle: me(), linked: [{ site: 'chesscom', username: 'you_demo' }] },
      black: { handle: 'maxk', linked: [{ site: 'chesscom', username: 'maxk_chess' }] },
      ...p, status: sans.length >= 2 ? 'playing' : 'waiting', result: null, termination: null, termination_text: null, winner: null,
      clock: { white: 527_000, black: 552_000 }, running: sans.length >= 2 ? p.turn : null, server_time: Date.now(),
      first_deadline: sans.length >= 2 ? null : Date.now() + 30_000, draw_offer: null, can_offer_draw: true, claim_at: null,
      opponent: { connected: true, gone_since: null, chat_on: true }, chat_on: true, chat_blocked: false, muted: false,
      rematch_from: null, acked: false, pgn: null, ...over,
    }
  }
  if (fgame) {
    game = baseGame(GID, NAJDORF)
    if (scenario === 'fgame-draw') game.draw_offer = 'black'
    if (scenario === 'fgame-left') Object.assign(game, { opponent: { connected: false, gone_since: Date.now() - 6000, chat_on: true }, claim_at: Date.now() + 24_000 })
    if (scenario === 'fgame-over') Object.assign(game, { status: 'over', result: '1-0', winner: 'white', termination: 'resign', termination_text: 'resignation', running: null, ended: Date.now(), pgn: '[Event "Zugzwang friend game"]\n\n*' })
  }
  const chatLines = [
    { from: 'black', handle: 'maxk', text: 'good luck', at: t0 - 150_000 },
    { from: 'white', handle: me(), text: 'you too', at: t0 - 148_000 },
    { from: 'black', handle: 'maxk', text: 'that knight is annoying', at: t0 - 20_000 },
    ...(scenario === 'fgame-draw' ? [{ from: 'black', handle: 'maxk', text: 'draw?', at: t0 - 2000 }] : []),
    ...(scenario === 'fgame-over' ? [{ from: 'black', handle: 'maxk', text: 'gg, rematch?', at: t0 - 1000 }] : []),
  ]
  // BETA-6: ?challenge=1 adds the same challenge to any scenario (the banner over a game screen, S6); ?challenge=3 three
  const extra = typeof location === 'undefined' ? 0 : Number(new URLSearchParams(location.search).get('challenge') ?? 0)
  const nChallenges = Math.max(scenario === 'friends-challenge' ? 1 : 0, extra)
  const incoming = Array.from({ length: nChallenges }, (_, i) => ({
    id: String.fromCharCode(99 + i).repeat(16), from_handle: ['maxk', 'benji', 'noa_p'][i % 3], to_handle: fx.handle, tc: ['5+0', '3+2', '10+0'][i % 3],
    colour: 'white', created: Date.now() - 8000, expires: Date.now() + 52_000, rematch_of: null,
  }))
  const snapshot = () => ({
    connected: true,
    challenges: incoming,
    games: game ? [{ id: game.id, white_handle: fx.handle, black_handle: 'maxk', tc: game.tc, status: game.status === 'over' ? 'over' : 'live', created: t0 }] : [],
  })
  const view = (id: string) => ({
    id, state: game && game.id === id ? { ...game, server_time: Date.now() } : null,
    chat: game && game.id === GID ? chatLines : [],
    ratings: { white: { rating: 1438, estimated: false }, black: { rating: 1446, estimated: false } },
    savedGameId: game && game.status === 'over' ? 1 : null, connected: true,
  })
  let collapsedSent = false
  const RATINGS: Record<string, { rating: number; estimated: boolean }> = { maxk: { rating: 1446, estimated: false }, benji: { rating: 1390, estimated: true } }

  return {
    friends_live: () => snapshot(),
    friends_live_game: (p, emit) => {
      if (scenario === 'fgame-collapsed' && !collapsedSent) {
        collapsedSent = true
        setTimeout(() => emit('friend_game', { id: GID, kind: 'chat', line: { from: 'black', handle: 'maxk', text: 'nice move', at: Date.now() } }), 2500)
      }
      return view(String(p.id))
    },
    friends_opening: () => (game && (game.sans as string[]).length >= 12 ? { eco: 'B90', name: 'Sicilian, Najdorf, English Attack' } : { eco: null, name: null }),
    friends_ratings: (p) => ({ you: { rating: 1438, estimated: false }, them: RATINGS[String(p.handle)] ?? { rating: null, estimated: false } }),
    friends_challenge: (p, emit) => {
      calls().push(['challenge', JSON.stringify({ handle: p.handle, tc: p.tc, colour: p.colour })])
      const c = { id: 'o'.repeat(16), from_handle: fx.handle, to_handle: String(p.handle), tc: String(p.tc), colour: String(p.colour), created: Date.now(), expires: Date.now() + 60_000, rematch_of: null }
      setTimeout(() => emit('friends_live', { kind: 'challenge', challenge: c, server_time: Date.now() }), 30)
      return { challenge: c }
    },
    friends_challenge_cancel: (p) => (calls().push(['cancel', String(p.id)]), { status: 'cancelled' }),
    friends_challenge_answer: (p) => {
      calls().push([p.accept ? 'accept' : 'decline', String(p.id)])
      incoming.splice(0, incoming.length)
      if (!p.accept) return { status: 'declined' }
      game = baseGame(NEW_GID, [], { you: 'black', white: { handle: 'maxk', linked: [] }, black: { handle: me(), linked: [] } })
      return { game: { id: NEW_GID, white_handle: 'maxk', black_handle: fx.handle, tc: '5+0', status: 'live', created: Date.now() } }
    },
    friends_game_send: (p, emit) => {
      const msg = p.msg as Record<string, unknown>
      calls().push(['game', JSON.stringify(msg)])
      if (!game) return { error: { code: 'no_such_game', message: 'That game is not open.' } }
      const g = game
      const push = (over: Record<string, unknown>) => {
        Object.assign(g, over, { server_time: Date.now() })
        setTimeout(() => emit('friend_game', { id: g.id, kind: 'state', state: { ...g } }), 20)
      }
      switch (msg.t) {
        case 'chat':
          setTimeout(() => emit('friend_game', { id: g.id, kind: 'chat', line: { from: g.you, handle: fx.handle, text: String(msg.text), at: Date.now() } }), 20)
          break
        case 'mute':
          push({ muted: !!msg.on })
          break
        case 'resign':
          push({ status: 'over', result: g.you === 'white' ? '0-1' : '1-0', winner: g.you === 'white' ? 'black' : 'white', termination: 'resign', running: null, pgn: '*' })
          break
        case 'draw_offer':
          push({ draw_offer: g.you })
          break
        case 'draw_accept':
          push({ status: 'over', result: '1/2-1/2', winner: null, termination: 'agreed', running: null, draw_offer: null, pgn: '*' })
          break
        case 'draw_decline':
          push({ draw_offer: null })
          break
        case 'claim_win':
          push({ status: 'over', result: '1-0', winner: g.you, termination: 'abandoned', running: null, pgn: '*' })
          break
        case 'move': {
          const sans = [...(g.sans as string[])]
          const c = new Chess(String(g.fen))
          const m = c.move({ from: String(msg.uci).slice(0, 2), to: String(msg.uci).slice(2, 4), promotion: String(msg.uci)[4] })
          push({ ...position([...sans, m.san]) })
          break
        }
      }
      return { sent: true }
    },
    friends_game_close: () => ({ ok: true }),
    friends_rematch: () => ({ challenge: { id: 'r'.repeat(16), from_handle: fx.handle, to_handle: 'maxk', tc: '10+0', colour: 'black', created: Date.now(), expires: Date.now() + 60_000, rematch_of: GID } }),
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
    // Check now at most once every 30 s (FRIENDS.md Z4): the sidecar says when it can be pressed again
    friends_chesscom_verify: () => (calls().push(['verify', '']), (cc = { ...cc, state: 'waiting', lastCheck: fx.now, nextCheck: fx.now + 15 * 60_000, checkNowAt: Date.now() + 30_000 })),
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
