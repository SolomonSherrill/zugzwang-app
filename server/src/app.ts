/**
 * The Zugzwang Friends server's logic (FRIENDS.md, FRIENDS-1 B); src/index.ts is the Worker entry: accounts, friend requests, friendships, blocks,
 * presence and linked accounts, over the six D1 tables of migrations/0001_init.sql and nothing else.
 *
 * Every route but /v1/health and /v1/handles/:handle is signed with the account's Ed25519 key (auth.ts).
 * Logging: nothing here logs a request or response body, and no IP address is written anywhere (V4);
 * an unexpected error logs its route and its message only.
 */
import { NonceCache, verifySigned } from './auth'
import { base32, sha256Hex } from './encoding'
import { handleProblem } from './handles'
import { MemoryLimiter, allowed, type RateLimitBinding } from './ratelimit'

export interface Env {
  DB: D1Database
  LICHESS_API: string
  CHESSCOM_API: string
  ADMIN_PUBLIC_KEY?: string
  LINK_SECRET?: string
  ACCOUNT_LIMITER?: RateLimitBinding
  ANON_LIMITER?: RateLimitBinding
}

export const VERSION = '1'
/** a friend is online when their last heartbeat is this recent (the app beats every 60 s) */
export const ONLINE_MS = 150_000
export const MAX_BODY = 4096
/** friend requests one account may send in an hour, and have pending at once */
export const REQUESTS_PER_HOUR = 20
export const MAX_PENDING_OUT = 50
/** how many hours a Chess.com code is accepted, counting the hour it was made in (BETA-5 ruling K3:
 *  Chess.com's public API refreshes a profile at most once every 12 hours, so the code lasts 24) */
export const LINK_CODE_HOURS = 24

const nonces = new NonceCache()
const accountFallback = new MemoryLimiter(120, 60_000)
const anonFallback = new MemoryLimiter(20, 60_000)

type Json = Record<string, unknown>

function json(status: number, body: Json): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  })
}
const err = (status: number, error: string, message: string) => json(status, { error, message })

interface Account {
  id: number
  handle: string
  public_key: string
  created: number
}

interface Ctx {
  env: Env
  req: Request
  url: URL
  now: number
  body: Uint8Array<ArrayBuffer>
  key: string | null
  account: Account | null
}

function parseBody(ctx: Ctx): Json {
  if (ctx.body.length === 0) return {}
  try {
    const v = JSON.parse(new TextDecoder().decode(ctx.body))
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {}
  } catch {
    return {}
  }
}

async function accountByHandle(env: Env, handle: string): Promise<Account | null> {
  return await env.DB.prepare('SELECT id, handle, public_key, created FROM accounts WHERE handle = ?')
    .bind(handle)
    .first<Account>()
}

async function addressKey(req: Request): Promise<string> {
  // hashed, so even this isolate's memory holds no address (the binding keys by it only to count)
  return 'a:' + (await sha256Hex('zz-rl:' + (req.headers.get('CF-Connecting-IP') ?? 'local'))).slice(0, 32)
}

function pairOf(x: number, y: number): [number, number] {
  return x < y ? [x, y] : [y, x]
}

async function areFriends(env: Env, x: number, y: number): Promise<boolean> {
  const [a, b] = pairOf(x, y)
  return !!(await env.DB.prepare('SELECT 1 FROM friendships WHERE a_id = ? AND b_id = ?').bind(a, b).first())
}

async function blocked(env: Env, blocker: number, blockedId: number): Promise<boolean> {
  return !!(await env.DB.prepare('SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?')
    .bind(blocker, blockedId)
    .first())
}

// ── routes ───────────────────────────────────────────────────────────────────────

async function handleAvailability(ctx: Ctx, handle: string): Promise<Response> {
  const problem = handleProblem(handle)
  if (problem) return json(200, { handle, available: false, reason: problem })
  const taken = await accountByHandle(ctx.env, handle)
  return json(200, { handle, available: !taken, reason: taken ? 'taken' : null })
}

