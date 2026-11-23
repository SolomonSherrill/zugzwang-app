/** FRIENDS-2 through the Worker and its Durable Objects: challenges, live games over WebSockets, chat, the
 *  switches, sharing, and deletion. The times are the shortened ones of vitest.config.ts. */
import { env } from 'cloudflare:workers'
import { runDurableObjectAlarm, runInDurableObject } from 'cloudflare:test'
import { Chess } from 'chess.js'
import { describe, expect, it } from 'vitest'
import { Client, Live, accountId, everyStoredText, rowsAbout, signup } from './helpers'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
let seq = 0

/** two friends, both checked in (online), each with a lobby socket */
async function pair(): Promise<{ a: Client; b: Client; la: Live; lb: Live; ha: string; hb: string }> {
  const n = ++seq
  const ha = 'pa' + n, hb = 'pb' + n
  const a = await signup(ha)
  const b = await signup(hb)
  const r = await a.send('POST', '/v1/requests', { handle: hb })
  await b.send('POST', `/v1/requests/${r.body.id}/accept`)
  await a.send('POST', '/v1/heartbeat')
  await b.send('POST', '/v1/heartbeat')
  const la = await a.live('/v1/live')
  const lb = await b.live('/v1/live')
  await la.next((m) => m.t === 'hello')
  await lb.next((m) => m.t === 'hello')
  return { a, b, la, lb, ha, hb }
}

/** a challenge from a (as `colour`) accepted by b; both game sockets open */
async function started(tc = '5+0', colour = 'white') {
  const p = await pair()
  const c = await p.a.send('POST', '/v1/challenges', { handle: p.hb, tc, colour })
  expect(c.status).toBe(201)
  await p.lb.next((m) => m.t === 'challenge')
  const acc = await p.b.send('POST', `/v1/challenges/${c.body.challenge.id}/accept`)
  expect(acc.status).toBe(200)
  const id = acc.body.game.id as string
  const ga = await p.a.live(`/v1/games/${id}/live`)
  const gb = await p.b.live(`/v1/games/${id}/live`)
  await ga.next((m) => m.t === 'state')
  await gb.next((m) => m.t === 'state')
  const white = colour === 'black' ? gb : ga
  const black = colour === 'black' ? ga : gb
  return { ...p, id, ga, gb, white, black }
}

async function moves(white: Live, black: Live, sans: string[]) {
  const c = new Chess()
  for (const san of sans) {
    const side = c.turn() === 'w' ? white : black
    const m = c.move(san)
    side.send({ t: 'move', uci: m.lan, ply: c.history().length - 1 })
    await side.next((x) => x.t === 'state' && x.moves.length === c.history().length)
  }
}

const gameStub = (id: string) => env.GAME.get(env.GAME.idFromName(id)) as unknown as DurableObjectStub
const lobbyStub = () => env.LOBBY.get(env.LOBBY.idFromName('lobby'))

describe('the settings switch (H3; sharing ignored, BETA-6 SG1)', () => {
  it('PUT /v1/settings stores chat_on, shows it in /v1/me, and friends see your chat is off', async () => {
    const { a, b, hb } = await pair()
    expect((await b.send('GET', '/v1/me')).body).toMatchObject({ chat_on: true })
    expect((await b.send('PUT', '/v1/settings', { chat_on: 'no' })).status).toBe(400)
    expect((await b.send('PUT', '/v1/settings', {})).status).toBe(400)
    // an app built before BETA-6 still sends share_games: checked, then ignored (the server keeps no switch)
    expect((await b.send('PUT', '/v1/settings', { share_games: 'yes' })).status).toBe(400)
    expect((await b.send('PUT', '/v1/settings', { chat_on: false, share_games: true })).body).toEqual({ chat_on: false })
    const me = (await b.send('GET', '/v1/me')).body
    expect(me).toMatchObject({ chat_on: false })
    expect(me).not.toHaveProperty('share_games')
    const f = (await a.send('GET', '/v1/friends')).body.friends.find((x: any) => x.handle === hb)
    expect(f.chat_on).toBe(false)
  })
})

