/**
 * BETA-6's layout checks over every case in beta6Specs.ts, in the harness browser (Chromium, or WebKit with
 * ZUGZWANG_HARNESS_BROWSER=webkit), at 1280 x 720 and 1440 x 900, with the longest names (?names=long):
 * long names (overlapping text, a cut name without "…" or tooltip), overlays topmost at centre and corners, and
 * for the banner (S6) the content's boxes with and without it (nothing moves) and, on Play's game screens, the
 * banner's box against the board's and the player strips' (the clocks). Shots and results go to
 * review/scratch/ui/beta6/<browser>/.
 *
 *   cd desktop && node harness/beta6Checks.ts
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_PORT=5233 node harness/beta6Checks.ts
 *   ZUGZWANG_B6_ONLY=<substring> limits the cases; ZUGZWANG_B6_NOSHOTS=1 takes no shots.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Browser, Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { ALL, SIZES, STORAGE, covered, type Case } from './beta6Specs.ts'
import { names, topmost } from './overlayCheck.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const out = resolve(repo, 'review', 'scratch', 'ui', 'beta6', harnessBrowserName)
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5232)
const only = process.env.ZUGZWANG_B6_ONLY ?? ''
const shots = process.env.ZUGZWANG_B6_NOSHOTS !== '1'

export async function settle(page: Page, maxMs = 6000): Promise<void> {
  const t0 = Date.now()
  let last = -1
  let stableSince = Date.now()
  while (Date.now() - t0 < maxMs) {
    const n = await page.evaluate(() => (window as unknown as { __harness?: { requestLog: unknown[] } }).__harness?.requestLog.length ?? 0)
    if (n !== last) {
      last = n
      stableSince = Date.now()
    } else if (Date.now() - stableSince > 600) break
    await page.waitForTimeout(100)
  }
  await page.evaluate(() => document.fonts.ready)
}

export async function openCase(browser: Browser, base: string, c: Case, size: { width: number; height: number }, path = c.path): Promise<Page> {
  const ctx = await browser.newContext({ viewport: size })
  await ctx.addInitScript((e: [string, string][]) => e.forEach(([k, v]) => localStorage.setItem(k, v)), Object.entries(STORAGE))
  const page = await ctx.newPage()
  await page.goto(base + path + (path.includes('?') ? '&' : '?') + 'names=long')
  await settle(page)
  if (c.prepare) {
    await c.prepare(page)
    await settle(page, 3000)
  }
  return page
}

/** every element in the content column but the banners: its box, by its path */
export async function contentBoxes(page: Page): Promise<Record<string, number[]>> {
  return page.evaluate(() => {
    const root = document.querySelector('main.content')
    const outBoxes: Record<string, number[]> = {}
    if (!root) return outBoxes
    const walk = (el: Element, path: string) => {
      // indexed among the siblings that are not the banners, so a path names the same element with and without them
      ;[...el.children].filter((ch) => !ch.classList.contains('banners')).forEach((ch, i) => {
        const p = path + '/' + ch.tagName.toLowerCase() + i
        const r = ch.getBoundingClientRect()
        if (r.width || r.height) outBoxes[p] = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]
        walk(ch, p)
      })
    }
    walk(root, '')
    return outBoxes
  })
}

/** on a game screen: the banners' box against the board and the player strips (with the clocks) */
export async function bannerCovers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const ban = document.querySelector('.banners')
    if (!ban) return ['no banner']
    const b = ban.getBoundingClientRect()
    const hits: string[] = []
    for (const el of document.querySelectorAll('.board-col .col > *')) {
      const r = el.getBoundingClientRect()
      if (!r.width || !r.height) continue
      const w = Math.min(b.right, r.right) - Math.max(b.left, r.left)
      const h = Math.min(b.bottom, r.bottom) - Math.max(b.top, r.top)
      if (w > 0 && h > 0) hits.push(`the banner covers ${el.className.split(' ')[0] || el.tagName} by ${Math.round(w)} x ${Math.round(h)} px`)
    }
    return hits
  })
}

export interface CaseResult {
  case: string
  size: string
  names?: Awaited<ReturnType<typeof names>>
  overlays?: Awaited<ReturnType<typeof topmost>>[]
  moved?: { compared: number; moved: string[] }
  covers?: string[]
  order?: string
  /** where a popover placed by use:floating went: below, above or inside */
  side?: string
  /** clicks that met something on top of their target (dispatched instead) */
  covered?: string[]
  failures: string[]
}