async function signup(ctx: Ctx): Promise<Response> {
  const b = parseBody(ctx)
  const handle = typeof b.handle === 'string' ? b.handle : ''
  // L1: the two checkboxes; the server keeps neither (the sign-up date stands for the agreement)
  if (b.age_confirmed !== true) return err(400, 'age_required', 'You must confirm you are 13 or older.')
  if (b.terms_accepted !== true) return err(400, 'terms_required', 'You must agree to the Terms of use and the Privacy policy.')
  const problem = handleProblem(handle)
  if (problem === 'invalid') return err(400, 'invalid_handle', 'A handle is 3 to 20 characters: letters, numbers, _ and -.')
  if (problem === 'reserved') return err(409, 'reserved_handle', 'That handle is reserved.')
  if (ctx.account) return err(409, 'key_taken', 'This key already has an account.')
  if (await accountByHandle(ctx.env, handle)) return err(409, 'handle_taken', 'That handle is taken.')
  try {
    const row = await ctx.env.DB.prepare('INSERT INTO accounts (handle, public_key, created) VALUES (?, ?, ?) RETURNING id')
      .bind(handle, ctx.key, ctx.now)
      .first<{ id: number }>()
    await ctx.env.DB.prepare('INSERT INTO presence (account_id, last_seen, appear_offline) VALUES (?, ?, 0)')
      .bind(row!.id, ctx.now)
      .run()
  } catch (e) {
    if (String(e).includes('UNIQUE')) return err(409, 'handle_taken', 'That handle is taken.')
    throw e
  }
  return json(201, { handle, created: ctx.now })
}

async function me(ctx: Ctx): Promise<Response> {
  const a = ctx.account!
  const links = await ctx.env.DB.prepare('SELECT site, username, verified FROM linked_accounts WHERE account_id = ? ORDER BY site')
    .bind(a.id)
    .all<{ site: string; username: string; verified: number }>()
  const p = await ctx.env.DB.prepare('SELECT appear_offline FROM presence WHERE account_id = ?')
    .bind(a.id)
    .first<{ appear_offline: number }>()
  return json(200, {
    handle: a.handle,
    created: a.created,
    appear_offline: !!p?.appear_offline,
    linked: links.results.map((l) => ({ site: l.site, username: l.username, verified: !!l.verified })),
  })
}

async function friendsList(ctx: Ctx): Promise<Response> {
  const id = ctx.account!.id
  const db = ctx.env.DB
  const [friends, links, incoming, outgoing, blocks] = await db.batch([
    db.prepare(
      `SELECT acc.id, acc.handle, f.created AS since, p.last_seen, p.appear_offline
         FROM friendships f
         JOIN accounts acc ON acc.id = CASE WHEN f.a_id = ?1 THEN f.b_id ELSE f.a_id END
         LEFT JOIN presence p ON p.account_id = acc.id
        WHERE f.a_id = ?1 OR f.b_id = ?1
        ORDER BY acc.handle COLLATE NOCASE`,
    ).bind(id),
    db.prepare(
      `SELECT l.account_id, l.site, l.username FROM linked_accounts l
        WHERE l.verified = 1 AND l.account_id IN (
          SELECT CASE WHEN a_id = ?1 THEN b_id ELSE a_id END FROM friendships WHERE a_id = ?1 OR b_id = ?1)
        ORDER BY l.site`,
    ).bind(id),
    // requests from an account you blocked are kept (the sender sees "sent") but not shown to you
    db.prepare(
      `SELECT r.id, acc.handle, r.created FROM friend_requests r JOIN accounts acc ON acc.id = r.from_id
        WHERE r.to_id = ?1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.blocker_id = ?1 AND b.blocked_id = r.from_id)
        ORDER BY r.created DESC`,
    ).bind(id),
    db.prepare(
      `SELECT r.id, acc.handle, r.created FROM friend_requests r JOIN accounts acc ON acc.id = r.to_id
        WHERE r.from_id = ? ORDER BY r.created DESC`,
    ).bind(id),
    db.prepare(
      `SELECT acc.handle, b.created FROM blocks b JOIN accounts acc ON acc.id = b.blocked_id
        WHERE b.blocker_id = ? ORDER BY acc.handle COLLATE NOCASE`,
    ).bind(id),
  ])
  type F = { id: number; handle: string; since: number; last_seen: number | null; appear_offline: number | null }
  type Link = { account_id: number; site: string; username: string }
  const linkRows = links.results as Link[]
  return json(200, {
    server_time: ctx.now,
    friends: (friends.results as F[]).map((f) => {
      const hidden = !!f.appear_offline
      return {
        handle: f.handle,
        since: f.since,
        online: !hidden && f.last_seen != null && ctx.now - f.last_seen <= ONLINE_MS,
        last_seen: hidden ? null : f.last_seen,
        linked: linkRows.filter((l) => l.account_id === f.id).map((l) => ({ site: l.site, username: l.username })),
      }
    }),
    incoming: incoming.results,
    outgoing: outgoing.results,
    blocked: blocks.results,
  })
}

