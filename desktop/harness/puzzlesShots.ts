/**
 * The Puzzles shots (UI-BUILD-2 E2), beside MinimalPuzzles.html and MinimalPuzzle.html. The
 * session shots play the recorded real puzzles by clicking squares, as a user would; the
 * Glicko-2 answers are the real ones recorded for that run (puzzlesHarness.ts).
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Page } from 'playwright'
import { Chess } from 'chess.js'
import type { Shot } from './shots.ts'

const here = dirname(fileURLToPath(import.meta.url))
const fixturesDir = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(here, '..', '..', 'review', 'ui_fixtures')
interface P {
  id: string
  fen: string
  movesUci: string[]
  finalMates?: string[]
}
let pf: { rated: P[]; survival: P[]; noPuzzleThemes?: string[] } | null = null
function fixtures() {
  pf ??= JSON.parse(readFileSync(resolve(fixturesDir, 'puzzles_fixtures.json'), 'utf8'))
  return pf!
}

const LOBBY = '/?screen=puzzles'

async function waitState(p: Page, s: string) {
  await p.waitForSelector(`.session[data-state="${s}"]`, { timeout: 20_000 })
}
const userWhite = (pz: P) => pz.fen.split(' ')[1] === 'b'

async function clickSquare(p: Page, sq: string, white: boolean) {
  const box = (await p.locator('.session cg-board').boundingBox())!
  const s = box.width / 8
  const f = sq.charCodeAt(0) - 97
  const r = Number(sq[1]) - 1
  const x = box.x + (white ? f + 0.5 : 7 - f + 0.5) * s
  const y = box.y + (white ? 7 - r + 0.5 : r + 0.5) * s
  await p.mouse.click(x, y)
}
async function play(p: Page, uci: string, white: boolean) {
  // chessground ignores a second click that follows the first too closely
  await clickSquare(p, uci.slice(0, 2), white)
  await p.waitForTimeout(150)
  await clickSquare(p, uci.slice(2, 4), white)
  await p.waitForFunction(() => (document.querySelector('.session') as HTMLElement | null)?.dataset.state !== 'awaiting', null, { timeout: 5000 })
}

/** Play every user move of the puzzle; waits for each turn. */
async function solve(p: Page, pz: P) {
  for (let i = 1; i < pz.movesUci.length; i += 2) {
    await waitState(p, 'awaiting')
    await play(p, pz.movesUci[i], userWhite(pz))
  }
  await waitState(p, 'complete')
}

/** A legal first move that is not the answer (nor another mate on a one-move puzzle). */
async function playWrong(p: Page, pz: P) {
  await waitState(p, 'awaiting')
  const b = new Chess(pz.fen)
  b.move({ from: pz.movesUci[0].slice(0, 2), to: pz.movesUci[0].slice(2, 4), promotion: pz.movesUci[0][4] })
  const bad = b
    .moves({ verbose: true })
    .find((m) => !m.promotion && m.from + m.to !== pz.movesUci[1].slice(0, 4) && !(pz.finalMates ?? []).some((u) => u.startsWith(m.from + m.to)))!
  await play(p, bad.from + bad.to, userWhite(pz))
}

/** The requests the page has made so far (harness/main.ts exposes the fake sidecar's log). */
async function requests(p: Page): Promise<string[]> {
  return p.evaluate(() =>
    ((window as unknown as { __harness: { requestLog: { method: string }[] } }).__harness.requestLog).map((r) => r.method),
  )
}

/** Mid-puzzle (J): the first puzzle's first move found, then a wrong try for the second. */
async function midPuzzle(p: Page) {
  const pz = fixtures().rated[0]
  await startRated(p)
  await waitState(p, 'awaiting')
  await play(p, pz.movesUci[1], userWhite(pz))
  await playWrong2(p, pz)
  await waitState(p, 'awaiting')
}

/** A legal move that is not the answer to the puzzle's second user move. */
async function playWrong2(p: Page, pz: P) {
  await waitState(p, 'awaiting')
  const b = new Chess(pz.fen)
  for (const u of pz.movesUci.slice(0, 3)) b.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] })
  const bad = b.moves({ verbose: true }).find((m) => !m.promotion && m.from + m.to !== pz.movesUci[3].slice(0, 4))!
  await play(p, bad.from + bad.to, userWhite(pz))
  await p.waitForTimeout(600)
}

