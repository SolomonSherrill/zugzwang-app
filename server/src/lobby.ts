/**
 * The lobby (FRIENDS.md "FRIENDS-2", ruling B): one SQLite-backed Durable Object for the whole server, holding
 * the pending challenges and each open app's live connection (a WebSocket accepted with the Hibernation API,
 * tagged by account). A challenge is pushed down the challenged app's socket the moment it is made, which is
 * how it reaches the other app within 3 s (the transport, decided: a socket costs nothing while idle and
 * delivers at once; polling every 2 s would spend about 43,000 requests a day per open app, beyond the free
 * plan's 100,000 for a handful of users).
 *
 * Stored here (never in D1): each pending challenge (its id, the two accounts' ids and handles, the time
 * control, the colour asked for, when it was made and expires, the game it is a rematch of), deleted when
 * it is accepted, declined, cancelled or expires (CHALLENGE_MS); and each live game's id, players and time
 * control, kept until both apps have saved the finished game.
 */
import { DurableObject } from 'cloudflare:workers'
import type { Env } from './app'
import * as core from './gamecore'
import type { Colour, Player, TimeControl } from './gamecore'
import { b64urlEncode } from './encoding'
import { timingOf } from './game'

export const CHALLENGE_MS_DEFAULT = 60_000
/** pending challenges one account may have out at once */
export const MAX_OUT = 3

export type AskedColour = 'white' | 'black' | 'random'

export interface Challenge {
  id: string
  from_id: number
  from_handle: string
  to_id: number
  to_handle: string
  tc: TimeControl
  colour: AskedColour
  created: number
  expires: number
  rematch_of: string | null
}

export interface LiveGame {
  id: string
  white_id: number
  black_id: number
  white_handle: string
  black_handle: string
  tc: string
  status: 'live' | 'over'
  created: number
}

type Gone = 'accepted' | 'declined' | 'cancelled' | 'expired' | 'busy'

