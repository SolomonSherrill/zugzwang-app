/**
 * Every chart readout, in WebKit and in Chromium (UI-BUILD-4 E; the readout is owner ruling 12 of
 * 2026-11-20, fourth, accepted by the fifth rulings, 1 I): Review's Report chart on Eval, Material
 * and Time, the Moves tab's graph, Insights' Accuracy over time and its stat sparklines, Home's
 * rating sparklines. Each chart is hovered at three points (10 %, 50 % and 98 % of its width) and
 * focused by keyboard (Shift, focus, then an arrow key). For each: the vertical guide, the dot and
 * the label exist, sit inside the chart's box, the label does not leave the window at the right
 * edge, and the label's text; then the same in the other browser, and the texts compared. WebKit
 * shots of each readout (the chart with a margin) go to review/scratch/ui/webkit/charts/, the
 * table to review/scratch/ui/webkit/charts.out.
 *
 *   cd desktop && ZUGZWANG_HARNESS_PORT=5214 node harness/chartsCheck.ts
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium, webkit, type Browser, type Page } from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const outDir = resolve(repo, 'review', 'scratch', 'ui', 'webkit', 'charts')
mkdirSync(outDir, { recursive: true })
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5214)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const base = `http://localhost:${port}`

const REVIEW = '/?screen=review&game=main&ply=66'
interface Chart {
  name: string
  url: string
  size?: { width: number; height: number }
  /** the slider's accessible name */
  slider: RegExp | string
  /** which of the matching sliders (several sparklines share a pattern) */
  nth?: number
  prep?: (p: Page) => Promise<void>
  yFrac?: number
  /** the arrow pressed after keyboard focus */
  key?: string
}
const INS = { width: 1440, height: 1640 }
const CHARTS: Chart[] = [
  { name: 'report-eval', url: REVIEW, slider: /^Evaluation through the game/, key: 'ArrowRight' },
  { name: 'report-material', url: REVIEW, slider: /^Material through the game/, prep: (p) => p.getByRole('radio', { name: 'Material' }).click(), key: 'ArrowRight' },
  { name: 'report-time', url: REVIEW, slider: /^Time spent per move through the game/, prep: (p) => p.getByRole('radio', { name: 'Time' }).click(), key: 'ArrowRight' },
  { name: 'moves-graph', url: REVIEW, slider: /notable moves/, prep: (p) => p.getByRole('tab', { name: 'Moves' }).click(), key: 'ArrowRight' },
  { name: 'insights-accuracy', url: '/?screen=insights', size: INS, slider: 'Accuracy by month', yFrac: 0.3, key: 'ArrowLeft' },
  { name: 'insights-spark-0', url: '/?screen=insights', size: INS, slider: /, 12 months$/, nth: 0, key: 'ArrowLeft' },
  { name: 'insights-spark-1', url: '/?screen=insights', size: INS, slider: /, 12 months$/, nth: 1, key: 'ArrowLeft' },
  { name: 'insights-spark-2', url: '/?screen=insights', size: INS, slider: /, 12 months$/, nth: 2, key: 'ArrowLeft' },
  { name: 'insights-spark-3', url: '/?screen=insights', size: INS, slider: /, 12 months$/, nth: 3, key: 'ArrowLeft' },
  // the right edge in the smallest window (fifth rulings, 2): the label must stay inside it
  { name: 'report-eval-1280x720', url: REVIEW, size: { width: 1280, height: 720 }, slider: /^Evaluation through the game/, key: 'ArrowRight' },
  { name: 'insights-spark-3-1280x720', url: '/?screen=insights', size: { width: 1280, height: 720 }, slider: /, 12 months$/, nth: 3, key: 'ArrowLeft' },
  { name: 'home-spark-0', url: '/?screen=home', slider: /rating, last 30 days$/, nth: 0, key: 'ArrowLeft' },
  { name: 'home-spark-1', url: '/?screen=home', slider: /rating, last 30 days$/, nth: 1, key: 'ArrowLeft' },
  { name: 'home-spark-2', url: '/?screen=home', slider: /rating, last 30 days$/, nth: 2, key: 'ArrowLeft' },
]
const POINTS = [0.1, 0.5, 0.98]

