/**
 * UI-BUILD A8: frame times while the board animates a move and while a piece is dragged,
 * in headless Chromium and headless WebKit (Playwright 1.65.1). Method:
 *  - the page records the interval between consecutive requestAnimationFrame callbacks;
 *  - animation: 20 moves (1.Nf3, taken back, …), each recorded from the prop change to
 *    300 ms later (chessground animates 220 ms), 400 ms apart;
 *  - drag: the e2 pawn picked up and carried in 60 mouse steps of ~16 ms across the board
 *    and back, then dropped on e4; 5 drags.
 * Each scenario runs in a fresh page after a 1 s warm-up. Reported per browser: frames,
 * median, p95 and max interval, and the share over 20 ms (a missed 60 Hz frame).
 * Headless: no window, no display; rAF is paced by the browser's own timer, so this
 * measures the page's main thread and rendering, not a screen.
 *   cd desktop && node harness/perf-measure.ts
 */
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium, webkit, type Page, type BrowserType } from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts') })
await server.listen()
const url = 'http://localhost:5174/perf.html'

type Perf = { toggle(): void; start(): void; stop(): number[] }
const call = (page: Page, fn: 'toggle' | 'start' | 'stop') =>
  page.evaluate((f) => (window as unknown as { __perf: Perf }).__perf[f](), fn) as Promise<number[] | undefined>

function stats(d: number[]) {
  const s = [...d].sort((a, b) => a - b)
  const q = (p: number) => s[Math.min(s.length - 1, Math.floor(p * s.length))]
  return {
    frames: s.length,
    medianMs: +q(0.5).toFixed(2),
    p95Ms: +q(0.95).toFixed(2),
    maxMs: +s[s.length - 1].toFixed(2),
    over20msPct: +((100 * s.filter((x) => x > 20).length) / s.length).toFixed(1),
  }
}

async function measure(bt: BrowserType) {
  const browser = await bt.launch({ headless: true })
  const out: Record<string, unknown> = { browser: bt.name(), version: browser.version() }
  try {
    // animation
    let page = await browser.newPage({ viewport: { width: 1440, height: 940 } })
    await page.goto(url)
    await page.waitForSelector('cg-board piece')
    await page.waitForTimeout(1000)
    const anim: number[] = []
    for (let i = 0; i < 20; i++) {
      await call(page, 'start')
      await call(page, 'toggle')
      await page.waitForTimeout(300)
      anim.push(...((await call(page, 'stop')) ?? []))
      await page.waitForTimeout(100)
    }
    out.animation = stats(anim)
    await page.close()
    // drag
    page = await browser.newPage({ viewport: { width: 1440, height: 940 } })
    await page.goto(url)
    await page.waitForSelector('cg-board piece')
    await page.waitForTimeout(1000)
    const box = (await page.locator('cg-board').boundingBox())!
    const sq = box.width / 8
    const at = (file: number, rank: number) => ({ x: box.x + (file + 0.5) * sq, y: box.y + (7 - rank + 0.5) * sq })
    const drag: number[] = []
    for (let i = 0; i < 5; i++) {
      const from = at(4, 1)
      await page.mouse.move(from.x, from.y)
      await call(page, 'start')
      await page.mouse.down()
      for (let s = 1; s <= 60; s++) {
        const t = s / 60
        const x = from.x + Math.sin(t * Math.PI) * 3 * sq
        const y = from.y - Math.sin(t * Math.PI * 2) * 2.5 * sq
        await page.mouse.move(x, y)
        await page.waitForTimeout(16)
      }
      const to = at(4, 3)
      await page.mouse.move(to.x, to.y)
      await page.mouse.up()
      await page.waitForTimeout(250)
      drag.push(...((await call(page, 'stop')) ?? []))
      await page.reload()
      await page.waitForSelector('cg-board piece')
      await page.waitForTimeout(500)
    }
    out.drag = stats(drag)
    await page.close()
  } finally {
    await browser.close()
  }
  return out
}

try {
  const results = []
  for (const bt of [chromium, webkit]) results.push(await measure(bt))
  console.log(JSON.stringify({ measuredAt: new Date().toISOString(), board: '744 px, cburnett, Stone', results }, null, 1))
} finally {
  await server.close()
}
