#!/usr/bin/env node
// The live check after a deploy (FRIENDS.md ruling V6): sign up two test accounts, befriend them,
// see each other's presence, a Chess.com link code that lasts 24 hours (BETA-5 ruling K3; only started, never
// verified, so Chess.com is not asked), then delete both. Prints one line per step; exit 0 when every step passed.
//
//   node scripts/live-check.mjs https://zugzwang-friends.<subdomain>.workers.dev
import { randomBytes } from 'node:crypto'
import { call, newIdentity } from './client.mjs'

const server = process.argv[2]
if (!server) {
  console.error('usage: live-check.mjs <server url>')
  process.exit(2)
}
const tag = randomBytes(3).toString('hex')
const [a, b] = [await newIdentity(), await newIdentity()]
const [ha, hb] = [`check-a-${tag}`, `check-b-${tag}`]
let failed = 0
const step = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`)
  if (!ok) failed++
}
try {
  const health = await fetch(server.replace(/\/$/, '') + '/v1/health').then((r) => r.json())
  step('health', health?.ok === true, JSON.stringify(health))
  const sa = await call(server, a, 'POST', '/v1/signup', { handle: ha, age_confirmed: true, terms_accepted: true })
  step('sign up A', sa.status === 201, ha)
  const sb = await call(server, b, 'POST', '/v1/signup', { handle: hb, age_confirmed: true, terms_accepted: true })
  step('sign up B', sb.status === 201, hb)
  const req = await call(server, a, 'POST', '/v1/requests', { handle: hb })
  step('A sends B a request', req.status === 201 && req.body?.status === 'sent')
  const acc = await call(server, b, 'POST', `/v1/requests/${req.body?.id}/accept`)
  step('B accepts', acc.status === 200 && acc.body?.status === 'friends')
  await call(server, b, 'POST', '/v1/heartbeat')
  const fa = await call(server, a, 'GET', '/v1/friends')
  const f = fa.body?.friends?.[0]
  step('A sees B online', f?.handle === hb && f?.online === true)
  const cs = await call(server, a, 'POST', '/v1/link/chesscom/start', { username: 'zz_live_check' })
  const left = (cs.body?.expires ?? 0) - Date.now()
  step('a Chess.com code lasts 24 hours', cs.status === 200 && left > 23 * 3_600_000 && left <= 24 * 3_600_000,
    `expires in ${(left / 3_600_000).toFixed(2)} h`)
  const da = await call(server, a, 'DELETE', '/v1/account')
  const db = await call(server, b, 'DELETE', '/v1/account')
  step('delete both', da.status === 200 && db.status === 200)
  const gone = await call(server, a, 'GET', '/v1/me')
  step('A is gone', gone.status === 401 && gone.body?.error === 'no_account')
} catch (e) {
  step('no exception', false, String(e))
  await call(server, a, 'DELETE', '/v1/account').catch(() => {})
  await call(server, b, 'DELETE', '/v1/account').catch(() => {})
}
console.log(failed ? `live check: FAILED (${failed})` : 'live check: OK')
process.exit(failed ? 1 : 0)
