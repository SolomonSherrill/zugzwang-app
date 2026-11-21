/**
 * Screenshots for review (UI-BUILD A5): each shot renders a harness URL and, where there is
 * one, the matching design mockup at 1440 x 940 in headless Chromium, and saves
 * <name>-app.png, <name>-mockup.png and <name>-side.png (the two side by side) in
 * review/scratch/ui/<dir>/.
 *
 *   cd desktop && node harness/shoot.ts [substring of "<dir>/<name>" to filter]
 *
 * The sizes/ shots (harness/sizesShots.ts, UI-BUILD-4 C) also run the DOM layout check and write
 * review/scratch/ui/sizes/layout_check.out:  node harness/shoot.ts sizes/
 *
 * WebKit (UI-BUILD-4 E): ZUGZWANG_HARNESS_BROWSER=webkit shoots in Playwright's WebKit (the engine
 * of the macOS app's WKWebView) into review/scratch/ui/webkit/<dir>/<name>-app.png, without the
 * mockups (ZUGZWANG_HARNESS_MOCKUPS=1 adds them), so the Chromium shots stay where they are.
 * ZUGZWANG_HARNESS_OUT=<dir> writes the shots somewhere else; ZUGZWANG_HARNESS_DOM=<file.json>
 * also writes each shot's DOM measurements (harness/domProbe.ts) for harness/browserCompare.ts.
 *
 * Never opens a window: the browser is headless, and the Vite server listens on localhost only.
 */
import { mkdirSync, readFileSync, existsSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { probeDom, type DomProbe } from './domProbe.ts'
import { SHOTS } from './shots.ts'
import { sizesShots } from './sizesShots.ts'
import { checkLayout, compareWidths, formatResult } from './layoutCheck.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const outRoot = process.env.ZUGZWANG_HARNESS_OUT
  ? resolve(process.env.ZUGZWANG_HARNESS_OUT)
  : harnessBrowserName === 'webkit'
    ? resolve(repo, 'review', 'scratch', 'ui', 'webkit')
    : resolve(repo, 'review', 'scratch', 'ui')
const withMockups = (process.env.ZUGZWANG_HARNESS_MOCKUPS ?? (harnessBrowserName === 'webkit' ? '0' : '1')) === '1'
const domOut = process.env.ZUGZWANG_HARNESS_DOM ? resolve(process.env.ZUGZWANG_HARNESS_DOM) : null
const doms: Record<string, DomProbe> = {}
const mockups = resolve(repo, 'design', 'mockups')
const filter = process.argv[2] ?? ''

// ZUGZWANG_HARNESS_PORT: another port when two worktrees shoot at once (the config's is 5174)
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5174)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port } })
await server.listen()
const base = `http://localhost:${port}`
const browser = await harnessBrowser.launch({ headless: true })

/** Wait until no RPC has been made for `quietMs` (the page has settled). */
async function settle(page: Page, quietMs = 600, maxMs = 8000): Promise<void> {
  const start = Date.now()
  let last = -1
  let since = Date.now()
  while (Date.now() - start < maxMs) {
    const n = await page.evaluate(
      () => (window as unknown as { __harness?: { requestLog: unknown[] } }).__harness?.requestLog.length ?? 0,
    )
    if (n !== last) {
      last = n
      since = Date.now()
    } else if (Date.now() - since >= quietMs) break
    await page.waitForTimeout(100)
  }
  await page.evaluate(() => document.fonts.ready)
}

