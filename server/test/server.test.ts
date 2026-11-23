import { env, exports } from 'cloudflare:workers'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WINDOW_MS } from '../src/auth'
import { handleProblem } from '../src/handles'
import { MAX_BODY, ONLINE_MS, REQUESTS_PER_HOUR, type Env } from '../src/app'
import { Client, TABLES, accountId, everyStoredText, jsonResponse, rowsAbout, signup, stubFetch } from './helpers'

let restore: (() => void) | null = null
afterEach(() => {
  restore?.()
  restore = null
  vi.restoreAllMocks()
})

describe('health and routing', () => {
  it('answers /v1/health through the deployed entry point', async () => {
    const r = await (exports as unknown as { default: Fetcher }).default.fetch('https://friends.test/v1/health')
    expect(r.status).toBe(200)
    expect(await r.json()).toEqual({ ok: true, version: '1' })
  })
  it('404s an unknown route and 405s a wrong method', async () => {
    const c = await Client.create()
    expect((await c.send('GET', '/v1/nothing')).status).toBe(404)
    expect((await c.send('PATCH', '/v1/me')).status).toBe(405)
  })
  it('has exactly the six tables of ruling V1', async () => {
    const t = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'd1_%' AND name NOT LIKE '_cf%' AND name NOT LIKE 'sqlite_%' ORDER BY name").all<{ name: string }>()
    expect(t.results.map((r) => r.name)).toEqual([...TABLES].sort())
  })
})

describe('handles (ruling A3)', () => {
  it('accepts 3 to 20 of [A-Za-z0-9_-] and nothing else', () => {
    for (const ok of ['abc', 'a_b-c', 'Ri_tan', 'x'.repeat(20), '123']) expect(handleProblem(ok)).toBeNull()
    for (const bad of ['ab', 'x'.repeat(21), 'a b', 'hannah.k', 'é_name', '', 'a/b']) expect(handleProblem(bad)).toBe('invalid')
  })
  it('blocks the reserved names, ignoring case, _ and -, and the reserved prefixes', () => {
    for (const r of ['admin', 'ADMIN', 'Ad_Min', 'support', 'zugzwang', 'Zugzwang', 'zugzwang_fan', 'admin2', 'mod', 'help', 'lichess']) {
      expect(handleProblem(r)).toBe('reserved')
    }
  })
  it('reports availability: available, invalid, reserved, taken (ignoring case)', async () => {
    await signup('maxk')
    const c = await Client.create()
    const ask = async (h: string) => (await c.send('GET', '/v1/handles/' + encodeURIComponent(h), undefined, { unsigned: true })).body
    expect(await ask('fresh_one')).toEqual({ handle: 'fresh_one', available: true, reason: null })
    expect(await ask('ab')).toMatchObject({ available: false, reason: 'invalid' })
    expect(await ask('support')).toMatchObject({ available: false, reason: 'reserved' })
    expect(await ask('MaxK')).toMatchObject({ available: false, reason: 'taken' })
  })
})

describe('sign up (rulings L1, A1, A3)', () => {
  it('requires the 13-or-older and the Terms confirmations', async () => {
    const c = await Client.create()
    expect((await c.send('POST', '/v1/signup', { handle: 'nobox', terms_accepted: true })).body.error).toBe('age_required')
    expect((await c.send('POST', '/v1/signup', { handle: 'nobox', age_confirmed: true })).body.error).toBe('terms_required')
    expect((await c.send('POST', '/v1/signup', { handle: 'nobox', age_confirmed: 'yes', terms_accepted: true })).body.error).toBe('age_required')
  })
  it('creates the account and refuses a taken handle in any case, a reserved one, and a second account per key', async () => {
    const a = await signup('ri_tan')
    const me = await a.send('GET', '/v1/me')
    expect(me.status).toBe(200)
    expect(me.body).toMatchObject({ handle: 'ri_tan', appear_offline: false, linked: [] })
    const b = await Client.create()
    expect((await b.send('POST', '/v1/signup', { handle: 'RI_TAN', age_confirmed: true, terms_accepted: true })).body.error).toBe('handle_taken')
    expect((await b.send('POST', '/v1/signup', { handle: 'zugzwang', age_confirmed: true, terms_accepted: true })).body.error).toBe('reserved_handle')
    expect((await b.send('POST', '/v1/signup', { handle: 'a.b', age_confirmed: true, terms_accepted: true })).body.error).toBe('invalid_handle')
    expect((await a.send('POST', '/v1/signup', { handle: 'second', age_confirmed: true, terms_accepted: true })).body.error).toBe('key_taken')
  })
  it('stores no IP address', async () => {
    const c = await Client.create()
    await c.send('POST', '/v1/signup', { handle: 'ipcheck', age_confirmed: true, terms_accepted: true }, { ip: '203.0.113.77' })
    await c.send('POST', '/v1/heartbeat', undefined, { ip: '203.0.113.77' })
    expect(await everyStoredText()).not.toContain('203.0.113.77')
  })
})

