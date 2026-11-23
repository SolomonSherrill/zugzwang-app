/**
 * BETA-6 overlays: every popover, dialog, menu and banner is the topmost element at its centre and each corner (document.elementFromPoint), with one friend and with many; the challenge banner (ruling S6) moves nothing, covers neither the board nor the clocks on a game screen, and has Accept before Decline.
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
import { OVERLAYS, BANNERS } from '../../../harness/beta6Specs'
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

describe.skipIf(!ready)(`BETA-6 overlays (${harnessBrowserName})`, () => {
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
  const GATE_BANNERS = ['home', 'play', 'fgame', 'fgame-over', 'games', 'review', 'friends-one']
  const cases = [...OVERLAYS, ...BANNERS.filter((b) => b.name.endsWith('+banner') && GATE_BANNERS.includes(b.name.replace('+banner', '')))]
  for (const c of cases) {
    it(c.name, async () => {
      const r = await runCase(browser!, base, c, SIZE)
      expect(r.failures).toEqual([])
      for (const o of r.overlays ?? []) expect(o.points.filter((p) => p.ok).length).toBe(5)
      if (c.name.includes('last online row')) expect(r.side).toBe('above')
    }, 60_000)
  }
})
