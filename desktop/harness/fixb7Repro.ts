/**
 * FIX-B7 B1: open a game in Review in the harness and report what the screen shows and every page error.
 * Reproduced on main with the stuck game merged into a copy of the fixtures:
 *
 *   cd desktop && ZUGZWANG_UI_FIXTURES=<dir> ZUGZWANG_HARNESS_PORT=5231 node harness/fixb7Repro.ts <game id> [waitMs]
 *
 * ZUGZWANG_HARNESS_BASE=<url> opens a harness already served there instead (a production build under
 * `vite preview`), to see what a release build does.
 *
 * Headless; the Vite server listens on localhost only.
 */
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { ConsoleMessage } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'

const here = dirname(fileURLToPath(import.meta.url))
const gameId = process.argv[2]
const waitMs = Number(process.argv[3] ?? 6000)
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5231)
const given = process.env.ZUGZWANG_HARNESS_BASE ?? null
const server = given ? null : await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port, host: '127.0.0.1' }, logLevel: 'silent' })
await server?.listen()
const base = given ?? `http://127.0.0.1:${port}`
const browser = await harnessBrowser.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 940 } })
const errors: string[] = []
page.on('pageerror', (e: Error) => errors.push(`pageerror: ${e.name}: ${e.message}`))
page.on('console', (m: ConsoleMessage) => { if (m.type() === 'error') errors.push(`console.error: ${m.text()}`) })
await page.goto(`${base}/?screen=review&game=${gameId}`)
await page.waitForTimeout(waitMs)
const shown = await page.evaluate(() => ({
  opening: document.body.innerText.includes('Opening the game…'),
  report: !!document.querySelector('[aria-label="Key moments"], .patterns, [data-testid="report-pattern"]'),
  couldNot: document.body.innerText.includes('could not be opened'),
  requests: ((window as unknown as { __harness: { requestLog: { method: string }[] } }).__harness.requestLog ?? []).map((r) => r.method),
}))
console.log(JSON.stringify({ browser: harnessBrowserName, base, gameId, waitMs, ...shown, errors }, null, 1))
await browser.close()
await server?.close()
