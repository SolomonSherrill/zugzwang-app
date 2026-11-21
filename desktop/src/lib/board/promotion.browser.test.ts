/**
 * The promotion picker on every screen that takes a move from the board (DESIGN.md fifth
 * rulings, 3; UI-BUILD-4 D): Play, Try it, exploring in Review, Analyse a position, puzzles, the
 * trainer. Each screen promotes through the picker (the piece chosen by its key or a click
 * arrives with the right UCI suffix), and Esc leaves the position unchanged with nothing sent.
 * The browser harness (Vite with vite.harness.config.ts, the app over the fake sidecar) in
 * headless Chromium, as reviewKeys.browser.test.ts; the promotion positions are
 * harness/promotionHarness.ts. Skipped when Chromium or the private fixtures are not installed.
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
const ready = haveBrowser && existsSync(resolve(fixtures, 'fixtures.json')) && existsSync(resolve(fixtures, 'puzzles_fixtures.json'))

/** White's b7 pawn can promote on a8, b8 or c8 (harness/promotionHarness.ts PROMO_FEN). */
const PROMO_FEN = 'r1bqkb1r/pP1npppp/5n2/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 5'
/** Black's g2 pawn promotes on g1; Black to move, so Analyse a position puts Black at the bottom. */
const BLACK_FEN = '4k3/8/8/8/8/8/6p1/4K3 b - - 0 1'

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
  const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
  await page.goto(base + url)
  await page.locator('cg-board:visible').first().waitFor()
  return page
}

/** Click a square of the board on screen; `black` when Black is at the bottom. */
async function clickSquare(page: Page, sq: string, black = false) {
  const box = (await page.locator('cg-board:visible').first().boundingBox())!
  const s = box.width / 8
  const f = sq.charCodeAt(0) - 97
  const r = Number(sq[1]) - 1
  const x = box.x + (black ? 7 - f + 0.5 : f + 0.5) * s
  const y = box.y + (black ? r + 0.5 : 7 - r + 0.5) * s
  await page.mouse.click(x, y)
}
/** A move by two clicks (chessground ignores a second click that follows the first too closely). */
async function move(page: Page, uci: string, black = false) {
  await clickSquare(page, uci.slice(0, 2), black)
  await page.waitForTimeout(150)
  await clickSquare(page, uci.slice(2, 4), black)
}

/** The params of every request of a method the page has made. */
async function sent(page: Page, method: string): Promise<Record<string, unknown>[]> {
  return page.evaluate(
    (m) =>
      (window as unknown as { __harness: { requestLog: { method: string; params: Record<string, unknown> }[] } }).__harness.requestLog
        .filter((r) => r.method === m)
        .map((r) => r.params),
    method,
  )
}

/** The piece chessground draws on a square of the visible board ("white pawn"), or null. */
async function pieceOn(page: Page, sq: string): Promise<string | null> {
  return page.locator('cg-board:visible').first().evaluate((b, k) => {
    for (const p of Array.from(b.querySelectorAll('piece'))) {
      const el = p as HTMLElement & { cgKey?: string }
      if (el.cgKey === k && !el.classList.contains('ghost') && !el.classList.contains('fading')) return el.className.replace(/\s*(anim|dragging)\b/g, '').trim()
    }
    return null
  }, sq)
}

const picker = (page: Page) => page.locator('.promo-scrim:visible')

/** The picker's four choices as drawn: piece and square, in order, and each box. */
async function choices(page: Page) {
  const out = []
  for (const b of await picker(page).locator('.promo-choice').all())
    out.push({ piece: await b.getAttribute('data-piece'), square: await b.getAttribute('data-square'), box: (await b.boundingBox())! })
  return out
}

