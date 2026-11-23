/**
 * Games against friends (FRIENDS-2 D), in the browser harness over the fake sidecar (harness/friendsHarness.ts,
 * synthetic data and the stage-2 mockups' positions): the challenge banner on any screen (Accept before
 * Decline, neither red nor green; ruling S2), the sidebar's count with challenges (S1), the Challenge popover
 * (Play as, the ten time controls, the ratings line; C1) on a friend's row and profile and only for a friend
 * online (C2), Play's "A friend", the game screen playing / draw offered / opponent left / over (P1, P3),
 * the chat below the moves (collapsible, expanded by default, unread count and last line, mute; H1-H4), and
 * Check now at most once every 30 s (Z4).
 * Skipped when the browser or the private fixtures are not installed (the public tree has none).
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
const STORAGE = { 'zugzwang-accounts': JSON.stringify({ chesscom: 'you_demo', lichess: '' }) }

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
const servers: ViteDevServer[] = []
let browser: Browser | null = null
const base: Record<'beta' | 'dev', string> = { beta: '', dev: '' }
async function harness(beta: boolean): Promise<string> {
  const port = await freePort()
  const server = await createServer({
    configFile: resolve(desktop, 'vite.harness.config.ts'),
    define: { __BETA__: JSON.stringify(beta) },
    server: { port, strictPort: true, host: '127.0.0.1' },
    logLevel: 'silent',
  })
  await server.listen()
  servers.push(server)
  return `http://127.0.0.1:${port}`
}
async function open(path: string, build: 'dev' | 'beta' = 'dev', size = { width: 1440, height: 940 }, savePath?: string | null, clock = false): Promise<Page> {
  const ctx = await browser!.newContext({ viewport: size })
  if (clock) {
    const p0 = await ctx.newPage()
    await p0.clock.install()
    await p0.goto(base[build] + path)
    return p0
  }
  await ctx.addInitScript((e: [string, string][]) => e.forEach(([k, v]) => localStorage.setItem(k, v)), Object.entries(STORAGE))
  if (savePath !== undefined) {
    // the dialog plugin's save() is invoke('plugin:dialog|save'): answered here as the dialog would be
    await ctx.addInitScript((answer: string | null) => {
      const w = window as unknown as { __TAURI_INTERNALS__: unknown; __zzDialog: unknown[] }
      w.__zzDialog = []
      w.__TAURI_INTERNALS__ = {
        invoke: async (cmd: string, args: unknown) => {
          w.__zzDialog.push([cmd, args])
          if (cmd === 'plugin:dialog|save') return answer
          throw new Error('not in the harness: ' + cmd)
        },
        transformCallback: () => 0,
      }
    }, savePath)
  }
  const page = await ctx.newPage()
  await page.goto(base[build] + path)
  return page
}


const calls = (page: Page) => page.evaluate(() => (window as unknown as { __zzFriendsCalls?: [string, string][] }).__zzFriendsCalls ?? [])
/** a button's colours as drawn: neither red (--loss) nor green may mark Accept or Decline (S2, S4) */
async function colours(page: Page, el: ReturnType<Page['locator']>): Promise<string[]> {
  return el.evaluate((b) => {
    const cs = getComputedStyle(b)
    return [cs.color, cs.backgroundColor, cs.borderColor]
  })
}
function reddishOrGreen(rgb: string): boolean {
  const m = rgb.match(/\d+(\.\d+)?/g)
  if (!m) return false
  const [r, g, b] = m.map(Number)
  return (r > 150 && g < 110 && b < 110) || (g > 150 && r < 110 && b < 140)
}

