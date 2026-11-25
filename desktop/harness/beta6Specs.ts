/**
 * BETA-6's layout cases (FRIENDS.md "BETA-6: the spec", B): every screen with the longest names (S7), and every
 * popover, dialog, menu and banner opened over it (topmost at its centre and corners), the friends list with one
 * friend and with many. Shared by harness/beta6Checks.ts (both browsers, shots, review/scratch/ui/beta6/) and
 * src/lib/shell/overlays.browser.test.ts (the gate's run).
 */
import type { Page } from 'playwright'
import { LONG } from './longNames.ts'

export interface Case {
  name: string
  path: string
  /** what to do once the page is up (open a popover, click a row) */
  prepare?: (page: Page) => Promise<void>
  /** the overlays to check as topmost (each a selector) */
  overlays?: string[]
  /** check the long names (default true) */
  names?: boolean
}

/** your own Chess.com and Lichess usernames (Settings), the longest allowed: 25 characters */
export const STORAGE = { 'zugzwang-accounts': JSON.stringify({ chesscom: LONG.username(20), lichess: LONG.username(19) }) }
export const SIZES = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
]

/** a click; when something lies over the target (a banner over Play's setup), the click is dispatched to it and noted */
export const covered: string[] = []
async function press(page: Page, loc: ReturnType<Page['locator']>, what: string) {
  try {
    await loc.click({ timeout: 4000 })
  } catch {
    covered.push(what)
    await loc.dispatchEvent('click')
  }
  await page.waitForTimeout(300)
}
const click = (sel: string) => async (page: Page) => press(page, page.locator(sel).first(), sel)
const role = (r: 'button' | 'menuitem' | 'radio' | 'tab', name: string | RegExp) => async (page: Page) =>
  press(page, page.getByRole(r, { name }).first(), `${r} ${String(name)}`)
const seq = (...fs: ((p: Page) => Promise<void>)[]) => async (page: Page) => {
  for (const f of fs) await f(page)
}
const firstFriend = click('.fli button.row')
const FEN = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'

export const SCREENS: Case[] = [
  { name: 'home', path: '/?screen=home' },
  { name: 'play', path: '/?screen=play' },
  { name: 'play-a-friend', path: '/?screen=play', prepare: role('radio', 'A friend') },
  { name: 'fgame', path: '/?screen=play&state=fgame' },
  { name: 'fgame-draw', path: '/?screen=play&state=fgame-draw' },
  { name: 'fgame-left', path: '/?screen=play&state=fgame-left' },
  { name: 'fgame-over', path: '/?screen=play&state=fgame-over' },
  { name: 'fgame-collapsed', path: '/?screen=play&state=fgame-collapsed' },
  { name: 'games', path: '/?screen=games' },
  { name: 'review', path: '/?screen=review&game=main' },
  { name: 'analyse-position', path: '/?screen=review&fen=' + encodeURIComponent(FEN) },
  { name: 'puzzles', path: '/?screen=puzzles' },
  { name: 'trainer', path: '/?screen=trainer' },
  { name: 'insights', path: '/?screen=insights' },
  // COACH-1 C: Coach (Focus, Behind your focus), its learning state, one focus item's positions shown
  { name: 'coach', path: '/?screen=coach' },
  { name: 'coach-learning', path: '/?screen=coach&state=coach-learning' },
  { name: 'coach-show', path: '/?screen=coach', prepare: role('button', 'Show positions') },
  // COACH-2 C: Practice: a session (Find the move, Spot the threat, a probe), an answer shown, the empty queue
  { name: 'practice', path: '/?screen=coach', prepare: role('button', 'Start practice') },
  { name: 'practice-threat', path: '/?screen=coach&state=practice-threat', prepare: role('button', 'Start practice') },
  { name: 'practice-probe', path: '/?screen=coach&state=practice-probe', prepare: role('button', 'Start practice') },
  { name: 'practice-answer', path: '/?screen=coach', prepare: seq(role('button', 'Start practice'), role('button', 'Show the answer')) },
  { name: 'practice-focus', path: '/?screen=coach', prepare: role('button', /^Practise$/) },
  { name: 'coach-practice-empty', path: '/?screen=coach&state=practice-empty' },
  { name: 'settings', path: '/?screen=settings' },
  // COACH-2 D (ruling CB1): background jobs running: the sidebar's activity line, the Review header's progress, the
  // Games row being re-analysed
  { name: 'home+jobs', path: '/?screen=home&jobs=all' },
  { name: 'review+jobs', path: '/?screen=review&game=main&jobs=all' },
  { name: 'review-moves+jobs', path: '/?screen=review&game=main&jobs=all', prepare: role('tab', 'Moves') },
  { name: 'games+jobs', path: '/?screen=games&jobs=all' },
  { name: 'friends', path: '/?screen=friends' },
  { name: 'friends-many', path: '/?screen=friends&friends=many' },
  { name: 'friends-one', path: '/?screen=friends&friends=one' },
  { name: 'friends-signup', path: '/?screen=friends&state=friends-signup' },
  { name: 'friend-profile', path: '/?screen=friends', prepare: firstFriend },
]

