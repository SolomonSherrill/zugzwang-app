/**
 * FIX-B7 B5: the acceptance checks (harness/fixb7Checks.ts) in the harness: the game that stayed on "Opening the
 * game…" (two patterns at one move) opens to its report with both rows; the seeded sample of games from the 'before'
 * list opens; a report built to throw shows Review's error within 2 s (ruling HF2) and sends it to the sidecar log;
 * the Coach page built to throw once shows the generic error and "Try again" redraws it. Skipped when the browser or
 * the private fixtures (review/ui_fixtures/keys_fixtures.json, record_keys_fixtures.py) are not installed: the
 * public tree has none.
 */
import { existsSync, readFileSync } from 'node:fs'
import { createServer as netServer } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Browser } from 'playwright'
import { createServer, type ViteDevServer } from 'vite'
import { harnessBrowser, harnessBrowserInstalled, harnessBrowserName } from '../../../harness/browser'
import { failedCoach, failedReview, openGame } from '../../../harness/fixb7Checks'

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..', '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(desktop, '..', 'review', 'ui_fixtures')
const keysFile = resolve(fixtures, 'keys_fixtures.json')
const ready = harnessBrowserInstalled() && existsSync(resolve(fixtures, 'fixtures.json')) && existsSync(keysFile)
type KeysMeta = { games: { external: string; gameId: number; sampled: boolean }[] }
const meta: KeysMeta = ready ? (JSON.parse(readFileSync(keysFile, 'utf8')) as { meta: KeysMeta }).meta : { games: [] }
// The game the run was opened for (BETA.md "FIX-B7"): the first recorded, not sampled
const stuck = meta.games.find((g) => !g.sampled)
const sample = meta.games.filter((g) => g.sampled)

function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const s = netServer()
    s.once('error', fail)
    s.listen(0, '127.0.0.1', () => {
      const p = (s.address() as { port: number }).port
      s.close(() => ok(p))
    })
  })
}

let server: ViteDevServer | null = null
let browser: Browser | null = null
let base = ''

describe.skipIf(!ready)(`FIX-B7: Review opens, and a screen that fails says so [${harnessBrowserName}]`, () => {
  beforeAll(async () => {
    const port = await freePort()
    server = await createServer({
      configFile: resolve(desktop, 'vite.harness.config.ts'),
      server: { port, strictPort: true, host: '127.0.0.1' },
      logLevel: 'silent',
    })
    await server.listen()
    base = `http://127.0.0.1:${port}`
    browser = await harnessBrowser.launch({ headless: true })
  }, 60_000)

  afterAll(async () => {
    await browser?.close()
    await server?.close()
  })

  it('(a) the game with two patterns at one move opens to its report and lists both', async () => {
    const r = await openGame(browser!, base, stuck!.gameId)
    expect(r.errors).toEqual([])
    expect(r.opening).toBe(false)
    expect(r.failed).toBe(false)
    expect(r.report).toBe(true)
    const at = r.patterns.filter((p) => p.move === '15. Qd2')
    expect(at).toHaveLength(2)
    expect(at.some((p) => p.say.includes('took a loose piece'))).toBe(true)
    expect(at.some((p) => p.say.includes('dealt with a loose piece'))).toBe(true)
  }, 30_000)

  it('(b) every game of the seeded sample from the before list opens to its report', async () => {
    expect(sample.length).toBe(20)
    const bad: string[] = []
    for (const g of sample) {
      const r = await openGame(browser!, base, g.gameId)
      if (r.errors.length || r.opening || r.failed || !r.report) bad.push(`${g.external}: ${JSON.stringify(r)}`)
    }
    expect(bad).toEqual([])
  }, 240_000)

  it('(c, d) a report that throws while drawing shows the error within 2 s and sends it to the log', async () => {
    const r = await failedReview(browser!, base)
    expect(r.ms).not.toBeNull()
    expect(r.ms!).toBeLessThan(2000)
    expect(r.opening).toBe(false)
    expect(r.sentence).toBe(true)
    expect(r.sub.length).toBeGreaterThan(0)
    expect(r.back).toBe(true)
    expect(r.logged?.screen).toBe('review')
    expect(r.logged?.message).toBe(r.sub)
    expect(r.logged!.stackLines).toBeGreaterThan(1)
  }, 30_000)

  it('(c) another screen that throws shows the generic error, and Try again redraws it', async () => {
    const r = await failedCoach(browser!, base)
    expect(r.ms).not.toBeNull()
    expect(r.sentence).toBe(true)
    expect(r.sub.length).toBeGreaterThan(0)
    expect(r.logged?.screen).toBe('coach')
    expect(r.redrawn).toBe(true)
    expect(r.failedAfter).toBe(false)
  }, 30_000)
})