async function sendRequest(ctx: Ctx): Promise<Response> {
  const me = ctx.account!
  const b = parseBody(ctx)
  const handle = typeof b.handle === 'string' ? b.handle.trim() : ''
  const to = handle ? await accountByHandle(ctx.env, handle) : null
  if (!to) return err(404, 'no_such_handle', 'No one has that handle.')
  if (to.id === me.id) return err(400, 'self', 'That is your own handle.')
  if (await areFriends(ctx.env, me.id, to.id)) return json(200, { status: 'friends', handle: to.handle })
  if (await blocked(ctx.env, me.id, to.id)) return err(409, 'you_blocked', 'You blocked this account: unblock it first.')
  const db = ctx.env.DB
  // their request to you, pending: sending one back accepts it (unless they blocked you, which cannot
  // happen with a pending request, as blocking removes requests both ways)
  const theirs = await db.prepare('SELECT id FROM friend_requests WHERE from_id = ? AND to_id = ?').bind(to.id, me.id).first<{ id: number }>()
  if (theirs) {
    const [a, c] = pairOf(me.id, to.id)
    await db.batch([
      db.prepare('DELETE FROM friend_requests WHERE (from_id = ?1 AND to_id = ?2) OR (from_id = ?2 AND to_id = ?1)').bind(me.id, to.id),
      db.prepare('INSERT OR IGNORE INTO friendships (a_id, b_id, created) VALUES (?, ?, ?)').bind(a, c, ctx.now),
    ])
    return json(200, { status: 'friends', handle: to.handle })
  }
  const existing = await db.prepare('SELECT id FROM friend_requests WHERE from_id = ? AND to_id = ?').bind(me.id, to.id).first<{ id: number }>()
  if (existing) return json(200, { status: 'sent', id: existing.id, handle: to.handle })
  const counts = await db
    .prepare('SELECT COUNT(*) AS pending, SUM(CASE WHEN created > ? THEN 1 ELSE 0 END) AS recent FROM friend_requests WHERE from_id = ?')
    .bind(ctx.now - 3_600_000, me.id)
    .first<{ pending: number; recent: number | null }>()
  if ((counts?.recent ?? 0) >= REQUESTS_PER_HOUR) return err(429, 'too_many_requests', 'Too many friend requests in the last hour.')
  if ((counts?.pending ?? 0) >= MAX_PENDING_OUT) return err(429, 'too_many_pending', 'Too many requests waiting for an answer: cancel some first.')
  // a request to someone who blocked you is stored and looks sent; they never see it
  const row = await db.prepare('INSERT INTO friend_requests (from_id, to_id, created) VALUES (?, ?, ?) RETURNING id')
    .bind(me.id, to.id, ctx.now)
    .first<{ id: number }>()
  return json(201, { status: 'sent', id: row!.id, handle: to.handle })
}

