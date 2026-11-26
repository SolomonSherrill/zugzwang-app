/**
 * B6, for real: one key press steps one ply in Review. Starts the browser harness (Vite with
 * vite.harness.config.ts, the app over the fake sidecar) on a free port and drives headless
 * Chromium through Playwright: focus a control by clicking it, press an arrow, read the
 * navigator's "N of M". Skipped when Chromium or the private fixtures are not installed
 * (the public tree has no fixtures).
 */
import { existsSync } from 'node:fs'
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
// headless Chromium, or WebKit with ZUGZWANG_HARNESS_BROWSER=webkit (harness/browser.ts)
const haveBrowser = harnessBrowserInstalled()
const ready = haveBrowser && existsSync(resolve(fixtures, 'fixtures.json'))

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

/** The navigator's position: "67 of 90" → 67. */
async function position(page: Page): Promise<number> {
  const t = (await page.locator('.nav .where > span').last().textContent()) ?? ''
  const m = /(\d+) of (\d+)/.exec(t)
  if (!m) throw new Error(`no "N of M" in ${JSON.stringify(t)}`)
  return Number(m[1])
}

async function openReview(): Promise<Page> {
  const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
  await page.goto(`${base}/?screen=review&game=main&ply=40`)
  await page.locator('.nav .where').waitFor()
  await page.getByRole('tab', { name: 'Report' }).waitFor()
  await page.waitForFunction(() => /\d+ of \d+/.test(document.querySelector('.nav .where')?.textContent ?? ''))
  return page
}