describe('signatures (ruling V2)', () => {
  it('refuses unsigned, tampered, stale, replayed and unknown-key requests', async () => {
    const a = await signup('signer')
    expect((await a.send('GET', '/v1/me', undefined, { unsigned: true })).body.error).toBe('unsigned')
    expect((await a.send('POST', '/v1/requests', { handle: 'x' }, { sendBody: JSON.stringify({ handle: 'y' }) })).body.error).toBe('bad_signature')
    expect((await a.send('GET', '/v1/friends', undefined, { signPath: '/v1/me' })).body.error).toBe('bad_signature')
    const now = Date.now()
    expect((await a.send('GET', '/v1/me', undefined, { time: now - WINDOW_MS - 1, now })).body.error).toBe('stale')
    expect((await a.send('GET', '/v1/me', undefined, { time: now + WINDOW_MS + 1, now })).body.error).toBe('stale')
    expect((await a.send('GET', '/v1/me', undefined, { time: now - WINDOW_MS + 1000, now })).status).toBe(200)
    const nonce = 'AAAAAAAAAAAAAAAAAAAAAA'
    expect((await a.send('GET', '/v1/me', undefined, { nonce, now })).status).toBe(200)
    expect((await a.send('GET', '/v1/me', undefined, { nonce, now })).body.error).toBe('replay')
    const stranger = await Client.create()
    expect((await stranger.send('GET', '/v1/me')).body.error).toBe('no_account')
  })
})

