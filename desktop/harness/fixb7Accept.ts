/**
 * FIX-B7 B5: the acceptance checks (harness/fixb7Checks.ts), every figure written to
 * review/scratch/fixb7_accept_<browser>.out, each game by its platform game id (the house rule).
 *
 *   cd desktop && node harness/fixb7Accept.ts                                   (Chromium)
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_PORT=5232 node harness/fixb7Accept.ts
 *
 * Headless; the Vite server listens on localhost only.
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { failedCoach, failedReview, openGame } from './fixb7Checks.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(repo, 'review', 'ui_fixtures')
const meta = (JSON.parse(readFileSync(resolve(fixtures, 'keys_fixtures.json'), 'utf8')) as {
  meta: { games: { external: string; source: string; gameId: number; sampled: boolean }[]; sampleSeed: number; db: string }
}).meta
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5231)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port, host: '127.0.0.1' }, logLevel: 'silent' })
await server.listen()
const base = `http://127.0.0.1:${port}`
const browser = await harnessBrowser.launch({ headless: true })
const lines: string[] = [`FIX-B7 acceptance in the harness, ${harnessBrowserName}, ${new Date().toISOString()}; fixtures from ${meta.db}, sample seed ${meta.sampleSeed}`]
let fails = 0
for (const g of meta.games) {
  const r = await openGame(browser, base, g.gameId)
  const ok = !r.errors.length && !r.opening && !r.failed && r.report
  if (!ok) fails++
  const tag = g.sampled ? '(b) sample' : '(a) the game'
  lines.push(`${ok ? 'PASS' : 'FAIL'} ${tag} ${g.source} ${g.external}: report ${r.report}, opening ${r.opening}, failed ${r.failed}, ${r.ms} ms, errors ${r.errors.length}, pattern rows ${r.patterns.length}`)
  if (!g.sampled) for (const p of r.patterns) lines.push(`      ${p.move} | ${p.say}`)
}
const fr = await failedReview(browser, base)
const frOk = fr.ms !== null && fr.ms < 2000 && !fr.opening && fr.sentence && fr.back && fr.logged?.screen === 'review'
if (!frOk) fails++
lines.push(`${frOk ? 'PASS' : 'FAIL'} (c) Review, a report built to throw: "This game could not be opened." after ${fr.ms} ms, "Opening the game…" shown ${fr.opening}, Back to games ${fr.back}; under it: ${JSON.stringify(fr.sub)}`)
lines.push(`${fr.logged ? 'PASS' : 'FAIL'} (d) client_error sent: screen ${fr.logged?.screen}, message ${JSON.stringify(fr.logged?.message)}, stack ${fr.logged?.stackLines} lines`)
const fc = await failedCoach(browser, base)
const fcOk = fc.ms !== null && fc.sentence && fc.redrawn && !fc.failedAfter && fc.logged?.screen === 'coach'
if (!fcOk) fails++
lines.push(`${fcOk ? 'PASS' : 'FAIL'} (c) Coach, built to throw once: "This screen could not be opened." after ${fc.ms} ms; under it: ${JSON.stringify(fc.sub)}; client_error screen ${fc.logged?.screen}; Try again redrew the focus cards ${fc.redrawn}, error still shown ${fc.failedAfter}`)
lines.push(`${fails ? 'FAILED' : 'ALL PASS'}: ${fails} failures`)
const out = resolve(repo, 'review', 'scratch', `fixb7_accept_${harnessBrowserName}.out`)
writeFileSync(out, lines.join('\n') + '\n')
console.log(lines.join('\n'))
await browser.close()
await server.close()
process.exit(fails ? 1 : 0)