describe('challenges', () => {
  it('reach the challenged app over its socket within 3 s, with the time control and colour', async () => {
    const { a, lb, la, hb, ha } = await pair()
    const t0 = Date.now()
    const c = await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0', colour: 'black' })
    expect(c.status).toBe(201)
    const m = await lb.next((x) => x.t === 'challenge', 3000)
    expect(Date.now() - t0).toBeLessThan(3000)
    expect(m.challenge).toMatchObject({ from_handle: ha, to_handle: hb, tc: '5+0', colour: 'black' })
    expect(m.challenge.expires - m.challenge.created).toBe(1500)
    expect((await la.next((x) => x.t === 'challenge')).challenge.id).toBe(c.body.challenge.id)
  })
  it('are listed in the hello of a socket opened later', async () => {
    const { a, b, hb } = await pair()
    const c = await a.send('POST', '/v1/challenges', { handle: hb, tc: '3+2' })
    const l2 = await b.live('/v1/live')
    const hello = await l2.next((x) => x.t === 'hello')
    expect(hello.challenges.map((x: any) => x.id)).toContain(c.body.challenge.id)
    expect(hello.challenges[0].colour).toBe('random')
  })
  it('refuse a bad time control (C1), a bad colour, yourself, and a non-friend', async () => {
    const { a, hb, ha } = await pair()
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '7+0' })).body.error).toBe('bad_time_control')
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: 'daily' })).body.error).toBe('bad_time_control')
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0', colour: 'green' })).body.error).toBe('bad_colour')
    expect((await a.send('POST', '/v1/challenges', { handle: ha, tc: '5+0' })).body.error).toBe('self')
    await signup('stranger' + seq)
    expect((await a.send('POST', '/v1/challenges', { handle: 'stranger' + seq, tc: '5+0' })).body.error).toBe('not_friends')
  })
  it('refuse a friend who appears offline, or has not checked in (C2)', async () => {
    const { a, b, hb } = await pair()
    await b.send('PUT', '/v1/presence', { appear_offline: true })
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0' })).body).toMatchObject({ error: 'offline', message: hb + ' is offline.' })
    await b.send('PUT', '/v1/presence', { appear_offline: false })
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0' })).status).toBe(201)
    await env.DB.prepare('UPDATE presence SET last_seen = 0 WHERE account_id = ?').bind(await accountId(hb)).run()
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0' })).body.error).toBe('offline')
  })
  it('refuse a friend who has blocked you (and a block cancels what was pending)', async () => {
    const { a, b, la, ha, hb } = await pair()
    const c = await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0' })
    await b.send('POST', '/v1/blocks', { handle: ha })
    expect((await la.next((x) => x.t === 'challenge_gone')).reason).toBe('cancelled')
    expect((await b.send('POST', `/v1/challenges/${c.body.challenge.id}/accept`)).status).toBe(404)
    expect((await a.send('POST', '/v1/challenges', { handle: hb, tc: '5+0' })).status).toBe(403)
  })
  it('decline tells the challenger; cancel tells the challenged; only the right side may do each', async () => {
    const { a, b, la, lb, hb } = await pair()
    const c1 = await a.send('POST', '/v1/challenges', { handle: hb, tc: '1+0' })
    expect((await a.send('POST', `/v1/challenges/${c1.body.challenge.id}/decline`)).status).toBe(404)
    expect((await b.send('POST', `/v1/challenges/${c1.body.challenge.id}/decline`)).body.status).toBe('declined')
    expect(await la.next((x) => x.t === 'challenge_gone')).toMatchObject({ id: c1.body.challenge.id, reason: 'declined' })
    const c2 = await a.send('POST', '/v1/challenges', { handle: hb, tc: '1+0' })
    expect((await b.send('DELETE', `/v1/challenges/${c2.body.challenge.id}`)).status).toBe(404)
    expect((await a.send('DELETE', `/v1/challenges/${c2.body.challenge.id}`)).body.status).toBe('cancelled')
    expect(await lb.next((x) => x.t === 'challenge_gone' && x.id === c2.body.challenge.id)).toMatchObject({ reason: 'cancelled' })
  })
  it('expire (here after 1.5 s), telling both, and cannot be accepted after', async () => {
    const { a, b, la, lb, hb } = await pair()
    const c = await a.send('POST', '/v1/challenges', { handle: hb, tc: '1+0' })
    await sleep(1600)
    await runDurableObjectAlarm(lobbyStub())
    expect(await lb.next((x) => x.t === 'challenge_gone')).toMatchObject({ reason: 'expired' })
    expect(await la.next((x) => x.t === 'challenge_gone')).toMatchObject({ reason: 'expired' })
    expect((await b.send('POST', `/v1/challenges/${c.body.challenge.id}/accept`)).status).toBe(404)
  })
  it('a second challenge to the same friend replaces the first; at most three out at once', async () => {
    const { a, b, la, hb, ha } = await pair()
    const c1 = await a.send('POST', '/v1/challenges', { handle: hb, tc: '1+0' })
    await a.send('POST', '/v1/challenges', { handle: hb, tc: '3+0' })
    expect(await la.next((x) => x.t === 'challenge_gone')).toMatchObject({ id: c1.body.challenge.id, reason: 'cancelled' })
    for (const n of [1, 2, 3]) {
      const f = await signup(`cap${seq}_${n}`)
      const r = await a.send('POST', '/v1/requests', { handle: f.handle })
      await f.send('POST', `/v1/requests/${r.body.id}/accept`)
      await f.send('POST', '/v1/heartbeat')
      const res = await a.send('POST', '/v1/challenges', { handle: f.handle, tc: '1+0' })
      expect(res.status, 'challenge ' + n).toBe(n < 3 ? 201 : 409)
      if (n === 3) expect(res.body.error).toBe('too_many_challenges')
    }
    void b
    void ha
  })
})

