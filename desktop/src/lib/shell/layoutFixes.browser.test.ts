/**
 * BETA-4 C (FIXPLAN UI-8), kept by the gate: the four layout findings of UI-BUILD-4 at the smallest
 * window, 1280 x 720, measured in the DOM (harness/layoutFixes.ts writes the same figures at every
 * size to review/scratch/ui/beta4/layout/layout_fixes.out). Headless Chromium (or WebKit) over the
 * fake sidecar; skipped when the browser or the private fixtures are not installed.
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

async function open(url: string): Promise<Page> {
  const page = await browser!.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 })
  await page.goto(base + url)
  await page.waitForTimeout(600)
  await page.evaluate(() => document.fonts.ready)
  return page
}

describe.skipIf(!ready)(`layout at 1280 x 720 (BETA-4 C) [${harnessBrowserName}]`, () => {
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

  it("Review's Report: an opened key moment's buttons are inside the panel's view", async () => {
    const page = await open('/?screen=review&game=main&ply=66')
    await page.getByRole('button', { name: /34… axb5/ }).click()
    await page.waitForTimeout(400)
    const room = await page.evaluate(() => {
      const a = document.querySelector('.moments li.open .acts')!.getBoundingClientRect()
      const s = document.querySelector('aside .scroll')!.getBoundingClientRect()
      return Math.min(s.bottom, window.innerHeight) - a.bottom
    })
    expect(room).toBeGreaterThanOrEqual(12)
    await page.close()
  }, 30_000)

  it('engine lines: a collapsed line shows whole moves only', async () => {
    const page = await open('/?screen=review&game=main&ply=66')
    await page.getByRole('tab', { name: 'Moves' }).click()
    await page.waitForTimeout(400)
    const rows = await page.evaluate(() =>
      [...document.querySelectorAll('.lines .rest')].map((el) => {
        const box = el.getBoundingClientRect()
        const shown = [...el.children].filter((k) => getComputedStyle(k).display !== 'none')
        return { over: el.scrollWidth - el.clientWidth, outside: shown.filter((k) => k.getBoundingClientRect().right > box.right + 0.5).length, last: shown.at(-1)?.textContent ?? '' }
      }),
    )
    expect(rows.length).toBeGreaterThan(0)
    for (const r of rows) {
      expect(r.over).toBeLessThanOrEqual(1)
      expect(r.outside).toBe(0)
      expect(r.last).not.toMatch(/^\d+(\.|…)$/)
    }
    await page.close()
  }, 30_000)

  it("Insights: the sparklines' end dots are whole", async () => {
    const page = await open('/?screen=insights')
    const shares = await page.evaluate(() =>
      [...document.querySelectorAll('.strip svg circle')].map((el) => {
        const b = el.getBoundingClientRect()
        let x0 = b.left, x1 = b.right
        for (let e = el.parentElement; e; e = e.parentElement) {
          if (getComputedStyle(e).overflowX !== 'visible') {
            const c = e.getBoundingClientRect()
            x0 = Math.max(x0, c.left)
            x1 = Math.min(x1, c.right)
          }
        }
        return (x1 - x0) / b.width
      }),
    )
    expect(shares.length).toBeGreaterThan(0)
    for (const s of shares) expect(s).toBeGreaterThan(0.99)
    await page.close()
  }, 30_000)

  it("Home's Recent games and Puzzles' table span their column", async () => {
    const home = await open('/?screen=home')
    const h = await home.evaluate(() => {
      const t = document.querySelector('.table')!.getBoundingClientRect()
      const p = document.querySelector('.pair')!.getBoundingClientRect()
      return [t.left - p.left, t.right - p.right]
    })
    expect(Math.abs(h[0])).toBeLessThanOrEqual(1)
    expect(Math.abs(h[1])).toBeLessThanOrEqual(1)
    await home.close()
    const pz = await open('/?screen=puzzles')
    const d = await pz.evaluate(() => {
      const el = document.querySelector('.table')!
      const p = el.parentElement!
      const cs = getComputedStyle(p)
      return p.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - el.getBoundingClientRect().width
    })
    expect(Math.abs(d)).toBeLessThanOrEqual(1)
    await pz.close()
  }, 30_000)
})