describe('friend requests (ruling V3)', () => {
  it('send, see, accept; both see the friendship', async () => {
    const a = await signup('alpha1')
    const b = await signup('bravo1')
    const sent = await a.send('POST', '/v1/requests', { handle: 'BRAVO1' })
    expect(sent.status).toBe(201)
    expect(sent.body).toMatchObject({ status: 'sent', handle: 'bravo1' })
    const bl = (await b.send('GET', '/v1/friends')).body
    expect(bl.incoming).toHaveLength(1)
    expect(bl.incoming[0]).toMatchObject({ handle: 'alpha1' })
    expect((await a.send('GET', '/v1/friends')).body.outgoing[0]).toMatchObject({ handle: 'bravo1' })
    // a second send returns the same request
    expect((await a.send('POST', '/v1/requests', { handle: 'bravo1' })).body.id).toBe(sent.body.id)
    // only the receiver can accept
    expect((await a.send('POST', `/v1/requests/${sent.body.id}/accept`)).status).toBe(404)
    expect((await b.send('POST', `/v1/requests/${sent.body.id}/accept`)).body).toMatchObject({ status: 'friends', handle: 'alpha1' })
    const af = (await a.send('GET', '/v1/friends')).body
    expect(af.friends.map((f: any) => f.handle)).toEqual(['bravo1'])
    expect(af.outgoing).toHaveLength(0)
    expect((await b.send('GET', '/v1/friends')).body.friends.map((f: any) => f.handle)).toEqual(['alpha1'])
    expect((await a.send('POST', '/v1/requests', { handle: 'bravo1' })).body.status).toBe('friends')
  })
  it('decline and cancel remove the request', async () => {
    const a = await signup('alpha2')
    const b = await signup('bravo2')
    const r1 = await a.send('POST', '/v1/requests', { handle: 'bravo2' })
    expect((await b.send('POST', `/v1/requests/${r1.body.id}/decline`)).body.status).toBe('declined')
    expect((await a.send('GET', '/v1/friends')).body.outgoing).toHaveLength(0)
    const r2 = await a.send('POST', '/v1/requests', { handle: 'bravo2' })
    expect((await b.send('DELETE', `/v1/requests/${r2.body.id}`)).status).toBe(404)
    expect((await a.send('DELETE', `/v1/requests/${r2.body.id}`)).body.status).toBe('cancelled')
    expect((await b.send('GET', '/v1/friends')).body.incoming).toHaveLength(0)
  })
  it('a request back to a pending sender makes you friends at once', async () => {
    const a = await signup('alpha3')
    const b = await signup('bravo3')
    await a.send('POST', '/v1/requests', { handle: 'bravo3' })
    expect((await b.send('POST', '/v1/requests', { handle: 'alpha3' })).body.status).toBe('friends')
    expect((await a.send('GET', '/v1/friends')).body.friends).toHaveLength(1)
    expect((await env.DB.prepare('SELECT COUNT(*) AS n FROM friend_requests WHERE from_id IN (?, ?)').bind(await accountId('alpha3'), await accountId('bravo3')).first<{ n: number }>())!.n).toBe(0)
  })
  it('refuses yourself and unknown handles; limits requests per hour', async () => {
    const a = await signup('alpha4')
    expect((await a.send('POST', '/v1/requests', { handle: 'alpha4' })).body.error).toBe('self')
    expect((await a.send('POST', '/v1/requests', { handle: 'nobody_here' })).body.error).toBe('no_such_handle')
    for (let i = 0; i < REQUESTS_PER_HOUR; i++) {
      await signup(`target${i}`)
      expect((await a.send('POST', '/v1/requests', { handle: `target${i}` })).status).toBe(201)
    }
    await signup('one_more')
    expect((await a.send('POST', '/v1/requests', { handle: 'one_more' })).body.error).toBe('too_many_requests')
  })
  it('remove friend ends the friendship for both', async () => {
    const a = await signup('alpha5')
    const b = await signup('bravo5')
    const r = await a.send('POST', '/v1/requests', { handle: 'bravo5' })
    await b.send('POST', `/v1/requests/${r.body.id}/accept`)
    expect((await b.send('DELETE', '/v1/friends/alpha5')).body.status).toBe('removed')
    expect((await a.send('GET', '/v1/friends')).body.friends).toHaveLength(0)
    expect((await a.send('DELETE', '/v1/friends/bravo5')).body.error).toBe('not_friends')
  })
})

describe('blocks', () => {
  it('blocking ends the friendship and requests; their new request looks sent but is never shown', async () => {
    const a = await signup('alpha6')
    const b = await signup('bravo6')
    const r = await a.send('POST', '/v1/requests', { handle: 'bravo6' })
    await b.send('POST', `/v1/requests/${r.body.id}/accept`)
    expect((await b.send('POST', '/v1/blocks', { handle: 'alpha6' })).body.status).toBe('blocked')
    expect((await a.send('GET', '/v1/friends')).body.friends).toHaveLength(0)
    const again = await a.send('POST', '/v1/requests', { handle: 'bravo6' })
    expect(again.body.status).toBe('sent')
    const bl = (await b.send('GET', '/v1/friends')).body
    expect(bl.incoming).toHaveLength(0)
    expect(bl.blocked.map((x: any) => x.handle)).toEqual(['alpha6'])
    expect((await b.send('POST', `/v1/requests/${again.body.id}/accept`)).status).toBe(404)
    expect((await b.send('POST', '/v1/requests', { handle: 'alpha6' })).body.error).toBe('you_blocked')
    expect((await b.send('DELETE', '/v1/blocks/alpha6')).body.status).toBe('unblocked')
    expect((await b.send('GET', '/v1/friends')).body.incoming).toHaveLength(1)
  })
})

