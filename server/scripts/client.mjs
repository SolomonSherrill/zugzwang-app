// A signing client for the server's scripts (Node 20+, WebCrypto Ed25519): the same request format as
// src/auth.ts and the app's zugzwang/core/friends_client.py.
import { createHash, randomBytes, webcrypto } from 'node:crypto'

const { subtle } = webcrypto
export const SIG_PREFIX = 'zugzwang-friends-v1'

export const b64url = (buf) => Buffer.from(buf).toString('base64url')

export async function newIdentity() {
  const keys = await subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify'])
  const pub = b64url(await subtle.exportKey('raw', keys.publicKey))
  const pkcs8 = b64url(await subtle.exportKey('pkcs8', keys.privateKey))
  return { pub, pkcs8, privateKey: keys.privateKey }
}

export async function loadIdentity({ pub, pkcs8 }) {
  const privateKey = await subtle.importKey('pkcs8', Buffer.from(pkcs8, 'base64url'), { name: 'Ed25519' }, false, ['sign'])
  return { pub, pkcs8, privateKey }
}

export async function call(server, identity, method, path, body) {
  const text = body === undefined ? '' : JSON.stringify(body)
  const time = String(Date.now())
  const nonce = b64url(randomBytes(16))
  const hash = createHash('sha256').update(text).digest('hex')
  const msg = [SIG_PREFIX, method, path, time, nonce, hash].join('\n')
  const sig = b64url(await subtle.sign({ name: 'Ed25519' }, identity.privateKey, new TextEncoder().encode(msg)))
  const headers = { 'X-Zz-Key': identity.pub, 'X-Zz-Time': time, 'X-Zz-Nonce': nonce, 'X-Zz-Sig': sig }
  if (text) headers['Content-Type'] = 'application/json'
  const r = await fetch(server.replace(/\/$/, '') + path, { method, headers, body: text || undefined })
  let json = null
  try {
    json = await r.json()
  } catch {}
  return { status: r.status, body: json }
}
