/**
 * COACH-2: pixel diffs of one shot folder against an earlier one, through harness/pixels.ts (DESIGN.md "Owner rulings,
 * 2026-11-21", 1: layout is reported as numbers). For each <browser>/<size>/<name>.png under <new root>, the same path
 * under <old root>; writes <new root>/<browser>/pixel_diff.out.
 *
 *   cd desktop && node harness/dirDiff.ts <new root> <old root> [<older root>...]
 *
 * With several old roots, each shot is diffed against the first that has it (the newest first), and the line names it.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'
import { chromium } from 'playwright'
import { pixelDiff } from './pixels.ts'

const [newRoot, ...oldRoots] = process.argv.slice(2).map((p) => resolve(p))
if (!newRoot || !oldRoots.length) throw new Error('usage: node harness/dirDiff.ts <new root> <old root> [<older root>...]')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.setContent('<body></body>')
for (const b of ['chromium', 'webkit']) {
  const root = resolve(newRoot, b)
  if (!existsSync(root)) continue
  const lines = [`# ${b}: each shot against the first of ${oldRoots.map((o) => relative(newRoot, resolve(o, b)) + '/').join(', ')} that has it, share of pixels changed (any channel > 32 of 255), regions WxH@x,y`]
  let n = 0
  for (const size of readdirSync(root).filter((d) => /^\d+x\d+$/.test(d)).sort()) {
    for (const f of readdirSync(resolve(root, size)).filter((f) => f.endsWith('.png')).sort()) {
      const oldRoot = oldRoots.find((o) => existsSync(resolve(o, b, size, f)))
      const old = oldRoot ? resolve(oldRoot, b, size, f) : ''
      n++
      if (!oldRoot) {
        lines.push(`${n}  ${size}/${f}: new (no earlier shot)`)
        continue
      }
      const d = await pixelDiff(page, readFileSync(old).toString('base64'), readFileSync(resolve(root, size, f)).toString('base64'))
      lines.push(`${n}  ${size}/${f} (vs ${relative(resolve(newRoot, '..'), oldRoot)}): ${(d.share * 100).toFixed(2)} % changed, ${d.nRegions} regions${d.regions.slice(0, 3).map((r) => ` ${r.w}x${r.h}@${r.x},${r.y}`).join('')}`)
    }
  }
  writeFileSync(resolve(root, 'pixel_diff.out'), lines.join('\n') + '\n')
  console.log(`${b}: ${n} shots diffed`)
}
await browser.close()
