/**
 * UI-BUILD-4 B: the stacked Games list measured in headless Chromium, beside MinimalGames.html
 * (no screenshots read): the grid's columns, a row's height and its two lines, the tones of names
 * and accuracies, the narrow window's columns and overflow, and Analyse on hover and on focus.
 *
 *   cd desktop && ZUGZWANG_HARNESS_PORT=5181 node harness/gamesMeasure.ts
 */
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createServer } from 'vite'
import { chromium, type Page } from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))
const mockup = pathToFileURL(resolve(here, '..', '..', 'design', 'mockups', 'MinimalGames.html')).href
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5174)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const base = `http://localhost:${port}`
const browser = await chromium.launch({ headless: true })
const STORAGE: [string, string][] = [['zugzwang-accounts', JSON.stringify({ chesscom: 'alice', lichess: '' })]]

async function open(url: string, width: number, height: number): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  await ctx.addInitScript((entries: [string, string][]) => {
    for (const [k, v] of entries) localStorage.setItem(k, v)
  }, STORAGE)
  const p = await ctx.newPage()
  await p.goto(url)
  await p.waitForTimeout(1500)
  await p.evaluate(() => document.fonts.ready)
  return p
}

/** The grid's resolved columns and gap, one row's box, its two player lines, and the tones. */
function rowFacts(p: Page, head: string, row: string, n: number) {
  return p.evaluate(
    ([head, row, n]) => {
      const h = document.querySelector(head as string) as HTMLElement
      const r = document.querySelectorAll(row as string)[n as number] as HTMLElement
      const cs = getComputedStyle(r)
      const cells = [...r.children].filter((c) => !(c as HTMLElement).matches('button.open, .open')) as HTMLElement[]
      const players = cells[1]
      const lines = [...players.children].map((l) => {
        const name = l.querySelector('.pname, span[style*="font-weight"]') as HTMLElement | null
        const ncs = name ? getComputedStyle(name) : null
        // names replaced: the recorded pages hold real players' names, which stay out of the output
        const full = (l as HTMLElement).innerText.trim()
        const text = name && name.innerText.trim() !== 'Stockfish' && name.innerText.trim() !== 'You' ? full.replace(name.innerText.trim(), '<name>') : full
        return { text, nameColor: ncs?.color, nameWeight: ncs?.fontWeight, y: Math.round(l.getBoundingClientRect().top - r.getBoundingClientRect().top) }
      })
      const accs = [...cells[2].children].map((a) => ({ text: (a as HTMLElement).innerText.trim(), color: getComputedStyle(a).color }))
      return {
        headCols: getComputedStyle(h).gridTemplateColumns,
        headCells: [...h.children].filter((c) => getComputedStyle(c).display !== 'none').map((c) => (c as HTMLElement).innerText.trim()),
        rowCols: cs.gridTemplateColumns,
        gap: cs.columnGap,
        border: cs.borderTopColor,
        padding: `${cs.paddingTop} ${cs.paddingRight} ${cs.paddingBottom} ${cs.paddingLeft}`,
        height: Math.round(r.getBoundingClientRect().height),
        width: Math.round(r.getBoundingClientRect().width),
        font: `${cs.fontSize} ${getComputedStyle(players).lineHeight}`,
        lines,
        accs,
      }
    },
    [head, row, n] as const,
  )
}

const kinds = base + '/?screen=games&state=games-kinds'
const out: Record<string, unknown> = {}
try {
  const m = await open(mockup, 1440, 940)
  out.mockup = await rowFacts(m, '.zg2[aria-hidden]', 'a.zg2', 0)
  out.mockupEngine = await rowFacts(m, '.zg2[aria-hidden]', 'a.zg2', 2)
  out.mockupUnanalysed = await rowFacts(m, '.zg2[aria-hidden]', 'a.zg2', 1)

  const a = await open(kinds, 1440, 940)
  out.app = await rowFacts(a, '.zg.head', 'li.row', 0)
  out.appUnanalysed = await rowFacts(a, '.zg.head', 'li.row', 1)
  out.appEngine = await rowFacts(a, '.zg.head', 'li.row', 2)
  out.appNoRatings = await rowFacts(a, '.zg.head', 'li.row', 5)
  const analyseShown = (pg: Page) =>
    pg.evaluate(() => {
      const r = document.querySelectorAll('li.row')[1]
      const an = r.querySelector('button.an') as HTMLElement | null
      const not = r.querySelector('.not') as HTMLElement | null
      const note = r.querySelector('.note') as HTMLElement | null
      const op = note?.parentElement?.firstElementChild as HTMLElement | undefined
      return {
        analyse: an ? getComputedStyle(an).display : 'absent',
        notAnalysed: not ? getComputedStyle(not).display : 'absent',
        noteBelowOpening: !!(note && op && note.getBoundingClientRect().top >= op.getBoundingClientRect().bottom - 1),
      }
    })
  out.unanalysedIdle = await analyseShown(a)
  await a.keyboard.press('j')
  await a.keyboard.press('j')
  out.unanalysedSelected = await analyseShown(a)
  const box = await a.locator('li.row').nth(1).boundingBox()
  if (box) await a.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await a.waitForTimeout(200)
  out.unanalysedHover = await analyseShown(a)
  await a.mouse.move(0, 0)
  await a.locator('li.row').nth(1).locator('button.open').focus()
  await a.waitForTimeout(200)
  out.unanalysedFocus = await analyseShown(a)

  for (const [w, h] of [[1280, 720], [1366, 768], [1439, 900], [1440, 900]]) {
    const n = await open(kinds, w, h)
    const f = await rowFacts(n, '.zg.head', 'li.row', 0)
    const overflow = await n.evaluate(() => {
      const s = document.querySelector('.games .scroll') as HTMLElement
      const t = document.querySelector('.games .table') as HTMLElement
      const clipped = [...document.querySelectorAll('li.row .pname, li.row .el.t2')].filter((e) => (e as HTMLElement).scrollWidth > (e as HTMLElement).clientWidth).length
      return { scrollW: s.scrollWidth, clientW: s.clientWidth, tableW: Math.round(t.getBoundingClientRect().width), ellipsised: clipped }
    })
    out[`window ${w}x${h}`] = { headCells: f.headCells, rowCols: f.rowCols, ...overflow }
  }
} finally {
  await browser.close()
  await server.close()
}
console.log(JSON.stringify(out, null, 1))
