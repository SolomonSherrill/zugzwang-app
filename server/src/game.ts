/**
 * One live friend game (FRIENDS.md "FRIENDS-2", ruling B): a SQLite-backed Durable Object per game, its two
 * players' WebSockets accepted with the Hibernation API (an idle game costs no duration), the clocks and the
 * rules decided here (gamecore.ts) on the server's clock, the alarm set for the next thing that can happen
 * (an abort, a flag, a claim becoming possible, a silent connection).
 *
 * Stored (this object's own storage, never D1): the game state of gamecore.ts (the two accounts' ids and
 * handles, their verified linked usernames and chat switches, the moves, the clocks, the result), until both
 * apps have saved the finished game or RESULT_KEEP_MS after the end, then deleted (deleteAll).
 * **Chat is never stored** (ruling H2): messages live in this object's memory only (the array below, lost
 * whenever the object hibernates or is evicted, and emptied when the game ends), are relayed to the other
 * player's sockets, and are never logged. After the end, messages are relayed and held nowhere.
 */
import { DurableObject } from 'cloudflare:workers'
import type { Env } from './app'
import * as core from './gamecore'
import type { Colour, GameState, Timing } from './gamecore'

export const CHAT_MAX = 200
/** the light chat limit (H1): at most CHAT_BURST messages in CHAT_WINDOW_MS per player */
export const CHAT_BURST = 5
export const CHAT_WINDOW_MS = 10_000
/** any message: at most this many per socket in 10 s, then the socket is closed */
export const FLOOD_LIMIT = 60
/** WebSocket.readyState of an open socket */
const OPEN = 1

export function timingOf(env: Env): Timing & { keepMs: number; staleMs: number } {
  const n = (v: string | undefined, d: number) => (v && /^[0-9]+$/.test(v) ? Number(v) : d)
  return {
    flagTestMs: env.FLAG_TEST_MS && /^[0-9]+$/.test(env.FLAG_TEST_MS) ? Number(env.FLAG_TEST_MS) : undefined,
    firstMoveMs: n(env.FIRST_MOVE_MS, core.DEFAULT_TIMING.firstMoveMs),
    disconnectMs: n(env.DISCONNECT_MS, core.DEFAULT_TIMING.disconnectMs),
    keepMs: n(env.RESULT_KEEP_MS, 24 * 3_600_000),
    staleMs: n(env.STALE_MS, 25_000),
  }
}

interface Attachment {
  c: Colour
  last: number
}

interface ChatLine {
  from: Colour
  text: string
  at: number
}

