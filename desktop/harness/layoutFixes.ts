/**
 * BETA-4 C (FIXPLAN UI-8): the DOM checks for the four layout findings of UI-BUILD-4, each a
 * measurement, so a re-run gives the same figures and nobody reads a PNG (DESIGN.md "Owner rulings,
 * 2026-11-21", 1). For each window size:
 *
 * 1. review-report: the open key moment's buttons (.acts) against the bottom of the panel's
 *    visible scroll area (px of room under them; negative = below the visible area);
 * 2. insights-spark, home-spark: every sparkline's end dot, the share of its width left visible after
 *    clipping by the svg and its ancestors (1 = whole);
 * 3. home-table: the Recent games table's right edge against the cards' (.pair) right edge; and
 *    games-table, puzzles-table: each screen's table against the width of the box it sits in;
 * 4. engine-lines: each collapsed engine line (.rest): cut mid-move (scrollWidth > clientWidth), or
 *    whole moves only, and how many of its tokens show.
 *
 *   cd desktop && ZUGZWANG_HARNESS_PORT=5241 node harness/layoutFixes.ts [out]
 *
 * The out file defaults to review/scratch/ui/beta4/layout/layout_fixes.out.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const out = resolve(process.argv[2] ?? resolve(repo, 'review', 'scratch', 'ui', 'beta4', 'layout', 'layout_fixes.out'))
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5241)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const base = `http://localhost:${port}`
const browser = await harnessBrowser.launch({ headless: true })
const SIZES = [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]
const REVIEW = '/?screen=review&game=main&ply=66'

async function open(url: string, size: { width: number; height: number }): Promise<Page> {
  const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 })
  await page.goto(base + url)
  await page.waitForTimeout(800)
  await page.evaluate(() => document.fonts.ready)
  return page
}

/** the share of el's width visible after clipping by overflow-clipping ancestors (and itself for svg) */
const visibleShare = (sel: string) => (page: Page) =>
  page.evaluate((s) => {
    return [...document.querySelectorAll(s)].map((el) => {
      const b = el.getBoundingClientRect()
      let x0 = b.left, x1 = b.right
      for (let e = el.parentElement; e; e = e.parentElement) {
        const cs = getComputedStyle(e)
        if (cs.overflowX !== 'visible') {
          const c = e.getBoundingClientRect()
          x0 = Math.max(x0, c.left)
          x1 = Math.min(x1, c.right)
        }
      }
      return +(Math.max(0, x1 - x0) / (b.width || 1)).toFixed(2)
    })
  }, sel)

const lines: string[] = [
  `# BETA-4 C layout checks (harness/layoutFixes.ts), ${harnessBrowserName}, ${new Date().toISOString().slice(0, 10)}`,
  `# Written by: cd desktop && node harness/layoutFixes.ts`,
  '',
]
try {
  for (const size of SIZES) {
    const tag = `${size.width}x${size.height}`
    // 1. Review's Report, the key moment the report shot opens
    {
      const page = await open(REVIEW, size)
      await page.getByRole('button', { name: /34… axb5/ }).click()
      await page.waitForTimeout(500)
      const r = await page.evaluate(() => {
        const acts = document.querySelector('.moments li.open .acts')
        const sc = document.querySelector('aside .scroll')
        if (!acts || !sc) return null
        const a = acts.getBoundingClientRect()
        const s = sc.getBoundingClientRect()
        return { room: Math.round(Math.min(s.bottom, window.innerHeight) - a.bottom), actsBottom: Math.round(a.bottom), scrollBottom: Math.round(s.bottom), scrollTop: Math.round(sc.scrollTop) }
      })
      lines.push(r
        ? `${tag} review-report: open moment's buttons end at y ${r.actsBottom}, panel visible to y ${r.scrollBottom}: ${r.room} px under them (scrollTop ${r.scrollTop}) ${r.room >= 12 ? 'OK' : 'FAIL'}`
        : `${tag} review-report: no open moment`)
      // 4. engine lines, on the Moves tab
      await page.getByRole('tab', { name: 'Moves' }).click()
      await page.waitForTimeout(400)
      const rows = await page.evaluate(() =>
        [...document.querySelectorAll('.lines .rest')].map((el) => {
          const kids = [...el.children] as HTMLElement[]
          const shown = kids.filter((k) => getComputedStyle(k).display !== 'none').length
          return { cut: el.scrollWidth > el.clientWidth + 1, sw: el.scrollWidth, cw: el.clientWidth, shown, total: kids.length, text: (el.textContent ?? '').replace(/\s+/g, ' ').trim() }
        }),
      )
      for (const [i, x] of rows.entries())
        lines.push(`${tag} engine-lines: collapsed line ${i + 1}: ${x.cut ? `cut mid-move (scrollWidth ${x.sw} > clientWidth ${x.cw}) FAIL` : `whole moves only (${x.total ? `${x.shown} of ${x.total} tokens shown` : 'plain text, fits'}) OK`}: "${x.text}"`)
      await page.close()
    }
    // 2. sparklines and 3. the Home table
    {
      const page = await open('/?screen=insights', size)
      const sh = await visibleShare('.strip svg circle')(page)
      lines.push(`${tag} insights-spark: ${sh.length} end dots, visible share ${sh.join(', ')} ${sh.length && sh.every((v) => v >= 0.99) ? 'OK' : 'FAIL'}`)
      await page.close()
    }
    {
      const page = await open('/?screen=home', size)
      const sh = await visibleShare('.ratings svg circle')(page)
      lines.push(sh.length ? `${tag} home-spark: ${sh.length} end dots, visible share ${sh.join(', ')} ${sh.every((v) => v >= 0.99) ? 'OK' : 'FAIL'}` : `${tag} home-spark: the ratings sparklines draw no end dot`)
      const t = await page.evaluate(() => {
        const table = document.querySelector('.table')?.getBoundingClientRect()
        const pair = document.querySelector('.pair')?.getBoundingClientRect()
        const cards = [...document.querySelectorAll('.pair > .card')].map((c) => Math.round(c.getBoundingClientRect().right))
        return table && pair ? { table: Math.round(table.right), pair: Math.round(pair.right), cards, left: [Math.round(table.left), Math.round(pair.left)] } : null
      })
      lines.push(t
        ? `${tag} home-table: table x ${t.left[0]}..${t.table}, cards x ${t.left[1]}..${t.pair} (card right edges ${t.cards.join(', ')}): ${t.pair - t.table} px short ${Math.abs(t.pair - t.table) <= 1 && Math.abs(t.left[0] - t.left[1]) <= 1 ? 'OK' : 'FAIL'}`
        : `${tag} home-table: not found`)
      await page.close()
    }
    for (const [screen, url] of [['games', '/?screen=games'], ['puzzles', '/?screen=puzzles']]) {
      const page = await open(url, size)
      const t = await page.evaluate(() => {
        const el = document.querySelector('.table')
        const p = el?.parentElement
        if (!el || !p) return null
        const cs = getComputedStyle(p)
        const inner = p.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
        return { w: Math.round(el.getBoundingClientRect().width), inner: Math.round(inner), display: getComputedStyle(el).display }
      })
      lines.push(t
        ? `${tag} ${screen}-table: table ${t.w} px wide (display ${t.display}) in a ${t.inner} px box: ${t.inner - t.w} px short ${Math.abs(t.inner - t.w) <= 1 ? 'OK' : 'FAIL'}`
        : `${tag} ${screen}-table: not found`)
      await page.close()
    }
  }
} finally {
  await browser.close()
  await server.close()
}
mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, lines.join('\n') + '\n')
console.log(lines.join('\n'))
