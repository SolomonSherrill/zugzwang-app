# The Zugzwang Friends server

A Cloudflare Worker over one D1 database: accounts, friend requests, friendships, blocks, presence and
linked Chess.com / Lichess accounts, for the app's Friends screens. Published with the app's source
(GPL-3.0-or-later). The plan and every ruling it follows: the private `FRIENDS.md` (FRIENDS-1 B).

- **Tables** (`migrations/0001_init.sql`): `accounts`, `linked_accounts`, `friend_requests`,
  `friendships`, `blocks`, `presence`. Nothing else.
- **Every request but two is signed** with the account's Ed25519 key (`src/auth.ts`): the key, a
  timestamp and a nonce, valid for 60 s. The two unsigned ones: `GET /v1/health` and
  `GET /v1/handles/:handle` (is a handle free).
- **No request or response bodies are logged and no IP address is stored** by this code. Rate limits
  per account (and per address for the unsigned routes and sign-up) use Cloudflare's rate-limit
  bindings, with an in-memory count when there is no binding.
- **Delete account** removes every row about the account, in every table.

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/v1/health` | `{ ok, version }` |
| GET | `/v1/handles/:handle` | `{ handle, available, reason: null \| "invalid" \| "reserved" \| "taken" }` (unsigned) |
| POST | `/v1/signup` | `{ handle, age_confirmed: true, terms_accepted: true }`, signed with the new key |
| GET | `/v1/me` | your handle, sign-up date, Appear offline, linked accounts |
| GET | `/v1/friends` | friends (with presence and their verified linked accounts), incoming and outgoing requests, blocked |
| POST | `/v1/requests` | `{ handle }`: send (a request back to a pending sender makes you friends) |
| POST | `/v1/requests/:id/accept`, `/v1/requests/:id/decline` | answer a request to you |
| DELETE | `/v1/requests/:id` | cancel your request |
| DELETE | `/v1/friends/:handle` | remove a friend |
| POST, DELETE | `/v1/blocks` `{ handle }`, `/v1/blocks/:handle` | block (ends the friendship and requests), unblock |
| POST | `/v1/heartbeat` | you are online (the app sends one a minute) |
| PUT | `/v1/presence` | `{ appear_offline }` |
| POST | `/v1/link/lichess` | `{ token }` from Lichess's sign-in: the server reads your username with it, revokes it, never stores it |
| POST | `/v1/link/chesscom/start`, `/v1/link/chesscom/verify` | `{ username }`: a code to put in your Chess.com profile's Location, then the check |
| DELETE | `/v1/link/:site` | unlink |
| DELETE | `/v1/account` | delete the account and every row about it |
| POST | `/v1/admin/remove-handle` | `{ handle }`, signed with the owner's admin key only (`scripts/admin.mjs`) |

## Test and run locally (no network, no Cloudflare account)

```bash
cd server && npm ci
npm test            # the Workers runtime locally (@cloudflare/vitest-plugin, Miniflare)
npm run check       # tsc
npx wrangler d1 migrations apply zugzwang-friends --local
npx wrangler dev --local --var LINK_SECRET:dev   # http://localhost:8787
node scripts/live-check.mjs http://localhost:8787
```

## Live games (FRIENDS-2)

Two Durable Object classes, both SQLite-backed (the only kind the Workers Free plan has), their WebSockets
accepted through the Hibernation API: **`Lobby`** (`src/lobby.ts`, one for the server: pending challenges and
each open app's live connection, `GET /v1/live`) and **`Game`** (`src/game.ts`, one per live game,
`GET /v1/games/<id>/live`; the rules are `src/gamecore.ts`, legality by chess.js, BSD-2-Clause). Chat is held in
the game object's memory only. A challenge reaches the challenged app down its lobby socket at once. The
routes: `PUT /v1/settings` (chat; a `share_games` sent by an older app is ignored: BETA-6 ruling SG1 dropped shared games), `POST /v1/challenges`, `POST /v1/challenges/<id>/accept|decline`,
`DELETE /v1/challenges/<id>`, `GET /v1/games/<id>` (the view and, once over, the PGN), `POST /v1/games/<id>/ack`
(saved; the game is deleted once both saved), `POST /v1/games/<id>/rematch`. The socket messages are listed at the top of `src/game.ts`'s `webSocketMessage` and in
`zugzwang/core/friends/live.py`.

**The Free plan's limits** (read 2026-11-22 from developers.cloudflare.com, Durable Objects "Pricing" and
"Limits", Workers "Limits"): Durable Objects requests 100,000 a day (WebSocket messages received count 1 in
20; messages sent are free; alarms count), duration 13,000 GB-s a day (not billed while a hibernatable object
is idle), rows read 5 million and rows written 100,000 a day (each `setAlarm` a row), 5 GB stored; Workers
100,000 requests a day and 10 ms of CPU per invocation (the same per message for a Durable Object).

**A 10-minute game (10+0, about 80 plies), estimated from the code:** Worker requests about 8 (challenge,
accept, two game sockets, two results, two saves), plus the heartbeats there are anyway. Durable Object
requests about 135: about 12 calls from the Worker and between the objects, about 345 messages received
(80 moves, about 20 chat lines, a few offers, and the apps' pings every 10 s on four sockets if pings count)
= 17, and about 105 alarms (one per move for the flag, one every 25 s to look at silent sockets). Rows written
about 195 (the state once per move, the alarm once per move, the looks at the sockets; an alarm that changes
nothing writes only the next alarm). Duration: with hibernation only the handlers' time, about 300 events of a
few ms, under 1 GB-s; even an object that never hibernated would be 600 s × 128 MB = 77 GB-s. CPU per message:
the position is kept in the state, so no message replays the game (a full replay measured 4.7 ms for 115
plies in Node, 2026-11-22; `test/gamecore.test.ts` holds a move after a wake under 5 ms). **So the Free plan
runs it**: rows written bind first, at roughly 500 such games a day (100,000 / 195), then requests at
roughly 750 (100,000 / about 135); far above what Friends will see in beta.

## Deploy

**Deployed 2026-11-22** (FRIENDS-1B C; redeployed 2026-11-23 by BETA-5 C: the Chess.com code lasts 24 hours,
ruling K3; redeployed 2026-11-27 04:28 UTC by BRIL-2 D: a live socket retries a retryable Durable Object error once): the Worker `zugzwang-friends` over the D1 database
`zugzwang-friends` (region ENAM), served **only at https://api.zugzwangapp.com**, a Workers custom domain on
the owner's zone `zugzwangapp.com` (FRIENDS.md ruling V8). `workers_dev = false`: the Worker is not served on workers.dev.
The account's workers.dev subdomain (`zugzwangapp`) was created on 2026-11-23 by FRIENDS-2 B through the API
(`PUT /accounts/<id>/workers/subdomain`), because Cloudflare refuses to deploy Durable Objects without one
(error 10063); nothing is served there. The app's `config.FRIENDS_SERVER_URL` is that address.
**Email Routing on the domain is the owner's: nothing here touches it** (a custom domain adds only the
`api` record).

The steps, as run (and to redeploy). Nothing here prints or stores the token anywhere but its file.

1. **An API token** in `~/.config/zugzwang/cloudflare-token` (alone on one line, `chmod 600`). The one in use
   has, on the account, Workers Scripts and D1 edit, and on the zone `zugzwangapp.com`, Workers Routes,
   DNS and Zone Settings edit (`GET /zones?name=zugzwangapp.com` lists them: `#worker:edit`,
   `#dns_records:edit`, `#zone_settings:edit`, `#zone:read`). The custom domain needs the zone's Workers
   Routes edit and DNS edit; without them deploy to workers.dev instead (`workers_dev = true`, no `routes`).