describe('a live game', () => {
  it('starts on accept with the colours asked for, told to both lobbies', async () => {
    const { la, lb, white, black, ha, hb } = await started('5+0', 'black')
    const sa = await la.next((x) => x.t === 'game_start')
    expect(sa.game).toMatchObject({ white_handle: hb, black_handle: ha, tc: '5+0', status: 'live' })
    expect((await lb.next((x) => x.t === 'game_start')).game.id).toBe(sa.game.id)
    expect(white.state()).toMatchObject({ you: 'white', status: 'waiting', turn: 'white', speed: 'blitz' })
    expect(black.state()!.you).toBe('black')
  })
  it('a full game: legal moves on the server, checkmate, the PGN to both, then gone once both saved it', async () => {
    const { a, b, id, white, black, ga } = await started('3+2')
    white.send({ t: 'move', uci: 'e2e5', ply: 0 })
    expect((await white.next((x) => x.t === 'error')).error).toBe('illegal')
    black.send({ t: 'move', uci: 'e7e5', ply: 0 })
    expect((await black.next((x) => x.t === 'error')).error).toBe('not_your_turn')
    await moves(white, black, ['e4', 'e5', 'Bc4', 'Nc6', 'Qh5', 'Nf6', 'Qxf7#'])
    const end = await black.next((x) => x.t === 'state' && x.status === 'over')
    expect(end).toMatchObject({ result: '1-0', termination: 'checkmate', winner: 'white' })
    expect(end.pgn).toContain('4. Qxf7# 1-0')
    white.send({ t: 'takeback' })
    expect((await white.next((x) => x.t === 'error')).error).toBe('bad_message') // P4: there is no takeback
    expect((await a.send('GET', '/v1/games/' + id)).body.pgn).toContain('Qxf7#')
    expect((await a.send('POST', `/v1/games/${id}/ack`)).body.status).toBe('saved')
    expect((await b.send('GET', '/v1/games/' + id)).status).toBe(200)
    expect((await b.send('POST', `/v1/games/${id}/ack`)).body.status).toBe('saved')
    expect((await a.send('GET', '/v1/games/' + id)).status).toBe(404)
    expect(await runInDurableObject(gameStub(id), async (_i, st) => (await st.storage.list()).size)).toBe(0)
    void ga
  })
  it('resign', async () => {
    const { white, black } = await started()
    await moves(white, black, ['d4', 'd5'])
    black.send({ t: 'resign' })
    expect(await white.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'resign', winner: 'white', result: '1-0' })
  })
  it('a draw offer, declined, then offered by the other and accepted', async () => {
    const { white, black } = await started()
    await moves(white, black, ['e4', 'e5'])
    white.send({ t: 'draw_offer' })
    expect((await black.next((x) => x.t === 'state' && x.draw_offer === 'white')).can_offer_draw).toBe(false)
    black.send({ t: 'draw_decline' })
    expect((await white.next((x) => x.t === 'state' && x.draw_offer === null && x.moves.length === 2 && x.can_offer_draw === false)).draw_offer).toBeNull()
    white.send({ t: 'draw_offer' })
    expect((await white.next((x) => x.t === 'error')).error).toBe('too_soon')
    black.send({ t: 'draw_offer' })
    await white.next((x) => x.t === 'state' && x.draw_offer === 'black')
    white.send({ t: 'draw_accept' })
    expect(await black.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'agreed', result: '1/2-1/2' })
  })
  it('a flag ends the game on time', async () => {
    const { id, white, black } = await started('1+0')
    await moves(white, black, ['e4', 'e5'])
    // White's clock: an alarm at the flag; here the stored clock is cut so the flag is due now
    await runInDurableObject(gameStub(id), async (inst: any, st) => {
      inst.s.clock.white = 1
      await st.storage.put('state', inst.s)
    })
    await sleep(5)
    await runDurableObjectAlarm(gameStub(id))
    expect(await black.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'timeout', winner: 'black' })
  })
  it('the alarm is set for the flag while a clock runs', async () => {
    const { id, white, black } = await started('1+0')
    await moves(white, black, ['e4', 'e5'])
    const alarm = await runInDurableObject(gameStub(id), (_i, st) => st.storage.getAlarm())
    const s = white.state()!
    expect(alarm).not.toBeNull()
    expect(Math.abs(alarm! - (s.server_time + s.clock.white))).toBeLessThan(1500)
  })
  it('abort with no first move in time (P2, here 1.5 s)', async () => {
    const { a, id, white, black, la } = await started()
    await sleep(1600)
    await runDurableObjectAlarm(gameStub(id))
    expect(await white.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'aborted', result: '*', pgn: null })
    expect((await la.next((x) => x.t === 'game_over')).id).toBe(id)
    void a
    void black
  })
  it('disconnect then claim (P1, here 0.7 s): too soon refused, then the win', async () => {
    const { id, white, black } = await started('10+0')
    await moves(white, black, ['e4', 'e5', 'Nf3'])
    black.close()
    const left = await white.next((x) => x.t === 'state' && x.opponent.connected === false)
    expect(left.claim_at).toBeGreaterThan(0)
    white.send({ t: 'claim_win' })
    expect((await white.next((x) => x.t === 'error')).error).toBe('too_soon')
    await sleep(750)
    white.send({ t: 'claim_win' })
    expect(await white.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'abandoned', winner: 'white' })
    void id
  })
  it('disconnect, come back, and play on; or call it a draw', async () => {
    const { b, id, white, black } = await started('10+0')
    await moves(white, black, ['e4', 'e5'])
    black.close()
    await white.next((x) => x.t === 'state' && x.opponent.connected === false)
    const back = await b.live(`/v1/games/${id}/live`)
    expect((await white.next((x) => x.t === 'state' && x.opponent.connected === true)).claim_at).toBeNull()
    back.close()
    await white.next((x) => x.t === 'state' && x.opponent.connected === false)
    await sleep(750)
    white.send({ t: 'call_draw' })
    expect(await white.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'abandoned_draw', result: '1/2-1/2' })
  })
  it('a challenge to someone in a game is refused; a challenge from them too', async () => {
    const { a, hb, ha } = await started()
    const c = await signup('third' + seq)
    for (const h of [ha, hb]) {
      const r = await c.send('POST', '/v1/requests', { handle: h })
      const other = h === ha ? a : null
      if (other) await other.send('POST', `/v1/requests/${r.body.id}/accept`)
    }
    await c.send('POST', '/v1/heartbeat')
    expect((await c.send('POST', '/v1/challenges', { handle: ha, tc: '5+0' })).body.error).toBe('in_game')
    expect((await a.send('POST', '/v1/challenges', { handle: c.handle, tc: '5+0' })).body.error).toBe('you_in_game')
  })
  it('rematch swaps colours (P3), with the same time control', async () => {
    const { a, b, id, white, black, ha, hb, la, lb } = await started('3+2', 'white')
    await moves(white, black, ['e4', 'e5'])
    black.send({ t: 'resign' })
    await white.next((x) => x.t === 'state' && x.status === 'over')
    expect((await a.send('POST', `/v1/games/${id}/rematch`)).status).toBe(201)
    const offer = await lb.next((x) => x.t === 'challenge' && x.challenge.rematch_of === id)
    expect(offer.challenge).toMatchObject({ from_handle: ha, tc: '3+2', colour: 'black' })
    expect((await black.next((x) => x.t === 'state' && x.rematch_from !== null)).rematch_from).toBe('white')
    const acc = await b.send('POST', `/v1/challenges/${offer.challenge.id}/accept`)
    expect(acc.body.game).toMatchObject({ white_handle: hb, black_handle: ha, tc: '3+2' })
    expect((await la.next((x) => x.t === 'game_start' && x.rematch_of === id)).game.id).toBe(acc.body.game.id)
  })
  it('a running game cannot be rematched', async () => {
    const { a, id } = await started()
    expect((await a.send('POST', `/v1/games/${id}/rematch`)).body.error).toBe('not_over')
  })
  it('only its players may open a game socket or read it', async () => {
    const { id } = await started()
    const c = await signup('outsider' + seq)
    await expect(c.live(`/v1/games/${id}/live`)).rejects.toThrow(/404/)
    expect((await c.send('GET', '/v1/games/' + id)).status).toBe(404)
  })
})