/** a banner (S6) over each screen above, with one challenge and with three (not sign-up: no account, no challenges) */
export const BANNERS: Case[] = SCREENS.filter((s) => s.name !== 'friends-signup').flatMap((s) => [
  { ...s, name: s.name + '+banner', path: s.path + '&challenge=1', overlays: ['.banners .banner'], names: false },
  { ...s, name: s.name + '+banners3', path: s.path + '&challenge=3', overlays: ['.banners .banner:nth-child(1)', '.banners .banner:nth-child(3)', '.banners'], names: false },
])

export const OVERLAYS: Case[] = [
  { name: 'friends-one: Challenge popover', path: '/?screen=friends&friends=one', prepare: click('.fli .end button'), overlays: ['.popat [role=dialog]'] },
  { name: 'friends: Challenge popover, first row', path: '/?screen=friends', prepare: click('.fli .end button'), overlays: ['.popat [role=dialog]'] },
  {
    name: 'friends-many: Challenge popover, last online row',
    path: '/?screen=friends&friends=many',
    prepare: async (page) => {
      const b = page.locator('.fli .end button')
      const last = b.nth((await b.count()) - 1)
      // the list scrolled to its end, so the last row sits at the window's bottom: no room below it
      await last.evaluate((el) => el.scrollIntoView({ block: 'end' }))
      await page.waitForTimeout(200)
      await last.click()
      await page.waitForTimeout(300)
    },
    overlays: ['.popat [role=dialog]'],
  },
  { name: 'profile: Challenge popover', path: '/?screen=friends', prepare: seq(firstFriend, click('.chal button')), overlays: ['.popat [role=dialog]'] },
  { name: 'profile: More menu', path: '/?screen=friends', prepare: seq(firstFriend, click('button[aria-label^="More: Remove friend"]')), overlays: ['[role=menu]'] },
  {
    name: 'profile: Remove friend? (S5)',
    path: '/?screen=friends',
    prepare: seq(firstFriend, click('button[aria-label^="More: Remove friend"]'), role('menuitem', /Remove/)),
    overlays: ['[role=alertdialog]'],
  },
  { name: 'command menu', path: '/?screen=home', prepare: click('button.search'), overlays: ['[role=dialog][aria-label="Command menu"]'] },
  { name: 'games: Import PGN', path: '/?screen=games', prepare: role('button', /Import/), overlays: ['[role=dialog][aria-label="Import PGN"]'] },
  { name: 'games: Analyse a position', path: '/?screen=games', prepare: role('button', /Analyse a position/), overlays: ['[role=dialog][aria-label="Analyse a position"]'] },
  { name: 'games: Sort menu', path: '/?screen=games', prepare: click('.sortwrap button'), overlays: ['[role=menu][aria-label=Sort]'] },
  { name: 'review: Analyse again', path: '/?screen=review&game=main', prepare: role('button', /Analyse again|^Analyse/), overlays: ['[role=dialog][aria-label="Analyse again"]'] },
  { name: 'review: More actions', path: '/?screen=review&game=main', prepare: role('button', 'More actions'), overlays: ['.over[role=menu]'] },
  { name: 'settings: Privacy policy', path: '/?screen=settings', prepare: role('button', 'Privacy policy'), overlays: ['[role=dialog][aria-modal=true]'] },
  { name: 'signup: Terms of use', path: '/?screen=friends&state=friends-signup', prepare: role('button', 'Terms of use'), overlays: ['[role=dialog][aria-modal=true]'] },
]

export const ALL: Case[] = [...SCREENS, ...OVERLAYS, ...BANNERS]
