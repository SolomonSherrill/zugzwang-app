/**
 * The cold-start check (FIX-STARTUP): every screen that loads on mount, opened the way the real
 * app opens — mounted first, the sidecar started by App's onMount, the spawn taking a while — must
 * show its loading state, then its content, and never its error panel. Before the fix, Home showed
 * "Home could not load your games. sidecar not started" on every launch: a request made while the
 * sidecar was starting was rejected at once. The ordinary harness starts the sidecar before
 * mounting (main.ts), so no shot could see it.
 *
 *   cd desktop && node harness/coldStart.ts [--spawn-ms N] [--latency N] [--warm] [screen ...]
 *
 * --warm runs the same checks with the sidecar started before mounting (the control). Exits 1 if
 * any screen fails. Headless Chromium, the Vite server on localhost only: never opens a window.
 */
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))

/** A screen's states, read from the content area's text and DOM. */
export interface ColdScreen {
  name: string
  url: string
  /** the text of its loading state(s) */
  loading: string
  /** a selector whose presence (with no loading text) means its content is shown */
  loaded: string
}

// Every screen whose onMount (or first effect) asks the sidecar for something.
export const COLD_SCREENS: ColdScreen[] = [
  { name: 'home', url: '?screen=home', loading: 'Loading your games…', loaded: 'dl.figures' },
  { name: 'games', url: '?screen=games', loading: 'Loading your games…', loaded: '.table ul li' },
  { name: 'insights', url: '?screen=insights', loading: 'Reading your games…', loaded: 'dl.strip' },
  { name: 'puzzles', url: '?screen=puzzles', loading: 'Opening the puzzle database…', loaded: 'dl.stats' },
  {
    name: 'settings',
    url: '?screen=settings',
    loading: "Looking for Stockfish…|Reading the build's details…|Reading the opening books…|Reading your games…",
    loaded: '#s-engine',
  },
  { name: 'openings', url: '?screen=trainer', loading: 'Loading the opening book…', loaded: '.list .row:not(.head)' },
  { name: 'review', url: '?screen=review&game=main', loading: 'Opening the game…', loaded: 'cg-board' },
]

const args = process.argv.slice(2)
const opt = (flag: string, dflt: number) => {
  const i = args.indexOf(flag)
  if (i < 0) return dflt
  const v = Number(args[i + 1])
  args.splice(i, 2)
  return v
}
const spawnMs = opt('--spawn-ms', 400)
const latency = opt('--latency', 200)
const warm = args.includes('--warm')
const only = args.filter((a) => !a.startsWith('--'))

const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5174)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const base = `http://localhost:${port}/`
const browser = await chromium.launch({ headless: true })

type State = 'loading' | 'loaded' | 'error' | 'other'
const failures: string[] = []
try {
  for (const s of COLD_SCREENS) {
    if (only.length && !only.includes(s.name)) continue
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 940 }, deviceScaleFactor: 1 })
    // Records every change of the content area's state, from the first render on.
    await ctx.addInitScript(
      ({ loading, loaded }: { loading: string; loaded: string }) => {
        const w = window as unknown as { __cold: { t: number; s: string; text?: string }[] }
        w.__cold = []
        const re = new RegExp(loading)
        const classify = () => {
          const c = document.querySelector('main.content')
          if (!c) return { s: 'other' }
          const text = (c as HTMLElement).innerText
          const alert = c.querySelector('[role=alert]')
          if (alert || /could not/i.test(text))
            return { s: 'error', text: ((alert as HTMLElement | null)?.innerText ?? text).slice(0, 200) }
          if (re.test(text)) return { s: 'loading' }
          if (c.querySelector(loaded)) return { s: 'loaded' }
          return { s: 'other' }
        }
        const t0 = performance.now()
        const tick = () => {
          const st = classify()
          const last = w.__cold[w.__cold.length - 1]
          if (!last || last.s !== st.s) w.__cold.push({ t: Math.round(performance.now() - t0), ...st })
        }
        const start = () => new MutationObserver(tick).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true })
        if (document.documentElement) start()
        else document.addEventListener('DOMContentLoaded', start)
      },
      { loading: s.loading, loaded: s.loaded },
    )
    const page = await ctx.newPage()
    const pageErrors: string[] = []
    page.on('pageerror', (e) => pageErrors.push(e.message))
    const url = `${base}${s.url}&latency=${latency}&spawnMs=${spawnMs}${warm ? '' : '&cold=1'}`
    await page.goto(url)
    // settled: the content shown and no RPC for 600 ms, or 10 s
    const t0 = Date.now()
    let lastN = -1
    let quietSince = Date.now()
    while (Date.now() - t0 < 10_000) {
      const { n, done } = await page.evaluate(() => {
        const w = window as unknown as { __cold: { s: string }[]; __harness?: { requestLog: unknown[] } }
        return { n: w.__harness?.requestLog.length ?? 0, done: w.__cold.at(-1)?.s === 'loaded' }
      })
      if (n !== lastN) {
        lastN = n
        quietSince = Date.now()
      } else if (done && Date.now() - quietSince >= 600) break
      await page.waitForTimeout(100)
    }
    const timeline = (await page.evaluate(() => (window as unknown as { __cold: unknown[] }).__cold)) as {
      t: number
      s: State
      text?: string
    }[]
    const states = timeline.map((x) => x.s)
    const errors = timeline.filter((x) => x.s === 'error')
    const iLoading = states.indexOf('loading')
    const iLoaded = states.indexOf('loaded')
    const problems: string[] = []
    if (errors.length) problems.push(`showed its error panel: ${JSON.stringify(errors[0].text)}`)
    if (iLoading < 0) problems.push('never showed its loading state')
    if (iLoaded < 0) problems.push('never showed its content')
    else if (iLoading > iLoaded) problems.push('showed its content before its loading state')
    if (states.at(-1) !== 'loaded') problems.push(`ended in ${states.at(-1) ?? 'no state'}`)
    if (pageErrors.length) problems.push(`page errors: ${pageErrors.join('; ')}`)
    const line = `${s.name.padEnd(9)} ${timeline.map((x) => `${x.s}@${x.t}`).join(' → ')}`
    console.log((problems.length ? 'FAIL ' : 'ok   ') + line)
    for (const p of problems) console.log(`       ${p}`)
    if (problems.length) failures.push(s.name)
    await ctx.close()
  }
} finally {
  await browser.close()
  await server.close()
}
console.log(`${warm ? 'warm' : 'cold'} start, spawn ${spawnMs} ms, latency ${latency} ms: ${failures.length ? `FAILED ${failures.join(', ')}` : 'all screens pass'}`)
process.exit(failures.length ? 1 : 0)
