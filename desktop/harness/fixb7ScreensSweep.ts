/**
 * FIX-B7 (ruling HF2): with every screen in a boundary, an error a screen used to throw and carry on past now shows
 * "This screen could not be opened." This opens every shot harness/shoot.ts takes (its URL, storage, actions) and
 * lists any that end in the failed state, with the error sent to client_error, and every page error.
 * Writes review/scratch/fixb7_screens_<browser>.out.
 *
 *   cd desktop && node harness/fixb7ScreensSweep.ts
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_PORT=5232 node harness/fixb7ScreensSweep.ts
 */
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { SHOTS } from './shots.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5231)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port, host: '127.0.0.1' }, logLevel: 'silent' })
await server.listen()
const base = `http://127.0.0.1:${port}`
const browser = await harnessBrowser.launch({ headless: true })
const lines: string[] = [`# FIX-B7: every harness shot (${SHOTS.length}) opened in ${harnessBrowserName}, ${new Date().toISOString()}: failed boundaries and page errors`]
let failed = 0
let withErrors = 0
for (const s of SHOTS) {
  if (!s.url.startsWith('/?') && s.url !== '/') continue
  const page = await browser.newPage({ viewport: s.size ?? { width: 1440, height: 940 } })
  const errors: string[] = []
  page.on('pageerror', (e: Error) => errors.push(e.message.split('\n')[0]))
  if (s.storage) {
    await page.addInitScript((st: Record<string, string>) => {
      for (const [k, v] of Object.entries(st)) localStorage.setItem(k, v)
    }, s.storage)
  }
  if (s.before) await s.before(page).catch(() => {})
  await page.goto(base + s.url)
  await page.waitForTimeout(s.waitMs ?? 700)
  let acted = 'no action'
  if (s.act) acted = await s.act(page).then(() => 'acted', (e: Error) => `action failed: ${e.message.split('\n')[0].slice(0, 80)}`)
  await page.waitForTimeout(500)
  const st = await page.evaluate(() => ({
    failed: document.querySelectorAll('[data-testid="screen-failed"]').length,
    logged: ((window as unknown as { __harness?: { requestLog: { method: string; params: Record<string, unknown> }[] } }).__harness?.requestLog ?? [])
      .filter((r) => r.method === 'client_error')
      .map((r) => `${r.params.screen}: ${String(r.params.message).split('\n')[0]}`),
  }))
  if (st.failed) failed++
  if (errors.length) withErrors++
  lines.push(`${st.failed ? 'FAILED' : 'ok    '} ${s.dir}/${s.name} (${acted}); boundaries failed ${st.failed}; client_error [${st.logged.join(' | ')}]; page errors ${errors.length}${errors.length ? ': ' + [...new Set(errors)].join(' | ').slice(0, 300) : ''}`)
  await page.close()
}
lines.push(`${failed} shots ended in a failed boundary; ${withErrors} had page errors`)
writeFileSync(resolve(repo, 'review', 'scratch', `fixb7_screens_${harnessBrowserName}.out`), lines.join('\n') + '\n')
console.log(lines.slice(-1)[0])
await browser.close()
await server.close()
