#!/usr/bin/env node
// The owner's handle removal (FRIENDS.md ruling A4): there is no admin screen; this script signs with
// the owner's admin key. The key file never leaves this computer and is never committed.
//
//   node scripts/admin.mjs keygen                      make the key, print its PUBLIC half
//   node scripts/admin.mjs remove <handle> <server>    remove an account by its handle
//
// Put the printed public key in wrangler.toml's ADMIN_PUBLIC_KEY and deploy.
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { call, loadIdentity, newIdentity } from './client.mjs'

const KEY_FILE = process.env.ZUGZWANG_ADMIN_KEY ?? join(homedir(), '.config', 'zugzwang', 'friends-admin-key.json')
const [cmd, ...args] = process.argv.slice(2)

if (cmd === 'keygen') {
  if (existsSync(KEY_FILE)) {
    console.error(`${KEY_FILE} exists; not overwriting. Its public key: ${JSON.parse(readFileSync(KEY_FILE, 'utf8')).pub}`)
    process.exit(1)
  }
  const id = await newIdentity()
  mkdirSync(join(KEY_FILE, '..'), { recursive: true })
  writeFileSync(KEY_FILE, JSON.stringify({ pub: id.pub, pkcs8: id.pkcs8 }) + '\n', { mode: 0o600 })
  chmodSync(KEY_FILE, 0o600)
  console.log(`wrote ${KEY_FILE} (mode 600). ADMIN_PUBLIC_KEY = "${id.pub}"`)
} else if (cmd === 'remove' && args.length === 2) {
  const [handle, server] = args
  const id = await loadIdentity(JSON.parse(readFileSync(KEY_FILE, 'utf8')))
  const r = await call(server, id, 'POST', '/v1/admin/remove-handle', { handle })
  console.log(r.status, JSON.stringify(r.body))
  process.exit(r.status === 200 ? 0 : 1)
} else {
  console.error('usage: admin.mjs keygen | admin.mjs remove <handle> <server url>')
  process.exit(2)
}