export class Lobby extends DurableObject<Env> {
  private sql: SqlStorage

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env)
    this.sql = ctx.storage.sql
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'))
    this.sql.exec(`CREATE TABLE IF NOT EXISTS challenges (
      id TEXT PRIMARY KEY, from_id INTEGER NOT NULL, from_handle TEXT NOT NULL, to_id INTEGER NOT NULL,
      to_handle TEXT NOT NULL, tc TEXT NOT NULL, colour TEXT NOT NULL, created INTEGER NOT NULL,
      expires INTEGER NOT NULL, rematch_of TEXT)`)
    this.sql.exec(`CREATE TABLE IF NOT EXISTS games (
      id TEXT PRIMARY KEY, white_id INTEGER NOT NULL, black_id INTEGER NOT NULL, white_handle TEXT NOT NULL,
      black_handle TEXT NOT NULL, tc TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL)`)
  }

  private get challengeMs(): number {
    const v = this.env.CHALLENGE_MS
    return v && /^[0-9]+$/.test(v) ? Number(v) : CHALLENGE_MS_DEFAULT
  }

  // ── the apps' live connections ─────────────────────────────────────────────────

  async fetch(req: Request): Promise<Response> {
    if (req.headers.get('Upgrade') !== 'websocket') return new Response('expected a WebSocket', { status: 426 })
    const id = Number(req.headers.get('X-Zz-Account-Id'))
    if (!Number.isInteger(id) || id <= 0) return new Response('no account', { status: 400 })
    const pair = new WebSocketPair()
    this.ctx.acceptWebSocket(pair[1], ['a:' + id])
    pair[1].serializeAttachment({ id })
    this.expire(Date.now())
    pair[1].send(JSON.stringify(this.hello(id)))
    return new Response(null, { status: 101, webSocket: pair[0] })
  }

  async webSocketMessage(ws: WebSocket, data: string | ArrayBuffer): Promise<void> {
    const a = ws.deserializeAttachment() as { id: number } | null
    if (!a) return ws.close(1011, 'no account')
    let msg: Record<string, unknown> = {}
    try {
      msg = JSON.parse(typeof data === 'string' ? data : new TextDecoder().decode(data))
    } catch {
      /* ignored */
    }
    if (msg.t === 'sync') ws.send(JSON.stringify(this.hello(a.id)))
  }

  async webSocketClose(): Promise<void> {}

  private hello(id: number): Record<string, unknown> {
    return { t: 'hello', challenges: this.challengesOf(id), games: this.gamesOf(id), server_time: Date.now() }
  }

  private push(accountId: number, msg: Record<string, unknown>): void {
    const text = JSON.stringify(msg)
    for (const ws of this.ctx.getWebSockets('a:' + accountId)) {
      try {
        ws.send(text)
      } catch {
        /* closing */
      }
    }
  }

  /** whether an app is connected for the account (tests, the live check) */
  async online(accountId: number): Promise<boolean> {
    return this.ctx.getWebSockets('a:' + accountId).length > 0
  }

  // ── challenges ─────────────────────────────────────────────────────────────

  private challengesOf(id: number): Challenge[] {
    return this.sql
      .exec<Record<string, SqlStorageValue>>('SELECT * FROM challenges WHERE from_id = ?1 OR to_id = ?1 ORDER BY created', id)
      .toArray() as unknown as Challenge[]
  }

  private gamesOf(id: number): LiveGame[] {
    return this.sql
      .exec<Record<string, SqlStorageValue>>('SELECT * FROM games WHERE white_id = ?1 OR black_id = ?1 ORDER BY created', id)
      .toArray() as unknown as LiveGame[]
  }

  private liveGameOf(id: number): LiveGame | null {
    return (this.sql
      .exec<Record<string, SqlStorageValue>>("SELECT * FROM games WHERE status = 'live' AND (white_id = ?1 OR black_id = ?1) LIMIT 1", id)
      .toArray()[0] as unknown as LiveGame) ?? null
  }

  private one(id: string): Challenge | null {
    return (this.sql.exec<Record<string, SqlStorageValue>>('SELECT * FROM challenges WHERE id = ?', id).toArray()[0] as unknown as Challenge) ?? null
  }

  private gone(c: Challenge, reason: Gone): void {
    this.sql.exec('DELETE FROM challenges WHERE id = ?', c.id)
    const msg = { t: 'challenge_gone', id: c.id, reason }
    this.push(c.from_id, msg)
    this.push(c.to_id, msg)
  }

  /** delete the expired challenges, telling both sides; then the alarm for the next expiry */
  private expire(now: number): void {
    for (const c of this.sql.exec<Record<string, SqlStorageValue>>('SELECT * FROM challenges WHERE expires <= ?', now).toArray()) {
      this.gone(c as unknown as Challenge, 'expired')
    }
  }

  private async rearm(): Promise<void> {
    const next = this.sql.exec<{ t: number | null }>('SELECT MIN(expires) AS t FROM challenges').one().t
    if (next !== null) await this.ctx.storage.setAlarm(next)
    else await this.ctx.storage.deleteAlarm()
  }

  async alarm(): Promise<void> {
    this.expire(Date.now())
    await this.rearm()
  }

  async createChallenge(
    from: { id: number; handle: string },
    to: { id: number; handle: string },
    tc: TimeControl,
    colour: AskedColour,
    rematchOf: string | null = null,
  ): Promise<{ challenge: Challenge } | { error: string; message: string }> {
    const now = Date.now()
    this.expire(now)
    // a challenge arriving while a game is on (decided): refused, for either side
    if (this.liveGameOf(from.id)) return { error: 'you_in_game', message: 'Finish your game first.' }
    if (this.liveGameOf(to.id)) return { error: 'in_game', message: `${to.handle} is playing a game.` }
    // a new challenge to the same friend replaces your earlier one
    for (const c of this.sql.exec<Record<string, SqlStorageValue>>('SELECT * FROM challenges WHERE from_id = ? AND to_id = ?', from.id, to.id).toArray()) {
      this.gone(c as unknown as Challenge, 'cancelled')
    }
    const out = this.sql.exec<{ n: number }>('SELECT COUNT(*) AS n FROM challenges WHERE from_id = ?', from.id).one().n
    if (out >= MAX_OUT) return { error: 'too_many_challenges', message: 'You have three challenges waiting: cancel one first.' }
    const c: Challenge = {
      id: b64urlEncode(crypto.getRandomValues(new Uint8Array(12))),
      from_id: from.id, from_handle: from.handle, to_id: to.id, to_handle: to.handle,
      tc, colour, created: now, expires: now + this.challengeMs, rematch_of: rematchOf,
    }
    this.sql.exec(
      'INSERT INTO challenges (id, from_id, from_handle, to_id, to_handle, tc, colour, created, expires, rematch_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      c.id, c.from_id, c.from_handle, c.to_id, c.to_handle, c.tc, c.colour, c.created, c.expires, c.rematch_of,
    )
    await this.rearm()
    const msg = { t: 'challenge', challenge: c, server_time: now }
    this.push(to.id, msg)
    this.push(from.id, msg)
    return { challenge: c }
  }

  async getChallenge(id: string): Promise<Challenge | null> {
    this.expire(Date.now())
    return this.one(id)
  }

  async decline(id: string, accountId: number): Promise<boolean> {
    const c = this.one(id)
    if (!c || c.to_id !== accountId) return false
    this.gone(c, 'declined')
    await this.rearm()
    return true
  }

  async cancel(id: string, accountId: number): Promise<boolean> {
    const c = this.one(id)
    if (!c || c.from_id !== accountId) return false
    this.gone(c, 'cancelled')
    await this.rearm()
    return true
  }

  /** Accept: the game starts. `players` carries both accounts' details, read from D1 by the Worker. */
  async accept(id: string, accountId: number, players: Record<number, Player>): Promise<{ game: LiveGame; white: string; black: string } | { error: string; message: string }> {
    const now = Date.now()
    this.expire(now)
    const c = this.one(id)
    if (!c || c.to_id !== accountId) return { error: 'no_such_challenge', message: 'That challenge is no longer open.' }
    if (this.liveGameOf(c.from_id) || this.liveGameOf(c.to_id)) {
      this.gone(c, 'busy')
      await this.rearm()
      return { error: 'in_game', message: 'One of you is already playing a game.' }
    }
    const challengerWhite = c.colour === 'white' || (c.colour === 'random' && crypto.getRandomValues(new Uint8Array(1))[0] < 128)
    const white = players[challengerWhite ? c.from_id : c.to_id]
    const black = players[challengerWhite ? c.to_id : c.from_id]
    if (!white || !black) return { error: 'no_such_challenge', message: 'That challenge is no longer open.' }
    const gameId = b64urlEncode(crypto.getRandomValues(new Uint8Array(12)))
    // the challenge goes, and every other challenge to or from either player (they are busy now)
    this.sql.exec('DELETE FROM challenges WHERE id = ?', c.id)
    for (const o of this.sql.exec<Record<string, SqlStorageValue>>(
      'SELECT * FROM challenges WHERE from_id IN (?1, ?2) OR to_id IN (?1, ?2)', c.from_id, c.to_id).toArray()) {
      this.gone(o as unknown as Challenge, 'busy')
    }
    const g: LiveGame = { id: gameId, white_id: white.id, black_id: black.id, white_handle: white.handle, black_handle: black.handle, tc: c.tc, status: 'live', created: now }
    this.sql.exec('INSERT INTO games (id, white_id, black_id, white_handle, black_handle, tc, status, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
      g.id, g.white_id, g.black_id, g.white_handle, g.black_handle, g.tc, g.status, g.created)
    await this.rearm()
    const stub = this.env.GAME.get(this.env.GAME.idFromName(gameId))
    await stub.init(core.newGame(gameId, white, black, c.tc, now, timingOf(this.env)))
    const accepted = { t: 'challenge_gone', id: c.id, reason: 'accepted', game_id: gameId }
    const start = { t: 'game_start', game: g, rematch_of: c.rematch_of }
    for (const who of [c.from_id, c.to_id]) {
      this.push(who, accepted)
      this.push(who, start)
    }
    return { game: g, white: white.handle, black: black.handle }
  }

  // ── games ─────────────────────────────────────────────────────────────────

  async gameOver(id: string): Promise<void> {
    const g = this.sql.exec<Record<string, SqlStorageValue>>('SELECT * FROM games WHERE id = ?', id).toArray()[0] as unknown as LiveGame | undefined
    if (!g) return
    this.sql.exec("UPDATE games SET status = 'over' WHERE id = ?", id)
    for (const who of [g.white_id, g.black_id]) this.push(who, { t: 'game_over', id })
  }

  async forget(id: string): Promise<void> {
    this.sql.exec('DELETE FROM games WHERE id = ?', id)
  }

  async liveGames(accountId: number): Promise<string[]> {
    return this.sql.exec<{ id: string }>("SELECT id FROM games WHERE status = 'live' AND (white_id = ?1 OR black_id = ?1)", accountId).toArray().map((r) => r.id)
  }

  async gamesBetween(a: number, b: number): Promise<string[]> {
    return this.sql
      .exec<{ id: string }>('SELECT id FROM games WHERE (white_id = ?1 AND black_id = ?2) OR (white_id = ?2 AND black_id = ?1)', a, b)
      .toArray()
      .map((r) => r.id)
  }

  /** two accounts stopped being friends (removed or blocked): their challenges go */
  async cancelBetween(a: number, b: number): Promise<void> {
    for (const c of this.sql.exec<Record<string, SqlStorageValue>>(
      'SELECT * FROM challenges WHERE (from_id = ?1 AND to_id = ?2) OR (from_id = ?2 AND to_id = ?1)', a, b).toArray()) {
      this.gone(c as unknown as Challenge, 'cancelled')
    }
    await this.rearm()
  }

  /** the account is deleted: its challenges go, its sockets close; returns its games, to abandon */
  async forgetAccount(id: number): Promise<string[]> {
    for (const c of this.challengesOf(id)) this.gone(c, 'cancelled')
    await this.rearm()
    const games = this.gamesOf(id).map((g) => g.id)
    for (const ws of this.ctx.getWebSockets('a:' + id)) {
      try {
        ws.close(1000, 'account deleted')
      } catch {
        /* closing */
      }
    }
    return games
  }

  /** every row this object holds about the account (the deletion test) */
  async rowsAbout(id: number): Promise<number> {
    return (
      this.sql.exec<{ n: number }>('SELECT COUNT(*) AS n FROM challenges WHERE from_id = ?1 OR to_id = ?1', id).one().n +
      this.sql.exec<{ n: number }>('SELECT COUNT(*) AS n FROM games WHERE white_id = ?1 OR black_id = ?1', id).one().n
    )
  }
}

export type { Colour }
