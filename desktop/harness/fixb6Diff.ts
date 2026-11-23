/**
 * FIX-B6 C's pixel diffs: each shot in review/scratch/ui/fixb6/banners/<browser>/<size>/ against BETA-6's shot of the
 * same case (review/scratch/ui/beta6/<browser>/<size>/), through harness/pixels.ts. Writes pixel_diff.out beside them.
 *
 *   cd desktop && node harness/fixb6Diff.ts
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { pixelDiff } from './pixels.ts'

const here = dirname(fileURLToPath(import.meta.url))
const ui = resolve(here, '..', '..', 'review', 'scratch', 'ui')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.setContent('<body></body>')
for (const b of ['chromium', 'webkit']) {
  const root = resolve(ui, 'fixb6', 'banners', b)
  if (!existsSync(root)) continue
  const lines = [`# FIX-B6 C, ${b}: each shot against BETA-6's (review/scratch/ui/beta6/${b}/), share of pixels changed (any channel > 32 of 255), regions WxH@x,y`]
  let n = 0
  for (const size of readdirSync(root).filter((d) => /^\d+x\d+$/.test(d)).sort()) {
    for (const f of readdirSync(resolve(root, size)).filter((f) => f.endsWith('.png')).sort()) {
      const old = resolve(ui, 'beta6', b, size, f)
      n++
      if (!existsSync(old)) {
        lines.push(`${n}  ${size}/${f}: new (no BETA-6 shot)`)
        continue
      }
      const d = await pixelDiff(page, readFileSync(old).toString('base64'), readFileSync(resolve(root, size, f)).toString('base64'))
      lines.push(`${n}  ${size}/${f}: ${(d.share * 100).toFixed(2)} % changed, ${d.nRegions} regions${d.regions.slice(0, 3).map((r) => ` ${r.w}x${r.h}@${r.x},${r.y}`).join('')}`)
    }
  }
  writeFileSync(resolve(root, 'pixel_diff.out'), lines.join('\n') + '\n')
  console.log(`${b}: ${n} shots diffed`)
}
await browser.close()
