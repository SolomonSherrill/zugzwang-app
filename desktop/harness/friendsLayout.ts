/**
 * The Friends screens against their mockups, by numbers (FRIENDS-1 E; DESIGN.md "Owner rulings,
 * 2026-11-21", 1): the same measurements taken in the app (harness) and in the mockup page — header
 * height, page padding (the first panel's left edge), panel left and right edges lining up, row
 * heights of each table, the two-column grids' top edges — and their differences in pixels.
 *
 *   cd desktop && node harness/friendsLayout.ts > ../review/scratch/ui/friends/alignment.out
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit node harness/friendsLayout.ts > ../review/scratch/ui/webkit/friends/alignment.out
 *
 * Kinds: height, width, left, right, top (page coordinates), and leftIn, rightIn, bottomIn, midYIn: the
 * element against its parent (its left edge from the parent's, the parent's right edge from its right,
 * the same for the bottom, its vertical centre minus the parent's): FRIENDS-1B D's sparkline, colour
 * square and chevron, whose page offsets carry the sidebar's +11 px.
 */
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5192)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port }, logLevel: 'silent' })
await server.listen()
const browser = await harnessBrowser.launch({ headless: true })
const STORAGE = { 'zugzwang-accounts': JSON.stringify({ chesscom: 'you_demo', lichess: '' }) }

type Probe = Record<string, number | number[] | null>
/** selectors per page kind: [app selector, mockup selector] */
type Kind = 'height' | 'width' | 'left' | 'right' | 'top' | 'leftIn' | 'rightIn' | 'bottomIn' | 'midYIn'
const SPECS: Record<string, { app: string; mockup: string; size: { width: number; height: number }; probes: Record<string, [string, string, Kind]> }> = {
  friends: {
    app: '/?screen=friends',
    mockup: 'MinimalFriends.html',
    size: { width: 1440, height: 940 },
    probes: {
      'header height': ['header', 'header', 'height'],
      'add box left': ['.add .search', 'main label', 'left'],
      'first panel left': ['main section', 'main section', 'left'],
      'first panel right': ['main section', 'main section', 'right'],
      'request row height': ['li.req', 'section[aria-labelledby=req-h] li', 'height'],
      'friend row height': ['button.row', 'a.zrow', 'height'],
      'friends column header height': ['.colhead', 'div.zfg[aria-hidden]', 'height'],
      'panel title row height': ['.phead', 'section > div:first-child', 'height'],
    },
  },
  friend: {
    app: '/?screen=friend&friend=maxk',
    mockup: 'MinimalFriend.html',
    size: { width: 1440, height: 1240 },
    probes: {
      'header height': ['header', 'header', 'height'],
      'strip left': ['.strip', 'main > div:nth-child(2)', 'left'],
      'strip right': ['.strip', 'main > div:nth-child(2)', 'right'],
      'strip height': ['.strip', 'main > div:nth-child(2)', 'height'],
      'together row height': ['.hrow:not(.colhead)', 'a.zh', 'height'],
      'scouting row height': ['.srow:not(.colhead)', 'div.zs:not([aria-hidden])', 'height'],
      'time-control row height': ['.trow', 'section[aria-labelledby=tc-h] > div:nth-child(2)', 'height'],
      'recent row height': ['.rrow:not(.colhead)', 'a.zr', 'height'],
      'panel title row height': ['.ph', '.zph', 'height'],
      'scouting panel top': ['section[aria-labelledby=sc-h]', 'section[aria-labelledby=sc-h]', 'top'],
      'together panel top': ['section[aria-labelledby=h2h-h]', 'section[aria-labelledby=h2h-h]', 'top'],
      'scouting panel left': ['section[aria-labelledby=sc-h]', 'section[aria-labelledby=sc-h]', 'left'],
      // FRIENDS-1B D: the parts FRIENDS-1 left out, against their parent (cell or row)
      'sparkline width': ['.strip svg.spark', 'main > div:nth-child(2) svg', 'width'],
      'sparkline height': ['.strip svg.spark', 'main > div:nth-child(2) svg', 'height'],
      'sparkline inset from cell right': ['.strip svg.spark', 'main > div:nth-child(2) svg', 'rightIn'],
      'sparkline inset from cell bottom': ['.strip svg.spark', 'main > div:nth-child(2) svg', 'bottomIn'],
      'colour square size': ['.hrow:not(.colhead) .sq', 'a.zh > span:nth-child(2)', 'width'],
      'colour square left in row': ['.hrow:not(.colhead) .sq', 'a.zh > span:nth-child(2)', 'leftIn'],
      'colour square centre − row centre': ['.hrow:not(.colhead) .sq', 'a.zh > span:nth-child(2)', 'midYIn'],
      'chevron size': ['.rrow:not(.colhead) svg.chev', 'a.zr > svg', 'width'],
      'chevron inset from row right': ['.rrow:not(.colhead) svg.chev', 'a.zr > svg', 'rightIn'],
      'chevron centre − row centre': ['.rrow:not(.colhead) svg.chev', 'a.zr > svg', 'midYIn'],
    },
  },
  signup: {
    app: '/?screen=friends&state=friends-signup',
    mockup: 'MinimalFriends-signup.html',
    size: { width: 1440, height: 940 },
    probes: {
      'column left': ['.col', 'main > div', 'left'],
      'column width': ['.col', 'main > div', 'right'],
      'column top': ['.col', 'main > div', 'top'],
    },
  },
}

