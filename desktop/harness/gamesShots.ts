/** The Games screen's shots (UI-BUILD-3 E; stacked rows, UI-BUILD-4 B): beside MinimalGames.html
 *  and its two popovers, plus the drafted states, the narrow window (1280 x 720: no Time, no
 *  Source) and an unanalysed row under the pointer. "alice" stands in for the saved username. */
import type { Page } from 'playwright'
import type { Shot } from './shots.ts'

const at2112 = new Date()
at2112.setHours(21, 12, 0, 0)
const STORAGE = {
  'zugzwang-accounts': JSON.stringify({ chesscom: 'alice', lichess: '' }),
  'zugzwang-last-synced': JSON.stringify({ chesscom: at2112.toISOString(), lichess: null }),
}
const URL = '/?screen=games'
const PGN =
  '[Event "Club championship, round 3"]\n[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n\n' +
  '1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5 4. d4 Nf6 5. Nf3 c6\n6. Bc4 Bf5 7. Bd2 e6 8. Qe2 Bb4 9. O-O-O 1-0'
const FEN = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'

async function hoverRow(p: Page, n: number): Promise<void> {
  const box = await p.locator('li.row').nth(n).boundingBox()
  if (box) await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
}

export const GAMES_SHOTS: Shot[] = [
  {
    dir: 'games',
    name: 'games',
    // the row kinds the mockup draws (unanalysed, Stockfish, no ratings): gamesHarness.ts
    url: URL + '&state=games-kinds',
    mockup: 'MinimalGames.html',
    storage: STORAGE,
    act: async (p) => {
      // the mockup draws the second game selected and the fourth under the pointer
      await p.keyboard.press('j')
      await p.keyboard.press('j')
      await hoverRow(p, 3)
    },
  },
  {
    dir: 'games',
    name: 'games-narrow',
    url: URL + '&state=games-kinds',
    size: { width: 1280, height: 720 },
    storage: STORAGE,
    act: async (p) => {
      await p.keyboard.press('j')
      await p.keyboard.press('j')
      await hoverRow(p, 3)
    },
  },
  {
    dir: 'games',
    name: 'games-unanalysed-hover',
    url: URL + '&state=games-kinds',
    storage: STORAGE,
    act: async (p) => {
      await hoverRow(p, 1)
    },
  },
  {
    dir: 'games',
    name: 'games-unanalysed-focus',
    url: URL + '&state=games-kinds',
    storage: STORAGE,
    act: async (p) => {
      // keyboard focus on the row (its open button) shows Analyse as hover does
      await p.locator('li.row').nth(1).locator('button.open').focus()
      await p.mouse.move(0, 0)
    },
  },
  {
    dir: 'games',
    name: 'games-import',
    url: URL,
    mockup: 'MinimalGames-import.html',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Import PGN' }).click()
      await p.getByRole('textbox', { name: 'PGN' }).fill(PGN)
    },
  },
  {
    dir: 'games',
    name: 'games-position',
    url: URL,
    mockup: 'MinimalGames-position.html',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Analyse a position' }).click()
      await p.getByRole('textbox', { name: 'FEN or PGN' }).fill(FEN)
    },
  },
  {
    dir: 'games',
    name: 'position-illegal',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Analyse a position' }).click()
      await p.getByRole('textbox', { name: 'FEN or PGN' }).fill('4k3/8/8/8/8/8/8/4RK2 w - - 0 1')
    },
  },
  {
    dir: 'games',
    name: 'position-empty',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Analyse a position' }).click()
    },
  },
  {
    dir: 'games',
    name: 'position-dialog-from-home',
    url: '/?screen=home',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Analyse a game' }).click()
      await p.getByRole('textbox', { name: 'FEN or PGN' }).fill(FEN)
    },
  },
  {
    dir: 'games',
    name: 'more-filters',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: /More filters/ }).click()
    },
  },
  {
    dir: 'games',
    name: 'sort-menu',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: /Newest first/ }).click()
    },
  },
  {
    dir: 'games',
    name: 'filtered-won',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('radio', { name: 'Won' }).click()
      await p.waitForTimeout(400)
    },
  },
  {
    dir: 'games',
    name: 'show-more',
    url: URL,
    storage: STORAGE,
    fullPage: true,
    act: async (p) => {
      await p.getByRole('button', { name: /Show 50 more/ }).click()
      await p.waitForTimeout(300)
    },
  },
  {
    dir: 'games',
    name: 'import-analysing',
    url: URL,
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Import PGN' }).click()
      await p.getByRole('textbox', { name: 'PGN' }).fill(PGN)
      await p.getByRole('button', { name: 'Import 1 game' }).click()
      await p.waitForTimeout(400)
    },
  },
  {
    dir: 'games',
    name: 'state-row-analysing',
    url: URL + '&state=games-row-analysing',
    storage: STORAGE,
    act: async (p) => {
      const row = p.locator('li.row', { hasText: 'Not analysed' }).first()
      await row.hover()
      await row.getByRole('button', { name: 'Analyse' }).click()
      await p.waitForTimeout(600)
    },
  },
  { dir: 'games', name: 'state-loading', url: URL + '&latency=60000', storage: STORAGE, waitMs: 600 },
  { dir: 'games', name: 'state-error', url: URL + '&state=games-error', storage: STORAGE },
  { dir: 'games', name: 'state-no-games', url: URL + '&state=games-none', storage: STORAGE },
  { dir: 'games', name: 'state-no-match', url: URL + '&state=games-no-match', storage: STORAGE },
  {
    dir: 'games',
    name: 'state-sync-running',
    url: URL + '&state=sync-running',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
  {
    dir: 'games',
    name: 'state-sync-failed',
    url: URL + '&state=sync-failed',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
  {
    dir: 'games',
    name: 'state-sync-finished',
    url: URL + '&state=sync-finished',
    storage: STORAGE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Sync now' }).click()
      await p.waitForTimeout(500)
    },
  },
]