describe('presence (ruling C2)', () => {
  it('online after a heartbeat, last seen after ONLINE_MS, hidden while appearing offline', async () => {
    const a = await signup('alpha7')
    const b = await signup('bravo7')
    const r = await a.send('POST', '/v1/requests', { handle: 'bravo7' })
    await b.send('POST', `/v1/requests/${r.body.id}/accept`)
    const t0 = Date.now()
    expect((await b.send('POST', '/v1/heartbeat', undefined, { now: t0 })).body.ok).toBe(true)
    let f = (await a.send('GET', '/v1/friends', undefined, { now: t0 + 1000 })).body.friends[0]
    expect(f).toMatchObject({ handle: 'bravo7', online: true, last_seen: t0 })
    f = (await a.send('GET', '/v1/friends', undefined, { now: t0 + ONLINE_MS + 1 })).body.friends[0]
    expect(f).toMatchObject({ online: false, last_seen: t0 })
    expect((await b.send('PUT', '/v1/presence', { appear_offline: true }, { now: t0 + 2000 })).body.appear_offline).toBe(true)
    await b.send('POST', '/v1/heartbeat', undefined, { now: t0 + 3000 })
    f = (await a.send('GET', '/v1/friends', undefined, { now: t0 + 4000 })).body.friends[0]
    expect(f).toMatchObject({ online: false, last_seen: null })
    expect((await b.send('GET', '/v1/me')).body.appear_offline).toBe(true)
    expect((await b.send('PUT', '/v1/presence', { appear_offline: 'no' })).status).toBe(400)
  })
})