/** The chart and its readout with a margin, for the shot (a whole window per readout is 56 large PNGs). */
async function chartClip(page: Page, chart: Chart) {
  const r = await page.getByRole('slider', { name: chart.slider }).nth(chart.nth ?? 0).evaluate((el) => {
    const b = (el.closest('.readout-box') ?? el).getBoundingClientRect()
    return { x: b.left, y: b.top, w: b.width, h: b.height, vw: innerWidth, vh: innerHeight }
  })
  const m = 160
  const x = Math.max(0, r.x - m), y = Math.max(0, r.y - 60)
  return { x, y, width: Math.min(r.vw, r.x + r.w + m) - x, height: Math.min(r.vh, r.y + r.h + 60) - y }
}

interface Reading { ok: boolean; text: string; problems: string[]; label?: string }

/** Read the readout drawn in the chart's box now. */
async function read(page: Page, chart: Chart): Promise<Reading> {
  const sl = page.getByRole('slider', { name: chart.slider }).nth(chart.nth ?? 0)
  return sl.evaluate((el) => {
    const box = el.closest('.readout-box') ?? el
    const b = box.getBoundingClientRect()
    const problems: string[] = []
    const notes: string[] = []
    const inside = (n: string, r: DOMRect, padX = 1, padY = 1) => {
      if (r.left < b.left - padX || r.right > b.right + padX || r.top < b.top - padY || r.bottom > b.bottom + padY)
        problems.push(`${n} ${Math.round(r.left)}..${Math.round(r.right)} x ${Math.round(r.top)}..${Math.round(r.bottom)} outside the box ${Math.round(b.left)}..${Math.round(b.right)} x ${Math.round(b.top)}..${Math.round(b.bottom)}`)
    }
    const guide = box.querySelector(':scope > .guide')
    const dot = box.querySelector(':scope > .dot')
    const label = box.querySelector(':scope > .label') as HTMLElement | null
    if (!guide) problems.push('no guide')
    else inside('guide', guide.getBoundingClientRect())
    // a time bar or an unscored point draws no dot (ChartReadout: y null); noted, not a failure
    if (dot) inside('dot', dot.getBoundingClientRect(), 4, 4)
    if (!label) problems.push('no label')
    else {
      const r = label.getBoundingClientRect()
      const cs = getComputedStyle(label)
      if (cs.visibility !== 'visible') problems.push('label hidden')
      if (r.right > innerWidth) problems.push(`label right ${Math.round(r.right)} > window ${innerWidth}`)
      if (r.width > b.width + 1) {
        // a label wider than its chart (the 84 px sparklines) cannot stay inside it: it is held
        // to the box's right edge and runs left; it must stay inside the tile that holds the chart
        let tile: Element | null = box.parentElement
        while (tile && tile.getBoundingClientRect().width < r.width + 2) tile = tile.parentElement
        const t = tile?.getBoundingClientRect()
        if (!t || r.left < t.left - 1 || r.right > t.right + 1) problems.push(`label ${Math.round(r.left)}..${Math.round(r.right)} wider than the chart and outside its tile`)
        else notes.push(`label ${Math.round(r.width)} px, wider than the ${Math.round(b.width)} px chart: held to its right edge, inside its tile ${Math.round(t.left)}..${Math.round(t.right)}`)
        if (Math.abs(r.right - b.right) > 1.5) problems.push(`label right ${Math.round(r.right)} not at the chart's right ${Math.round(b.right)}`)
      } else if (r.left < b.left - 1 || r.right > b.right + 1) problems.push(`label ${Math.round(r.left)}..${Math.round(r.right)} leaves the box ${Math.round(b.left)}..${Math.round(b.right)}`)
      if (label.scrollWidth > label.clientWidth + 1) problems.push(`label text wider than the label (${label.scrollWidth} > ${label.clientWidth})`)
    }
    const g = guide?.getBoundingClientRect()
    const where = g ? `guide x ${Math.round(g.left - b.left)}/${Math.round(b.width)}` : ''
    return {
      text: (label?.textContent ?? '').replace(/\s+/g, ' ').trim(),
      problems: [...problems, ...notes, ...(dot || !guide ? [] : ['note: no dot (none drawn at this point)'])],
      ok: problems.length === 0,
      label: where + (label ? `, label ${Math.round(label.getBoundingClientRect().left - b.left)}..${Math.round(label.getBoundingClientRect().right - b.left)}` : ''),
    }
  })
}

