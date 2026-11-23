/** Games against friends in the webview (FRIENDS-2 D): the live connection's snapshot (pending challenges,
 *  games), the open game's state, chat (this window's memory only, H2) and ratings at its start, kept fresh
 *  by the sidecar's `friends_live` and `friend_game` events (core/friends/live.py). The account key never
 *  reaches the webview: every message goes through an RPC. */
import { sidecar } from '../api'
import {
  friendsApi, type AskedColour, type Challenge, type ChatLine, type GameMessage, type GameState, type LiveSnapshot,
  type StartRatings, type TimeControl,
} from './friendsApi'
import { errorText, friendsState } from './friendsState.svelte'

export interface GameView {
  state: GameState | null
  chat: ChatLine[]
  ratings: StartRatings | null
  savedGameId: number | null
  connected: boolean
  /** the last refusal from the server (illegal, too_soon, opponent_chat_off, …) */
  error: { code: string; message: string } | null
  /** Date.now() - server_time at the last state: the clocks run on this computer between states */
  skew: number
  /** chat lines arrived while the chat was collapsed (H4) */
  unread: number
}

export const live = $state<{
  snapshot: LiveSnapshot
  /** the game on Play's screen */
  activeId: string | null
  games: Record<string, GameView>
  /** Date.now() - server_time from the lobby: a challenge's "Expires in" */
  skew: number
  /** the challenges you sent and their fate, by friend handle (lower case): the popover's waiting state */
  sent: Record<string, { challenge: Challenge; outcome: 'waiting' | 'declined' | 'expired' | 'cancelled' | 'accepted' | 'busy' }>
  /** chat expanded (H4: by default), per game */
  chatOpen: boolean
}>({ snapshot: { connected: false, challenges: [], games: [] }, activeId: null, games: {}, skew: 0, sent: {}, chatOpen: true })

/** the App's hook: a game started, so Play opens (set by App.svelte) */
export const liveHooks: { ongamestart: (id: string) => void } = { ongamestart: () => {} }

const me = () => (friendsState.status?.handle ?? '').toLowerCase()

export function incomingChallenges(): Challenge[] {
  const h = me()
  return live.snapshot.challenges.filter((c) => c.to_handle.toLowerCase() === h)
}

export function outgoingTo(handle: string): Challenge | null {
  const h = me()
  return live.snapshot.challenges.find((c) => c.from_handle.toLowerCase() === h && c.to_handle.toLowerCase() === handle.toLowerCase()) ?? null
}

/** seconds until a challenge expires, by the server's clock */
export function secondsLeft(c: Challenge, now = Date.now()): number {
  return Math.max(0, Math.ceil((c.expires - (now - live.skew)) / 1000))
}

/** the colour the challenged player plays: "White", "Black" or "Random" */
export function youPlay(c: Challenge): 'White' | 'Black' | 'Random' {
  return c.colour === 'random' ? 'Random' : c.colour === 'white' ? 'Black' : 'White'
}

function view(id: string): GameView {
  if (!live.games[id]) live.games[id] = { state: null, chat: [], ratings: null, savedGameId: null, connected: false, error: null, skew: 0, unread: 0 }
  // the store's own (reactive) object, not the literal assigned
  return live.games[id]
}

/** a game's clock for a side, in ms, as of now (the server's at its last state, run on locally) */
export function clockNow(g: GameView, side: 'white' | 'black', now = Date.now()): number {
  const s = g.state
  if (!s) return 0
  const base = s.clock[side]
  if (s.status !== 'playing' || s.running !== side) return base
  // never before the state arrived (the display's own clock ticks every 100 ms)
  return Math.max(0, base - Math.max(0, now - g.skew - s.server_time))
}

function onLive(d: Record<string, unknown>) {
  const snap = d.live as LiveSnapshot | undefined
  if (snap) live.snapshot = snap
  if (typeof d.server_time === 'number') live.skew = Date.now() - d.server_time
  const kind = d.kind
  if (kind === 'challenge') {
    const c = d.challenge as Challenge
    if (c.from_handle.toLowerCase() === me()) live.sent[c.to_handle.toLowerCase()] = { challenge: c, outcome: 'waiting' }
  } else if (kind === 'challenge_gone') {
    for (const [h, s] of Object.entries(live.sent)) {
      if (s.challenge.id === d.id) live.sent[h] = { ...s, outcome: (d.reason as never) ?? 'cancelled' }
    }
  } else if (kind === 'game_start') {
    const g = d.game as { id: string }
    live.activeId = g.id
    live.chatOpen = true
    view(g.id)
    void friendsApi.liveGame(g.id).then((v) => applyView(g.id, v)).catch(() => {})
    liveHooks.ongamestart(g.id)
  }
}