describe.skipIf(!ready)(`Review: one arrow key, one ply (B6) [${harnessBrowserName}]`, () => {
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

  it('with nothing focused, → steps one ply (the window handler)', async () => {
    const page = await openReview()
    const before = await position(page)
    await page.keyboard.press('ArrowRight')
    expect(await position(page)).toBe(before + 1)
    await page.close()
  }, 30_000)

  it('the Report chart, clicked then →, steps one ply', async () => {
    const page = await openReview()
    const chart = page.getByRole('slider', { name: /through the game\. Click to jump/ })
    const box = (await chart.boundingBox())!
    await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.5)
    expect(await chart.evaluate((el) => el === document.activeElement)).toBe(true)
    const at = await position(page)
    await page.keyboard.press('ArrowRight')
    expect(await position(page)).toBe(at + 1)
    await page.keyboard.press('ArrowLeft')
    expect(await position(page)).toBe(at)
    await page.close()
  }, 30_000)

  it('the Moves graph, clicked then →, steps one ply', async () => {
    const page = await openReview()
    await page.getByRole('tab', { name: 'Moves' }).click()
    const graph = page.getByRole('slider', { name: /^Evaluation through the game\. \d+ notable moves/ })
    const box = (await graph.boundingBox())!
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5)
    expect(await graph.evaluate((el) => el === document.activeElement)).toBe(true)
    const at = await position(page)
    await page.keyboard.press('ArrowRight')
    expect(await position(page)).toBe(at + 1)
    await page.close()
  }, 30_000)

  it('a move chart clicked then → shows its readout at the new move (guide and label; UI-BUILD-4 E)', async () => {
    const page = await openReview()
    await page.getByRole('radio', { name: 'Material' }).click()
    const chart = page.getByRole('slider', { name: /^Material through the game/ })
    const box = (await chart.boundingBox())!
    await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.5)
    await page.keyboard.press('ArrowRight')
    const readout = chart.locator('xpath=ancestor::div[contains(@class, "readout-box")][1]')
    await readout.locator(':scope > .guide').waitFor()
    expect(await readout.locator(':scope > .label').evaluate((el) => getComputedStyle(el).visibility)).toBe('visible')
    await page.close()
  }, 30_000)

  it('the Report has no "Tactical errors" row (ruling D10, FIX-B8; it replaced UI-BUILD-4 E\'s "N of M" check)', async () => {
    const page = await openReview()
    await page.getByRole('tab', { name: 'Report' }).click()
    await page.locator('.row.top').first().waitFor()
    expect(await page.locator('.row.err').count()).toBe(0)
    expect(await page.evaluate(() => document.body.innerText)).not.toContain('Tactical errors')
    await page.close()
  }, 30_000)

  it('the split handle resizes on → and does not step', async () => {
    const page = await openReview()
    const split = page.getByRole('separator', { name: 'Resize board and panel' })
    await split.focus()
    const at = await position(page)
    const width = Number(await split.getAttribute('aria-valuenow'))
    await page.keyboard.press('ArrowRight')
    expect(await position(page)).toBe(at)
    expect(Number(await split.getAttribute('aria-valuenow'))).toBe(Math.max(320, width - 16))
    await page.close()
  }, 30_000)

  it('exploring: an engine line played to its third move is a variation; arrows step in it, Esc returns', async () => {
    const page = await openReview()
    await page.getByRole('tab', { name: 'Moves' }).click()
    const at = await position(page)
    await page.locator('.lines .line').nth(1).click()
    await page.locator('.lines .lw').nth(1).locator('button.san').nth(2).click()
    await page.getByText('Variation, 3 of 3').waitFor()
    expect(await page.locator('.vrow .vmove').count()).toBe(3)
    await page.keyboard.press('ArrowLeft')
    await page.getByText('Variation, 2 of 3').waitFor()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight') // the variation's end: no further, never the game's next move
    await page.getByText('Variation, 3 of 3').waitFor()
    await page.keyboard.press('Escape')
    expect(await position(page)).toBe(at)
    // the variation is kept under its move
    expect(await page.locator('.vrow .vmove').count()).toBe(3)
    await page.close()
  }, 30_000)

  it('exploring: a legal move dragged on the board starts a variation; Back to the game returns', async () => {
    const page = await openReview()
    const at = await position(page)
    // any legal move: the first square chessground marks as a destination after picking a piece
    const board = page.locator('.review cg-board')
    const box = (await board.boundingBox())!
    const sq = box.width / 8
    let played = false
    for (let i = 0; i < 64 && !played; i++) {
      await page.mouse.click(box.x + ((i % 8) + 0.5) * sq, box.y + (Math.floor(i / 8) + 0.5) * sq)
      await page.waitForTimeout(40)
      const dest = page.locator('.review cg-board square.move-dest').first()
      if (await dest.count()) {
        const d = (await dest.boundingBox())!
        await page.mouse.click(d.x + d.width / 2, d.y + d.height / 2)
        played = true
      }
    }
    expect(played).toBe(true)
    await page.getByRole('button', { name: 'Back to the game' }).first().waitFor()
    expect(await page.getByRole('tab', { name: 'Moves' }).getAttribute('aria-selected')).toBe('true')
    await page.getByRole('button', { name: 'Back to the game' }).first().click()
    expect(await position(page)).toBe(at)
    await page.close()
  }, 30_000)

  it('Analyse a position: a click on an engine-line move plays the line to it; ← steps back one', async () => {
    const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
    const fen = 'r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4'
    await page.goto(`${base}/?screen=review&fen=${encodeURIComponent(fen)}`)
    await page.locator('.lines .lw button.san').first().waitFor()
    await page.locator('.lines .lw').first().locator('button.san').nth(3).click()
    await page.getByText('4 of 4').waitFor()
    await page.keyboard.press('ArrowLeft')
    await page.getByText('3 of 4').waitFor()
    await page.close()
  }, 30_000)

  it('the Eval / Material / Time switch moves on ← and does not step', async () => {
    const page = await openReview()
    await page.getByRole('radio', { name: 'Material' }).click()
    const at = await position(page)
    await page.keyboard.press('ArrowLeft')
    expect(await page.getByRole('radio', { name: 'Eval' }).getAttribute('aria-checked')).toBe('true')
    expect(await position(page)).toBe(at)
    await page.close()
  }, 30_000)
})