async function answerRequest(ctx: Ctx, id: number, accept: boolean): Promise<Response> {
  const me = ctx.account!
  const db = ctx.env.DB
  const r = await db.prepare('SELECT id, from_id FROM friend_requests WHERE id = ? AND to_id = ?').bind(id, me.id).first<{ id: number; from_id: number }>()
  if (!r || (await blocked(ctx.env, me.id, r.from_id))) return err(404, 'no_such_request', 'No such request.')
  if (!accept) {
    await db.prepare('DELETE FROM friend_requests WHERE id = ?').bind(id).run()
    return json(200, { status: 'declined' })
  }
  const [a, b] = pairOf(me.id, r.from_id)
  await db.batch([
    db.prepare('DELETE FROM friend_requests WHERE (from_id = ?1 AND to_id = ?2) OR (from_id = ?2 AND to_id = ?1)').bind(me.id, r.from_id),
    db.prepare('INSERT OR IGNORE INTO friendships (a_id, b_id, created) VALUES (?, ?, ?)').bind(a, b, ctx.now),
  ])
  const other = await db.prepare('SELECT handle FROM accounts WHERE id = ?').bind(r.from_id).first<{ handle: string }>()
  return json(200, { status: 'friends', handle: other?.handle })
}

async function cancelRequest(ctx: Ctx, id: number): Promise<Response> {
  const res = await ctx.env.DB.prepare('DELETE FROM friend_requests WHERE id = ? AND from_id = ?').bind(id, ctx.account!.id).run()
  if (!res.meta.changes) return err(404, 'no_such_request', 'No such request.')
  return json(200, { status: 'cancelled' })
}

async function removeFriend(ctx: Ctx, handle: string): Promise<Response> {
  const other = await accountByHandle(ctx.env, handle)
  if (!other) return err(404, 'no_such_handle', 'No one has that handle.')
  const [a, b] = pairOf(ctx.account!.id, other.id)
  const res = await ctx.env.DB.prepare('DELETE FROM friendships WHERE a_id = ? AND b_id = ?').bind(a, b).run()
  if (!res.meta.changes) return err(404, 'not_friends', 'You are not friends.')
  return json(200, { status: 'removed' })
}

async function block(ctx: Ctx): Promise<Response> {
  const me = ctx.account!
  const b = parseBody(ctx)
  const handle = typeof b.handle === 'string' ? b.handle.trim() : ''
  const other = handle ? await accountByHandle(ctx.env, handle) : null
  if (!other) return err(404, 'no_such_handle', 'No one has that handle.')
  if (other.id === me.id) return err(400, 'self', 'That is your own handle.')
  const db = ctx.env.DB
  const [a, c] = pairOf(me.id, other.id)
  await db.batch([
    db.prepare('DELETE FROM friendships WHERE a_id = ? AND b_id = ?').bind(a, c),
    db.prepare('DELETE FROM friend_requests WHERE from_id = ?1 AND to_id = ?2').bind(me.id, other.id),
    // their requests to you stay (so they see "sent") but are hidden from you; see friendsList
    db.prepare('INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created) VALUES (?, ?, ?)').bind(me.id, other.id, ctx.now),
  ])
  return json(200, { status: 'blocked', handle: other.handle })
}

async function unblock(ctx: Ctx, handle: string): Promise<Response> {
  const other = await accountByHandle(ctx.env, handle)
  if (!other) return err(404, 'no_such_handle', 'No one has that handle.')
  await ctx.env.DB.prepare('DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?').bind(ctx.account!.id, other.id).run()
  return json(200, { status: 'unblocked' })
}

async function heartbeat(ctx: Ctx): Promise<Response> {
  await ctx.env.DB.prepare(
    `INSERT INTO presence (account_id, last_seen, appear_offline) VALUES (?1, ?2, 0)
     ON CONFLICT(account_id) DO UPDATE SET last_seen = ?2`,
  ).bind(ctx.account!.id, ctx.now).run()
  return json(200, { ok: true, server_time: ctx.now })
}

async function setPresence(ctx: Ctx): Promise<Response> {
  const b = parseBody(ctx)
  if (typeof b.appear_offline !== 'boolean') return err(400, 'bad_request', 'appear_offline must be true or false.')
  const off = b.appear_offline ? 1 : 0
  await ctx.env.DB.prepare(
    `INSERT INTO presence (account_id, last_seen, appear_offline) VALUES (?1, ?2, ?3)
     ON CONFLICT(account_id) DO UPDATE SET appear_offline = ?3`,
  ).bind(ctx.account!.id, ctx.now, off).run()
  return json(200, { appear_offline: !!off })
}

