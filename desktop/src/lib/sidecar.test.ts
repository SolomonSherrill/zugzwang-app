import { describe, expect, it, beforeEach, vi } from 'vitest'

// A stand-in for the Tauri shell plugin. Each Command.create() records itself so
// a test can drive the process it represents: push a stdout line, fire `close`,
// or check what was written to it.
const { commands, spawnPlan } = vi.hoisted(() => ({
  /** how the next spawn behaves: hold it until `gate` resolves, or fail with `fail` */
  spawnPlan: { gate: null as Promise<void> | null, fail: null as string | null },
  commands: [] as {
    written: string[]
    killed: boolean
    emit: Record<string, (...a: never[]) => void>
    stdoutLine: (line: string) => void
    close: () => void
  }[],
}))

vi.mock('@tauri-apps/plugin-shell', () => ({
  Command: {
    create: () => {
      const cmd = {
        written: [] as string[],
        killed: false,
        emit: {} as Record<string, (...a: never[]) => void>,
        stdout: { on: (_e: string, fn: (l: string) => void) => (cmd.emit.stdout = fn as never) },
        stderr: { on: () => {} },
        on: (e: string, fn: (...a: never[]) => void) => (cmd.emit[e] = fn),
        spawn: async () => {
          if (spawnPlan.gate) await spawnPlan.gate
          if (spawnPlan.fail) throw new Error(spawnPlan.fail)
          return {
            write: async (p: string) => void cmd.written.push(p),
            kill: async () => void (cmd.killed = true),
          }
        },
        stdoutLine: (line: string) => (cmd.emit.stdout as unknown as (l: string) => void)(line),
        close: () => (cmd.emit.close as unknown as () => void)(),
      }
      commands.push(cmd)
      return cmd
    },
  },
}))

import { Sidecar } from './sidecar'

beforeEach(() => {
  commands.length = 0
  spawnPlan.gate = null
  spawnPlan.fail = null
  vi.useRealTimers()
})

function reply(cmdIndex: number, id: number, result: unknown): void {
  commands[cmdIndex].stdoutLine(JSON.stringify({ id, result }) + '\n')
}

describe('request correlation', () => {
  it('resolves the promise whose id the reply carries', async () => {
    const s = new Sidecar()
    await s.start()
    const first = s.request<{ n: number }>('a')
    const second = s.request<{ n: number }>('b')
    reply(0, 2, { n: 2 })
    reply(0, 1, { n: 1 })
    expect(await first).toEqual({ n: 1 })
    expect(await second).toEqual({ n: 2 })
  })
})

describe('a backend that exits on its own', () => {
  it('rejects requests still in flight', async () => {
    const s = new Sidecar()
    await s.start()
    const p = s.request('insights')
    commands[0].close()
    await expect(p).rejects.toThrow('the engine backend stopped')
  })

  it('stops accepting requests instead of writing into a dead pipe', async () => {
    // The point of clearing `child`: otherwise the write is silently lost and
    // the caller waits out the full timeout for a reply that cannot come.
    const s = new Sidecar()
    await s.start()
    commands[0].close()
    await expect(s.request('ping')).rejects.toThrow(/restarting|not running/)
  })

  it('restarts once, and gives up on the second death', async () => {
    const s = new Sidecar()
    const seen: string[] = []
    s.onStatus((st) => seen.push(st))
    await s.start()

    commands[0].close()
    await vi.waitFor(() => expect(commands).toHaveLength(2))
    await vi.waitFor(() => expect(s.status).toBe('up'))

    // A sidecar that dies on startup must not spawn in a loop.
    commands[1].close()
    await vi.waitFor(() => expect(s.status).toBe('down'))
    expect(commands).toHaveLength(2)
    expect(seen).toEqual(['starting', 'up', 'restarting', 'up', 'down'])
  })

  it('routes replies from the replacement process', async () => {
    const s = new Sidecar()
    await s.start()
    commands[0].close()
    await vi.waitFor(() => expect(s.status).toBe('up'))
    const p = s.request<{ pong: boolean }>('ping')
    reply(1, 1, { pong: true })
    expect(await p).toEqual({ pong: true })
  })
})

describe('a deliberate stop', () => {
  it('is not mistaken for a crash', async () => {
    const s = new Sidecar()
    await s.start()
    await s.stop()
    commands[0].close()
    expect(commands).toHaveLength(1)
    expect(s.status).toBe('up')
  })
})