2. **Install and sign in for this shell:**
   ```bash
   cd ~/zugzwang/server && npm ci
   export CLOUDFLARE_API_TOKEN="$(cat ~/.config/zugzwang/cloudflare-token)"
   npx wrangler whoami
   ```
3. **The database** (done once): `npx wrangler d1 create zugzwang-friends` printed the `database_id` that
   `wrangler.toml` holds; then `npx wrangler d1 migrations apply zugzwang-friends --remote` (and again after
   any new file in `migrations/`, **before** the deploy that reads it: FRIENDS-2's `0002_friends2.sql` adds
   columns the new code selects, and adding them does not disturb the code already deployed). The Durable
   Object classes are created by the deploy itself (`[[migrations]]` in `wrangler.toml`).
4. **Your admin key** (done once; ruling A4): `node scripts/admin.mjs keygen` wrote
   `~/.config/zugzwang/friends-admin-key.json` (mode 600; back it up with the updater key, never commit it)
   and printed the `ADMIN_PUBLIC_KEY` that `wrangler.toml` holds.
5. **Deploy:** `npx wrangler deploy`. It ends with `api.zugzwangapp.com (custom domain)`.
6. **The Chess.com code secret** (done once; it survives deploys):
   `openssl rand -base64 32 | npx wrangler secret put LINK_SECRET`.
7. **The live checks:** `node scripts/live-check.mjs https://api.zugzwangapp.com` (every line PASS, then
   `live check: OK`), and from the app's own code, two sidecars against the server and every table counted
   after: `.venv/bin/python sidecar/friends_live_check.py https://api.zugzwangapp.com` (from the repository
   root, with `CLOUDFLARE_API_TOKEN` exported as in step 2; `--no-tables` without it).
8. **The app's address** is `FRIENDS_SERVER_URL` in `zugzwang/config.py`; `ZUGZWANG_FRIENDS_URL` overrides it
   (the tests, the end-to-end run).
9. **Remove an abusive handle:** `node scripts/admin.mjs remove <handle> https://api.zugzwangapp.com`.