export async function runCase(browser: Browser, base: string, c: Case, size: { width: number; height: number }, shotPath?: string): Promise<CaseResult> {
  const before = covered.length
  const page = await openCase(browser, base, c, size)
  const r: CaseResult = { case: c.name, size: `${size.width}x${size.height}`, failures: [] }
  if (covered.length > before) r.covered = covered.slice(before)
  const side = await page.evaluate(() => (document.querySelector('.popat') as HTMLElement | null)?.dataset.side ?? null)
  if (side) r.side = side
  if (c.names !== false) {
    r.names = await names(page)
    r.failures.push(...r.names.failures)
  }
  if (c.overlays) {
    r.overlays = []
    for (const sel of c.overlays) {
      const t = await topmost(page, sel)
      r.overlays.push(t)
      r.failures.push(...t.failures)
    }
  }
  if (c.name.includes('+banner')) {
    // S6: Accept before Decline, in the DOM and on screen
    r.order = await page.evaluate(() => {
      const bs = [...document.querySelectorAll('.banners .banner')][0]?.querySelectorAll('button')
      if (!bs || bs.length < 2) return 'no buttons'
      const [a, d] = [bs[0], bs[1]]
      const ok = a.textContent?.trim() === 'Accept' && d.textContent?.trim() === 'Decline' && a.getBoundingClientRect().left < d.getBoundingClientRect().left
      return ok ? 'Accept, Decline' : `${a.textContent?.trim()}, ${d.textContent?.trim()}`
    })
    if (r.order !== 'Accept, Decline') r.failures.push('buttons: ' + r.order)
    if (await page.locator('.board-col').count()) {
      r.covers = await bannerCovers(page)
      r.failures.push(...r.covers)
    }
    const withB = await contentBoxes(page)
    const plain = await openCase(browser, base, { ...c, path: c.path.replace(/&challenge=\d/, '') }, size)
    const without = await contentBoxes(plain)
    await plain.context().close()
    const keys = Object.keys(without).filter((k) => k in withB)
    const moved = keys.filter((k) => withB[k].join() !== without[k].join()).map((k) => `${k}: ${without[k].join(',')} -> ${withB[k].join(',')}`)
    r.moved = { compared: keys.length, moved }
    if (!keys.length) r.failures.push('no content boxes to compare')
    if (moved.length) r.failures.push(`${moved.length} of ${keys.length} content boxes moved with the banner, e.g. ${moved[0]}`)
  }
  if (shotPath) {
    mkdirSync(dirname(shotPath), { recursive: true })
    await page.screenshot({ path: shotPath })
  }
  await page.context().close()
  return r
}

export const slug = (s: string) => s.replace(/[^a-z0-9+-]+/gi, '_').replace(/^_|_$/g, '').toLowerCase()

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port }, logLevel: 'silent' })
  await server.listen()
  const browser = await harnessBrowser.launch({ headless: true })
  const base = `http://localhost:${port}`
  const results: CaseResult[] = []
  for (const size of SIZES) {
    for (const c of ALL.filter((x) => !only || x.name.includes(only))) {
      const shot = shots ? resolve(out, `${size.width}x${size.height}`, slug(c.name) + '.png') : undefined
      let r: CaseResult
      try {
        r = await runCase(browser, base, c, size, shot)
      } catch (e) {
        r = { case: c.name, size: `${size.width}x${size.height}`, failures: ['error: ' + String((e as Error).message ?? e).split('\n')[0]] }
      }
      results.push(r)
      console.log(`${r.failures.length ? 'FAIL' : 'PASS'}  ${r.size}  ${r.case}${r.side ? ` [popover ${r.side}]` : ''}${r.covered ? ` [covered: ${r.covered.join('; ')}]` : ''}${r.names ? `  (${r.names.texts} texts, ${r.names.names} names, ${r.names.cut} cut)` : ''}${r.failures.length ? '\n      ' + r.failures.slice(0, 12).join('\n      ') + (r.failures.length > 12 ? `\n      … ${r.failures.length - 12} more` : '') : ''}`)
    }
  }
  mkdirSync(out, { recursive: true })
  writeFileSync(resolve(out, 'checks.json'), JSON.stringify(results, null, 1))
  const failed = results.filter((r) => r.failures.length).length
  console.log(`${harnessBrowserName}: ${results.length - failed} of ${results.length} cases pass, ${failed} fail`)
  await browser.close()
  await server.close()
}
