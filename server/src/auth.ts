/**
 * Signed requests (FRIENDS.md ruling V2): every request carries the account's Ed25519 public key, a
 * timestamp, a nonce and a signature over
 *
 *     zugzwang-friends-v1\n<METHOD>\n<path and query>\n<time ms>\n<nonce>\n<sha256 hex of the body>
 *
 * in the headers X-Zz-Key, X-Zz-Time, X-Zz-Nonce and X-Zz-Sig (base64url, no padding). A request is
 * valid for WINDOW_MS either side of the server's clock, and a nonce is accepted once in that window.
 * The nonces live in this isolate's memory only (V1 allows no other table): a replay that reaches a
 * different isolate within the window is not caught, which the window and TLS bound.
 */
import { b64urlDecode, sha256Hex } from './encoding'

export const SIG_PREFIX = 'zugzwang-friends-v1'
export const WINDOW_MS = 60_000

export function canonical(method: string, pathAndQuery: string, time: string, nonce: string, bodyHash: string): string {
  return [SIG_PREFIX, method.toUpperCase(), pathAndQuery, time, nonce, bodyHash].join('\n')
}

/** Nonces seen in the last window, with when each may be forgotten. */
export class NonceCache {
  private seen = new Map<string, number>()
  /** false when the nonce was already used (and is still in the window) */
  use(key: string, nonce: string, now: number): boolean {
    if (this.seen.size > 50_000) this.sweep(now)
    const k = key + ':' + nonce
    const until = this.seen.get(k)
    if (until !== undefined && until > now) return false
    this.seen.set(k, now + 2 * WINDOW_MS)
    return true
  }
  sweep(now: number): void {
    for (const [k, until] of this.seen) if (until <= now) this.seen.delete(k)
  }
}

export type AuthResult = { ok: true; key: string } | { ok: false; status: number; error: string; message: string }

const fail = (error: string, message: string, status = 401): AuthResult => ({ ok: false, status, error, message })

export async function verifySigned(req: Request, body: Uint8Array<ArrayBuffer>, now: number, nonces: NonceCache): Promise<AuthResult> {
  const key = req.headers.get('X-Zz-Key') ?? ''
  const time = req.headers.get('X-Zz-Time') ?? ''
  const nonce = req.headers.get('X-Zz-Nonce') ?? ''
  const sig = req.headers.get('X-Zz-Sig') ?? ''
  if (!key || !time || !nonce || !sig) return fail('unsigned', 'This request must be signed.')
  const pub = b64urlDecode(key)
  const sigBytes = b64urlDecode(sig)
  if (!pub || pub.length !== 32) return fail('bad_key', 'The public key is not 32 bytes of base64url.')
  if (!sigBytes || sigBytes.length !== 64) return fail('bad_signature', 'The signature is not 64 bytes of base64url.')
  if (!/^[0-9]{10,16}$/.test(time)) return fail('bad_time', 'The timestamp is not a time in milliseconds.')
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(nonce)) return fail('bad_nonce', 'The nonce is not 16 to 64 base64url characters.')
  if (Math.abs(now - Number(time)) > WINDOW_MS) {
    return fail('stale', "The request's timestamp is outside the server's window: check this computer's clock.")
  }
  const url = new URL(req.url)
  const message = canonical(req.method, url.pathname + url.search, time, nonce, await sha256Hex(body))
  let good = false
  try {
    const k = await crypto.subtle.importKey('raw', pub, { name: 'Ed25519' }, false, ['verify'])
    good = await crypto.subtle.verify({ name: 'Ed25519' }, k, sigBytes, new TextEncoder().encode(message))
  } catch {
    good = false
  }
  if (!good) return fail('bad_signature', 'The signature does not match the request.')
  if (!nonces.use(key, nonce, now)) return fail('replay', 'This request was already received.')
  return { ok: true, key }
}