async function measure(page: Page, probes: Record<string, string>, kind: Record<string, string>): Promise<Probe> {
  return page.evaluate(
    ([probes, kind]) => {
      const out: Record<string, number | null> = {}
      for (const [k, sel] of Object.entries(probes)) {
        // the first one on view (Play stays mounted, hidden, with its own header)
        const el = [...document.querySelectorAll(sel)].find((e) => e.getBoundingClientRect().width > 0)
        if (!el) {
          out[k] = null
          continue
        }
        const b = el.getBoundingClientRect()
        const p = el.parentElement!.getBoundingClientRect()
        const what = kind[k]
        const v: Record<string, number> = {
          height: b.height, width: b.width, left: b.left, right: b.right, top: b.top,
          leftIn: b.left - p.left, rightIn: p.right - b.right, bottomIn: p.bottom - b.bottom,
          midYIn: (b.top + b.bottom) / 2 - (p.top + p.bottom) / 2,
        }
        out[k] = Math.round(v[what])
      }
      return out
    },
    [probes, kind] as const,
  )
}

const lines = [`# Friends screens vs their mockups (harness/friendsLayout.ts), ${harnessBrowserName}; px; diff = app − mockup`]
try {
  for (const [name, spec] of Object.entries(SPECS)) {
    const ctx = await browser.newContext({ viewport: spec.size, deviceScaleFactor: 1 })
    await ctx.addInitScript((e: [string, string][]) => e.forEach(([k, v]) => localStorage.setItem(k, v)), Object.entries(STORAGE))
    const app = await ctx.newPage()
    await app.goto(`http://localhost:${port}${spec.app}`)
    await app.waitForTimeout(1500)
    const mock = await ctx.newPage()
    await mock.goto(pathToFileURL(resolve(repo, 'design', 'mockups', spec.mockup)).href)
    await mock.waitForTimeout(500)
    const kind = Object.fromEntries(Object.entries(spec.probes).map(([k, v]) => [k, v[2]]))
    const a = await measure(app, Object.fromEntries(Object.entries(spec.probes).map(([k, v]) => [k, v[0]])), kind)
    const m = await measure(mock, Object.fromEntries(Object.entries(spec.probes).map(([k, v]) => [k, v[1]])), kind)
    lines.push(`\n== ${name} (${spec.size.width}x${spec.size.height}; mockup ${spec.mockup})`)
    for (const k of Object.keys(spec.probes)) {
      const d = a[k] != null && m[k] != null ? (a[k] as number) - (m[k] as number) : null
      lines.push(`  ${k.padEnd(30)} app ${String(a[k]).padStart(5)}  mockup ${String(m[k]).padStart(5)}  diff ${d == null ? 'n/a' : (d > 0 ? '+' : '') + d}`)
    }
    await ctx.close()
  }
} finally {
  await browser.close()
  await server.close()
}
console.log(lines.join('\n'))
