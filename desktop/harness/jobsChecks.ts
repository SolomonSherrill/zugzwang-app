/**
 * COACH-2 D (ruling CB1): DOM checks that the background jobs show where the ruling puts them, in the harness browser
 * (Chromium, or WebKit with ZUGZWANG_HARNESS_BROWSER=webkit), at 1280 x 720 (the icon rail) and 1440 x 900, with
 * ?jobs=all (harness/jobsHarness.ts): the activity line is the sidebar's last element, inside it and the window, one
 * entry per job, the sidebar not scrolling; a click on the analysis opens its review; the Review header's progress on
 * both tabs, inside the header and clear of the breadcrumb and the actions, centred on the header's middle; the Games
 * row of the game being re-analysed says so. Writes review/scratch/ui/coach2/bg/<browser>/jobs_checks.out.
 *
 *   cd desktop && node harness/jobsChecks.ts
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { SIZES } from './beta6Specs.ts'
import { openCase } from './beta6Checks.ts'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', '..', 'review', 'scratch', 'ui', 'coach2', 'bg', harnessBrowserName)
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5250)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port }, logLevel: 'silent' })
await server.listen()
const browser = await harnessBrowser.launch({ headless: true })
const base = `http://localhost:${port}`
const lines: string[] = []
let fails = 0
const check = (ok: boolean, what: string) => {
  lines.push(`${ok ? 'PASS' : 'FAIL'}  ${what}`)
  if (!ok) fails++
}

type Box = { l: number; t: number; r: number; b: number }
const box = (page: Page, sel: string) =>
  page.evaluate((s) => {
    const el = document.querySelector(s)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom) }
  }, sel) as Promise<Box | null>
const inside = (a: Box, b: Box) => a.l >= b.l && a.r <= b.r && a.t >= b.t && a.b <= b.b
const meets = (a: Box, b: Box) => Math.min(a.r, b.r) - Math.max(a.l, b.l) > 0 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 0

for (const size of SIZES) {
  const sz = `${size.width}x${size.height}`
  // the activity line
  const home = await openCase(browser, base, { name: 'home+jobs', path: '/?screen=home&jobs=all' }, size)
  const act = await box(home, '[data-testid=activity]')
  const nav = await box(home, 'nav.sidebar')
  check(!!act && !!nav, `${sz} home: the activity line is drawn`)
  if (act && nav) {
    check(inside(act, nav), `${sz} home: inside the sidebar (activity ${JSON.stringify(act)}, sidebar ${JSON.stringify(nav)})`)
    check(act.b <= size.height, `${sz} home: inside the window (bottom ${act.b} of ${size.height})`)
  }
  const info = await home.evaluate(() => {
    const n = document.querySelector('nav.sidebar') as HTMLElement
    const a = document.querySelector('[data-testid=activity]') as HTMLElement
    const jobs = [...a.querySelectorAll('button.job')].map((b) => (b.getAttribute('aria-label') ?? (b.querySelector('.text') as HTMLElement)?.textContent ?? '').trim())
    const cut = [...a.querySelectorAll('.text')].filter((t) => (t as HTMLElement).scrollWidth > (t as HTMLElement).clientWidth).map((t) => ({ text: t.textContent, title: (t.closest('button') as HTMLElement).title }))
    return { last: n.lastElementChild === a, scrolls: n.scrollHeight > n.clientHeight + 1, jobs, cut }
  })
  check(info.last, `${sz} home: the sidebar's last element`)
  check(!info.scrolls, `${sz} home: the sidebar does not scroll`)
  check(
    JSON.stringify(info.jobs) ===
      JSON.stringify(['Analysing at depth 24: 38 of 90 moves', 'Syncing: analysing 4 of 10 games', 'Downloading puzzles: 120 of 310 MB', 'The coach is reading your games: 120 of 412']),
    `${sz} home: the four jobs, most specific first: ${JSON.stringify(info.jobs)}`,
  )
  check(info.cut.every((c) => c.title === c.text), `${sz} home: a cut job line has its whole text as title (${info.cut.length} cut)`)
  await home.locator('[data-testid=activity] button.job').first().click()
  await home.waitForTimeout(600)
  check((await home.locator('[data-testid=review-analysing]').count()) === 1, `${sz} home: a click on the analysis opens its review`)
  await home.context().close()

  // the Review header, both tabs
  for (const tab of ['Report', 'Moves']) {
    const page = await openCase(browser, base, { name: 'review+jobs', path: '/?screen=review&game=main&jobs=all' }, size)
    if (tab === 'Moves') {
      await page.getByRole('tab', { name: 'Moves' }).click()
      await page.waitForTimeout(300)
    }
    const pr = await box(page, '[data-testid=review-analysing]')
    const hd = await box(page, '.review > header')
    const cr = await box(page, '.review > header .crumb')
    const ac = await box(page, '.review > header .actions')
    check(!!pr, `${sz} review, ${tab}: the header shows the analysis`)
    if (pr && hd && cr && ac) {
      check(inside(pr, hd), `${sz} review, ${tab}: inside the header`)
      check(!meets(pr, cr) && !meets(pr, ac), `${sz} review, ${tab}: clear of the breadcrumb and the actions (gap to the actions ${ac.l - pr.r} px)`)
      const mid = (pr.t + pr.b) / 2 - (hd.t + hd.b - 1) / 2
      check(Math.abs(mid) <= 2, `${sz} review, ${tab}: centred on the header's middle (off by ${mid.toFixed(1)} px)`)
    }
    const text = await page.locator('[data-testid=review-analysing] .bgt').textContent()
    check(text === 'Analysing at depth 24: 38 of 90 moves', `${sz} review, ${tab}: "${text}"`)
    await page.context().close()
  }

  // the Games row
  const games = await openCase(browser, base, { name: 'games+jobs', path: '/?screen=games&jobs=all' }, size)
  const notes = await games.evaluate(() =>
    [...document.querySelectorAll('.note .nt')].map((n) => ({ text: n.textContent, cut: (n as HTMLElement).scrollWidth > (n as HTMLElement).clientWidth, title: (n as HTMLElement).title })),
  )
  const re = notes.filter((n) => n.text?.startsWith('Re-analysing at depth 24'))
  check(re.length === 1, `${sz} games: one row says "${re[0]?.text ?? ''}"`)
  check(re.every((n) => !n.cut || n.title === n.text), `${sz} games: the row's words are whole or have them as title (${re.filter((n) => n.cut).length} cut)`)
  await games.context().close()
}
mkdirSync(out, { recursive: true })
writeFileSync(resolve(out, 'jobs_checks.out'), `# COACH-2 D, ${harnessBrowserName}: harness/jobsChecks.ts\n` + lines.join('\n') + `\n${lines.length - fails} of ${lines.length} checks pass\n`)
console.log(lines.filter((l) => l.startsWith('FAIL')).join('\n'))
console.log(`${harnessBrowserName}: ${lines.length - fails} of ${lines.length} checks pass`)
await browser.close()
await server.close()
