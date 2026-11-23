/** The shots harness/shoot.ts takes: harness URL, matching mockup, and any actions. */
import type { Page } from 'playwright'
import { PUZZLE_SHOTS } from './puzzlesShots.ts'
import { GAMES_SHOTS } from './gamesShots.ts'
import { PROMOTION_SHOTS } from './promotionShots.ts'
import { FLAG_SHOTS } from './flagShots.ts'
import { FRIENDS_SHOTS } from './friendsShots.ts'

export interface Shot {
  dir: string
  name: string
  url: string
  mockup?: string
  /** before the page loads (e.g. a fake clock) */
  before?: (page: Page) => Promise<void>
  act?: (page: Page) => Promise<void>
  mockupAct?: (page: Page) => Promise<void>
  size?: { width: number; height: number }
  /** localStorage entries set before the page loads */
  storage?: Record<string, string>
  fullPage?: boolean
  waitMs?: number
  /** run the small-windows layout check (harness/layoutCheck.ts) after the screenshot */
  check?: boolean
}

/** Play a move on the harness board by clicking its two squares (White at the bottom). */
async function clickMove(page: Page, from: string, to: string, board = 'cg-board'): Promise<void> {
  const box = await page.locator(board).boundingBox()
  if (!box) throw new Error('no board')
  const sq = box.width / 8
  const at = (s: string) => ({ x: box.x + (s.charCodeAt(0) - 97 + 0.5) * sq, y: box.y + (8 - Number(s[1]) + 0.5) * sq })
  for (const s of [from, to]) {
    const p = at(s)
    await page.mouse.click(p.x, p.y)
  }
}
/** Start a game and play the mockup's line as White, waiting for each scripted reply. */
async function playLine(page: Page, moves: [string, string][]): Promise<void> {
  await page.getByRole('button', { name: /Start game/ }).click()
  await page.waitForTimeout(200)
  for (const [i, [a, b]] of moves.entries()) {
    await clickMove(page, a, b)
    await page.locator('button[role=gridcell]').nth(i * 2 + 1).waitFor()
    await page.waitForTimeout(120)
  }
}
const NAJDORF: [string, string][] = [['e2', 'e4'], ['g1', 'f3'], ['d2', 'd4'], ['f3', 'd4'], ['b1', 'c3'], ['c1', 'e3']]
/** Type the two usernames into Settings' Accounts and Save; wait for the check's answer. */
async function saveNames(page: Page, chesscom: string, lichess: string, waitMs = 700): Promise<void> {
  const inputs = page.locator('input[placeholder="Username"]')
  await inputs.nth(0).fill(chesscom)
  await inputs.nth(1).fill(lichess)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  if (waitMs) await page.waitForTimeout(waitMs)
}
/** Settings is drawn 1440 x 1240 (design/README.md). */
const SETTINGS_SIZE = { width: 1440, height: 1240 }
const ACCOUNT = { 'zugzwang-accounts': JSON.stringify({ chesscom: 'alice', lichess: '' }) }
const MERIDA = { 'zugzwang.pieceSet': 'merida', 'zugzwang.boardTheme': 'walnut' }

/** Hover a chart (found by its slider's accessible name) at a fraction of its width (UI-BUILD-3 I). */
async function hoverChart(page: Page, name: RegExp | string, frac: number, yFrac = 0.5): Promise<void> {
  const el = page.getByRole('slider', { name }).first()
  await el.waitFor()
  const box = await el.boundingBox()
  if (!box) throw new Error(`no chart ${String(name)}`)
  await page.mouse.move(box.x + box.width * frac, box.y + box.height * yFrac, { steps: 4 })
  await page.waitForTimeout(150)
}
/** Focus a chart as the keyboard would (a key first, so the focus is focus-visible). */
async function keyboardFocus(page: Page, name: RegExp | string): Promise<void> {
  await page.mouse.move(2, 2)
  await page.keyboard.press('Shift')
  await page.getByRole('slider', { name }).first().focus()
  await page.waitForTimeout(100)
}
const INSIGHTS_SIZE = { width: 1440, height: 1640 }