describe('linked accounts (rulings K1, K2)', () => {
  it('Lichess: the sign-in token proves the name, is revoked at once and never stored', async () => {
    const a = await signup('alpha8')
    const b = await signup('bravo8')
    const r = await a.send('POST', '/v1/requests', { handle: 'bravo8' })
    await b.send('POST', `/v1/requests/${r.body.id}/accept`)
    // a stand-in for the sign-in grant Lichess hands the app
    const grant = ['lio', 'example', 'grant', 'value'].join('-')
    const s = stubFetch((url, init) => {
      if (url === 'https://lichess.org/api/account') return jsonResponse(200, { id: 'pawnstorm', username: 'PawnStorm' })
      if (url === 'https://lichess.org/api/token' && init?.method === 'DELETE') return new Response(null, { status: 204 })
      return jsonResponse(500, {})
    })
    restore = s.restore
    const link = await a.send('POST', '/v1/link/lichess', { token: grant })
    expect(link.body).toEqual({ site: 'lichess', username: 'PawnStorm', verified: true })
    expect(s.calls.map((c) => [c.method, c.url, c.auth])).toEqual([
      ['GET', 'https://lichess.org/api/account', 'Bearer ' + grant],
      ['DELETE', 'https://lichess.org/api/token', 'Bearer ' + grant],
    ])
    expect(await everyStoredText()).not.toContain(grant)
    expect((await b.send('GET', '/v1/friends')).body.friends[0].linked).toEqual([{ site: 'lichess', username: 'PawnStorm' }])
    expect((await a.send('GET', '/v1/me')).body.linked).toEqual([{ site: 'lichess', username: 'PawnStorm', verified: true }])
  })
  it('Lichess: a refused token links nothing', async () => {
    const a = await signup('alpha9')
    restore = stubFetch(() => jsonResponse(401, { error: 'No such token' })).restore
    const refused = 'lio-refused'
    expect((await a.send('POST', '/v1/link/lichess', { token: refused })).body.error).toBe('bad_token')
    expect((await a.send('GET', '/v1/me')).body.linked).toEqual([])
  })
  it('Chess.com: a code in the profile Location proves the name; without it, nothing is proven', async () => {
    const a = await signup('alpha10')
    const start = await a.send('POST', '/v1/link/chesscom/start', { username: 'Knight_Rider' })
    expect(start.status).toBe(200)
    expect(start.body.code).toMatch(/^ZZ-[0-9A-HJKMNP-TV-Z]{8}$/)
    expect(start.body.field).toBe('location')
    expect((await a.send('GET', '/v1/me')).body.linked).toEqual([{ site: 'chesscom', username: 'Knight_Rider', verified: false }])
    let location = 'Somewhere'
    const s = stubFetch((url) =>
      url === 'https://api.chess.com/pub/player/knight_rider'
        ? jsonResponse(200, { username: 'knight_rider', location })
        : jsonResponse(404, {}),
    )
    restore = s.restore
    expect((await a.send('POST', '/v1/link/chesscom/verify', { username: 'Knight_Rider' })).body.error).toBe('code_not_found')
    location = `Leeds ${start.body.code.toLowerCase()}`
    const v = await a.send('POST', '/v1/link/chesscom/verify', { username: 'Knight_Rider' })
    expect(v.body).toEqual({ site: 'chesscom', username: 'knight_rider', verified: true })
    expect(await everyStoredText()).not.toContain(start.body.code)
    expect((await a.send('POST', '/v1/link/chesscom/verify', { username: 'nobody_there' })).body.error).toBe('not_found')
  })
  it('Chess.com: the code lasts 24 hours (BETA-5 ruling K3), on a fake clock and a fake Chess.com', async () => {
    const a = await signup('alpha10b')
    const b = await signup('bravo10b')
    const hour = 3_600_000
    const t0 = Math.floor(Date.now() / hour) * hour + 25 * 60_000      // 25 minutes into an hour
    const sa = await a.send('POST', '/v1/link/chesscom/start', { username: 'slow_profile' }, { now: t0 })
    const sb = await b.send('POST', '/v1/link/chesscom/start', { username: 'late_profile' }, { now: t0 })
    expect(sa.body.expires).toBe(Math.floor(t0 / hour) * hour + 24 * hour)
    const locations: Record<string, string> = { slow_profile: 'Nowhere', late_profile: 'Nowhere' }
    restore = stubFetch((url) => {
      const name = url.split('/').pop()!
      return name in locations ? jsonResponse(200, { username: name, location: locations[name] }) : jsonResponse(404, {})
    }).restore
    const nf = await a.send('POST', '/v1/link/chesscom/verify', { username: 'slow_profile' }, { now: t0 + hour })
    expect(nf.body.error).toBe('code_not_found')
    expect(nf.body.message).toBe("The code is not in that profile's Location yet. Chess.com's public profile can take up to 12 hours to update.")
    expect(nf.body.message).not.toMatch(/minute/)
    // Chess.com shows the code 12 hours later: still accepted, the last minute before it expires too
    locations.slow_profile = 'Leeds ' + sa.body.code
    locations.late_profile = sb.body.code
    expect((await a.send('POST', '/v1/link/chesscom/verify', { username: 'slow_profile' }, { now: sa.body.expires - 60_000 })).body.verified).toBe(true)
    // ... and refused from the moment it expires
    expect((await b.send('POST', '/v1/link/chesscom/verify', { username: 'late_profile' }, { now: sb.body.expires })).body.error).toBe('code_not_found')
  })
  it('Chess.com: a code made for another account or name does not prove this one', async () => {
    const a = await signup('alpha11')
    const b = await signup('bravo11')
    const codeA = (await a.send('POST', '/v1/link/chesscom/start', { username: 'shared_name' })).body.code
    restore = stubFetch(() => jsonResponse(200, { username: 'shared_name', location: codeA })).restore
    expect((await b.send('POST', '/v1/link/chesscom/verify', { username: 'shared_name' })).body.error).toBe('code_not_found')
    expect((await a.send('POST', '/v1/link/chesscom/verify', { username: 'shared_name' })).body.verified).toBe(true)
  })
  it('a proven name moves to the account that proved it; unlink removes it', async () => {
    const a = await signup('alpha12')
    const b = await signup('bravo12')
    restore = stubFetch(() => jsonResponse(200, { username: 'OnePlayer' })).restore
    await a.send('POST', '/v1/link/lichess', { token: 't1' })
    await b.send('POST', '/v1/link/lichess', { token: 't2' })
    expect((await a.send('GET', '/v1/me')).body.linked).toEqual([])
    expect((await b.send('GET', '/v1/me')).body.linked).toHaveLength(1)
    expect((await b.send('DELETE', '/v1/link/lichess')).body.status).toBe('unlinked')
    expect((await b.send('GET', '/v1/me')).body.linked).toEqual([])
  })
})