async function startRated(p: Page) {
  await p.getByRole('button', { name: /Start rated/ }).click()
}

export const PUZZLE_SHOTS: Shot[] = [
  { dir: 'puzzles', name: 'puzzles', url: LOBBY, mockup: 'MinimalPuzzles.html', size: { width: 1440, height: 1000 } },
  {
    dir: 'puzzles',
    name: 'session',
    url: LOBBY,
    mockup: 'MinimalPuzzle.html',
    act: async (p) => {
      const rated = fixtures().rated
      await startRated(p)
      for (let i = 0; i < 6; i++) {
        if (i === 2) {
          await playWrong(p, rated[i])
          await p.waitForTimeout(500)
        }
        await solve(p, rated[i])
        await p.keyboard.press('Enter')
      }
      await waitState(p, 'awaiting')
    },
  },
  {
    dir: 'puzzles',
    name: 'session-first',
    url: LOBBY,
    act: async (p) => {
      await startRated(p)
      await waitState(p, 'awaiting')
    },
  },
  {
    dir: 'puzzles',
    name: 'session-solved',
    url: LOBBY,
    act: async (p) => {
      await startRated(p)
      await solve(p, fixtures().rated[0])
    },
  },
  {
    dir: 'puzzles',
    name: 'session-wrong',
    url: LOBBY,
    act: async (p) => {
      await startRated(p)
      await playWrong(p, fixtures().rated[0])
      await p.waitForTimeout(600)
    },
  },
  {
    dir: 'puzzles',
    name: 'session-hint',
    url: LOBBY,
    act: async (p) => {
      await startRated(p)
      await waitState(p, 'awaiting')
      await p.keyboard.press('h')
    },
  },
  {
    // J: the solution folded into the move list. The first move was found, the second given up:
    // the board is where solving stopped, the arrow on the move not found, the rest in grey.
    dir: 'puzzles',
    name: 'session-solution',
    url: LOBBY,
    mockup: 'MinimalPuzzle.html',
    act: async (p) => {
      const pz = fixtures().rated[0]
      await startRated(p)
      await waitState(p, 'awaiting')
      await play(p, pz.movesUci[1], userWhite(pz))
      await waitState(p, 'awaiting')
      await p.getByRole('button', { name: 'View solution' }).click()
      await waitState(p, 'solution')
    },
  },
  {
    // J: mid-puzzle, the move list from the setup move, a wrong try struck beside the move to find
    dir: 'puzzles',
    name: 'session-moves',
    url: LOBBY,
    mockup: 'MinimalPuzzle.html',
    act: midPuzzle,
  },
  {
    // J: looking back (← twice). The board is locked and stepping sends nothing: the shot fails if
    // a request is made while stepping or if a move can be played on the board.
    dir: 'puzzles',
    name: 'session-looking-back',
    url: LOBBY,
    mockup: 'MinimalPuzzle.html',
    act: async (p) => {
      const pz = fixtures().rated[0]
      await midPuzzle(p)
      await p.waitForTimeout(800)
      const before = await requests(p)
      await p.keyboard.press('ArrowLeft')
      await p.keyboard.press('ArrowLeft')
      await p.keyboard.press('Home')
      await p.keyboard.press('ArrowRight')
      // the right answer, tried on the locked board, must not be played
      await clickSquare(p, pz.movesUci[3].slice(0, 2), userWhite(pz))
      await p.waitForTimeout(150)
      await clickSquare(p, pz.movesUci[3].slice(2, 4), userWhite(pz))
      await p.waitForTimeout(800)
      const after = await requests(p)
      if (after.length !== before.length) throw new Error(`looking back sent requests: ${after.slice(before.length).join(', ')}`)
      const state = await p.locator('.session').getAttribute('data-state')
      if (state !== 'awaiting') throw new Error(`the locked board took a move (state ${state})`)
      if ((await p.getByRole('heading', { name: 'Looking back' }).count()) !== 1) throw new Error('no Looking back panel')
    },
  },
  {
    // J: End returns to the puzzle, and the right move is then played
    dir: 'puzzles',
    name: 'session-back-to-play',
    url: LOBBY,
    act: async (p) => {
      const pz = fixtures().rated[0]
      await midPuzzle(p)
      await p.keyboard.press('Home')
      await p.keyboard.press('End')
      await play(p, pz.movesUci[3], userWhite(pz))
      await waitState(p, 'awaiting')
    },
  },
  {
    // J: Rush, looking back: the clock keeps running
    dir: 'puzzles',
    name: 'rush-looking-back',
    url: LOBBY,
    act: async (p) => {
      await p.getByRole('button', { name: 'Start rush' }).click()
      const rated = fixtures().rated
      await solve(p, rated[0])
      await waitState(p, 'awaiting')
      await p.keyboard.press('Home')
      const t0 = await p.locator('.top .metric').textContent()
      await p.waitForTimeout(2100)
      const t1 = await p.locator('.top .metric').textContent()
      if (t0 === t1) throw new Error('the Rush clock stopped while looking back')
    },
  },
  {
    dir: 'puzzles',
    name: 'rush',
    url: LOBBY,
    act: async (p) => {
      await p.getByRole('radio', { name: '5 min' }).click()
      await p.getByRole('button', { name: 'Start rush' }).click()
      const rated = fixtures().rated
      await solve(p, rated[0])
      await solve(p, rated[1])
      await waitState(p, 'awaiting')
    },
  },
  {
    dir: 'puzzles',
    name: 'rush-ended',
    url: LOBBY,
    before: async (p) => {
      await p.clock.install()
    },
    act: async (p) => {
      await p.getByRole('button', { name: 'Start rush' }).click()
      await solve(p, fixtures().rated[0])
      await p.clock.runFor(181_000)
      await waitState(p, 'ended')
    },
  },
  {
    dir: 'puzzles',
    name: 'survival-ended',
    url: LOBBY,
    act: async (p) => {
      await p.getByRole('button', { name: 'Start survival' }).click()
      const s = fixtures().survival
      await solve(p, s[0])
      await p.keyboard.press('Enter')
      await solve(p, s[1])
      await p.keyboard.press('Enter')
      await playWrong(p, s[2])
      await waitState(p, 'ended')
    },
  },
  {
    dir: 'puzzles',
    name: 'lobby-themes',
    url: LOBBY,
    size: { width: 1440, height: 1000 },
    act: async (p) => {
      await p.getByRole('button', { name: /more$/ }).click()
      await p.getByRole('button', { name: 'Fork', exact: true }).click()
    },
  },
  {
    dir: 'puzzles',
    name: 'state-no-theme-puzzles',
    url: LOBBY,
    size: { width: 1440, height: 1000 },
    act: async (p) => {
      await p.getByRole('button', { name: /more$/ }).click()
      await p.getByRole('button', { name: 'En passant', exact: true }).click()
      await p.getByRole('button', { name: 'Underpromotion', exact: true }).click()
      await startRated(p)
    },
  },
  { dir: 'puzzles', name: 'state-loading', url: LOBBY + '&latency=60000', waitMs: 600 },
  { dir: 'puzzles', name: 'state-error', url: LOBBY + '&state=puzzles-error' },
  { dir: 'puzzles', name: 'state-not-imported', url: LOBBY + '&state=puzzles-not-imported' },
  { dir: 'puzzles', name: 'state-no-csv', url: LOBBY + '&state=puzzles-no-csv' },
  { dir: 'puzzles', name: 'state-importing', url: LOBBY + '&state=puzzles-importing' },
  {
    dir: 'puzzles',
    name: 'state-import-error',
    url: LOBBY + '&state=puzzles-import-error',
    act: async (p) => {
      await p.getByRole('button', { name: 'Import puzzles' }).click()
    },
  },
  { dir: 'puzzles', name: 'state-new-player', url: LOBBY + '&state=puzzles-new', size: { width: 1440, height: 1000 } },
  {
    dir: 'puzzles',
    name: 'state-session-slow',
    url: LOBBY + '&state=puzzles-slow',
    act: async (p) => {
      await startRated(p)
      await p.waitForTimeout(3000)
    },
  },
  {
    dir: 'puzzles',
    name: 'state-session-empty',
    url: LOBBY + '&state=puzzles-empty',
    act: async (p) => {
      await startRated(p)
      await waitState(p, 'empty')
    },
  },
]
