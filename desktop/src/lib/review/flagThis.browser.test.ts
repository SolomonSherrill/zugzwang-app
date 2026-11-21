/**
 * "Flag this" restored (BETA-4 B, FIXPLAN FLAG-RESTORE; DESIGN.md "Owner rulings, 2026-11-21", 2),
 * one test per placement: the Moves tab's selected-move explanation, each key moment and each report
 * line of the Report tab, and ⌘K's "Flag this move". Each runs on a beta harness (the flag renders,
 * and the flag it saves carries that placement's kind, game id and ply) and on a dev harness (no
 * flag anywhere, no ⌘K entry). Headless Chromium (or WebKit) over the fake sidecar; skipped when
 * the browser or the private fixtures are not installed (the public tree has no fixtures).
 */
import { existsSync, readFileSync } from 'node:fs'
import { createServer as netServer } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Browser, Page } from 'playwright'
import { harnessBrowser, harnessBrowserInstalled, harnessBrowserName } from '../../../harness/browser'
import { createServer, type ViteDevServer } from 'vite'

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..', '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(desktop, '..', 'review', 'ui_fixtures')
const ready = harnessBrowserInstalled() && existsSync(resolve(fixtures, 'fixtures.json'))
const mainGameId: number = ready
  ? (JSON.parse(readFileSync(resolve(fixtures, 'fixtures.json'), 'utf8')) as { meta: { mainGameId: number } }).meta.mainGameId
  : 0
/** a move of the main game with a rule sentence (explain_move answers one for it) */
const PLY = 63

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

const servers: ViteDevServer[] = []
let browser: Browser | null = null
const base: Record<'beta' | 'dev', string> = { beta: '', dev: '' }

async function harness(beta: boolean): Promise<string> {
  const port = await freePort()
  const server = await createServer({
    configFile: resolve(desktop, 'vite.harness.config.ts'),
    define: { __BETA__: JSON.stringify(beta) },
    server: { port, strictPort: true, host: '127.0.0.1' },
    logLevel: 'silent',
  })
  await server.listen()
  servers.push(server)
  return `http://127.0.0.1:${port}`
}