/** Analyse a position: the Italian Game after 4. … (a textbook position, no stored game). */
const ANALYSE = '/?screen=review&fen=' + encodeURIComponent('r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4')
/** Open the main fixture game at 34. b5 (ply 66), as the mockups draw it. */
const REVIEW = '/?screen=review&game=main&ply=66'

export const SHOTS: Shot[] = [
  { dir: 'components', name: 'gallery', url: '/gallery.html', fullPage: true },
  { dir: 'components', name: 'boards', url: '/boards.html' },
  {
    dir: 'review',
    name: 'report',
    url: REVIEW,
    mockup: 'MinimalReview.html',
    act: async (p) => {
      await p.getByRole('button', { name: /34… axb5/ }).click()
    },
  },
  {
    dir: 'review',
    name: 'report-material',
    url: REVIEW,
    mockup: 'MinimalReview-material.html',
    act: async (p) => {
      await p.getByRole('radio', { name: 'Material' }).click()
    },
  },
  {
    dir: 'review',
    name: 'report-time',
    url: REVIEW,
    mockup: 'MinimalReview-time.html',
    act: async (p) => {
      await p.getByRole('radio', { name: 'Time' }).click()
    },
  },
  {
    dir: 'review',
    name: 'moves',
    url: REVIEW,
    mockup: 'MinimalMoves.html',
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
    },
  },
  {
    dir: 'review',
    name: 'depth-menu',
    url: REVIEW,
    mockup: 'MinimalMoves-depth-menu.html',
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      await p.getByRole('button', { name: /Analyse again/ }).click()
    },
  },
  {
    dir: 'review',
    name: 'command-menu',
    url: REVIEW,
    mockup: 'MinimalMoves-command-menu.html',
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      await p.keyboard.press('Meta+k')
      await p.keyboard.type('34')
    },
  },
  {
    dir: 'review',
    name: 'try-it',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('button', { name: /34… axb5/ }).click()
      await p.getByRole('button', { name: /Try it/ }).click()
    },
  },
  {
    dir: 'review',
    name: 'show-best',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('button', { name: /34… axb5/ }).click()
      await p.getByRole('button', { name: 'Show the best move' }).click()
    },
  },
  // Exploring (UI-BUILD-3 C): not designed; drafted beside the Moves mockup.
  {
    dir: 'review',
    name: 'explore-variation',
    url: REVIEW,
    mockup: 'MinimalMoves.html',
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      // the second engine line, opened, played to its fourth move: a variation off 34… axb5
      await p.locator('.lines .line').nth(1).click()
      await p.locator('.lines .lw').nth(1).locator('button.san').nth(3).click()
      await p.waitForTimeout(300)
      await p.keyboard.press('ArrowLeft')
    },
  },
  {
    dir: 'review',
    name: 'explore-line-click',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      await p.locator('.lines .lw').first().locator('button.san').nth(2).click()
    },
  },
  {
    dir: 'review',
    name: 'explore-report-note',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      await p.locator('.lines .line').nth(1).click()
      await p.locator('.lines .lw').nth(1).locator('button.san').nth(1).click()
      await p.waitForTimeout(300)
      await p.getByRole('tab', { name: 'Report' }).click()
    },
  },
  { dir: 'review', name: 'state-not-analysed', url: '/?screen=review&game=unanalysed' },
  // Analyse a position (UI-BUILD-3 D): Review's Moves layout with no game; not designed.
  { dir: 'analyse', name: 'analyse', url: ANALYSE, mockup: 'MinimalMoves.html' },
  {
    dir: 'analyse',
    name: 'line-click',
    url: ANALYSE,
    act: async (p) => {
      await p.locator('.lines .lw').first().locator('button.san').nth(3).click()
    },
  },
  {
    dir: 'analyse',
    name: 'variation',
    url: ANALYSE,
    mockup: 'MinimalMoves.html',
    act: async (p) => {
      // the best line to its fourth move, back two, then the second line from there: a branch
      await p.locator('.lines .lw').first().locator('button.san').nth(3).click()
      await p.waitForTimeout(300)
      await p.keyboard.press('ArrowLeft')
      await p.keyboard.press('ArrowLeft')
      await p.waitForTimeout(300)
      await p.locator('.lines .line').nth(1).click()
      await p.locator('.lines .lw').nth(1).locator('button.san').nth(1).click()
    },
  },
  {
    dir: 'analyse',
    name: 'board-move',
    url: ANALYSE,
    act: async (p) => {
      await clickMove(p, 'd2', 'd3', '.review cg-board')
    },
  },
  { dir: 'analyse', name: 'state-pending', url: ANALYSE + '&state=live-pending', waitMs: 600 },
  { dir: 'analyse', name: 'state-no-engine', url: ANALYSE + '&state=no-engine' },
  { dir: 'analyse', name: 'state-engine-error', url: ANALYSE + '&state=live-error' },
  { dir: 'analyse', name: 'state-illegal', url: '/?screen=review&fen=' + encodeURIComponent('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0') + 'x' },
  { dir: 'analyse', name: 'state-refused', url: ANALYSE + '&state=live-illegal' },
  {
    dir: 'analyse',
    name: 'checkmate',
    url: '/?screen=review&fen=' + encodeURIComponent('r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4'),
  },
  {
    dir: 'review',
    name: 'state-analysing',
    url: '/?screen=review&game=main&state=analysing',
    act: async (p) => {
      await p.getByRole('button', { name: 'Analyse at depth 14' }).last().click()
      await p.waitForTimeout(1800)
    },
  },
  { dir: 'review', name: 'state-loading', url: '/?screen=review&game=main&latency=60000', waitMs: 600 },
  { dir: 'review', name: 'state-error', url: '/?screen=review&game=999999' },
  { dir: 'review', name: 'state-no-engine', url: '/?screen=review&game=unanalysed&state=no-engine' },
  { dir: 'home', name: 'home', url: '/?screen=home', mockup: 'MinimalHome.html' },
  // UI-BUILD-3 I: chart readouts (ruling 12 of 2026-11-20, fourth), each chart hovered, two focused.
  { dir: 'charts', name: 'report-eval-hover', url: REVIEW, act: (p) => hoverChart(p, /^Evaluation through the game/, 0.42) },
  { dir: 'charts', name: 'report-eval-right-edge', url: REVIEW, act: (p) => hoverChart(p, /^Evaluation through the game/, 0.985) },
  {
    dir: 'charts',
    name: 'report-material-hover',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('radio', { name: 'Material' }).click()
      await hoverChart(p, /^Material through the game/, 0.6)
    },
  },
  {
    dir: 'charts',
    name: 'report-time-hover',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('radio', { name: 'Time' }).click()
      await hoverChart(p, /^Time spent per move through the game/, 0.27)
    },
  },
  {
    dir: 'charts',
    name: 'report-eval-focus',
    url: REVIEW,
    act: async (p) => {
      await keyboardFocus(p, /^Evaluation through the game/)
      await p.keyboard.press('ArrowRight')
    },
  },
  {
    dir: 'charts',
    name: 'moves-graph-hover',
    url: REVIEW,
    act: async (p) => {
      await p.getByRole('tab', { name: 'Moves' }).click()
      await hoverChart(p, /notable moves/, 0.3)
    },
  },
  { dir: 'charts', name: 'insights-accuracy-hover', url: '/?screen=insights', size: INSIGHTS_SIZE, act: (p) => hoverChart(p, 'Accuracy by month', 0.55, 0.3) },
  {
    dir: 'charts',
    name: 'insights-accuracy-focus',
    url: '/?screen=insights',
    size: INSIGHTS_SIZE,
    act: async (p) => {
      await keyboardFocus(p, 'Accuracy by month')
      await p.keyboard.press('ArrowLeft')
      await p.keyboard.press('ArrowLeft')
    },
  },
  { dir: 'charts', name: 'insights-sparkline-hover', url: '/?screen=insights', size: INSIGHTS_SIZE, act: (p) => hoverChart(p, 'Win rate, 12 months', 0.7) },
  { dir: 'charts', name: 'home-sparkline-hover', url: '/?screen=home', act: (p) => hoverChart(p, /^Blitz rating/, 0.5) },
  { dir: 'trainer', name: 'families', url: '/?screen=trainer' },
  {
    dir: 'trainer',
    name: 'choose',
    url: '/?screen=trainer',
    mockup: 'MinimalTrainerChoose.html',
    act: async (p) => {
      await p.getByRole('button', { name: /^Scandinavian Defense/ }).first().click()
      await p.waitForTimeout(500)
      await p.getByRole('button', { name: /Valencian/ }).first().click()
      await p.getByRole('button', { name: 'Black', exact: true }).click()
      await p.getByRole('button', { name: 'This line only', exact: true }).click()
    },
  },
  {
    dir: 'trainer',
    name: 'train',
    url: '/?screen=trainer',
    mockup: 'MinimalTrainer.html',
    waitMs: 1500,
    act: async (p) => {
      await p.getByRole('button', { name: /^Scandinavian Defense/ }).first().click()
      await p.waitForTimeout(500)
      await p.getByRole('button', { name: /Valencian/ }).first().click()
      await p.getByRole('button', { name: 'Black', exact: true }).click()
      await p.getByRole('button', { name: 'This line only', exact: true }).click()
      await p.getByRole('button', { name: /Start training/ }).click()
      await p.waitForTimeout(1200)
      // 1… d5 by clicking the squares (Black's view: the board is flipped)
      const box = (await p.locator('.trainer cg-board').boundingBox())!
      const sq = (f: number, r: number) => ({ x: box.x + (7 - f + 0.5) * (box.width / 8), y: box.y + (r - 1 + 0.5) * (box.height / 8) })
      const a = sq(3, 7), b = sq(3, 5)
      await p.mouse.click(a.x, a.y)
      await p.mouse.click(b.x, b.y)
      await p.waitForTimeout(1500)
    },
  },
  {
    dir: 'trainer',
    name: 'train-done',
    url: '/?screen=trainer',
    waitMs: 1200,
    act: async (p) => {
      await p.getByRole('button', { name: /^Scandinavian Defense/ }).first().click()
      await p.waitForTimeout(500)
      await p.getByRole('button', { name: /Valencian/ }).first().click()
      await p.getByRole('button', { name: 'Black', exact: true }).click()
      await p.getByRole('button', { name: 'This line only', exact: true }).click()
      await p.getByRole('button', { name: /Start training/ }).click()
      await p.waitForTimeout(1200)
      const box = (await p.locator('.trainer cg-board').boundingBox())!
      const at = (s: string) => ({ x: box.x + (7 - (s.charCodeAt(0) - 97) + 0.5) * (box.width / 8), y: box.y + (Number(s[1]) - 1 + 0.5) * (box.height / 8) })
      for (const [a, b] of [['d7', 'd5'], ['d8', 'd5'], ['d5', 'd8']]) {
        for (const s of [a, b]) {
          const q = at(s)
          await p.mouse.click(q.x, q.y)
        }
        await p.waitForTimeout(1400)
      }
    },
  },
  { dir: 'trainer', name: 'state-no-book', url: '/?screen=trainer&state=no-book' },
  { dir: 'insights', name: 'insights', url: '/?screen=insights', mockup: 'MinimalInsights.html', size: { width: 1440, height: 1640 } },
  {
    dir: 'insights',
    name: 'insights-move-quality',
    url: '/?screen=insights',
    mockup: 'MinimalInsights-move-quality.html',
    size: { width: 1440, height: 1640 },
    act: async (p) => {
      await p.getByRole('button', { name: 'Move quality', exact: true }).click()
    },
  },
  {
    dir: 'insights',
    name: 'insights-white-patterns-open',
    url: '/?screen=insights',
    size: { width: 1440, height: 1640 },
    act: async (p) => {
      await p.getByRole('button', { name: 'White', exact: true }).click()
      await p.waitForTimeout(400)
      await p.getByRole('button', { name: /Your answers that weren't the engine's move/ }).click()
    },
  },
  { dir: 'insights', name: 'insights-daily', url: '/?screen=insights', size: { width: 1440, height: 1640 }, act: async (p) => { await p.getByRole('button', { name: 'Daily' }).click() } },
  { dir: 'insights', name: 'state-loading', url: '/?screen=insights&latency=60000', waitMs: 600 },
  { dir: 'insights', name: 'state-no-games', url: '/?screen=insights&state=no-games' },
  { dir: 'insights', name: 'state-pending', url: '/?screen=insights&state=insights-pending' },
  { dir: 'insights', name: 'state-error', url: '/?screen=insights&state=insights-error' },
  { dir: 'home', name: 'state-loading', url: '/?screen=home&latency=60000', waitMs: 600 },
  { dir: 'home', name: 'state-no-games', url: '/?screen=home&state=no-games' },
  { dir: 'home', name: 'state-error', url: '/?screen=home&state=home-error' },
  {
    dir: 'home',
    name: 'retry-try-it',
    url: '/?screen=home',
    act: async (p) => {
      await p.getByRole('button', { name: /Try it/ }).click()
    },
  },
  // Play (UI-BUILD-2)
  { dir: 'play', name: 'setup', url: '/?screen=play', mockup: 'MinimalPlaySetup.html' },
  {
    dir: 'play',
    name: 'game',
    url: '/?screen=play',
    mockup: 'MinimalPlayGame.html',
    act: async (p) => {
      await playLine(p, NAJDORF)
      await p.waitForTimeout(600)
    },
  },
  {
    dir: 'play',
    name: 'setup-black-blitz',
    url: '/?screen=play',
    act: async (p) => {
      await p.getByRole('radio', { name: 'Black' }).click()
      await p.getByRole('radio', { name: '3+2 Blitz' }).click()
      await p.locator('#lvl').fill('4')
    },
  },
  {
    dir: 'play',
    name: 'confirm-resign',
    url: '/?screen=play',
    act: async (p) => {
      await playLine(p, NAJDORF.slice(0, 2))
      await p.getByRole('button', { name: 'Resign' }).click()
    },
  },
  {
    dir: 'play',
    name: 'dot-on-home',
    url: '/?screen=play',
    act: async (p) => {
      await playLine(p, NAJDORF.slice(0, 1))
      await p.getByRole('button', { name: /^Home/ }).click()
    },
  },
  {
    dir: 'play',
    name: 'ended-opens-review',
    url: '/?screen=play',
    act: async (p) => {
      await playLine(p, NAJDORF.slice(0, 2))
      await p.getByRole('button', { name: 'Resign' }).click()
      await p.getByRole('button', { name: 'Confirm resign' }).click()
    },
  },
  {
    dir: 'play',
    name: 'state-ended-while-away',
    url: '/?screen=play&state=engine-mates',
    act: async (p) => {
      await p.getByRole('button', { name: /Start game/ }).click()
      await p.waitForTimeout(200)
      await clickMove(p, 'e2', 'e4')
      await p.getByRole('button', { name: /^Home/ }).click()
      await p.waitForTimeout(1800)
      await p.getByRole('button', { name: /^Play/ }).click()
    },
  },
  { dir: 'play', name: 'state-loading', url: '/?screen=play&state=engine-starting', waitMs: 600 },
  { dir: 'play', name: 'state-no-engine', url: '/?screen=play&state=no-engine' },
  {
    dir: 'play',
    name: 'state-start-error',
    url: '/?screen=play&state=play-start-error',
    act: async (p) => {
      await p.getByRole('button', { name: /Start game/ }).click()
    },
  },
  {
    dir: 'play',
    name: 'state-engine-stopped',
    url: '/?screen=play&state=engine-stops',
    act: async (p) => {
      await p.getByRole('button', { name: /Start game/ }).click()
      await p.waitForTimeout(200)
      await clickMove(p, 'e2', 'e4')
      await p.waitForTimeout(600)
    },
  },
  // A sidecar older than the clocks: the move is resent without clock_ms and the game goes on.
  {
    dir: 'play',
    name: 'old-sidecar',
    url: '/?screen=play&state=old-sidecar',
    act: async (p) => {
      await playLine(p, NAJDORF.slice(0, 2))
    },
  },
  // A game played in the app keeps its clocks (UI-BUILD-3 F, ruling 9): Review's Time chart on it.
  {
    dir: 'play',
    name: 'played-review-time',
    url: '/?screen=review&game=played',
    act: async (p) => {
      await p.getByRole('radio', { name: 'Time' }).click()
    },
  },
  // Settings (UI-BUILD-2 E1). "alice" stands in for the saved username: the counts beside it
  // are the fixture database's.
  { dir: 'settings', name: 'settings', url: '/?screen=settings', mockup: 'MinimalSettings.html', size: SETTINGS_SIZE, storage: ACCOUNT },
  {
    dir: 'settings',
    name: 'pieces-merida',
    url: '/?screen=settings',
    size: SETTINGS_SIZE,
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('radio', { name: /Merida/ }).click()
      await p.getByRole('radio', { name: 'Walnut' }).click()
    },
  },
  { dir: 'settings', name: 'state-no-account', url: '/?screen=settings', size: SETTINGS_SIZE },
  // The username check on Save (UI-BUILD-3 G, ruling 5): found, not found, the site unreachable,
  // and the wait. "alice" / "bob" stand in for real names; the fake never touches the network.
  { dir: 'settings', name: 'username-found', url: '/?screen=settings', size: SETTINGS_SIZE, act: (p) => saveNames(p, 'alice', 'alice') },
  {
    dir: 'settings',
    name: 'username-not-found',
    url: '/?screen=settings&state=username-missing',
    size: SETTINGS_SIZE,
    act: (p) => saveNames(p, 'bob', 'alice'),
  },
  {
    dir: 'settings',
    name: 'username-unreachable',
    url: '/?screen=settings&state=username-unreachable',
    size: SETTINGS_SIZE,
    act: (p) => saveNames(p, 'alice', 'alice'),
  },
  {
    dir: 'settings',
    name: 'username-checking',
    url: '/?screen=settings&state=username-checking',
    size: SETTINGS_SIZE,
    act: (p) => saveNames(p, 'alice', '', 0),
  },
  { dir: 'settings', name: 'state-loading', url: '/?screen=settings&latency=60000', storage: ACCOUNT, waitMs: 600 },
  {
    dir: 'settings',
    name: 'state-sync-running',
    url: '/?screen=settings&state=sync-running',
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
  {
    dir: 'settings',
    name: 'state-sync-finished',
    url: '/?screen=settings&state=sync-finished',
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
  {
    dir: 'settings',
    name: 'state-sync-failed',
    url: '/?screen=settings&state=sync-failed',
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
  { dir: 'settings', name: 'state-no-engine', url: '/?screen=settings&state=no-engine', storage: ACCOUNT },
  { dir: 'settings', name: 'state-no-book', url: '/?screen=settings&state=no-book', size: SETTINGS_SIZE, storage: ACCOUNT },
  {
    dir: 'settings',
    name: 'state-book-downloading',
    url: '/?screen=settings&state=book-downloading',
    size: SETTINGS_SIZE,
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('button', { name: 'Download and use' }).first().click()
      await p.waitForTimeout(400)
    },
  },
  {
    dir: 'settings',
    name: 'state-book-failed',
    url: '/?screen=settings&state=book-failed',
    size: SETTINGS_SIZE,
    storage: ACCOUNT,
    act: async (p) => {
      await p.getByRole('button', { name: 'Download and use' }).first().click()
      await p.waitForTimeout(400)
    },
  },
  // Every board draws the chosen set: Review and Home with merida on walnut.
  { dir: 'settings', name: 'board-merida-review', url: REVIEW, storage: MERIDA },
  { dir: 'settings', name: 'board-fantasy-home', url: '/?screen=home', storage: { 'zugzwang.pieceSet': 'fantasy' } },
  { dir: 'shell', name: 'settings-old-screen', url: '/?screen=settings' },
  ...PUZZLE_SHOTS,
  ...GAMES_SHOTS,
  ...PROMOTION_SHOTS,
  // the Flag this shots only in a beta harness (ZUGZWANG_HARNESS_BETA=1, harness/flagShots.ts)
  ...(process.env.ZUGZWANG_HARNESS_BETA === '1' ? FLAG_SHOTS : []),
  // Friends (FRIENDS-1 E): not in beta builds (ruling L4)
  ...(process.env.ZUGZWANG_HARNESS_BETA === '1' ? [] : FRIENDS_SHOTS),
]