async function fetchJson(url: string, init: RequestInit = {}): Promise<{ status: number; body: Json | null }> {
  try {
    const r = await fetch(url, { ...init, signal: AbortSignal.timeout(8000) })
    let body: Json | null = null
    try {
      body = (await r.json()) as Json
    } catch {
      body = null
    }
    return { status: r.status, body }
  } catch {
    return { status: 0, body: null }
  }
}

/** a proven link moves to the account that proved it: any other account's row for that name goes */
async function saveVerifiedLink(env: Env, accountId: number, site: string, username: string): Promise<void> {
  const db = env.DB
  await db.batch([
    db.prepare('DELETE FROM linked_accounts WHERE site = ? AND username = ? AND account_id <> ?').bind(site, username, accountId),
    db.prepare(
      `INSERT INTO linked_accounts (account_id, site, username, verified) VALUES (?, ?, ?, 1)
       ON CONFLICT(account_id, site) DO UPDATE SET username = excluded.username, verified = 1`,
    ).bind(accountId, site, username),
  ])
}

async function linkLichess(ctx: Ctx): Promise<Response> {
  const b = parseBody(ctx)
  const token = typeof b.token === 'string' ? b.token : ''
  if (!token || token.length > 200) return err(400, 'bad_request', 'A Lichess sign-in token is needed.')
  const base = ctx.env.LICHESS_API.replace(/\/$/, '')
  const auth = { Authorization: 'Bearer ' + token, Accept: 'application/json' }
  const r = await fetchJson(base + '/api/account', { headers: auth })
  if (r.status === 401 || r.status === 403) return err(401, 'bad_token', 'Lichess did not accept the sign-in.')
  if (r.status !== 200 || !r.body || typeof r.body.username !== 'string') {
    return err(502, 'lichess_unreachable', 'Lichess could not be reached. Try again.')
  }
  // the token was only for this: it is revoked at once and never stored
  await fetchJson(base + '/api/token', { method: 'DELETE', headers: auth })
  const username = r.body.username
  await saveVerifiedLink(ctx.env, ctx.account!.id, 'lichess', username)
  return json(200, { site: 'lichess', username, verified: true })
}

async function linkCode(env: Env, accountId: number, username: string, hour: number): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(env.LINK_SECRET!), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`chesscom|${accountId}|${username.toLowerCase()}|${hour}`))
  return 'ZZ-' + base32(new Uint8Array(mac)).slice(0, 8)
}

const CHESSCOM_NAME = /^[A-Za-z0-9_-]{3,25}$/

async function chesscomStart(ctx: Ctx): Promise<Response> {
  if (!ctx.env.LINK_SECRET) return err(503, 'not_configured', 'Chess.com linking is not set up on this server.')
  const b = parseBody(ctx)
  const username = typeof b.username === 'string' ? b.username.trim() : ''
  if (!CHESSCOM_NAME.test(username)) return err(400, 'bad_username', 'That is not a Chess.com username.')
  const hour = Math.floor(ctx.now / 3_600_000)
  const code = await linkCode(ctx.env, ctx.account!.id, username, hour)
  // the name is kept unverified until the code is found, unless a proven name is already linked
  await ctx.env.DB.prepare(
    `INSERT INTO linked_accounts (account_id, site, username, verified) VALUES (?, 'chesscom', ?, 0)
     ON CONFLICT(account_id, site) DO UPDATE SET username = excluded.username WHERE verified = 0`,
  ).bind(ctx.account!.id, username).run()
  return json(200, { site: 'chesscom', username, code, field: 'location', expires: (hour + LINK_CODE_HOURS) * 3_600_000 })
}

