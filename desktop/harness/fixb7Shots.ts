/**
 * FIX-B7: the run's screenshots, each with the DOM layout check (harness/layoutCheck.ts: overflow, overlaps,
 * clipped text, controls out of reach) written beside them; nobody reads the PNGs (DESIGN.md "Owner rulings,
 * 2026-11-21", 1). Into review/scratch/ui/fixb7/ (WebKit: review/scratch/ui/webkit/fixb7/), with layout_check.out.
 *
 *   cd desktop && node harness/fixb7Shots.ts                 (needs review/ui_fixtures/keys_fixtures.json)
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_PORT=5232 node harness/fixb7Shots.ts
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { checkLayout, formatResult } from './layoutCheck.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(repo, 'review', 'ui_fixtures')
const meta = (JSON.parse(readFileSync(resolve(fixtures, 'keys_fixtures.json'), 'utf8')) as {
  meta: { games: { gameId: number; sampled: boolean }[] }
}).meta
const stuck = meta.games.find((g) => !g.sampled)!.gameId
const outDir = resolve(repo, 'review', 'scratch', 'ui', ...(harnessBrowserName === 'webkit' ? ['webkit'] : []), 'fixb7')
mkdirSync(outDir, { recursive: true })
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5231)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port, host: '127.0.0.1' }, logLevel: 'silent' })
await server.listen()
const base = `http://127.0.0.1:${port}`
const browser = await harnessBrowser.launch({ headless: true })

const shots: { name: string; url: string; ready: (p: Page) => Promise<void> }[] = [
  {
    // the game that stayed on "Opening the game…": its report, scrolled to "Your patterns in this game"
    name: 'stuck-game-patterns',
    url: `/?screen=review&game=${stuck}`,
    ready: async (p) => {
      await p.locator('section.patterns').waitFor({ timeout: 8000 })
      await p.locator('section.patterns').scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'review-error',
    url: '/?screen=review&game=main&state=report-throws',
    ready: async (p) => p.getByText('This game could not be opened.').waitFor({ timeout: 4000 }),
  },
  {
    name: 'coach-error',
    url: '/?screen=coach&state=coach-throws-once',
    ready: async (p) => p.getByText('This screen could not be opened.').waitFor({ timeout: 4000 }),
  },
]
const lines = [`# FIX-B7 shots, ${harnessBrowserName}, 1440 x 940, ${new Date().toISOString()}: harness/layoutCheck.ts per shot`]
for (const s of shots) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 940 } })
  await page.goto(base + s.url)
  await s.ready(page)
  await page.waitForTimeout(400)
  const png = resolve(outDir, `${s.name}-app.png`)
  await page.screenshot({ path: png })
  lines.push(formatResult(s.name, await checkLayout(page)))
  await page.close()
}
writeFileSync(resolve(outDir, 'layout_check.out'), lines.join('\n') + '\n')
console.log(lines.join('\n'))
await browser.close()
await server.close()