describe('chat (H1–H4, L3)', () => {
  it('relays text to the opponent and echoes it, at most 200 characters, with a light rate limit', async () => {
    const { white, black, ha } = await started()
    white.send({ t: 'chat', text: '  good luck  ' })
    expect(await black.next((x) => x.t === 'chat')).toMatchObject({ from: 'white', handle: ha, text: 'good luck' })
    expect((await white.next((x) => x.t === 'chat')).text).toBe('good luck')
    white.send({ t: 'chat', text: 'x'.repeat(201) })
    expect((await white.next((x) => x.t === 'error')).error).toBe('too_long')
    white.send({ t: 'chat', text: 'é'.repeat(200) })
    expect((await black.next((x) => x.t === 'chat')).text).toHaveLength(200)
    white.send({ t: 'chat', text: { image: 'data:' } })
    expect((await white.next((x) => x.t === 'error')).error).toBe('bad_message')
    for (let i = 0; i < 4; i++) white.send({ t: 'chat', text: 'm' + i })
    expect((await white.next((x) => x.t === 'error' && x.error === 'chat_rate')).message).toMatch(/Slow down/)
  })
  it('is never written to storage or D1, and is gone when the game ends (H2)', async () => {
    const { id, white, black } = await started()
    white.send({ t: 'chat', text: 'secret-words-17' })
    await black.next((x) => x.t === 'chat')
    const stored = await runInDurableObject(gameStub(id), async (_i, st) => JSON.stringify([...(await st.storage.list()).entries()]))
    expect(stored).not.toContain('secret-words-17')
    expect(await everyStoredText()).not.toContain('secret-words-17')
    await moves(white, black, ['e4', 'e5'])
    white.send({ t: 'resign' })
    await black.next((x) => x.t === 'state' && x.status === 'over')
    const held: number = await runInDurableObject(gameStub(id), (inst): number => (inst as unknown as { chat: unknown[] }).chat.length)
    expect(held).toBe(0)
  })
  it('off (the Settings switch): you cannot send, and the other side sees your chat is off', async () => {
    const { b, white, black } = await started()
    await b.send('PUT', '/v1/settings', { chat_on: false })
    expect((await white.next((x) => x.t === 'state' && x.opponent.chat_on === false)).opponent.chat_on).toBe(false)
    white.send({ t: 'chat', text: 'hello?' })
    expect((await white.next((x) => x.t === 'error')).error).toBe('opponent_chat_off')
    black.send({ t: 'chat', text: 'hi' })
    expect((await black.next((x) => x.t === 'error')).error).toBe('chat_off')
    expect(black.msgs.some((m) => m.t === 'chat')).toBe(false)
  })
  it('a game started with chat off has it off from the start', async () => {
    const p = await pair()
    await p.b.send('PUT', '/v1/settings', { chat_on: false })
    const c = await p.a.send('POST', '/v1/challenges', { handle: p.hb, tc: '5+0', colour: 'white' })
    const acc = await p.b.send('POST', `/v1/challenges/${c.body.challenge.id}/accept`)
    const ga = await p.a.live(`/v1/games/${acc.body.game.id}/live`)
    expect((await ga.next((x) => x.t === 'state')).opponent.chat_on).toBe(false)
  })
  it('muted: the muting player no longer receives the other\'s messages, this game only', async () => {
    const { white, black } = await started()
    black.send({ t: 'mute', on: true })
    await black.next((x) => x.t === 'state' && x.muted === true)
    white.send({ t: 'chat', text: 'can you hear me' })
    expect((await white.next((x) => x.t === 'chat')).text).toBe('can you hear me')
    await sleep(100)
    expect(black.msgs.some((m) => m.t === 'chat')).toBe(false)
    black.send({ t: 'mute', on: false })
    await black.next((x) => x.t === 'state' && x.muted === false)
    white.send({ t: 'chat', text: 'now?' })
    expect((await black.next((x) => x.t === 'chat')).text).toBe('now?')
  })
  it('blocked during the game: no chat either way, the game goes on', async () => {
    const { a, hb, white, black } = await started()
    await a.send('POST', '/v1/blocks', { handle: hb })
    expect((await black.next((x) => x.t === 'state' && x.chat_blocked)).chat_on).toBe(false)
    black.send({ t: 'chat', text: 'hey' })
    expect((await black.next((x) => x.t === 'error')).error).toBe('chat_unavailable')
    await moves(white, black, ['e4', 'e5'])
    expect(black.state()!.status).toBe('playing')
  })
})