const done: string[] = []
const failed: string[] = []
const checks: string[] = []
const ALL = [...SHOTS, ...sizesShots(SHOTS)]
try {
  for (const shot of ALL) {
    const id = `${shot.dir}/${shot.name}`
    if (filter && !id.includes(filter)) continue
    const dir = resolve(outRoot, shot.dir)
    mkdirSync(dir, { recursive: true })
    const size = shot.size ?? { width: 1440, height: 940 }
    const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1 })
    try {
    if (shot.storage) {
      // localStorage as the app would find it (saved usernames, the chosen piece set)
      await ctx.addInitScript((entries: [string, string][]) => {
        for (const [k, v] of entries) localStorage.setItem(k, v)
      }, Object.entries(shot.storage))
    }
    const page = await ctx.newPage()
    page.on('pageerror', (e) => console.error(`[${id}] page error:`, e.message))
    if (shot.before) await shot.before(page)
    await page.goto(base + shot.url)
    await settle(page)
    if (shot.act) {
      await shot.act(page)
      await settle(page, 400)
    }
    await page.waitForTimeout(shot.waitMs ?? 300)
    const appPng = resolve(dir, `${shot.name}-app.png`)
    await page.screenshot({ path: appPng, fullPage: !!shot.fullPage })
    const missing = await page.evaluate(
      () =>
        (window as unknown as { __harness?: { requestLog: { method: string; missing: boolean }[] } }).__harness?.requestLog
          .filter((r) => r.missing)
          .map((r) => r.method) ?? [],
    )
    if (missing.length) console.warn(`[${id}] RPCs with no fixture: ${[...new Set(missing)].join(', ')}`)
    let line = `${id}: ${appPng}`
    if (domOut) doms[id] = await probeDom(page)
    if (withMockups && shot.mockup && existsSync(resolve(mockups, shot.mockup))) {
      const mpage = await ctx.newPage()
      await mpage.goto(pathToFileURL(resolve(mockups, shot.mockup)).href)
      await mpage.waitForLoadState('networkidle').catch(() => {})
      await mpage.evaluate(() => document.fonts.ready)
      if (shot.mockupAct) await shot.mockupAct(mpage)
      const mockPng = resolve(dir, `${shot.name}-mockup.png`)
      await mpage.screenshot({ path: mockPng, fullPage: !!shot.fullPage })
      const side = await ctx.newPage()
      const a = readFileSync(appPng).toString('base64')
      const b = readFileSync(mockPng).toString('base64')
      await side.setViewportSize({ width: size.width * 2 + 16, height: size.height })
      await side.setContent(
        `<body style="margin:0;background:#444;display:flex;gap:16px;align-items:flex-start">` +
          `<img src="data:image/png;base64,${a}"><img src="data:image/png;base64,${b}"></body>`,
      )
      const sidePng = resolve(dir, `${shot.name}-side.png`)
      await side.screenshot({ path: sidePng, fullPage: true })
      line += ` | mockup ${shot.mockup} | side ${sidePng}`
    }
    if (shot.check) {
      const res = await checkLayout(page)
      let vs940: string[] | undefined
      if (size.width === 1440 && size.height === 900) {
        // ruling 2: at 1440 x 900 nothing changes from the 1440 x 940 the mockups draw but height
        await page.setViewportSize({ width: 1440, height: 940 })
        await page.waitForTimeout(400)
        vs940 = compareWidths(res.blocks, (await checkLayout(page)).blocks)
      }
      checks.push(formatResult(id, res, vs940))
    }
    done.push(line)
    } catch (e) {
      // one shot failing (a timeout under load) does not lose the rest of the run
      failed.push(`${id}: ${String((e as Error).message ?? e).split('\n')[0]}`)
      console.error(`[${id}] FAILED:`, (e as Error).message)
    } finally {
      await ctx.close()
    }
  }
} finally {
  await browser.close()
  await server.close()
}
if (checks.length) {
  const out = resolve(outRoot, 'sizes', 'layout_check.out')
  mkdirSync(dirname(out), { recursive: true })
  const head =
    `# The small-windows layout check (harness/layoutCheck.ts), ${checks.length} shots, filter "${filter}", ${harnessBrowserName}.\n` +
    `# Written by: cd desktop && ${harnessBrowserName === 'webkit' ? 'ZUGZWANG_HARNESS_BROWSER=webkit ' : ''}node harness/shoot.ts ${filter}\n`
  writeFileSync(out, head + '\n' + checks.join('\n\n') + '\n')
  console.log(`layout check: ${out}`)
}
if (domOut) {
  mkdirSync(dirname(domOut), { recursive: true })
  writeFileSync(domOut, JSON.stringify({ browser: harnessBrowserName, root: outRoot, shots: doms }))
  console.log(`DOM measurements: ${domOut}`)
}
console.log(done.join('\n'))
if (failed.length) {
  console.log(`\n${failed.length} shot(s) FAILED:\n${failed.join('\n')}`)
  process.exitCode = 1
}
