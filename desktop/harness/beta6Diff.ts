/**
 * BETA-6's pixel diffs: each shot of harness/beta6Checks.ts (review/scratch/ui/beta6/<browser>/<size>/) against the
 * same case shot on the run's base (a checkout of main before BETA-6's UI part, the control), through
 * harness/pixels.ts: the share of pixels changed and the largest changed regions, numbered, as numbers only.
 *
 *   cd desktop && node harness/beta6Diff.ts <control checkout> [--out <file>]
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { pixelDiff } from './pixels.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const args = process.argv.slice(2)
const oi = args.indexOf('--out')
const out = oi >= 0 ? resolve(args[oi + 1]) : null
if (oi >= 0) args.splice(oi, 2)
const control = resolve(args[0])
const base = resolve(repo, 'review', 'scratch', 'ui', 'beta6')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.setContent('<body></body>')
const lines = [`# BETA-6 pixel diffs: each shot against the same case on the control (main before BETA-6 B's UI), harness/beta6Diff.ts; share of pixels changed (any channel > 32 of 255), regions WxH@x,y`]
let n = 0
for (const br of ['chromium', 'webkit']) {
  for (const size of ['1280x720', '1440x900']) {
    const dir = resolve(base, br, size)
    if (!existsSync(dir)) continue
    for (const f of readdirSync(dir).filter((x) => x.endsWith('.png')).sort()) {
      const rel = `review/scratch/ui/beta6/${br}/${size}/${f}`
      const old = resolve(control, rel)
      n++
      if (!existsSync(old)) {
        lines.push(`${n}. ${rel}: no control shot`)
        continue
      }
      const r = await pixelDiff(page, readFileSync(old).toString('base64'), readFileSync(resolve(repo, rel)).toString('base64'))
      const regs = r.regions.slice(0, 3).map((b) => `${b.w}x${b.h}@${b.x},${b.y}`).join(' ')
      lines.push(`${n}. ${rel}: ${(r.share * 100).toFixed(2)} % changed, ${r.nRegions} regions${regs ? ': ' + regs : ''}`)
    }
  }
}
await browser.close()
const text = lines.join('\n') + '\n'
if (out) writeFileSync(out, text)
process.stdout.write(text)