describe('no shared games (BETA-6 ruling SG1)', () => {
  it('a finished game is kept nowhere in D1, whatever the apps send, and its listing route is gone', async () => {
    const g = await started()
    await g.a.send('PUT', '/v1/settings', { share_games: true })
    await g.b.send('PUT', '/v1/settings', { share_games: true })
    await moves(g.white, g.black, ['f3', 'e5', 'g4', 'Qh4#'])
    await g.white.next((x) => x.t === 'state' && x.status === 'over')
    await sleep(50)
    const t = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'shared_games'").all()
    expect(t.results).toHaveLength(0)
    const cols = await env.DB.prepare('PRAGMA table_info(presence)').all<{ name: string }>()
    expect(cols.results.map((c) => c.name)).not.toContain('share_games')
    expect((await everyStoredText()).includes(g.id)).toBe(false)
    expect((await g.a.send('GET', `/v1/friends/${g.hb}/games`)).status).toBe(404)
  })
})

describe('deleting an account in FRIENDS-2', () => {
  it('resigns its live game, cancels its challenges and leaves no row about it in D1 or the lobby', async () => {
    const g = await started()
    await moves(g.white, g.black, ['e4', 'e5'])
    const idA = await accountId(g.ha)
    expect((await g.a.send('DELETE', '/v1/account')).body.status).toBe('deleted')
    expect(await g.gb.next((x) => x.t === 'state' && x.status === 'over')).toMatchObject({ termination: 'resign', winner: 'black' })
    for (const [t, n] of Object.entries(await rowsAbout(idA))) expect(n, t).toBe(0)
    // the finished game stays for its other player to save, then goes
    await g.b.send('POST', `/v1/games/${g.id}/ack`)
    await runDurableObjectAlarm(gameStub(g.id))
    expect(await lobbyStub().rowsAbout(idA)).toBe(0)
    expect(await runInDurableObject(gameStub(g.id), async (_i, st) => (await st.storage.list()).size)).toBe(0)
  })
})