describe.skipIf(!ready)(`the promotion picker (UI-BUILD-4 D) [${harnessBrowserName}]`, () => {
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

  // ── Analyse a position ──────────────────────────────────────────────────────
  const ANALYSE = `/?screen=review&fen=${encodeURIComponent(PROMO_FEN)}`

  it('Analyse a position: b7-a8 opens the picker over a8, queen first, toward the centre; R plays b7a8r', async () => {
    const page = await open(ANALYSE)
    await move(page, 'b7a8')
    await picker(page).waitFor()
    const c = await choices(page)
    expect(c.map((x) => x.piece)).toEqual(['q', 'n', 'r', 'b'])
    expect(c.map((x) => x.square)).toEqual(['a8', 'a7', 'a6', 'a5'])
    const board = (await page.locator('cg-board:visible').first().boundingBox())!
    const sq = board.width / 8
    // the queen sits on a8 (top-left), each next one a square lower
    expect(Math.abs(c[0].box.x - board.x)).toBeLessThan(2)
    expect(Math.abs(c[0].box.y - board.y)).toBeLessThan(2)
    for (let i = 1; i < 4; i++) expect(Math.abs(c[i].box.y - c[i - 1].box.y - sq)).toBeLessThan(2)
    // the queen has the focus, so Enter would take it too
    expect(await page.evaluate(() => (document.activeElement as HTMLElement | null)?.dataset.piece)).toBe('q')
    expect(await sent(page, 'probe_move')).toEqual([])
    await page.keyboard.press('r')
    await expect.poll(() => sent(page, 'probe_move')).toEqual([{ fen: PROMO_FEN, uci: 'b7a8r' }])
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'a8')).toBe('white rook')
    await page.close()
  }, 30_000)

  it('Analyse a position: Esc cancels: the pawn goes back, nothing is sent', async () => {
    const page = await open(ANALYSE)
    await move(page, 'b7b8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    expect(await pieceOn(page, 'b8')).toBe(null)
    await page.waitForTimeout(200)
    expect(await sent(page, 'probe_move')).toEqual([])
    await page.close()
  }, 30_000)

  it('Analyse a position: a click outside the picker cancels like Esc', async () => {
    const page = await open(ANALYSE)
    await move(page, 'b7c8')
    await picker(page).waitFor()
    // a square of the dimmed board, away from the column
    await clickSquare(page, 'f4')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    // and a click off the board altogether
    await move(page, 'b7c8')
    await picker(page).waitFor()
    await page.mouse.click(1400, 30)
    expect(await picker(page).count()).toBe(0)
    await page.waitForTimeout(200)
    expect(await sent(page, 'probe_move')).toEqual([])
    expect(await pieceOn(page, 'c8')).toBe('black bishop')
    await page.close()
  }, 30_000)

  it('Analyse a position, Black at the bottom: the column runs down from g1 at the top; a click on the knight plays g2g1n', async () => {
    const page = await open(`/?screen=review&fen=${encodeURIComponent(BLACK_FEN)}`)
    await move(page, 'g2g1', true)
    await picker(page).waitFor()
    const c = await choices(page)
    expect(c.map((x) => x.square)).toEqual(['g1', 'g2', 'g3', 'g4'])
    const board = (await page.locator('cg-board:visible').first().boundingBox())!
    const sq = board.width / 8
    // g1 is the second column from the left, top row, with Black at the bottom
    expect(Math.abs(c[0].box.x - (board.x + sq))).toBeLessThan(2)
    expect(Math.abs(c[0].box.y - board.y)).toBeLessThan(2)
    expect(c[3].box.y).toBeGreaterThan(c[0].box.y)
    expect(await picker(page).locator('piece').first().getAttribute('class')).toContain('black queen')
    await picker(page).locator('.promo-choice[data-piece="n"]').click()
    await expect.poll(() => sent(page, 'probe_move')).toEqual([{ fen: BLACK_FEN, uci: 'g2g1n' }])
    await page.close()
  }, 30_000)

  // ── Review: exploring and Try it ─────────────────────────────────────────────
  it('Review, exploring: N plays b7c8n into a variation; Esc first leaves the position and the game where they were', async () => {
    const page = await open('/?screen=review&game=promo&ply=7')
    await page.waitForFunction(() => /8 of 12/.test(document.querySelector('.nav .where')?.textContent ?? ''))
    await move(page, 'b7c8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.waitForTimeout(200)
    expect(await sent(page, 'probe_move')).toEqual([])
    expect(await page.locator('.nav .where').textContent()).toMatch(/8 of 12/)
    await move(page, 'b7c8')
    await picker(page).waitFor()
    await page.keyboard.press('n')
    await expect.poll(async () => (await sent(page, 'probe_move')).map((p) => p.uci)).toEqual(['b7c8n'])
    await page.getByRole('button', { name: 'Back to the game' }).first().waitFor()
    await expect.poll(() => pieceOn(page, 'c8')).toBe('white knight')
    await page.close()
  }, 30_000)

  it('Review, Try it: B is judged as b7a8b; Esc cancels the move and keeps the try open', async () => {
    const page = await open('/?screen=review&game=promo')
    await page.locator('.moments .km').first().click()
    await page.getByRole('button', { name: /Try it/ }).first().click()
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await move(page, 'b7a8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.waitForTimeout(200)
    expect(await sent(page, 'judge_move')).toEqual([])
    // still trying: the board still takes the move (Esc went to the picker, not the screen)
    await move(page, 'b7a8')
    await picker(page).waitFor()
    await page.keyboard.press('b')
    await expect.poll(() => sent(page, 'judge_move')).toEqual([{ fen: PROMO_FEN, uci: 'b7a8b' }])
    await page.close()
  }, 30_000)

  // ── Play ─────────────────────────────────────────────────────────────────
  async function playFromPromo(): Promise<Page> {
    const page = await open(ANALYSE)
    await page.getByRole('button', { name: 'Play it vs Stockfish' }).click()
    await expect.poll(async () => (await sent(page, 'new_game')).length).toBe(1)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    return page
  }

  it('Play: N sends user_move b7a8n', async () => {
    const page = await playFromPromo()
    await move(page, 'b7a8')
    await picker(page).waitFor()
    expect(await sent(page, 'user_move')).toEqual([])
    // the user's clock keeps running while the picker is open (10+0, the default)
    const clock = page.locator('.clock.active:visible').first()
    const before = await clock.textContent()
    await page.waitForTimeout(2200)
    expect(await clock.textContent()).not.toBe(before)
    expect(await picker(page).count()).toBe(1)
    await page.keyboard.press('N')
    await expect.poll(async () => (await sent(page, 'user_move')).map((p) => p.uci)).toEqual(['b7a8n'])
    await page.close()
  }, 30_000)

  it('Play: Esc cancels: the pawn goes back, no user_move', async () => {
    const page = await playFromPromo()
    await move(page, 'b7b8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.waitForTimeout(300)
    expect(await sent(page, 'user_move')).toEqual([])
    // the position still takes the promotion afterwards
    await move(page, 'b7b8')
    await picker(page).waitFor()
    await page.keyboard.press('q')
    await expect.poll(async () => (await sent(page, 'user_move')).map((p) => p.uci)).toEqual(['b7b8q'])
    await page.close()
  }, 30_000)

  // ── Puzzles ──────────────────────────────────────────────────────────────
  async function puzzle(): Promise<Page> {
    const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
    await page.goto(base + '/?screen=puzzles&state=promotion')
    await page.getByRole('button', { name: /Start rated/ }).click()
    await page.waitForSelector('.session[data-state="awaiting"]', { timeout: 20_000 })
    return page
  }
  const state = (page: Page) => page.locator('.session').getAttribute('data-state')

  it('Puzzles: a solution that under-promotes accepts the knight', async () => {
    const page = await puzzle()
    await move(page, 'f7f8')
    await picker(page).waitFor()
    await page.keyboard.press('n')
    await expect.poll(() => state(page)).toBe('complete')
    await expect.poll(async () => (await sent(page, 'rate_puzzle')).map((p) => p.outcome)).toEqual([1])
    await page.close()
  }, 40_000)

  it('Puzzles: the same square with the queen is wrong', async () => {
    const page = await puzzle()
    await move(page, 'f7f8')
    await picker(page).waitFor()
    await page.keyboard.press('q')
    await expect.poll(async () => (await sent(page, 'rate_puzzle')).map((p) => p.outcome)).toEqual([0])
    expect(await state(page)).not.toBe('complete')
    await page.close()
  }, 40_000)

  it('Puzzles: Esc cancels: still awaiting, nothing judged; the next puzzle (as Black) flips the column', async () => {
    const page = await puzzle()
    await move(page, 'f7f8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'f7')).toBe('white pawn')
    await page.waitForTimeout(300)
    expect(await state(page)).toBe('awaiting')
    expect(await sent(page, 'rate_puzzle')).toEqual([])
    // solve it, then the second puzzle: the user is Black, at the bottom
    await move(page, 'f7f8')
    await picker(page).waitFor()
    await page.keyboard.press('n')
    await expect.poll(() => state(page)).toBe('complete')
    await page.keyboard.press('Enter')
    await page.waitForSelector('.session[data-state="awaiting"]', { timeout: 20_000 })
    await move(page, 'f2f1', true)
    await picker(page).waitFor()
    const c = await choices(page)
    expect(c.map((x) => x.square)).toEqual(['f1', 'f2', 'f3', 'f4'])
    const board = (await page.locator('cg-board:visible').first().boundingBox())!
    expect(Math.abs(c[0].box.y - board.y)).toBeLessThan(2) // f1 at the top with Black at the bottom
    await page.keyboard.press('n')
    await expect.poll(() => state(page)).toBe('complete')
    await page.close()
  }, 60_000)

  // ── the opening trainer ───────────────────────────────────────────────────
  async function trainer(): Promise<Page> {
    const page = await browser!.newPage({ viewport: { width: 1440, height: 940 } })
    await page.goto(base + '/?screen=trainer&state=promotion')
    await page.getByRole('button', { name: /^Promotion drill/ }).first().click()
    await page.getByRole('button', { name: 'White', exact: true }).click()
    await page.getByRole('button', { name: 'Line start', exact: true }).click()
    await page.getByRole('button', { name: /Start training/ }).click()
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.waitForTimeout(300)
    return page
  }

  it('the trainer: the book move b7a8n is met by the knight', async () => {
    const page = await trainer()
    await move(page, 'b7a8')
    await picker(page).waitFor()
    await page.keyboard.press('n')
    await expect.poll(async () => (await sent(page, 'book_moves')).map((p) => p.fen)).toContain(PROMO_FEN)
    // accepted: the knight goes on a8 and, the book having no reply, the run ends there
    await expect.poll(() => pieceOn(page, 'a8')).toBe('white knight')
    await page.getByText('End of the book').waitFor()
    expect((await sent(page, 'trainer_complete')).length).toBe(1)
    await page.close()
  }, 30_000)

  it('the trainer: the queen on the same square is not the book move', async () => {
    const page = await trainer()
    await move(page, 'b7a8')
    await picker(page).waitFor()
    await page.keyboard.press('q')
    await page.getByText(/is not a book move/).waitFor()
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.close()
  }, 30_000)

  it('the trainer: Esc cancels: the pawn goes back, nothing asked of the book', async () => {
    const page = await trainer()
    const asked = (await sent(page, 'book_moves')).length
    await move(page, 'b7a8')
    await picker(page).waitFor()
    await page.keyboard.press('Escape')
    expect(await picker(page).count()).toBe(0)
    await expect.poll(() => pieceOn(page, 'b7')).toBe('white pawn')
    await page.waitForTimeout(300)
    expect((await sent(page, 'book_moves')).length).toBe(asked)
    expect(await page.getByText(/is in the book|is not a book move/).count()).toBe(0)
    await page.close()
  }, 30_000)
})
