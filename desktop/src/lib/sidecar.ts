/**
 * RPC client for the Python sidecar.
 *
 * The sidecar speaks newline-delimited JSON over stdio:
 *   request  → {"id": 1, "method": "...", "params": {...}}
 *   response ← {"id": 1, "result": {...}} | {"id": 1, "error": {"message": "..."}}
 *   event    ← {"event": "...", "data": {...}}
 *
 * Requests are correlated by id and returned as promises; events fan out to
 * subscribers registered with on().
 */
import { Command, type Child } from '@tauri-apps/plugin-shell'
import { BETA } from './build'

/** Injected by `vite.config.ts`, which resolves it from the repo location (or
 *  `$ZUGZWANG_SIDECAR`). Must stay in sync with the arg validator in
 *  `src-tauri/capabilities/default.json`, which is what actually authorises the
 *  spawn — a path this does not match is rejected by Tauri, not by us. */
declare const __SIDECAR_SCRIPT__: string
const SIDECAR_SCRIPT = __SIDECAR_SCRIPT__

/** Bounds a *hang*, not the work. A sidecar that exits is caught by the close
 *  handler immediately, so this only catches one that is alive but stuck, and
 *  the cost of being generous is small while the cost of being tight is failing
 *  real calls. Set above the slowest handler measured against the live database
 *  by ~3×: the first puzzle query after launch is 27 s (1.1 GB table, cold page
 *  cache; 0.3–3.5 s once warm) and an Insights build is ~12 s. */
const REQUEST_TIMEOUT_MS = 90_000

function isWindows(): boolean {
  return typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)
}

export type SidecarStatus =
  /** the first spawn is in flight */
  | 'starting'
  /** a process is running */
  | 'up'
  /** it exited on its own and the single retry is in flight */
  | 'restarting'
  /** it exited and will not be restarted */
  | 'down'

type Pending = {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
  timer: ReturnType<typeof setTimeout>
}
type EventHandler = (data: Record<string, unknown>) => void

export class Sidecar {
  private child: Child | null = null
  private nextId = 1
  private pending = new Map<number, Pending>()
  private handlers = new Map<string, EventHandler[]>()
  private statusFns: ((s: SidecarStatus) => void)[] = []
  private current: SidecarStatus = 'starting'
  /** set by stop(), so a deliberate kill is not mistaken for a crash */
  private stopping = false
  private respawned = false

  get status(): SidecarStatus {
    return this.current
  }

  /** Calls back with the current status immediately, then on every change.
   *  Returns an unsubscribe. */
  onStatus(fn: (s: SidecarStatus) => void): () => void {
    this.statusFns.push(fn)
    fn(this.current)
    return () => {
      const i = this.statusFns.indexOf(fn)
      if (i >= 0) this.statusFns.splice(i, 1)
    }
  }

  private setStatus(s: SidecarStatus): void {
    if (this.current === s) return
    this.current = s
    for (const fn of this.statusFns) fn(s)
  }

  on<T = Record<string, unknown>>(event: string, fn: (data: T) => void): void {
    const arr = this.handlers.get(event) ?? []
    arr.push(fn as EventHandler)
    this.handlers.set(event, arr)
  }

  off<T = Record<string, unknown>>(event: string, fn: (data: T) => void): void {
    const arr = this.handlers.get(event)
    if (!arr) return
    const i = arr.indexOf(fn as EventHandler)
    if (i >= 0) arr.splice(i, 1)
  }

  async start(): Promise<void> {
    this.setStatus('starting')
    await this.spawn()
  }

  private async spawn(): Promise<void> {
    // The packaged build spawns the frozen sidecar from its resource folder
    // (capabilities/beta.json, `$RESOURCE/sidecar/…`; the executable's name differs on
    // Windows); the dev run spawns the checkout's script with its venv (default.json).
    // `--app` tells the frozen sidecar the app launched it, so it may open the default
    // database; started any other way it refuses (BETA-PUB, the live-database guard).
    const cmd = BETA
      ? Command.create(isWindows() ? 'zugzwang-sidecar-win' : 'zugzwang-sidecar', ['--app'])
      : Command.create('zugzwang-sidecar', [SIDECAR_SCRIPT])
    cmd.stdout.on('data', (line: string) => this.onLine(line))
    cmd.stderr.on('data', (line: string) => console.debug(line))
    cmd.on('close', () => this.onClose())
    cmd.on('error', (err) => console.error('[sidecar] spawn error:', err))
    this.child = await cmd.spawn()
    this.setStatus('up')
  }

  private onClose(): void {
    // Clearing this is what stops request() writing into a dead pipe, where the
    // promise would never settle and the caller would wait for the timeout.
    this.child = null
    const why = this.stopping ? 'sidecar stopped' : 'the engine backend stopped'
    for (const p of this.pending.values()) {
      clearTimeout(p.timer)
      p.reject(new Error(why))
    }
    this.pending.clear()
    if (this.stopping) return
    // Exactly one retry, never reset: a sidecar that dies on startup would
    // otherwise spawn in a loop, and the second death is evidence the problem
    // is not transient.
    if (this.respawned) {
      this.setStatus('down')
      return
    }
    this.respawned = true
    this.setStatus('restarting')
    this.spawn().catch((e) => {
      console.error('[sidecar] respawn failed:', e)
      this.setStatus('down')
    })
  }

  private onLine(chunk: string): void {
    for (const raw of chunk.split('\n')) {
      const text = raw.trim()
      if (!text) continue
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(text)
      } catch {
        console.warn('[sidecar] unparseable line:', text)
        continue
      }
      if (typeof msg.event === 'string') {
        for (const fn of this.handlers.get(msg.event) ?? []) {
          fn(msg.data as Record<string, unknown>)
        }
      } else if (typeof msg.id === 'number') {
        const p = this.pending.get(msg.id)
        if (!p) continue
        this.pending.delete(msg.id)
        clearTimeout(p.timer)
        const err = msg.error as { message: string } | undefined
        if (err) p.reject(new Error(err.message))
        else p.resolve(msg.result)
      }
    }
  }

  request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const child = this.child
    if (!child) {
      return Promise.reject(
        new Error(
          this.current === 'restarting'
            ? 'the engine backend is restarting'
            : this.current === 'down'
              ? 'the engine backend is not running'
              : 'sidecar not started',
        ),
      )
    }
    const id = this.nextId++
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`${method} timed out after ${REQUEST_TIMEOUT_MS / 1000}s`))
      }, REQUEST_TIMEOUT_MS)
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer })
      child.write(JSON.stringify({ id, method, params }) + '\n').catch((e) => {
        this.pending.delete(id)
        clearTimeout(timer)
        reject(e)
      })
    })
  }

  async stop(): Promise<void> {
    this.stopping = true
    await this.child?.kill()
    this.child = null
  }
}