describe('delete account (ruling V3: every row about the user)', () => {
  it('leaves no row naming the account in any table, and the others intact', async () => {
    const a = await signup('alpha13')
    const b = await signup('bravo13')
    const c = await signup('charlie13')
    const r = await a.send('POST', '/v1/requests', { handle: 'bravo13' })
    await b.send('POST', `/v1/requests/${r.body.id}/accept`)
    await a.send('POST', '/v1/requests', { handle: 'charlie13' })
    await signup('delta13')
    await a.send('POST', '/v1/requests', { handle: 'delta13' })
    await c.send('POST', '/v1/blocks', { handle: 'alpha13' })
    await a.send('POST', '/v1/blocks', { handle: 'charlie13' })
    restore = stubFetch(() => jsonResponse(200, { username: 'alpha_on_lichess' })).restore
    await a.send('POST', '/v1/link/lichess', { token: 't' })
    await a.send('POST', '/v1/heartbeat')
    const id = await accountId('alpha13')
    const before = await rowsAbout(id)
    for (const t of TABLES) expect(before[t], t).toBeGreaterThan(0)
    expect((await a.send('DELETE', '/v1/account')).body.status).toBe('deleted')
    const after = await rowsAbout(id)
    for (const t of TABLES) expect(after[t], t).toBe(0)
    expect((await a.send('GET', '/v1/me')).body.error).toBe('no_account')
    expect((await b.send('GET', '/v1/friends')).body.friends).toHaveLength(0)
    expect((await b.send('GET', '/v1/me')).status).toBe(200)
    // the handle is free again
    expect((await b.send('GET', '/v1/handles/alpha13', undefined, { unsigned: true })).body.available).toBe(true)
  })
})

describe("the owner's removal of a handle (ruling A4)", () => {
  it('works only with the admin key, and removes every row', async () => {
    const admin = await Client.create()
    const adminEnv = { ...(env as unknown as Env), ADMIN_PUBLIC_KEY: admin.pub }
    const victim = await signup('abusive_one')
    const id = await accountId('abusive_one')
    expect((await victim.send('POST', '/v1/admin/remove-handle', { handle: 'abusive_one' }, { env: adminEnv })).body.error).toBe('forbidden')
    expect((await admin.send('POST', '/v1/admin/remove-handle', { handle: 'abusive_one' })).body.error).toBe('forbidden')
    expect((await admin.send('POST', '/v1/admin/remove-handle', { handle: 'abusive_one' }, { env: adminEnv })).body).toEqual({ status: 'removed', handle: 'abusive_one' })
    for (const n of Object.values(await rowsAbout(id))) expect(n).toBe(0)
  })
})

describe('limits and logs (ruling V4)', () => {
  it('rate-limits each account', async () => {
    const a = await signup('busy_one')
    let limited = 0
    for (let i = 0; i < 130; i++) if ((await a.send('POST', '/v1/heartbeat')).status === 429) limited++
    expect(limited).toBeGreaterThan(0)
    const other = await signup('calm_one')
    expect((await other.send('POST', '/v1/heartbeat')).status).toBe(200)
  })
  it('refuses a body over the limit', async () => {
    const a = await signup('big_body')
    expect((await a.send('POST', '/v1/requests', { handle: 'x'.repeat(MAX_BODY) })).status).toBe(413)
  })
  it('logs no request body and no response body', async () => {
    const logged: string[] = []
    for (const m of ['log', 'info', 'warn', 'error', 'debug'] as const) {
      vi.spyOn(console, m).mockImplementation((...args: unknown[]) => void logged.push(args.map(String).join(' ')))
    }
    const marker = 'MARKER_7c1d'
    const a = await signup('logcheck')
    await a.send('POST', '/v1/requests', { handle: marker })
    await a.send('POST', '/v1/link/chesscom/start', { username: marker })
    await a.send('POST', '/v1/signup', { handle: marker, age_confirmed: true, terms_accepted: true })
    // a failing route: the database answers an error
    const broken = { ...(env as unknown as Env), DB: { prepare: () => { throw new Error('boom') } } as unknown as D1Database }
    expect((await a.send('POST', '/v1/requests', { handle: marker }, { env: broken })).status).toBe(500)
    expect(logged.join('\n')).not.toContain(marker)
  })
})