async function chesscomVerify(ctx: Ctx): Promise<Response> {
  if (!ctx.env.LINK_SECRET) return err(503, 'not_configured', 'Chess.com linking is not set up on this server.')
  const b = parseBody(ctx)
  const username = typeof b.username === 'string' ? b.username.trim() : ''
  if (!CHESSCOM_NAME.test(username)) return err(400, 'bad_username', 'That is not a Chess.com username.')
  const base = ctx.env.CHESSCOM_API.replace(/\/$/, '')
  const r = await fetchJson(base + '/pub/player/' + encodeURIComponent(username.toLowerCase()), {
    headers: { Accept: 'application/json', 'User-Agent': 'zugzwang-friends (account link check)' },
  })
  if (r.status === 404 || r.status === 410) return err(404, 'not_found', 'Chess.com has no player of that name.')
  if (r.status !== 200 || !r.body) return err(502, 'chesscom_unreachable', 'Chess.com could not be reached. Try again.')
  const hour = Math.floor(ctx.now / 3_600_000)
  const fields = [r.body.location, r.body.name].filter((v): v is string => typeof v === 'string').map((v) => v.toUpperCase())
  let found = false
  for (let h = hour; h > hour - LINK_CODE_HOURS && !found; h--) {
    const code = await linkCode(ctx.env, ctx.account!.id, username, h)
    found = fields.some((f) => f.includes(code))
  }
  if (!found) return err(409, 'code_not_found', "The code is not in that profile's Location yet. Chess.com's public profile can take up to 12 hours to update.")
  const exact = typeof r.body.username === 'string' ? r.body.username : username
  await saveVerifiedLink(ctx.env, ctx.account!.id, 'chesscom', exact)
  return json(200, { site: 'chesscom', username: exact, verified: true })
}

async function unlink(ctx: Ctx, site: string): Promise<Response> {
  if (site !== 'chesscom' && site !== 'lichess') return err(404, 'not_found', 'No such site.')
  await ctx.env.DB.prepare('DELETE FROM linked_accounts WHERE account_id = ? AND site = ?').bind(ctx.account!.id, site).run()
  return json(200, { status: 'unlinked', site })
}

/** Every row about the account, in every table (ruling V3). */
export async function deleteAccountRows(env: Env, id: number): Promise<void> {
  const db = env.DB
  await db.batch([
    db.prepare('DELETE FROM linked_accounts WHERE account_id = ?').bind(id),
    db.prepare('DELETE FROM friend_requests WHERE from_id = ?1 OR to_id = ?1').bind(id),
    db.prepare('DELETE FROM friendships WHERE a_id = ?1 OR b_id = ?1').bind(id),
    db.prepare('DELETE FROM blocks WHERE blocker_id = ?1 OR blocked_id = ?1').bind(id),
    db.prepare('DELETE FROM presence WHERE account_id = ?').bind(id),
    db.prepare('DELETE FROM accounts WHERE id = ?').bind(id),
  ])
}

async function deleteAccount(ctx: Ctx): Promise<Response> {
  await deleteAccountRows(ctx.env, ctx.account!.id)
  return json(200, { status: 'deleted' })
}

/** The owner's removal of a handle (ruling A4): signed with the admin key, no screen. */
async function adminRemove(ctx: Ctx): Promise<Response> {
  const admin = ctx.env.ADMIN_PUBLIC_KEY ?? ''
  if (!admin || ctx.key !== admin) return err(403, 'forbidden', 'Not the admin key.')
  const b = parseBody(ctx)
  const handle = typeof b.handle === 'string' ? b.handle : ''
  const acc = handle ? await accountByHandle(ctx.env, handle) : null
  if (!acc) return err(404, 'no_such_handle', 'No one has that handle.')
  await deleteAccountRows(ctx.env, acc.id)
  return json(200, { status: 'removed', handle: acc.handle })
}

// ── dispatch ────────────────────────────────────────────────────────────────────

type Route = [method: string, pattern: RegExp, signed: 'none' | 'key' | 'account', fn: (ctx: Ctx, ...m: string[]) => Promise<Response>]

