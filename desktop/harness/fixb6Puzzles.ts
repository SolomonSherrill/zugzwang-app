/**
 * FIX-B6 B's checks of the Puzzles lobby's database states (ruling PZ1), by code: each state's
 * texts and buttons, the DOM layout check (harness/layoutCheck.ts) and a pixel diff against the
 * previous shot of the same state (review/scratch/ui/puzzles/<name>-app.png, UI-BUILD-2's), in the
 * harness browser (Chromium, or WebKit with ZUGZWANG_HARNESS_BROWSER=webkit). Shots and results go to
 * review/scratch/ui/fixb6/<browser>/puzzles/.
 *
 *   cd desktop && node harness/fixb6Puzzles.ts
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { checkLayout, formatResult } from './layoutCheck.ts'
import { pixelDiff } from './pixels.ts'
import { settle } from './beta6Checks.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const out = resolve(repo, 'review', 'scratch', 'ui', 'fixb6', harnessBrowserName, 'puzzles')
const prev = resolve(repo, 'review', 'scratch', 'ui', 'puzzles')
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5241)

interface S { name: string; state?: string; size?: { width: number; height: number }; act?: (p: Page) => Promise<void> }
const STATES: S[] = [
  { name: 'state-not-imported', state: 'puzzles-not-imported' },
  { name: 'state-importing', state: 'puzzles-importing' },
  {
    name: 'state-import-error', state: 'puzzles-import-error',
    act: async (p) => { await p.getByRole('button', { name: 'Download puzzles from Lichess' }).click() },
  },
  { name: 'lobby', size: { width: 1440, height: 1200 } },
  { name: 'state-updating', state: 'puzzles-updating', size: { width: 1440, height: 1200 } },
  {
    name: 'state-check-newer', state: 'puzzles-check-newer', size: { width: 1440, height: 1200 },
    act: async (p) => {
      await p.getByRole('button', { name: 'Check for new puzzles' }).click()
      await p.getByRole('button', { name: 'Download the new puzzles' }).waitFor()
    },
  },
  {
    name: 'state-check-newest', size: { width: 1440, height: 1200 },
    act: async (p) => {
      await p.getByRole('button', { name: 'Check for new puzzles' }).click()
      await p.getByText('You have the newest').waitFor()
    },
  },
]

mkdirSync(out, { recursive: true })
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const browser = await harnessBrowser.launch({ headless: true })
const diffPage = await (await browser.newContext()).newPage()
await diffPage.setContent('<body></body>')
const lines: string[] = [`# FIX-B6 B: the Puzzles lobby's database states, ${harnessBrowserName} (harness/fixb6Puzzles.ts)`]
let failed = 0
for (const s of STATES) {
  const size = s.size ?? { width: 1440, height: 940 }
  const ctx = await browser.newContext({ viewport: size })
  const page = await ctx.newPage()
  await page.goto(`http://localhost:${port}/?screen=puzzles${s.state ? '&state=' + s.state : ''}`)
  await settle(page)
  if (s.act) {
    await s.act(page)
    await settle(page, 3000)
  }
  const res = await checkLayout(page)
  const bad = res.overflow.length + res.overlaps.length + res.unreachable.length + res.clipped.length + res.wraps.length
  if (bad) failed++
  lines.push(formatResult(s.name, res))
  const db = await page.evaluate(() => {
    const el = document.querySelector('section.db, main .empty') as HTMLElement | null
    return el ? el.innerText.replace(/\s+/g, ' ').trim() : '(none)'
  })
  const buttons = await page.evaluate(() =>
    [...document.querySelectorAll('section.db button, main .empty button')].map((b) => (b as HTMLElement).innerText.trim()))
  lines.push(`  database text: ${db}`)
  lines.push(`  its buttons: ${buttons.join(' | ') || '(none)'}`)
  const png = resolve(out, s.name + '-app.png')
  await page.screenshot({ path: png, fullPage: true })
  const old = resolve(prev, s.name + '-app.png')
  if (existsSync(old)) {
    const d = await pixelDiff(diffPage, readFileSync(old).toString('base64'), readFileSync(png).toString('base64'))
    lines.push(`  pixel diff vs review/scratch/ui/puzzles/${s.name}-app.png: ${(d.share * 100).toFixed(2)} % changed, ${d.nRegions} regions${d.regions.slice(0, 3).map((r) => ` ${r.w}x${r.h}@${r.x},${r.y}`).join('')}`)
  } else {
    lines.push('  pixel diff: no previous shot of this state (new)')
  }
  await ctx.close()
}
lines.push(`${failed} of ${STATES.length} states with a layout failure`)
writeFileSync(resolve(out, 'checks.out'), lines.join('\n') + '\n')
console.log(lines.join('\n'))
await browser.close()
await server.close()
