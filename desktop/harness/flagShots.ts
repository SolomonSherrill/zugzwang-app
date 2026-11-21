/**
 * "Flag this" shots (BETA-4 B, FLAG-RESTORE): Review's Moves and Report tabs with the ⚑ placements,
 * ⌘K's "Flag this move", and the note form open, at 1440 x 940 and 1280 x 720, each with the DOM
 * layout check. Taken in a beta harness:
 *
 *   cd desktop && ZUGZWANG_HARNESS_BETA=1 ZUGZWANG_HARNESS_MOCKUPS=0 \
 *     ZUGZWANG_HARNESS_OUT=../review/scratch/ui/beta4 node harness/shoot.ts flag/
 *
 * (shoot.ts writes the layout check to <out>/sizes/layout_check.out; BETA-4 moved it to
 * review/scratch/ui/beta4/flag/layout_check.out.)
 */
import type { Shot } from './shots.ts'

/** ply 63 of the main game: a move with a rule sentence */
const URL = '/?screen=review&game=main&ply=63'
const SMALL = { width: 1280, height: 720 }
const BIG = { width: 1440, height: 940 }

const moves = async (p: import('playwright').Page) => {
  await p.getByRole('tab', { name: 'Moves' }).click()
  await p.locator('.why .say').first().waitFor()
}
const report = async (p: import('playwright').Page) => {
  await p.locator('.moments .km').first().click()
}
const menu = async (p: import('playwright').Page) => {
  await p.keyboard.press('ControlOrMeta+k')
  await p.keyboard.type('flag')
}
const flagOpen = async (p: import('playwright').Page) => {
  await menu(p)
  await p.keyboard.press('Enter')
  await p.locator('.why .flag input').waitFor()
}

export const FLAG_SHOTS: Shot[] = [
  ...([['', BIG], ['-1280x720', SMALL]] as const).flatMap(([sfx, size]) => [
    { dir: 'flag', name: `moves${sfx}`, url: URL, act: moves, size, check: true },
    { dir: 'flag', name: `report${sfx}`, url: URL, act: report, size, check: true },
    { dir: 'flag', name: `command-menu${sfx}`, url: URL, act: menu, size, check: true },
    { dir: 'flag', name: `moves-flag-open${sfx}`, url: URL, act: flagOpen, size, check: true },
  ]),
]