function applyView(id: string, v: { state: GameState | null; chat: ChatLine[]; ratings: StartRatings | null; savedGameId: number | null; connected: boolean }) {
  const g = view(id)
  if (v.state) {
    g.state = v.state
    g.skew = Date.now() - v.state.server_time
  }
  if (v.chat.length > g.chat.length) g.chat = v.chat
  if (v.ratings) g.ratings = v.ratings
  if (v.savedGameId != null) g.savedGameId = v.savedGameId
  g.connected = v.connected
}

function onGame(d: Record<string, unknown>) {
  const id = String(d.id)
  const g = view(id)
  switch (d.kind) {
    case 'state': {
      const s = d.state as GameState
      g.state = s
      g.skew = Date.now() - s.server_time
      if (d.ratings) g.ratings = d.ratings as StartRatings
      g.error = null
      break
    }
    case 'chat':
      g.chat = [...g.chat, d.line as ChatLine]
      if (!live.chatOpen && (d.line as ChatLine).from !== g.state?.you) g.unread += 1
      break
    case 'error':
      g.error = { code: String(d.error), message: String(d.message) }
      break
    case 'ratings':
      g.ratings = d.ratings as StartRatings
      break
    case 'saved':
      g.savedGameId = (d.gameId as number | null) ?? null
      break
    case 'connection':
      g.connected = !!d.connected
      break
  }
}

let wired = false
/** Once, when signed in: the snapshot and the events. */
export function startLive(): void {
  if (wired) return
  wired = true
  sidecar.on('friends_live', onLive)
  sidecar.on('friend_game', onGame)
  void refreshLive()
}

export async function refreshLive(): Promise<void> {
  try {
    live.snapshot = await friendsApi.live()
    // a live game reopens; so does one that ended within the last hour and is not yet saved by both (its
    // result, a rematch)
    const mine =
      live.snapshot.games.find((g) => g.status === 'live') ??
      live.snapshot.games.filter((g) => g.status === 'over' && Date.now() - g.created < 3_600_000).sort((a, b) => b.created - a.created)[0]
    if (mine && !live.activeId) {
      live.activeId = mine.id
      applyView(mine.id, await friendsApi.liveGame(mine.id))
    }
  } catch {
    /* not signed in, or no sidecar: nothing live */
  }
}

export async function sendChallenge(handle: string, tc: TimeControl, colour: AskedColour): Promise<Challenge> {
  const out = await friendsApi.challenge(handle, tc, colour)
  live.sent[handle.toLowerCase()] = { challenge: out.challenge, outcome: 'waiting' }
  if (!live.snapshot.challenges.some((c) => c.id === out.challenge.id)) live.snapshot.challenges = [...live.snapshot.challenges, out.challenge]
  return out.challenge
}

export async function cancelChallenge(handle: string): Promise<void> {
  const s = live.sent[handle.toLowerCase()]
  if (!s) return
  await friendsApi.challengeCancel(s.challenge.id).catch(() => {})
  live.sent[handle.toLowerCase()] = { ...s, outcome: 'cancelled' }
  live.snapshot.challenges = live.snapshot.challenges.filter((c) => c.id !== s.challenge.id)
}

export function forgetSent(handle: string): void {
  delete live.sent[handle.toLowerCase()]
}

export async function answerChallenge(c: Challenge, accept: boolean): Promise<string | null> {
  live.snapshot.challenges = live.snapshot.challenges.filter((x) => x.id !== c.id)
  try {
    const out = await friendsApi.challengeAnswer(c.id, accept)
    if (accept && out.game) {
      live.activeId = out.game.id
      live.chatOpen = true
      view(out.game.id)
      applyView(out.game.id, await friendsApi.liveGame(out.game.id))
      liveHooks.ongamestart(out.game.id)
    }
    return null
  } catch (e) {
    return errorText(e)
  }
}

export async function send(msg: GameMessage): Promise<void> {
  const id = live.activeId
  if (!id) return
  try {
    await friendsApi.gameSend(id, msg)
  } catch (e) {
    view(id).error = { code: 'send', message: errorText(e) }
  }
}

/** leave the finished game's screen: the app acknowledges it to the server */
export function closeGame(): void {
  const id = live.activeId
  if (!id) return
  void friendsApi.gameClose(id).catch(() => {})
  live.activeId = null
}

export async function rematch(): Promise<string | null> {
  const id = live.activeId
  if (!id) return null
  try {
    const out = await friendsApi.rematch(id)
    live.sent[out.challenge.to_handle.toLowerCase()] = { challenge: out.challenge, outcome: 'waiting' }
    return null
  } catch (e) {
    return errorText(e)
  }
}

export function setChatOpen(open: boolean): void {
  live.chatOpen = open
  if (open && live.activeId) view(live.activeId).unread = 0
}
