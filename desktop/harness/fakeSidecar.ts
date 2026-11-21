/**
 * A fake sidecar for the browser harness (UI-BUILD A5): answers the RPC protocol of
 * `src/lib/sidecar.ts` from recorded fixtures, so screens render in a plain browser with no
 * Tauri and no Python. Fixtures are recorded from the real sidecar against a backup-API copy
 * of the database (`review/ui_fixtures/record_fixtures.py`, private: never published) and
 * served to the page as `/fixtures.json`.
 *
 * A scenario (the URL's `?state=`) changes what the fake answers, for the empty and loading
 * states: `analysing` replays the main game's analysis as `analysis_ply` events.
 */
import type { SidecarProcess, SidecarTransport } from '../src/lib/sidecar'
import { playHandlers } from './fakePlay'
import { analyzeFen, probeMove } from './fakeAnalysis'

export interface Fixtures {
  meta: Record<string, unknown> & { mainGameId: number; unanalysedGameId: number }
  events: Record<string, Record<string, unknown>>
  responses: Record<string, unknown>
}

export function fixtureKey(method: string, params: Record<string, unknown>): string {
  const sorted = (v: unknown): unknown =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(
          Object.keys(v as object)
            .sort()
            .map((k) => [k, sorted((v as Record<string, unknown>)[k])]),
        )
      : Array.isArray(v)
        ? v.map(sorted)
        : v
  return method + ' ' + JSON.stringify(sorted(params))
}

type Handler = (params: Record<string, unknown>, emit: Emit) => unknown
type Emit = (event: string, data: Record<string, unknown>) => void

export interface FakeOptions {
  scenario?: string
  /** answer delay, so loading states can be seen; 0 by default */
  latencyMs?: number
  /** extra or overriding handlers, by method */
  handlers?: Record<string, Handler>
  /** the ready event to send instead of the fixtures' (null: none, the engine still starting) */
  ready?: Record<string, unknown> | null
  /** how long the spawn takes before the process is up (Tauri's spawn is not instant); 0 by default */
  spawnDelayMs?: number
}

/** Every flag saved through flag_item ("Flag this", beta builds), for the harness's checks. */
export const flagLog: Record<string, unknown>[] = []

/** Every request the page made, for the harness's own checks. */
export const requestLog: { method: string; params: Record<string, unknown>; missing: boolean }[] = []

export function fakeTransport(fx: Fixtures, opts: FakeOptions = {}): SidecarTransport {
  let judgeToken = 0
  const builtin: Record<string, Handler> = {
    // Pure functions of their params that the fixtures cannot enumerate.
    list_games: (p) => {
      const all = fx.responses[fixtureKey('list_games', {})] as { games: unknown[] }
      return { games: typeof p.limit === 'number' ? all.games.slice(0, p.limit) : all.games }
    },
    set_active_screen: (p) => ({ screen: p.screen, bulkSlots: 1, cores: 8, ceiling: 8 }),
    // exploring and Analyse a position (UI-BUILD-3 C/D): chess.js and canned lines
    analyze_fen: analyzeFen(),
    probe_move: probeMove,
    cancel_analysis: () => ({ ok: true }),
    // the trainer's record writes (UI-BUILD-2 E3): acknowledged, nothing stored
    trainer_attempt: () => ({ ok: true }),
    // "Flag this" (beta builds): kept in memory, never written anywhere
    flag_item: (p) => {
      flagLog.push(p)
      return { path: '/harness/flags.jsonl', count: flagLog.length }
    },
    // Settings' username check (UI-BUILD-3 G): every name is found, after a short wait (the
    // scenarios username-missing and username-unreachable answer otherwise). Never the network.
    check_usernames: (p) =>
      new Promise((done) =>
        setTimeout(
          () =>
            done({
              chesscom: p.chesscom ? { status: 'found', message: null } : null,
              lichess: p.lichess ? { status: 'found', message: null } : null,
            }),
          150,
        ),
      ),
    // Play (UI-BUILD-2): a scripted engine over chess.js
    ...playHandlers({ gameId: fx.meta.mainGameId }),
    judge_move: (p, emit) => {
      const token = ++judgeToken
      setTimeout(() => emit('move_judged', { token, fen: p.fen, uci: p.uci, accepted: false, loss: 0 }), 50)
      return { token }
    },
  }
  return {
    async spawn(onLine, onClose): Promise<SidecarProcess> {
      if (opts.spawnDelayMs) await new Promise((r) => setTimeout(r, opts.spawnDelayMs))
      let open = true
      const send = (msg: unknown) => {
        if (open) onLine(JSON.stringify(msg) + '\n')
      }
      const emit: Emit = (event, data) => send({ event, data })
      const ready = opts.ready === undefined ? (fx.events.ready ?? { ok: true }) : opts.ready
      if (ready) setTimeout(() => emit('ready', ready), 0)
      return {
        async write(line: string) {
          const req = JSON.parse(line) as { id: number; method: string; params: Record<string, unknown> }
          const handler = opts.handlers?.[req.method] ?? builtin[req.method]
          const key = fixtureKey(req.method, req.params ?? {})
          let reply: unknown
          let missing = false
          if (handler) {
            try {
              reply = { id: req.id, result: await handler(req.params ?? {}, emit) }
            } catch (e) {
              reply = { id: req.id, error: { message: String((e as Error).message ?? e) } }
            }
          } else if (key in fx.responses) {
            const res = fx.responses[key] as { __error?: { message: string } }
            reply = res && res.__error ? { id: req.id, error: res.__error } : { id: req.id, result: res }
          } else {
            missing = true
            reply = { id: req.id, error: { message: `harness: no fixture for ${key}` } }
            console.warn('[harness] no fixture for', key)
          }
          requestLog.push({ method: req.method, params: req.params ?? {}, missing })
          setTimeout(() => send(reply), opts.latencyMs ?? 0)
        },
        async kill() {
          open = false
          onClose()
        },
      }
    },
  }
}