async function run(browser: Browser, shots: boolean) {
  const res: Record<string, Reading> = {}
  for (const c of CHARTS) {
    const ctx = await browser.newContext({ viewport: c.size ?? { width: 1440, height: 940 }, deviceScaleFactor: 1 })
    const page = await ctx.newPage()
    try {
      await page.goto(base + c.url)
      // the screen is up when its first chart is; a mode or tab switch then brings this chart
      await page.getByRole('slider').first().waitFor({ timeout: 15000 })
      await page.waitForTimeout(600)
      if (c.prep) { await c.prep(page); await page.waitForTimeout(500) }
      const sl = page.getByRole('slider', { name: c.slider }).nth(c.nth ?? 0)
      await sl.waitFor({ timeout: 15000 })
      await sl.scrollIntoViewIfNeeded()
      for (const f of POINTS) {
        const bb = (await sl.boundingBox())!
        await page.mouse.move(bb.x + bb.width * f, bb.y + bb.height * (c.yFrac ?? 0.5), { steps: 4 })
        await page.waitForTimeout(200)
        const k = `${c.name} hover ${Math.round(f * 100)}%`
        res[k] = await read(page, c)
        if (shots) await page.screenshot({ path: resolve(outDir, `${c.name}-hover-${Math.round(f * 100)}-app.png`), clip: await chartClip(page, c) })
      }
      await page.mouse.move(2, 2)
      await page.waitForTimeout(150)
      await page.keyboard.press('Shift')
      await sl.focus()
      await page.keyboard.press(c.key ?? 'ArrowRight')
      await page.waitForTimeout(250)
      const focusVisible = await sl.evaluate((el) => {
        const t = (el.closest('.readout-box[role=slider]') ?? el) as HTMLElement
        return document.activeElement === t || t.contains(document.activeElement) ? (t.matches(':focus-visible') ? 'focus-visible' : 'focused, not focus-visible') : 'not focused'
      })
      const k = `${c.name} keyboard`
      res[k] = await read(page, c)
      res[k].label = (res[k].label ?? '') + `, ${focusVisible}`
      if (shots) await page.screenshot({ path: resolve(outDir, `${c.name}-focus-app.png`), clip: await chartClip(page, c) })
    } catch (e) {
      res[`${c.name} (error)`] = { ok: false, text: '', problems: [String((e as Error).message).split('\n')[0]] }
    } finally {
      await ctx.close()
    }
  }
  return res
}

let wk: Record<string, Reading>, cr: Record<string, Reading>
try {
  const w = await webkit.launch({ headless: true })
  wk = await run(w, true)
  await w.close()
  const c = await chromium.launch({ headless: true })
  cr = await run(c, false)
  await c.close()
} finally {
  await server.close()
}
const lines: string[] = [
  '# Chart readouts in WebKit against Chromium (harness/chartsCheck.ts, UI-BUILD-4 E).',
  '# Written by: cd desktop && ZUGZWANG_HARNESS_PORT=5214 node harness/chartsCheck.ts',
  '# Per readout: WebKit pass/FAIL, the label text, where the guide and label sit in the chart box (px),',
  '# then "same text" or the Chromium text when it differs, and any problem found in either browser.',
  '',
]
let pass = 0, total = 0, same = 0
for (const k of Object.keys(wk!)) {
  const a = wk![k], b = cr![k]
  total++
  if (a.ok) pass++
  const eq = b && a.text === b.text
  if (eq) same++
  lines.push(`${k.padEnd(30)} ${a.ok ? 'pass' : 'FAIL'}  "${a.text}"  (${a.label ?? ''})  ${eq ? 'same text in Chromium' : 'Chromium: "' + (b?.text ?? 'none') + '"'}`)
  if (a.problems.length) lines.push(`    WebKit: ${a.problems.join('; ')}`)
  if (b && b.problems.length) lines.push(`    Chromium: ${b.problems.join('; ')}${b.ok ? '' : ' (FAIL)'}`)
}
lines.splice(4, 0, `# ${total} readouts: ${pass} pass in WebKit, ${Object.values(cr!).filter((r) => r.ok).length} pass in Chromium, ${same} with the same text in both.`)
writeFileSync(resolve(outDir, '..', 'charts.out'), lines.join('\n') + '\n')
console.log(lines.slice(0, 6).join('\n'))
