/**
 * Small windows (DESIGN.md fifth rulings, 2; UI-BUILD-4 C), in the browser harness as
 * reviewKeys.browser.test.ts runs it: below 1440 wide the sidebar is an icon rail, each label a
 * tooltip on hover and keyboard focus and the button's accessible name; the search field an icon
 * button opening the command menu; Recent games hidden; a board screen fits its board at
 * 1280 x 720; Home goes to one column below 1248. Skipped without Chromium or the fixtures.
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

async function open(url: string, width: number, height: number): Promise<Page> {
  const page = await browser!.newPage({ viewport: { width, height } })
  await page.goto(base + url)
  await page.locator('nav.sidebar').waitFor()
  return page
}
const tipShown = (page: Page, name: string) =>
  page
    .getByRole('navigation', { name: 'Sidebar' })
    .getByRole('button', { name, exact: true })
    .locator('.tip')
    .evaluate((el) => getComputedStyle(el).visibility === 'visible')

describe.skipIf(!ready)(`small windows (fifth rulings, 2) [${harnessBrowserName}]`, () => {
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

  it('at 1280 x 720 the sidebar is a rail: labels are names and tooltips, on hover and on focus', async () => {
    const page = await open('/?screen=home', 1280, 720)
    const nav = page.getByRole('navigation', { name: 'Sidebar' })
    expect(await nav.evaluate((el) => el.classList.contains('rail'))).toBe(true)
    expect(Math.round((await nav.boundingBox())!.width)).toBe(52)
    for (const name of ['Home', 'Play', 'Puzzles', 'Openings', 'Games', 'Insights', 'Settings', 'Search or jump to'])
      await expect(nav.getByRole('button', { name, exact: true }).count()).resolves.toBe(1)
    expect(await tipShown(page, 'Games')).toBe(false)
    await nav.getByRole('button', { name: 'Games', exact: true }).hover()
    expect(await tipShown(page, 'Games')).toBe(true)
    await page.mouse.move(800, 400)
    expect(await tipShown(page, 'Games')).toBe(false)
    await page.keyboard.press('Shift')
    await nav.getByRole('button', { name: 'Insights', exact: true }).focus()
    expect(await tipShown(page, 'Insights')).toBe(true)
    await page.close()
  }, 30_000)

  it('the rail search button and ⌘K open the same command menu', async () => {
    const page = await open('/?screen=home', 1280, 720)
    await page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Search or jump to' }).click()
    await page.getByRole('dialog', { name: 'Command menu' }).waitFor()
    await page.keyboard.press('Escape')
    await page.getByRole('dialog', { name: 'Command menu' }).waitFor({ state: 'detached' })
    await page.keyboard.press('Meta+k')
    await page.getByRole('dialog', { name: 'Command menu' }).waitFor()
    await page.close()
  }, 30_000)

  it('Recent games: hidden in the rail on Review, shown at 1440', async () => {
    const small = await open('/?screen=review&game=main', 1280, 720)
    await small.locator('.nav .where').waitFor()
    await small.waitForTimeout(400)
    expect(await small.getByText('Recent games', { exact: true }).count()).toBe(0)
    await small.close()
    const wide = await open('/?screen=review&game=main', 1440, 940)
    await wide.getByText('Recent games', { exact: true }).waitFor()
    const nav = wide.getByRole('navigation', { name: 'Sidebar' })
    expect(await nav.evaluate((el) => el.classList.contains('rail'))).toBe(false)
    expect(Math.round((await nav.boundingBox())!.width)).toBe(232)
    await wide.close()
  }, 30_000)

  it('Review at 1280 x 720: the board, its strips and the navigator fit without scrolling', async () => {
    const page = await open('/?screen=review&game=main&ply=66', 1280, 720)
    await page.locator('.nav .where').waitFor()
    await page.waitForTimeout(300)
    const board = (await page.locator('.review cg-board').boundingBox())!
    expect(board.y + board.height).toBeLessThanOrEqual(720)
    const nav = (await page.locator('.nav .where').boundingBox())!
    expect(nav.y + nav.height).toBeLessThanOrEqual(720)
    await page.close()
  }, 30_000)

  it('Home is one column below 1248 wide, two at 1280', async () => {
    const dir = async (w: number) => {
      const page = await open('/?screen=home', w, 720)
      await page.locator('.pair').waitFor()
      const d = await page.locator('.pair').evaluate((el) => getComputedStyle(el).flexDirection)
      await page.close()
      return d
    }
    expect(await dir(1280)).toBe('row')
    expect(await dir(1200)).toBe('column')
  }, 30_000)
})