export class Game extends DurableObject<Env> {
  private s: GameState | null = null
  private chat: ChatLine[] = []
  private chatHits: Record<Colour, number[]> = { white: [], black: [] }
  private flood = new Map<WebSocket, number[]>()
  private alarmAt: number | null = null

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env)
    // the apps' keep-alive, answered without waking the object (no duration, FRIENDS-2 B's estimate)
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'))
    ctx.blockConcurrencyWhile(async () => {
      this.s = (await ctx.storage.get<GameState>('state')) ?? null
    })
  }

  private get timing() {
    return timingOf(this.env)
  }

  // ── RPC from the Worker and the Lobby ───────────────────────────────────────────

  async init(state: GameState): Promise<void> {
    this.s = state
    await this.save()
  }

  /** the finished (or running) game as one player sees it, with the PGN once it is over */
  async result(accountId: number): Promise<Record<string, unknown> | null> {
    const s = this.s
    if (!s) return null
    const c = core.colourOf(s, accountId)
    if (!c) return null
    await this.settle()
    return this.view(c, Date.now())
  }

  async ack(accountId: number): Promise<boolean> {
    const s = this.s
    if (!s || s.status !== 'over') return false
    const c = core.colourOf(s, accountId)
    if (!c) return false
    s.acked[c] = true
    await this.save()
    if (s.acked.white && s.acked.black) await this.cleanup()
    return true
  }

  /** the player's Chat switch changed mid-game (H3) */
  async setChat(accountId: number, on: boolean): Promise<void> {
    const s = this.s
    if (!s) return
    const c = core.colourOf(s, accountId)
    if (!c) return
    s[c].chat = on
    await this.save()
    this.broadcast()
  }

  /** one player blocked the other: no chat either way from now on */
  async blockChat(): Promise<void> {
    if (!this.s) return
    this.s.chat_blocked = true
    this.chat = []
    await this.save()
    this.broadcast()
  }

  /** the account is being deleted: it resigns (or the game is aborted before the first moves) */
  async abandon(accountId: number): Promise<void> {
    const s = this.s
    if (!s) return
    const c = core.colourOf(s, accountId)
    if (!c) return
    const was = s.status
    core.abandon(s, c, Date.now())
    // a deleted account saves nothing: the game is kept only until the other player has saved it
    s.acked[c] = true
    await this.after(was)
  }

  /** a rematch from this game (P3): who offers, to whom, the same time control, the colours swapped */
  async rematchInfo(accountId: number): Promise<{ opponent: number; tc: core.TimeControl; colour: Colour } | { error: string }> {
    const s = this.s
    if (!s) return { error: 'no_such_game' }
    const c = core.colourOf(s, accountId)
    if (!c) return { error: 'no_such_game' }
    await this.settle()
    if (s.status !== 'over') return { error: 'not_over' }
    return { opponent: s[core.other(c)].id, tc: s.tc, colour: core.other(c) }
  }

  async markRematch(accountId: number): Promise<void> {
    const s = this.s
    if (!s) return
    const c = core.colourOf(s, accountId)
    if (!c) return
    s.rematch_from = c
    await this.save()
    this.broadcast()
  }

  // ── sockets ──────────────────────────────────────────────────────────────────

  async fetch(req: Request): Promise<Response> {
    const s = this.s
    if (req.headers.get('Upgrade') !== 'websocket') return new Response('expected a WebSocket', { status: 426 })
    if (!s) return new Response(JSON.stringify({ error: 'no_such_game', message: 'No such game.' }), { status: 404 })
    const c = core.colourOf(s, Number(req.headers.get('X-Zz-Account-Id')))
    if (!c) return new Response(JSON.stringify({ error: 'no_such_game', message: 'No such game.' }), { status: 404 })
    const pair = new WebSocketPair()
    const now = Date.now()
    this.ctx.acceptWebSocket(pair[1], [c])
    pair[1].serializeAttachment({ c, last: now } satisfies Attachment)
    s.gone[c] = null
    s.seen[c] = true
    const was = s.status
    await this.after(was)
    // what was said while this player was away (memory only; empty after a hibernation)
    for (const line of this.chat) if (this.delivers(line.from, c)) pair[1].send(JSON.stringify(this.chatOut(line)))
    return new Response(null, { status: 101, webSocket: pair[0] })
  }

  async webSocketMessage(ws: WebSocket, data: string | ArrayBuffer): Promise<void> {
    const s = this.s
    const a = ws.deserializeAttachment() as Attachment | null
    if (!s || !a) return ws.close(1011, 'no game')
    const now = Date.now()
    ws.serializeAttachment({ ...a, last: now })
    const hits = (this.flood.get(ws) ?? []).filter((t) => t > now - 10_000)
    hits.push(now)
    this.flood.set(ws, hits)
    if (hits.length > FLOOD_LIMIT) return ws.close(1008, 'too many messages')
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(typeof data === 'string' ? data : new TextDecoder().decode(data))
    } catch {
      return this.sendError(ws, 'bad_message', 'That message is not JSON.')
    }
    const c = a.c
    const was = s.status
    try {
      switch (msg.t) {
        case 'move':
          core.move(s, c, String(msg.uci ?? ''), typeof msg.ply === 'number' ? msg.ply : undefined, now)
          break
        case 'resign':
          core.resign(s, c, now)
          break
        case 'draw_offer':
          core.offerDraw(s, c, now)
          break
        case 'draw_accept':
          core.answerDraw(s, c, true, now)
          break
        case 'draw_decline':
          core.answerDraw(s, c, false, now)
          break
        case 'claim_win':
        case 'call_draw':
          core.claim(s, c, msg.t === 'claim_win', this.connected(now), this.timing, now)
          break
        case 'mute':
          s.muted[c] = msg.on === true
          break
        case 'chat':
          return this.chatIn(ws, c, msg.text, now)
        case 'sync':
          await this.settle()
          ws.send(JSON.stringify(this.view(c, now)))
          return
        default:
          return this.sendError(ws, 'bad_message', 'Unknown message.')
      }
    } catch (e) {
      if (e instanceof core.RuleError) {
        await this.after(was)
        return this.sendError(ws, e.code, e.message)
      }
      throw e
    }
    await this.after(was)
  }

  async webSocketClose(ws: WebSocket): Promise<void> {
    await this.dropped(ws)
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    await this.dropped(ws)
  }

  private async dropped(ws: WebSocket): Promise<void> {
    this.flood.delete(ws)
    // settle() finds the colour with no open socket (the closing one can still be listed, as another
    // object and without its attachment, while its close is handled)
    if (this.s) await this.after(this.s.status)
  }

  async alarm(): Promise<void> {
    const s = this.s
    if (!s) return
    const now = Date.now()
    if (s.status === 'over' && ((s.acked.white && s.acked.black) || now >= (s.ended ?? now) + this.timing.keepMs)) {
      await this.cleanup()
      return
    }
    // rows written are the Free plan's tightest limit (100,000 a day): an alarm that changed nothing (a
    // look at the sockets) writes nothing but the next alarm
    const was = s.status
    const changed = await this.settle()
    if (was !== 'over' && s.status === 'over') await this.ended()
    if (changed) await this.save()
    await this.schedule()
    if (changed) this.broadcast()
  }

  // ── internals ────────────────────────────────────────────────────────────────

  private sockets(c?: Colour): WebSocket[] {
    return c ? this.ctx.getWebSockets(c) : this.ctx.getWebSockets()
  }

  /** a socket counts as connected while it has spoken (or pinged) within staleMs */
  private lastHeard(ws: WebSocket): number {
    const a = ws.deserializeAttachment() as Attachment | null
    const pinged = this.ctx.getWebSocketAutoResponseTimestamp(ws)?.getTime() ?? 0
    return Math.max(a?.last ?? 0, pinged)
  }

  private connected(now: number): Record<Colour, boolean> {
    const out = { white: false, black: false }
    for (const c of ['white', 'black'] as Colour[]) {
      out[c] = this.sockets(c).some((w) => w.readyState === OPEN && now - this.lastHeard(w) < this.timing.staleMs)
    }
    return out
  }

  /** close the silent sockets (marking their player gone since last heard) and apply the clock */
  private async settle(): Promise<boolean> {
    const s = this.s!
    const now = Date.now()
    let changed = false
    for (const c of ['white', 'black'] as Colour[]) {
      const open = this.sockets(c).filter((w) => w.readyState === OPEN)
      const silent = open.filter((w) => now - this.lastHeard(w) >= this.timing.staleMs)
      for (const w of silent) {
        try {
          w.close(1001, 'silent')
        } catch {
          /* already closing */
        }
      }
      const live = open.length - silent.length
      if (live === 0 && s.seen[c] && s.gone[c] === null) {
        // gone since last heard for a silent socket, since now for a closed one
        const heard = silent.map((w) => this.lastHeard(w)).filter((t) => t > 0)
        s.gone[c] = heard.length ? Math.max(...heard) : now
        changed = true
      }
    }
    return core.tick(s, now) || changed
  }

  /** after anything that may have changed the game: end-of-game duties, save, the alarm, both views */
  private async after(was: core.Status): Promise<void> {
    const s = this.s!
    await this.settle()
    if (was !== 'over' && s.status === 'over') await this.ended()
    await this.save()
    await this.schedule()
    this.broadcast()
  }

  private async ended(): Promise<void> {
    const s = this.s!
    this.chat = [] // H2: gone when the game ends
    try {
      await this.env.LOBBY.get(this.env.LOBBY.idFromName('lobby')).gameOver(s.id)
    } catch (e) {
      console.error('error', 'game over: lobby', e instanceof Error ? e.message : 'unknown')
    }
  }

  private async save(): Promise<void> {
    if (this.s) await this.ctx.storage.put('state', this.s)
  }

  private async schedule(): Promise<void> {
    const s = this.s!
    const now = Date.now()
    const t = this.timing
    let wake: number | null
    if (s.status === 'over') wake = (s.ended ?? now) + t.keepMs
    else {
      const next = core.nextWake(s, this.connected(now), t)
      // while the game runs, look at the sockets now and then: a silent one counts as gone (P1)
      const look = this.sockets().length ? now + t.staleMs : null
      wake = [next, look].filter((v): v is number => v !== null).reduce((x, y) => Math.min(x, y), Infinity)
      if (wake === Infinity) wake = now + t.staleMs
    }
    const at = Math.max(wake, now + 1)
    if (at !== this.alarmAt) {
      await this.ctx.storage.setAlarm(at)
      this.alarmAt = at
    }
  }

  private async cleanup(): Promise<void> {
    const id = this.s?.id
    for (const w of this.sockets()) {
      try {
        w.close(1000, 'game saved')
      } catch {
        /* closing */
      }
    }
    this.s = null
    this.chat = []
    await this.ctx.storage.deleteAlarm()
    await this.ctx.storage.deleteAll()
    this.alarmAt = null
    if (id) {
      try {
        await this.env.LOBBY.get(this.env.LOBBY.idFromName('lobby')).forget(id)
      } catch {
        /* the lobby forgets it on its own schedule */
      }
    }
  }

  private view(c: Colour, now: number): Record<string, unknown> {
    const s = this.s!
    const o = core.other(c)
    const conn = this.connected(now)
    return {
      t: 'state',
      id: s.id,
      you: c,
      white: { handle: s.white.handle, linked: s.white.linked },
      black: { handle: s.black.handle, linked: s.black.linked },
      tc: s.tc,
      speed: core.speedOf(s.tc),
      created: s.created,
      ended: s.ended,
      moves: s.moves,
      sans: s.sans,
      fen: s.fen,
      turn: core.turnOf(s),
      status: s.status,
      result: s.result,
      termination: s.termination,
      termination_text: core.terminationText(s.termination),
      winner: s.winner,
      clock: { white: Math.max(0, core.remaining(s, 'white', now)), black: Math.max(0, core.remaining(s, 'black', now)) },
      running: s.status === 'playing' ? core.turnOf(s) : null,
      server_time: now,
      first_deadline: s.first_deadline,
      draw_offer: s.draw_offer,
      can_offer_draw: core.canOfferDraw(s, c),
      claim_at: core.claimAt(s, c, conn, this.timing),
      opponent: { connected: conn[o], gone_since: conn[o] ? null : s.gone[o], chat_on: s[o].chat && !s.chat_blocked },
      chat_on: s[c].chat && !s.chat_blocked,
      chat_blocked: s.chat_blocked,
      muted: s.muted[c],
      rematch_from: s.rematch_from,
      acked: s.acked[c],
      pgn: s.status === 'over' && s.result !== '*' ? core.pgn(s) : null,
    }
  }

  private broadcast(): void {
    if (!this.s) return
    const now = Date.now()
    for (const w of this.sockets()) {
      const a = w.deserializeAttachment() as Attachment | null
      if (!a) continue
      try {
        w.send(JSON.stringify(this.view(a.c, now)))
      } catch {
        /* closing */
      }
    }
  }

  private sendError(ws: WebSocket, error: string, message: string): void {
    try {
      ws.send(JSON.stringify({ t: 'error', error, message }))
    } catch {
      /* closing */
    }
  }

  /** a message from `from` reaches `to` (H3): both chats on, no block, `to` has not muted this game */
  private delivers(from: Colour, to: Colour): boolean {
    const s = this.s!
    if (from === to) return true
    return s.white.chat && s.black.chat && !s.chat_blocked && !s.muted[to]
  }

  private chatOut(line: ChatLine): Record<string, unknown> {
    return { t: 'chat', from: line.from, handle: this.s![line.from].handle, text: line.text, at: line.at }
  }

  private chatIn(ws: WebSocket, c: Colour, raw: unknown, now: number): void {
    const s = this.s!
    const o = core.other(c)
    if (typeof raw !== 'string') return this.sendError(ws, 'bad_message', 'A chat message is text.')
    const text = raw.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').trim()
    if (!text) return this.sendError(ws, 'empty', 'Nothing to send.')
    if ([...text].length > CHAT_MAX) return this.sendError(ws, 'too_long', 'A message is at most 200 characters.')
    if (s.chat_blocked) return this.sendError(ws, 'chat_unavailable', 'Chat is not available in this game.')
    if (!s[c].chat) return this.sendError(ws, 'chat_off', 'Your chat in friend games is off (Settings).')
    if (!s[o].chat) return this.sendError(ws, 'opponent_chat_off', `${s[o].handle} has chat turned off.`)
    const hits = this.chatHits[c].filter((t) => t > now - CHAT_WINDOW_MS)
    if (hits.length >= CHAT_BURST) {
      this.chatHits[c] = hits
      return this.sendError(ws, 'chat_rate', 'Slow down: a few messages at a time.')
    }
    hits.push(now)
    this.chatHits[c] = hits
    const line: ChatLine = { from: c, text, at: now }
    if (s.status !== 'over') this.chat.push(line) // after the end: relayed, held nowhere
    if (this.chat.length > 200) this.chat.shift()
    const out = JSON.stringify(this.chatOut(line))
    for (const to of ['white', 'black'] as Colour[]) {
      if (!this.delivers(c, to)) continue
      for (const w of this.sockets(to)) {
        try {
          w.send(out)
        } catch {
          /* closing */
        }
      }
    }
  }
}