async function openReview(build: 'beta' | 'dev', tab: 'Report' | 'Moves'): Promise<Page> {
  const page = await browser!.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${base[build]}/?screen=review&game=main&ply=${PLY}`)
  await page.getByRole('tab', { name: 'Report' }).waitFor()
  await page.waitForFunction(() => /\d+ of \d+/.test(document.querySelector('.nav .where')?.textContent ?? ''))
  if (tab === 'Moves') {
    await page.getByRole('tab', { name: 'Moves' }).click()
    await page.locator('.why').waitFor()
    await page.locator('.why .say').first().waitFor()
  } else {
    await page.locator('.moments .km').first().waitFor()
  }
  return page
}

type Flag = { kind: string; game_id: number | null; ply: number | null; label: string | null; shown: string; note: string }
const flags = (page: Page) => page.evaluate(() => (window as unknown as { __harness: { flagLog: unknown[] } }).__harness.flagLog) as Promise<Flag[]>

/** Click a ⚑ inside `scope`, type a note, press Enter; the flag the fake sidecar received. */
async function flagFrom(page: Page, scope: string, note: string): Promise<Flag> {
  const before = (await flags(page)).length
  await page.locator(`${scope} button[aria-label="Flag this"]`).first().click()
  const input = page.locator(`${scope} .flag input`)
  await input.fill(note)
  await input.press('Enter')
  await page.locator(`${scope} .flag .saved`).first().waitFor()
  const all = await flags(page)
  expect(all.length).toBe(before + 1)
  return all[all.length - 1]
}

describe.skipIf(!ready)(`Flag this, per placement (FLAG-RESTORE) [${harnessBrowserName}]`, () => {
  beforeAll(async () => {
    base.beta = await harness(true)
    base.dev = await harness(false)
    browser = await harnessBrowser.launch({ headless: true })
  }, 90_000)

  afterAll(async () => {
    await browser?.close()
    for (const s of servers) await s.close()
  })

  it("Moves tab: ⚑ at the right of the selected move's explanation, flags that move", async () => {
    const page = await openReview('beta', 'Moves')
    const why = page.locator('.why')
    const top = await why.locator('.top').boundingBox()
    const btn = await why.locator('button[aria-label="Flag this"]').boundingBox()
    // at the right: the button ends within 24 px of the row's right edge
    expect(btn && top && top.x + top.width - (btn.x + btn.width)).toBeLessThan(24)
    const f = await flagFrom(page, '.why', 'moves tab')
    expect(f).toMatchObject({ kind: 'move explanation', game_id: mainGameId, ply: PLY, note: 'moves tab' })
    expect(f.label).toBeTruthy()
    expect(f.shown).toContain(await why.locator('.say').first().textContent())
    await page.close()
  }, 60_000)

  it('Report tab: a ⚑ on each key moment, flagging that moment', async () => {
    const page = await openReview('beta', 'Report')
    const rows = page.locator('.moments li')
    const n = await rows.count()
    expect(n).toBeGreaterThan(0)
    expect(await page.locator('.moments .kmrow button[aria-label="Flag this"]').count()).toBe(n)
    const f = await flagFrom(page, '.moments li:nth-child(1) .kmrow', 'moment')
    expect(f).toMatchObject({ kind: 'report moment', game_id: mainGameId })
    expect(typeof f.ply).toBe('number')
    await page.close()
  }, 60_000)

  it('Report tab: a ⚑ on each report line (headline, an open moment, the context)', async () => {
    const page = await openReview('beta', 'Report')
    expect(await page.locator('.head h1 button[aria-label="Flag this"]').count()).toBe(1)
    const h = await flagFrom(page, '.head h1', 'headline')
    expect(h).toMatchObject({ kind: 'report headline', game_id: mainGameId, ply: null })
    // open each moment until one has a sentence: every sentence of it carries a ⚑
    const rows = page.locator('.moments li')
    let found = false
    for (let i = 0; i < (await rows.count()) && !found; i++) {
      await rows.nth(i).locator('.km').click()
      const says = rows.nth(i).locator('.body .say')
      if ((await says.count()) > 0) {
        found = true
        expect(await rows.nth(i).locator('.body .say button[aria-label="Flag this"]').count()).toBe(await says.count())
        const f = await flagFrom(page, `.moments li:nth-child(${i + 1}) .body .say`, 'line')
        expect(['report claim', 'report qualifier', 'report description']).toContain(f.kind)
        expect(f.game_id).toBe(mainGameId)
        expect(typeof f.ply).toBe('number')
      }
      await rows.nth(i).locator('.km').click()
    }
    expect(found).toBe(true)
    const ctx = page.locator('.context p')
    if ((await ctx.count()) > 0) expect(await page.locator('.context p button[aria-label="Flag this"]').count()).toBe(await ctx.count())
    await page.close()
  }, 60_000)

  it('⌘K: "Flag this move" opens the Moves tab\'s flag on the selected move', async () => {
    const page = await openReview('beta', 'Report')
    await page.keyboard.press('ControlOrMeta+k')
    const q = page.getByRole('textbox', { name: 'Search moves and actions' })
    await q.fill('flag')
    const opt = page.locator('[id="cmd-flag"]')
    await opt.waitFor()
    expect(await opt.textContent()).toContain('Flag this move')
    await q.press('Enter')
    const input = page.locator('.why .flag input')
    await input.waitFor()
    expect(await input.evaluate((el) => el === document.activeElement)).toBe(true)
    await input.fill('from the command menu')
    await input.press('Enter')
    await page.locator('.why .flag .saved').waitFor()
    const all = await flags(page)
    expect(all[all.length - 1]).toMatchObject({ kind: 'move explanation', game_id: mainGameId, ply: PLY, note: 'from the command menu' })
    await page.close()
  }, 60_000)

  it('dev build: no ⚑ on either tab, no "Flag this move" in ⌘K', async () => {
    const page = await openReview('dev', 'Report')
    await page.locator('.moments li .km').first().click()
    expect(await page.locator('button[aria-label="Flag this"]').count()).toBe(0)
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByRole('textbox', { name: 'Search moves and actions' }).fill('flag')
    expect(await page.locator('[id="cmd-flag"]').count()).toBe(0)
    await page.keyboard.press('Escape')
    await page.getByRole('tab', { name: 'Moves' }).click()
    await page.locator('.why .say').first().waitFor()
    expect(await page.locator('button[aria-label="Flag this"]').count()).toBe(0)
    await page.close()
  }, 60_000)
})
