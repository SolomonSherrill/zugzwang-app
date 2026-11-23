/**
 * BETA-6 long names (FRIENDS.md ruling S7): on every screen, with the longest names allowed (a 20-character handle of W's, a 25-character Chess.com username, a 60-character PGN name), no two text boxes overlap and every name cut short ends in "…" with its full text as a tooltip.
 * The cases are harness/beta6Specs.ts's, at 1280 x 720 (the smallest window), in the harness browser; the full
 * run, both browsers and both sizes with shots, is harness/beta6Checks.ts (review/scratch/ui/beta6/).
 * Skipped when the browser or the private fixtures are not installed (the public tree has none).
 */
import { existsSync } from 'node:fs'
import { createServer as netServer } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Browser } from 'playwright'
import { createServer, type ViteDevServer } from 'vite'
import { harnessBrowser, harnessBrowserInstalled, harnessBrowserName } from '../../../harness/browser'
import { SCREENS } from '../../../harness/beta6Specs'
import { runCase } from '../../../harness/beta6Checks'

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..', '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(desktop, '..', 'review', 'ui_fixtures')
const ready = harnessBrowserInstalled() && existsSync(resolve(fixtures, 'fixtures.json'))
const SIZE = { width: 1280, height: 720 }

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

describe.skipIf(!ready)(`BETA-6 long names (FRIENDS.md ruling S7) (${harnessBrowserName})`, () => {
  beforeAll(async () => {
    const port = await freePort()
    server = await createServer({ configFile: resolve(desktop, 'vite.harness.config.ts'), server: { port, strictPort: true, host: '127.0.0.1' }, logLevel: 'silent' })
    await server.listen()
    base = `http://127.0.0.1:${port}`
    browser = await harnessBrowser.launch({ headless: true })
  }, 60_000)
  afterAll(async () => {
    await browser?.close()
    await server?.close()
  })
  for (const c of SCREENS) {
    it(c.name, async () => {
      const r = await runCase(browser!, base, c, SIZE)
      expect(r.failures).toEqual([])
      expect(r.names!.texts).toBeGreaterThan(0)
    }, 60_000)
  }
})