describe.skipIf(!ready)(`Games against friends (FRIENDS-2) [${harnessBrowserName}]`, () => {
  beforeAll(async () => {
    base.dev = await harness(false)
    browser = await harnessBrowser.launch({ headless: true })
  }, 90_000)
  afterAll(async () => {
    await browser?.close()
    for (const s of servers) await s.close()
  })

  it('a challenge shows on any screen, Accept before Decline, neither red nor green; Accept opens the game', async () => {
    for (const screen of ['home', 'games', 'settings']) {
      const page = await open(`/?screen=${screen}&state=friends-challenge`)
      const banner = page.getByRole('alertdialog', { name: 'Challenge from maxk' })
      await banner.waitFor()
      const text = (await banner.textContent())!.replace(/\s+/g, ' ')
      expect(text).toContain('maxk challenges you to a 5+0 game. You play Black.')
      expect(text).toContain('Unrated. Ratings shown in the game: you 1438, maxk 1446 (Chess.com blitz).')
      expect(text).toMatch(/Expires in 0:5\d\./)
      const names = await banner.getByRole('button').allTextContents()
      expect(names.map((n) => n.trim())).toEqual(['Accept', 'Decline'])
      for (const b of await banner.getByRole('button').all()) for (const c of await colours(page, b)) expect(reddishOrGreen(c), c).toBe(false)
      if (screen === 'home') {
        // S1: the sidebar's count is the requests and the challenges: 2 + 1
        const nav = page.getByRole('navigation').getByRole('button', { name: /Friends/ })
        expect((await nav.textContent())!.replace(/\s+/g, '')).toContain('Friends3')
        await banner.getByRole('button', { name: 'Accept' }).click()
        await page.locator('.crumb .title', { hasText: 'maxk' }).waitFor()
        expect(await page.locator('.crumb').textContent()).toMatch(/5\+0\s*Unrated/)
        expect(await page.getByRole('alertdialog', { name: 'Challenge from maxk' }).count()).toBe(0)
        expect(await calls(page)).toContainEqual(['accept', 'c'.repeat(16)])
      }
      await page.context().close()
    }
  }, 90_000)

  it('Decline sends the answer and the banner goes', async () => {
    const page = await open('/?screen=home&state=friends-challenge')
    const banner = page.getByRole('alertdialog', { name: 'Challenge from maxk' })
    await banner.getByRole('button', { name: 'Decline' }).click()
    await banner.waitFor({ state: 'detached' })
    expect(await calls(page)).toContainEqual(['decline', 'c'.repeat(16)])
    await page.context().close()
  }, 60_000)

  it('the Challenge popover on a friend online: Play as, the ten time controls, the ratings line; sent, then waiting with Cancel', async () => {
    const page = await open('/?screen=friends')
    await page.locator('li.fli', { hasText: 'maxk' }).getByRole('button', { name: 'Challenge', exact: true }).waitFor()
    // C2: Challenge only for the friends online (maxk, benji)
    expect(await page.getByRole('button', { name: 'Challenge', exact: true }).count()).toBe(2)
    await page.locator('li.fli', { hasText: 'maxk' }).getByRole('button', { name: 'Challenge', exact: true }).click()
    const pop = page.getByRole('dialog', { name: 'Challenge maxk' })
    await pop.waitFor()
    expect(await pop.getByRole('radio', { name: 'Random' }).getAttribute('aria-checked')).toBe('true')
    const tcs = await pop.getByRole('radiogroup', { name: 'Time control' }).getByRole('radio').allTextContents()
    expect(tcs).toEqual(['1+0', '2+1', '3+0', '3+2', '5+0', '5+3', '10+0', '10+5', '15+10', '30+0'])
    await pop.getByRole('radio', { name: 'Black' }).click()
    await pop.getByRole('radio', { name: '3+2 Blitz' }).click()
    await pop.getByText(/Ratings shown in the game: you 1438, maxk 1446 \(Chess\.com blitz\)\./).waitFor()
    await pop.getByRole('button', { name: 'Send challenge' }).click()
    await pop.getByText(/Waiting for maxk to answer: a 3\+2 game\. Expires in 0:[56]\d\./).waitFor()
    expect(await calls(page)).toContainEqual(['challenge', JSON.stringify({ handle: 'maxk', tc: '3+2', colour: 'black' })])
    await pop.getByRole('button', { name: 'Cancel challenge' }).click()
    await pop.waitFor({ state: 'detached' })
    expect((await calls(page)).some(([k]) => k === 'cancel')).toBe(true)
    await page.context().close()
  }, 60_000)

  it("a friend's profile has Challenge while they are online, and none while offline", async () => {
    const page = await open('/?screen=friend&friend=maxk')
    await page.getByRole('button', { name: 'Challenge', exact: true }).waitFor()
    await page.getByRole('button', { name: 'Challenge', exact: true }).click()
    await page.getByRole('dialog', { name: 'Challenge maxk' }).waitFor()
    await page.context().close()
    const off = await open('/?screen=friend&friend=hannah_k')
    await off.getByRole('button', { name: 'Refresh' }).waitFor()
    expect(await off.getByRole('button', { name: 'Challenge', exact: true }).count()).toBe(0)
    await off.context().close()
  }, 60_000)

  it("Play's \"A friend\": the friends online to choose, the offline ones not; Send challenge with ↵", async () => {
    const page = await open('/?screen=play')
    await page.getByRole('radiogroup', { name: 'Against' }).waitFor()
    await page.getByRole('radio', { name: 'A friend' }).click()
    await page.getByRole('heading', { name: 'New game against a friend' }).waitFor()
    const friends = page.getByRole('radiogroup', { name: 'Friend' })
    // online first (most recently seen first), with each one's rating for the mode; ≈ for the Lichess-only one
    const rows = (await friends.getByRole('radio').allTextContents()).map((t) => t.replace(/\s+/g, ' ').trim())
    expect(rows).toHaveLength(2)
    expect(rows.find((r) => r.startsWith('benji'))).toMatch(/^benji Blitz ≈\d{4}$/)
    expect(rows.find((r) => r.startsWith('maxk'))).toMatch(/^maxk Blitz \d{4}$/)
    expect(await friends.locator('[aria-disabled=true]').count()).toBe(3)
    const first = rows[0].split(' ')[0]
    await page.getByText('Unrated. Saved to both your libraries, then analysed. Ratings shown: Chess.com blitz.').waitFor()
    await page.locator('body').click({ position: { x: 700, y: 400 } })
    await page.keyboard.press('Enter')
    await page.getByText(new RegExp(`Waiting for ${first}: a 5\\+0 game`)).waitFor()
    expect(await calls(page)).toContainEqual(['challenge', JSON.stringify({ handle: first, tc: '5+0', colour: 'random' })])
    await page.context().close()
  }, 60_000)

  it('the game, playing: strips with ratings and clocks, the moves, the chat below them, Offer a draw and Resign (two clicks)', async () => {
    const page = await open('/?screen=play&state=fgame')
    await page.getByRole('region', { name: 'Chat' }).waitFor()
    expect((await page.locator('.crumb').textContent())!.replace(/\s+/g, ' ').trim()).toBe('Play / maxk 10+0 Unrated')
    const timers = await page.getByRole('timer').allTextContents()
    expect(timers).toEqual(['9:12', '8:47'])
    await page.getByText('Sicilian, Najdorf, English Attack').waitFor()
    await page.getByText('B90, unrated').waitFor()
    expect(await page.getByRole('grid', { name: 'Moves' }).getByRole('gridcell').count()).toBe(12)
    expect(await page.getByText('maxk (1446)').count()).toBe(1)
    const chat = page.getByRole('region', { name: 'Chat' })
    expect(await chat.getByRole('button', { name: /^Chat/ }).getAttribute('aria-expanded')).toBe('true')
    expect((await chat.getByRole('log').innerText()).split('\n')).toEqual(['maxk good luck', 'You you too', 'maxk that knight is annoying'])
    const input = chat.getByRole('textbox', { name: 'Message maxk' })
    expect(await input.getAttribute('maxlength')).toBe('200')
    await input.fill('nice try')
    await input.press('Enter')
    await chat.getByText('nice try').waitFor()
    await chat.getByRole('button', { name: 'Mute chat for this game' }).click()
    await chat.getByRole('button', { name: 'Unmute chat for this game' }).waitFor()
    await page.getByText('Unrated. Saved to both your libraries when it ends.').waitFor()
    await page.getByRole('button', { name: 'Resign' }).click()
    expect((await calls(page)).filter(([k, v]) => k === 'game' && v.includes('resign'))).toHaveLength(0)
    await page.getByRole('button', { name: 'Confirm resign' }).click()
    await page.getByText('You lost').waitFor()
    await page.getByText('You resigned').waitFor()
    const sent = (await calls(page)).filter(([k]) => k === 'game').map(([, v]) => JSON.parse(v).t)
    expect(sent).toEqual(['chat', 'mute', 'resign'])
    await page.context().close()
  }, 60_000)

  it('the game, a move on the board goes to the server with its ply', async () => {
    const page = await open('/?screen=play&state=fgame')
    await page.getByRole('region', { name: 'Chat' }).waitFor()
    const box = (await page.getByRole('region', { name: 'Board' }).locator('cg-board').boundingBox())!
    const sq = box.width / 8
    const at = (s: string) => ({ x: box.x + (s.charCodeAt(0) - 97 + 0.5) * sq, y: box.y + (8 - Number(s[1]) + 0.5) * sq })
    for (const s of ['d4', 'b5']) await page.mouse.click(at(s).x, at(s).y)
    await page.waitForFunction(() => ((window as unknown as { __zzFriendsCalls?: [string, string][] }).__zzFriendsCalls ?? []).some(([k]) => k === 'game'))
    expect((await calls(page)).find(([k]) => k === 'game')![1]).toBe(JSON.stringify({ t: 'move', uci: 'd4b5', ply: 12 }))
    await page.context().close()
  }, 60_000)

  it('the game, draw offered: Accept before Decline; Decline answers', async () => {
    const page = await open('/?screen=play&state=fgame-draw')
    const alert = page.getByRole('alert').filter({ hasText: 'offers a draw' })
    await alert.waitFor()
    expect((await alert.textContent())!.replace(/\s+/g, ' ')).toContain('maxk offers a draw')
    expect((await alert.getByRole('button').allTextContents()).map((t) => t.trim())).toEqual(['Accept', 'Decline'])
    await alert.getByRole('button', { name: 'Decline' }).click()
    await alert.waitFor({ state: 'detached' })
    expect((await calls(page)).map(([, v]) => v)).toContain(JSON.stringify({ t: 'draw_decline' }))
    await page.context().close()
  }, 60_000)

  it('the game, opponent left: "Disconnected", the claim after the countdown (P1), then the win', async () => {
    const page = await open('/?screen=play&state=fgame-left', 'dev', { width: 1440, height: 940 }, undefined, true)
    const alert = page.getByRole('alert').filter({ hasText: 'left the game' })
    await alert.waitFor()
    await page.getByText('Disconnected').waitFor()
    expect((await alert.textContent())!.replace(/\s+/g, ' ')).toMatch(/In 0:2\d you can claim the win or call it a draw\. Or keep playing on: they may come back\./)
    expect(await alert.getByRole('button', { name: 'Claim the win' }).isDisabled()).toBe(true)
    expect(await alert.getByRole('button', { name: 'Call it a draw' }).isDisabled()).toBe(true)
    await page.clock.fastForward(25_000)
    await alert.getByRole('button', { name: 'Claim the win' }).click()
    await page.getByText('You won').waitFor()
    await page.getByText('maxk left the game').waitFor()
    await page.context().close()
  }, 60_000)

  it('the game, over: You won, maxk resigned; Review the game and Rematch; saved, analysing at depth 14', async () => {
    const page = await open('/?screen=play&state=fgame-over')
    await page.getByText('You won').waitFor()
    await page.getByText('maxk resigned').waitFor()
    await page.getByText('Saved to both your libraries. Analysing at depth 14.').waitFor()
    const review = page.getByRole('button', { name: 'Review the game' })
    expect(await review.getAttribute('class')).toContain('primary')
    await page.getByRole('button', { name: 'Rematch' }).click()
    await page.getByRole('button', { name: 'Rematch offered' }).waitFor()
    await review.click()
    await page.getByRole('tab', { name: 'Moves' }).waitFor()
    await page.context().close()
  }, 60_000)

  it('chat: expanded by default, collapsible; collapsed, an unread count and the last line (H4)', async () => {
    const page = await open('/?screen=play&state=fgame-collapsed')
    const chat = page.getByRole('region', { name: 'Chat' })
    const toggle = chat.getByRole('button', { name: /^Chat/ })
    await toggle.waitFor()
    expect(await toggle.getAttribute('aria-expanded')).toBe('true')
    await toggle.click()
    expect(await toggle.getAttribute('aria-expanded')).toBe('false')
    expect(await chat.getByRole('log').count()).toBe(0)
    await chat.getByLabel('1 unread').waitFor()
    await chat.getByText('maxk: nice move').waitFor()
    await toggle.click()
    expect(await chat.getByLabel('1 unread').count()).toBe(0)
    await chat.getByRole('log').getByText('nice move').waitFor()
    await page.context().close()
  }, 60_000)

  it('Check now at most once every 30 s (Z4): pressed, it waits and says when; then it can be pressed again', async () => {
    const page = await open('/?screen=friends&state=friends-cc-waiting', 'dev', { width: 1440, height: 940 }, undefined, true)
    const btn = page.getByRole('button', { name: 'Check now' })
    await btn.waitFor()
    await btn.click()
    const again = page.getByRole('button', { name: /Check again in 0:(30|29)/ })
    await again.waitFor()
    expect(await again.isDisabled()).toBe(true)
    await page.clock.fastForward(31_000)
    await page.getByRole('button', { name: 'Check now' }).waitFor()
    expect((await calls(page)).filter(([k]) => k === 'verify')).toHaveLength(1)
    await page.context().close()
  }, 60_000)
})
