/**
 * The promotion picker's shots (UI-BUILD-4 D; DESIGN.md fifth rulings, 3): the picker open on
 * each of the six screens that take a move from the board, plus Black at the bottom and a
 * second theme and piece set. App only (no mockup draws the picker). Positions:
 * harness/promotionHarness.ts.
 */
import type { Page } from 'playwright'
import type { Shot } from './shots.ts'

const PROMO_FEN = 'r1bqkb1r/pP1npppp/5n2/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 5'
const BLACK_FEN = '4k3/8/8/8/8/8/6p1/4K3 b - - 0 1'
const ANALYSE = '/?screen=review&fen=' + encodeURIComponent(PROMO_FEN)

async function move(p: Page, uci: string, black = false) {
  const box = (await p.locator('cg-board:visible').first().boundingBox())!
  const s = box.width / 8
  for (const sq of [uci.slice(0, 2), uci.slice(2, 4)]) {
    const f = sq.charCodeAt(0) - 97
    const r = Number(sq[1]) - 1
    await p.mouse.click(box.x + (black ? 7 - f + 0.5 : f + 0.5) * s, box.y + (black ? r + 0.5 : 7 - r + 0.5) * s)
    await p.waitForTimeout(150)
  }
  await p.locator('.promo-scrim:visible').waitFor()
  await p.mouse.move(2, 900) // off the picker: no hover ring in the shot
}

export const PROMOTION_SHOTS: Shot[] = [
  {
    dir: 'promotion',
    name: 'play',
    url: ANALYSE,
    act: async (p) => {
      await p.getByRole('button', { name: 'Play it vs Stockfish' }).click()
      await p.waitForTimeout(600)
      await move(p, 'b7a8')
    },
  },
  {
    dir: 'promotion',
    name: 'try-it',
    url: '/?screen=review&game=promo',
    act: async (p) => {
      await p.locator('.moments .km').first().click()
      await p.getByRole('button', { name: /Try it/ }).first().click()
      await p.waitForTimeout(400)
      await move(p, 'b7a8')
    },
  },
  { dir: 'promotion', name: 'explore', url: '/?screen=review&game=promo&ply=7', act: (p) => move(p, 'b7c8') },
  { dir: 'promotion', name: 'analyse', url: ANALYSE, act: (p) => move(p, 'b7b8') },
  {
    dir: 'promotion',
    name: 'puzzle',
    url: '/?screen=puzzles&state=promotion',
    act: async (p) => {
      await p.getByRole('button', { name: /Start rated/ }).click()
      await p.waitForSelector('.session[data-state="awaiting"]', { timeout: 20_000 })
      await move(p, 'f7f8')
    },
  },
  {
    dir: 'promotion',
    name: 'trainer',
    url: '/?screen=trainer&state=promotion',
    act: async (p) => {
      await p.getByRole('button', { name: /^Promotion drill/ }).first().click()
      await p.getByRole('button', { name: 'White', exact: true }).click()
      await p.getByRole('button', { name: 'Line start', exact: true }).click()
      await p.getByRole('button', { name: /Start training/ }).click()
      await p.waitForTimeout(600)
      await move(p, 'b7a8')
    },
  },
  // Black at the bottom: the column runs down from g1, now on the top edge
  { dir: 'promotion', name: 'analyse-black', url: '/?screen=review&fen=' + encodeURIComponent(BLACK_FEN), act: (p) => move(p, 'g2g1', true) },
  // the board's own theme and set: Walnut with Merida
  {
    dir: 'promotion',
    name: 'analyse-walnut-merida',
    url: ANALYSE,
    storage: { 'zugzwang.pieceSet': 'merida', 'zugzwang.boardTheme': 'walnut' },
    act: (p) => move(p, 'b7a8'),
  },
]
