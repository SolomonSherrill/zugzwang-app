import { describe, expect, it, beforeEach, vi } from 'vitest'

// A stand-in for the Tauri shell plugin. Each Command.create() records itself so
// a test can drive the process it represents: push a stdout line, fire `close`,
// or check what was written to it.
const { commands } = vi.hoisted(() => ({
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
        spawn: async () => ({
          write: async (p: string) => void cmd.written.push(p),
          kill: async () => void (cmd.killed = true),
        }),
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