const ROUTES: Route[] = [
  ['GET', /^\/v1\/handles\/([^/]+)$/, 'none', (c, h) => handleAvailability(c, decodeURIComponent(h))],
  ['POST', /^\/v1\/signup$/, 'key', signup],
  ['POST', /^\/v1\/admin\/remove-handle$/, 'key', adminRemove],
  ['GET', /^\/v1\/me$/, 'account', me],
  ['GET', /^\/v1\/friends$/, 'account', friendsList],
  ['POST', /^\/v1\/requests$/, 'account', sendRequest],
  ['POST', /^\/v1\/requests\/(\d+)\/accept$/, 'account', (c, id) => answerRequest(c, Number(id), true)],
  ['POST', /^\/v1\/requests\/(\d+)\/decline$/, 'account', (c, id) => answerRequest(c, Number(id), false)],
  ['DELETE', /^\/v1\/requests\/(\d+)$/, 'account', (c, id) => cancelRequest(c, Number(id))],
  ['DELETE', /^\/v1\/friends\/([^/]+)$/, 'account', (c, h) => removeFriend(c, decodeURIComponent(h))],
  ['POST', /^\/v1\/blocks$/, 'account', block],
  ['DELETE', /^\/v1\/blocks\/([^/]+)$/, 'account', (c, h) => unblock(c, decodeURIComponent(h))],
  ['POST', /^\/v1\/heartbeat$/, 'account', heartbeat],
  ['PUT', /^\/v1\/presence$/, 'account', setPresence],
  ['POST', /^\/v1\/link\/lichess$/, 'account', linkLichess],
  ['POST', /^\/v1\/link\/chesscom\/start$/, 'account', chesscomStart],
  ['POST', /^\/v1\/link\/chesscom\/verify$/, 'account', chesscomVerify],
  ['DELETE', /^\/v1\/link\/([a-z]+)$/, 'account', (c, s) => unlink(c, s)],
  ['DELETE', /^\/v1\/account$/, 'account', deleteAccount],
]

export async function handle(req: Request, env: Env, now = Date.now()): Promise<Response> {
  try {
    return await dispatch(req, env, now)
  } catch (e) {
    // the route and the message only: never a body, a header or an address (V4)
    console.error('error', req.method, new URL(req.url).pathname.replace(/\/[^/]+$/, '/…'), e instanceof Error ? e.message : 'unknown')
    return err(500, 'server_error', 'Something went wrong on the server.')
  }
}

async function dispatch(req: Request, env: Env, now: number): Promise<Response> {
  const url = new URL(req.url)
  if (url.pathname === '/v1/health' && req.method === 'GET') return json(200, { ok: true, version: VERSION })
  let match: RegExpMatchArray | null = null
  const route = ROUTES.find(([m, re]) => m === req.method && (match = url.pathname.match(re)))
  if (!route || !match) {
    return ROUTES.some(([, re]) => re.test(url.pathname))
      ? err(405, 'method_not_allowed', 'Method not allowed.')
      : err(404, 'not_found', 'No such route.')
  }
  const declared = Number(req.headers.get('Content-Length') ?? '0')
  if (declared > MAX_BODY) return err(413, 'too_large', 'The request body is too large.')
  const body = new Uint8Array(await req.arrayBuffer())
  if (body.length > MAX_BODY) return err(413, 'too_large', 'The request body is too large.')
  const ctx: Ctx = { env, req, url, now, body, key: null, account: null }
  const [, , signed, fn] = route
  // unsigned routes and sign-up have no account to count against: they count per address
  if (signed === 'none' || fn === signup) {
    if (!(await allowed(env.ANON_LIMITER, anonFallback, await addressKey(req), now))) {
      return err(429, 'rate_limited', 'Too many requests. Wait a minute.')
    }
  }
  if (signed !== 'none') {
    const v = await verifySigned(req, body, now, nonces)
    if (!v.ok) return err(v.status, v.error, v.message)
    ctx.key = v.key
    ctx.account = await env.DB.prepare('SELECT id, handle, public_key, created FROM accounts WHERE public_key = ?')
      .bind(v.key)
      .first<Account>()
    if (signed === 'account' && !ctx.account) return err(401, 'no_account', 'No account has this key.')
    if (ctx.account && !(await allowed(env.ACCOUNT_LIMITER, accountFallback, 'k:' + ctx.account.id, now))) {
      return err(429, 'rate_limited', 'Too many requests. Wait a minute.')
    }
  }
  return await fn(ctx, ...(match as RegExpMatchArray).slice(1))
}