describe('request timeout', () => {
  it('rejects a request the backend never answers', async () => {
    vi.useFakeTimers()
    const s = new Sidecar()
    await s.start()
    const p = s.request('insights')
    const assertion = expect(p).rejects.toThrow('insights timed out after 90s')
    await vi.advanceTimersByTimeAsync(90_000)
    await assertion
  })

  it('does not fire once the reply has arrived', async () => {
    vi.useFakeTimers()
    const s = new Sidecar()
    await s.start()
    const p = s.request<{ ok: boolean }>('ping')
    reply(0, 1, { ok: true })
    expect(await p).toEqual({ ok: true })
    // An uncleared timer would reject an already-settled promise here, which
    // surfaces as an unhandled rejection rather than a test failure.
    await vi.advanceTimersByTimeAsync(90_000)
  })
})

describe('onStatus', () => {
  it('reports the current status on subscribe and stops after unsubscribe', async () => {
    const s = new Sidecar()
    const seen: string[] = []
    const off = s.onStatus((st) => seen.push(st))
    expect(seen).toEqual(['starting'])
    off()
    await s.start()
    expect(seen).toEqual(['starting'])
  })
})

// FIX-STARTUP: a screen's onMount runs before App's, which is what calls start(), so Home's
// first request used to meet a sidecar still 'starting' and fail with "sidecar not started".
describe('a request made while the sidecar is starting', () => {
  it('made before start() is sent once the process is up, and resolves', async () => {
    const s = new Sidecar()
    const p = s.request<{ games: number }>('home_summary')
    expect(commands).toHaveLength(0)
    await s.start()
    await vi.waitFor(() => expect(commands[0].written).toHaveLength(1))
    expect(JSON.parse(commands[0].written[0])).toMatchObject({ id: 1, method: 'home_summary' })
    reply(0, 1, { games: 3 })
    expect(await p).toEqual({ games: 3 })
  })

  it('made while the spawn is in flight waits for it', async () => {
    let release!: () => void
    spawnPlan.gate = new Promise((r) => (release = r))
    const s = new Sidecar()
    const starting = s.start()
    const p = s.request<{ ok: boolean }>('ping')
    await Promise.resolve()
    expect(commands[0].written).toHaveLength(0)
    release()
    await starting
    await vi.waitFor(() => expect(commands[0].written).toHaveLength(1))
    reply(0, 1, { ok: true })
    expect(await p).toEqual({ ok: true })
  })

  it('rejects with the spawn error when the spawn fails, and so do later requests', async () => {
    spawnPlan.fail = 'No such file or directory (os error 2)'
    const s = new Sidecar()
    const early = s.request('home_summary')
    await expect(s.start()).rejects.toThrow('No such file or directory (os error 2)')
    await expect(early).rejects.toThrow('No such file or directory (os error 2)')
    await expect(s.request('ping')).rejects.toThrow('No such file or directory (os error 2)')
  })

  it('times out within the usual request timeout if the spawn never ends', async () => {
    vi.useFakeTimers()
    const s = new Sidecar()
    const p = s.request('insights')
    const assertion = expect(p).rejects.toThrow('insights timed out after 90s')
    await vi.advanceTimersByTimeAsync(90_000)
    await assertion
  })

  it('counts the wait against the timeout', async () => {
    vi.useFakeTimers()
    let release!: () => void
    spawnPlan.gate = new Promise((r) => (release = r))
    const s = new Sidecar()
    const starting = s.start()
    const p = s.request('insights')
    let settled = false
    p.catch(() => (settled = true))
    await vi.advanceTimersByTimeAsync(60_000)
    release()
    await starting
    await vi.advanceTimersByTimeAsync(29_999)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    await expect(p).rejects.toThrow('insights timed out after 90s')
  })

  it('spawns once when start() is called twice', async () => {
    const s = new Sidecar()
    await Promise.all([s.start(), s.start()])
    expect(commands).toHaveLength(1)
  })
})

describe('a request once the backend is down', () => {
  it('still rejects at once', async () => {
    const s = new Sidecar()
    await s.start()
    commands[0].close()
    await vi.waitFor(() => expect(s.status).toBe('up'))
    commands[1].close()
    expect(s.status).toBe('down')
    vi.useFakeTimers()
    let err: Error | null = null
    s.request('ping').catch((e: Error) => (err = e))
    await Promise.resolve()
    await Promise.resolve()
    expect(err).not.toBeNull()
    expect(err!.message).toBe('the engine backend is not running')
  })
})
