/**
 * FIX-B8 B: Review opened while a depth-24 run is under way (started elsewhere) reads "Analysing at depth 24", from
 * the analysis_ply event's own depth (ruling CB1); before the fix it read "depth 14". The harness state
 * `analysing-24` (harness/scenarios.ts) sends the events. Skipped when the browser or the private fixtures are not
 * installed (the public tree has none).
 */
import { existsSync } from 'node:fs'
import { createServer as netServer } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Browser } from 'playwright'
import { harnessBrowser, harnessBrowserInstalled, harnessBrowserName } from '../../../harness/browser'
import { createServer, type ViteDevServer } from 'vite'

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..', '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(desktop, '..', 'review', 'ui_fixtures')
const ready = harnessBrowserInstalled() && existsSync(resolve(fixtures, 'fixtures.json'))

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

describe.skipIf(!ready)(`Review mid-run names the run's depth (FIX-B8 B) [${harnessBrowserName}]`, () => {
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

  it('reads "Analysing at depth 24", never "depth 14"', async () => {
    const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
    await page.goto(`${base}/?screen=review&game=main&state=analysing-24`)
    await page.getByText(/Analysing at depth 24: \d+ of \d+ moves/).first().waitFor({ timeout: 10_000 })
    const text = await page.evaluate(() => document.body.innerText)
    expect(text).toMatch(/Analysing at depth 24: \d+ of \d+ moves/)
    expect(text).not.toMatch(/Analysing at depth 14/)
    await page.close()
  }, 30_000)
})
