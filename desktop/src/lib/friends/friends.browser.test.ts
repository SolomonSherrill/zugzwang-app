/**
 * The Friends screens, one test per screen (FRIENDS-1 E), in the browser harness over the fake
 * sidecar (harness/friendsHarness.ts, synthetic data): sign up (the two boxes required, a taken
 * handle), the recovery code, the friends list (requests with Accept before Decline, online first,
 * no Challenge buttons), a friend's profile (every panel; As White / Against 1.e4 / Against 1.d4; the
 * ≈ estimate with its source; FRIENDS-1B D: the rating sparklines, your colour's square on "Your games
 * together", the chevron on recent games and the row opening Analyse), Settings → Friends (the switches,
 * the code hidden until Show, Delete with a confirmation), the destructive buttons red and Accept / Decline
 * never red or green (FRIENDS.md ruling S4, 2026-11-21), the sidebar's request count, and Friends in a
 * beta build too (ruling L9, 2026-11-22).
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
async function open(path: string, build: 'dev' | 'beta' = 'dev', size = { width: 1440, height: 940 }, savePath?: string | null): Promise<Page> {
  const ctx = await browser!.newContext({ viewport: size })
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

describe.skipIf(!ready)(`Friends screens (FRIENDS-1) [${harnessBrowserName}]`, () => {
  beforeAll(async () => {
    base.dev = await harness(false)
    base.beta = await harness(true)
    browser = await harnessBrowser.launch({ headless: true })
  }, 90_000)
  afterAll(async () => {
    await browser?.close()
    for (const s of servers) await s.close()
  })

  it('sign up: Create account needs an available handle and both boxes', async () => {
    const page = await open('/?screen=friends&state=friends-signup')
    const create = page.getByRole('button', { name: 'Create account' })
    await create.waitFor()
    expect(await create.isDisabled()).toBe(true)
    await page.locator('#hdl').fill('maxk')
    await page.getByText('Taken').waitFor()
    await page.locator('#hdl').fill('ab')
    await page.getByText('Too short: at least 3 characters.').waitFor()
    await page.locator('#hdl').fill('pawn_one')
    await page.getByText('Available').waitFor()
    expect(await create.isDisabled()).toBe(true)
    await page.getByLabel('I’m 13 or older').check()
    expect(await create.isDisabled()).toBe(true)
    await page.locator('label.cb').nth(1).locator('input').check()
    expect(await create.isDisabled()).toBe(false)
    expect(await page.getByText('No email and no password').count()).toBe(1)
    await page.context().close()
  }, 60_000)

  it('the recovery code: shown once after sign-up, Continue needs the box', async () => {
    const page = await open('/?screen=friends&state=friends-signup')
    await page.locator('#hdl').fill('pawn_one')
    await page.getByText('Available').waitFor()
    await page.getByLabel('I’m 13 or older').check()
    await page.locator('label.cb').nth(1).locator('input').check()
    await page.getByRole('button', { name: 'Create account' }).click()
    const code = page.getByLabel('Recovery code')
    await code.waitFor()
    expect((await code.textContent())?.trim()).toMatch(/^([0-9A-Z]{4}-){8}[0-9A-Z]{4}$/)
    const cont = page.getByRole('button', { name: 'Continue' })
    expect(await cont.isDisabled()).toBe(true)
    await page.getByLabel("I've saved it somewhere safe").check()
    await cont.click()
    await page.getByRole('heading', { name: /Friends/ }).first().waitFor()
    await page.context().close()
  }, 60_000)

  async function toRecovery(savePath: string | null): Promise<Page> {
    const page = await open('/?screen=friends&state=friends-signup', 'dev', { width: 1440, height: 940 }, savePath)
    await page.locator('#hdl').fill('pawn_one')
    await page.getByText('Available').waitFor()
    await page.getByLabel('I’m 13 or older').check()
    await page.locator('label.cb').nth(1).locator('input').check()
    await page.getByRole('button', { name: 'Create account' }).click()
    await page.getByLabel('Recovery code').waitFor()
    return page
  }

  it('"Save as a file" (BETA-5 B): the save dialog, named zugzwang-recovery-code.txt; the sidecar writes; "Saved to <path>"', async () => {
    const page = await toRecovery('/home/demo/Documents/zugzwang-recovery-code.txt')
    await page.getByRole('button', { name: 'Save as a file' }).click()
    await page.getByText('Saved to /home/demo/Documents/zugzwang-recovery-code.txt').waitFor()
    const dialog = (await page.evaluate(() => (window as unknown as { __zzDialog: [string, { options: { defaultPath: string } }][] }).__zzDialog))
    expect(dialog.map(([c]) => c)).toEqual(['plugin:dialog|save'])
    expect(dialog[0][1].options.defaultPath).toBe('zugzwang-recovery-code.txt')
    // the box stays manual
    expect(await page.getByLabel("I've saved it somewhere safe").isChecked()).toBe(false)
    expect(await page.getByRole('button', { name: 'Continue' }).isDisabled()).toBe(true)
    await page.context().close()
  }, 60_000)

  it('"Save as a file": cancelling the dialog does nothing; a failed write says what failed', async () => {
    const cancel = await toRecovery(null)
    await cancel.getByRole('button', { name: 'Save as a file' }).click()
    await cancel.waitForTimeout(300)
    expect(await cancel.locator('p.note').count()).toBe(0)
    await cancel.context().close()
    const fail = await toRecovery('/readonly/zugzwang-recovery-code.txt')
    await fail.getByRole('button', { name: 'Save as a file' }).click()
    const alert = fail.getByRole('alert')
    await alert.waitFor()
    expect(await alert.textContent()).toBe('The code could not be saved to /readonly/zugzwang-recovery-code.txt: Permission denied.')
    await fail.context().close()
  }, 60_000)

  it('Copy puts the code on the clipboard (in this browser; the Tauri webview is the owner\'s step)', async () => {
    const page = await toRecovery(null)
    if (harnessBrowserName === 'chromium') await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    const code = (await page.getByLabel('Recovery code').textContent())?.trim()
    await page.getByRole('button', { name: 'Copy' }).click()
    await page.getByRole('button', { name: 'Copied' }).waitFor()
    if (harnessBrowserName === 'chromium') expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(code)
    await page.context().close()
  }, 60_000)

  it('Chess.com waits for Chess.com (BETA-5 K3): Waiting, Check now, Cancel', async () => {
    const page = await open('/?screen=friends&state=friends-cc-waiting')
    await page.getByText('Waiting for Chess.com').waitFor()
    const panel = page.locator('section.panel', { hasText: 'Your linked accounts' })
    expect(await panel.getByText("Chess.com's public profile can take up to 12 hours to update. Leave the code in your Location; Zugzwang checks every 15 minutes while it's open.", { exact: true }).count()).toBe(1)
    expect(await panel.getByText('ZZ-7K4Q2M9D').count()).toBe(1)
    expect(await panel.textContent()).not.toMatch(/a minute/)
    const buttons = (await panel.locator('.row').first().getByRole('button').allTextContents()).map((s) => s.trim())
    expect(buttons).toEqual(['Check now', 'Cancel'])
    await panel.getByRole('button', { name: 'Check now' }).click()
    await page.getByText('Waiting for Chess.com').waitFor()
    await panel.getByRole('button', { name: 'Cancel' }).click()
    await panel.getByLabel('Chess.com username').waitFor()
    // Verify, then Check: the harness's Chess.com has not shown the code, so the link waits
    await panel.getByRole('button', { name: 'Verify' }).click()
    await panel.getByRole('button', { name: 'Check', exact: true }).click()
    await page.getByText('Waiting for Chess.com').waitFor()
    await page.context().close()
  }, 60_000)

  it('Chess.com: an expired code says so and offers a new one', async () => {
    const page = await open('/?screen=friends&state=friends-cc-expired')
    const panel = page.locator('section.panel', { hasText: 'Your linked accounts' })
    await panel.getByText('The code expired').waitFor()
    expect(await panel.getByText(/did not show it within 24 hours, so Zugzwang stopped checking/).count()).toBe(1)
    await panel.getByRole('button', { name: 'Start again' }).click()
    await panel.getByText(/in your Chess.com profile's Location, then check/).waitFor()
    await page.context().close()
  }, 60_000)

  it('Remove friend and Block ask first (BETA-5 S5): the confirming button red, Keep quiet and calling nothing', async () => {
    const page = await open('/?screen=friend&friend=maxk', 'dev', { width: 1440, height: 1240 })
    const more = page.getByRole('button', { name: /More: Remove friend/ })
    const red = (b: Element) => [getComputedStyle(b).color, getComputedStyle(b).borderTopColor].join(' ')
    const calls = () => page.evaluate(() => (window as unknown as { __zzFriendsCalls?: unknown[] }).__zzFriendsCalls ?? [])
    await more.click()
    await page.getByRole('menuitem', { name: 'Remove friend' }).click()
    await page.getByText('Remove maxk as a friend?', { exact: true }).waitFor()
    const ask = page.getByRole('alertdialog')
    expect((await ask.getByRole('button').allTextContents()).map((s) => s.trim())).toEqual(['Remove', 'Keep'])
    expect(await ask.getByRole('button', { name: 'Remove' }).evaluate(red)).toBe('rgb(248, 113, 113) rgb(74, 42, 45)')
    expect(await ask.getByRole('button', { name: 'Keep' }).evaluate((b) => getComputedStyle(b).color)).not.toBe('rgb(248, 113, 113)')
    await ask.getByRole('button', { name: 'Keep' }).click()
    expect(await page.getByRole('alertdialog').count()).toBe(0)
    expect(await calls()).toEqual([])
    await more.click()
    await page.getByRole('menuitem', { name: 'Block' }).click()
    await page.getByText('Block maxk?', { exact: true }).waitFor()
    expect((await page.getByRole('alertdialog').getByRole('button').allTextContents()).map((s) => s.trim())).toEqual(['Block', 'Keep'])
    expect(await page.getByRole('alertdialog').getByRole('button', { name: 'Block' }).evaluate(red)).toBe('rgb(248, 113, 113) rgb(74, 42, 45)')
    expect(await calls()).toEqual([])
    await page.getByRole('alertdialog').getByRole('button', { name: 'Block' }).click()
    await page.getByRole('heading', { name: /Requests/ }).waitFor()
    expect(await calls()).toEqual([['block', 'maxk']])
    await page.context().close()
  }, 60_000)

  it('Remove friend, confirmed, removes and goes back to the list', async () => {
    const page = await open('/?screen=friend&friend=maxk', 'dev', { width: 1440, height: 1240 })
    await page.getByRole('button', { name: /More: Remove friend/ }).click()
    await page.getByRole('menuitem', { name: 'Remove friend' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Remove' }).click()
    await page.getByRole('heading', { name: /Requests/ }).waitFor()
    expect(await page.evaluate(() => (window as unknown as { __zzFriendsCalls?: unknown[] }).__zzFriendsCalls)).toEqual([['remove', 'maxk']])
    await page.context().close()
  }, 60_000)

  it('the friends list: requests (Accept before Decline), online first, no Challenge buttons', async () => {
    const page = await open('/?screen=friends')
    await page.getByRole('heading', { name: /Requests/ }).waitFor()
    const first = page.locator('li.req').first()
    const labels = await first.getByRole('button').allTextContents()
    expect(labels.map((s) => s.trim())).toEqual(['Accept', 'Decline'])
    expect(await page.locator('li.req').count()).toBe(3)
    const names = await page.locator('button.row .names .strong').allTextContents()
    expect(names.slice(0, 2).sort()).toEqual(['benji', 'maxk'])
    expect(await page.getByRole('button', { name: 'Challenge' }).count()).toBe(0)
    expect(await page.getByText('≈').count()).toBeGreaterThan(0)
    expect(await page.locator('[title*="ChessGoals"]').count()).toBeGreaterThan(0)
    // Accept and Decline (and every other button here) are never red or green (ruling S4)
    const colours = await page.locator('main button').evaluateAll((bs) => bs.map((b) => getComputedStyle(b).backgroundColor + getComputedStyle(b).color))
    expect(colours.join(' ')).not.toMatch(/rgb\(74, 222, 128\)|rgb\(248, 113, 113\)/)
    await page.context().close()
  }, 60_000)

  it("a friend's profile: every panel, the scouting views, Analyse on request", async () => {
    const page = await open('/?screen=friend&friend=maxk', 'dev', { width: 1440, height: 1240 })
    for (const h of ['Your games together', 'Scouting', 'Results by time control', 'How their games end', "maxk's recent games"]) {
      await page.getByRole('heading', { name: h }).waitFor()
    }
    expect(await page.getByText('Blitz on Chess.com').count()).toBe(1)
    for (const t of ['As White', 'Against 1.e4', 'Against 1.d4']) {
      await page.getByRole('tab', { name: t }).click()
      expect(await page.getByRole('tab', { name: t }).getAttribute('aria-selected')).toBe('true')
    }
    expect(await page.getByText('No engine involved.').count()).toBe(1)
    expect(await page.getByRole('button', { name: 'Challenge' }).count()).toBe(0)
    await page.getByRole('button', { name: 'Load games older than 12 months' }).waitFor()
    // FRIENDS-1B D: a sparkline in each rating cell with a series, your colour on each game together,
    // a chevron on each recent game
    expect(await page.locator('.strip svg.spark polyline').count()).toBeGreaterThan(0)
    const pts = await page.locator('.strip svg.spark polyline').first().getAttribute('points')
    expect((pts ?? '').split(' ').length).toBeGreaterThanOrEqual(2)
    const squares = page.getByRole('img', { name: /^You played (White|Black)$/ })
    const together = await page.locator('.hrow:not(.colhead)').count()
    expect(together).toBeGreaterThan(0)
    expect(await squares.count()).toBe(together)
    const recentRows = await page.locator('.rrow:not(.colhead)').count()
    expect(await page.locator('.rrow:not(.colhead) svg.chev').count()).toBe(recentRows)
    expect(await page.locator('.rrow .site').count()).toBe(0)
    // the menu's Remove friend and Block are red (ruling S4)
    await page.getByRole('button', { name: /More: Remove friend/ }).click()
    for (const name of ['Remove friend', 'Block']) {
      expect(await page.getByRole('menuitem', { name }).evaluate((b) => getComputedStyle(b).color)).toBe('rgb(248, 113, 113)')
    }
    await page.getByRole('button', { name: /More: Remove friend/ }).click()
    const row = page.locator('.rrow').nth(1)
    await row.hover()
    await row.getByRole('button', { name: 'Analyse' }).click()
    await page.getByRole('region', { name: 'Board' }).waitFor()
    await page.context().close()
  }, 60_000)

  it("a recent game's row opens Analyse, as its button does", async () => {
    const page = await open('/?screen=friend&friend=maxk', 'dev', { width: 1440, height: 1240 })
    const row = page.locator('.rrow:not(.colhead)').nth(2)
    await row.waitFor()
    await row.locator('svg.chev').click()
    await page.getByRole('region', { name: 'Board' }).waitFor()
    await page.context().close()
  }, 60_000)

  it('a Lichess-only friend shows the ≈ Chess.com estimate with its source', async () => {
    const page = await open('/?screen=friend&friend=benji', 'dev', { width: 1440, height: 1240 })
    const est = page.locator('.strip [title*="ChessGoals"]').first()
    await est.waitFor()
    expect(await est.textContent()).toMatch(/^≈\d+ on Chess\.com$/)
    await page.context().close()
  }, 60_000)

  it('Settings → Friends: the code hidden until Show, the switches, Delete with a confirmation', async () => {
    const page = await open('/?screen=settings', 'dev', { width: 1440, height: 1240 })
    await page.getByRole('heading', { name: 'Friends' }).waitFor()
    expect(await page.getByLabel('Hidden').count()).toBe(1)
    await page.getByRole('button', { name: 'Show', exact: true }).click()
    await page.getByText(/^([0-9A-Z]{4}-){8}[0-9A-Z]{4}$/).waitFor()
    for (const s of ['Share the games you play in Zugzwang', 'Appear offline', 'Chat in friend games']) {
      expect(await page.getByRole('switch', { name: new RegExp(s) }).count()).toBe(1)
    }
    expect(await page.getByRole('switch', { name: /Chat in friend games/ }).getAttribute('aria-checked')).toBe('true')
    await page.getByRole('button', { name: 'Privacy policy' }).click()
    await page.getByRole('dialog', { name: 'Privacy policy' }).getByText(/Version 1, effective the day Zugzwang 0.1.0-beta.5 is published/).waitFor()
    await page.getByRole('button', { name: 'Close' }).click()
    // ruling S4: Delete account is red (--loss text on the --danger-border outline), and so is its confirmation
    const red = (b: Element) => [getComputedStyle(b).color, getComputedStyle(b).borderTopColor].join(' ')
    const del = page.getByRole('button', { name: 'Delete account' })
    expect(await del.evaluate(red)).toBe('rgb(248, 113, 113) rgb(74, 42, 45)')
    await del.click()
    const it2 = page.getByRole('button', { name: 'Delete it' })
    await it2.waitFor()
    expect(await it2.evaluate(red)).toBe('rgb(248, 113, 113) rgb(74, 42, 45)')
    expect(await page.getByRole('button', { name: 'Keep it' }).evaluate((b) => getComputedStyle(b).color)).not.toBe('rgb(248, 113, 113)')
    await page.getByRole('button', { name: 'Keep it' }).click()
    await page.context().close()
  }, 60_000)

  it('the sidebar: Friends above Settings with the request count; in a beta build too (L9)', async () => {
    const page = await open('/?screen=home')
    const item = page.locator('nav button.item', { hasText: 'Friends' })
    await item.locator('.count').waitFor()
    expect((await item.locator('.count').textContent())?.trim()).toBe('2')
    const order = await page.locator('nav button.item').allTextContents()
    const i = order.findIndex((t) => t.includes('Friends'))
    expect(order[i + 1]).toContain('Settings')
    await page.context().close()
    const beta = await open('/?screen=home', 'beta')
    await beta.locator('nav').waitFor()
    await beta.waitForTimeout(500)
    expect(await beta.locator('nav button.item', { hasText: 'Friends' }).count()).toBe(1)
    await beta.goto(base.beta + '/?screen=settings')
    await beta.getByRole('heading', { name: 'Accounts' }).waitFor()
    await beta.getByRole('heading', { name: 'Friends' }).waitFor()
    await beta.context().close()
  }, 60_000)
})
