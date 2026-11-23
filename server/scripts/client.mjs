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

/** a signed WebSocket (FRIENDS-2): GET path signed as any request, its messages kept in order; Node 22+
 *  (its WebSocket takes headers) */
export async function live(server, identity, path) {
  const time = String(Date.now())
  const nonce = b64url(randomBytes(16))
  const hash = createHash('sha256').update('').digest('hex')
  const msg = [SIG_PREFIX, 'GET', path, time, nonce, hash].join('\n')
  const sig = b64url(await subtle.sign({ name: 'Ed25519' }, identity.privateKey, new TextEncoder().encode(msg)))
  const url = server.replace(/\/$/, '').replace(/^http/, 'ws') + path
  const ws = new WebSocket(url, { headers: { 'X-Zz-Key': identity.pub, 'X-Zz-Time': time, 'X-Zz-Nonce': nonce, 'X-Zz-Sig': sig } })
  const msgs = []
  const waiters = []
  let seen = 0
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    msgs.push(m)
    for (const w of [...waiters]) if (w.pred(m)) {
      waiters.splice(waiters.indexOf(w), 1)
      w.resolve(m)
    }
  })
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', () => reject(new Error('WebSocket ' + path + ' failed to open')), { once: true })
  })
  const ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 15_000)
  ws.addEventListener('close', () => clearInterval(ping))
  return {
    msgs,
    send: (m) => ws.send(JSON.stringify(m)),
    close: () => ws.close(1000, 'bye'),
    next(pred = () => true, ms = 5000) {
      for (let i = seen; i < msgs.length; i++) if (pred(msgs[i])) {
        seen = i + 1
        return Promise.resolve(msgs[i])
      }
      return new Promise((resolve, reject) => {
        const t = setTimeout(() => reject(new Error('no such message within ' + ms + ' ms on ' + path)), ms)
        waiters.push({ pred, resolve: (m) => { clearTimeout(t); seen = msgs.indexOf(m) + 1; resolve(m) } })
      })
    },
  }
}
