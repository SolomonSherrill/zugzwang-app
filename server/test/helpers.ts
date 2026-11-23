/** A signing client for the tests: what the app's sidecar does (zugzwang/core/friends_client.py). */
import { env } from 'cloudflare:workers'
import { canonical } from '../src/auth'
import { b64urlEncode, sha256Hex } from '../src/encoding'
import { handle, type Env } from '../src/app'

export const TABLES = ['accounts', 'linked_accounts', 'friend_requests', 'friendships', 'blocks', 'presence'] as const

let ipSeq = 0

export interface Sent {
  status: number
  body: Record<string, any>
}

export interface SendOptions {
  time?: number
  nonce?: string
  /** sign this body but send another */
  sendBody?: string
  /** sign this path but send another */
  signPath?: string
  unsigned?: boolean
  now?: number
  env?: Env
  ip?: string
}

export class Client {
  ip: string
  handle = ''
  private constructor(
    readonly keys: CryptoKeyPair,
    readonly pub: string,
  ) {
    this.ip = `198.51.100.${++ipSeq % 250}`
  }

  static async create(): Promise<Client> {
    const keys = (await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify'])) as CryptoKeyPair
    const raw = new Uint8Array((await crypto.subtle.exportKey('raw', keys.publicKey)) as ArrayBuffer)
    return new Client(keys, b64urlEncode(raw))
  }

  async send(method: string, path: string, body?: unknown, o: SendOptions = {}): Promise<Sent> {
    const now = o.now ?? Date.now()
    const text = body === undefined ? '' : JSON.stringify(body)
    const headers: Record<string, string> = { 'CF-Connecting-IP': o.ip ?? this.ip }
    if (text) headers['Content-Type'] = 'application/json'
    if (!o.unsigned) {
      const time = String(o.time ?? now)
      const nonce = o.nonce ?? b64urlEncode(crypto.getRandomValues(new Uint8Array(16)))
      const msg = canonical(method, o.signPath ?? path, time, nonce, await sha256Hex(text))
      const sig = new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, this.keys.privateKey, new TextEncoder().encode(msg)))
      Object.assign(headers, { 'X-Zz-Key': this.pub, 'X-Zz-Time': time, 'X-Zz-Nonce': nonce, 'X-Zz-Sig': b64urlEncode(sig) })
    }
    const sent = o.sendBody ?? text
    const req = new Request('https://friends.test' + path, { method, headers, body: sent && method !== 'GET' ? sent : undefined })
    const res = await handle(req, (o.env ?? env) as Env, now)
    return { status: res.status, body: (await res.json()) as Record<string, any> }
  }
}

export async function signup(handleName: string): Promise<Client> {
  const c = await Client.create()
  const r = await c.send('POST', '/v1/signup', { handle: handleName, age_confirmed: true, terms_accepted: true })
  if (r.status !== 201) throw new Error(`signup ${handleName}: ${r.status} ${JSON.stringify(r.body)}`)
  c.handle = handleName
  return c
}

export async function accountId(handleName: string): Promise<number> {
  const r = await env.DB.prepare('SELECT id FROM accounts WHERE handle = ?').bind(handleName).first<{ id: number }>()
  return r!.id
}

/** How many rows of each table name the account, by every column that can. */
export async function rowsAbout(id: number): Promise<Record<string, number>> {
  const q: Record<string, string> = {
    accounts: 'SELECT COUNT(*) AS n FROM accounts WHERE id = ?1',
    linked_accounts: 'SELECT COUNT(*) AS n FROM linked_accounts WHERE account_id = ?1',
    friend_requests: 'SELECT COUNT(*) AS n FROM friend_requests WHERE from_id = ?1 OR to_id = ?1',
    friendships: 'SELECT COUNT(*) AS n FROM friendships WHERE a_id = ?1 OR b_id = ?1',
    blocks: 'SELECT COUNT(*) AS n FROM blocks WHERE blocker_id = ?1 OR blocked_id = ?1',
    presence: 'SELECT COUNT(*) AS n FROM presence WHERE account_id = ?1',
  }
  const out: Record<string, number> = {}
  for (const t of TABLES) out[t] = (await env.DB.prepare(q[t]).bind(id).first<{ n: number }>())!.n
  return out
}

/** Every text value stored in any table, for "this was never stored" checks. */
export async function everyStoredText(): Promise<string> {
  const parts: string[] = []
  for (const t of TABLES) {
    const rows = await env.DB.prepare(`SELECT * FROM ${t}`).all()
    parts.push(JSON.stringify(rows.results))
  }
  const schema = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all<{ name: string }>()
  parts.push(schema.results.map((r) => r.name).join(','))
  return parts.join('\n')
}

/** Answer the Worker's outbound fetches (Lichess, Chess.com) from a function, never the network. */
export function stubFetch(answer: (url: string, init?: RequestInit) => Response | Promise<Response>): { calls: { url: string; method: string; auth: string | null }[]; restore: () => void } {
  const real = globalThis.fetch
  const calls: { url: string; method: string; auth: string | null }[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const h = new Headers(init?.headers)
    calls.push({ url, method: init?.method ?? 'GET', auth: h.get('Authorization') })
    return answer(url, init)
  }) as typeof fetch
  return { calls, restore: () => (globalThis.fetch = real) }
}

export const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
