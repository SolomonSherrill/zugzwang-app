/**
 * Pixel diffs against the previous shots (BETA-4; DESIGN.md "Owner rulings, 2026-11-21", 1: layout
 * is checked by code and reported as numbers, nobody reads the PNGs). For each PNG given, its
 * committed version at <ref> (git show) against the file in the working tree, through
 * harness/pixels.ts: the share of pixels changed and the largest changed regions.
 *
 *   cd desktop && node harness/pixelDiff.ts <ref> <png>... [--out <file>]
 *
 * Paths are relative to the repository root or absolute. A PNG not in <ref> is reported as new.
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { pixelDiff } from './pixels.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const args = process.argv.slice(2)
const oi = args.indexOf('--out')
const out = oi >= 0 ? resolve(args[oi + 1]) : null
if (oi >= 0) args.splice(oi, 2)
const [ref, ...pngs] = args
if (!ref || !pngs.length) throw new Error('usage: node harness/pixelDiff.ts <ref> <png>... [--out <file>]')

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.setContent('<body></body>')
const lines = [`# Pixel diff against ${ref} (harness/pixelDiff.ts): share of pixels changed (any channel > 32 of 255), regions as WxH@x,y`]
try {
  for (const p of pngs) {
    const rel = relative(repo, resolve(repo, p))
    let old: Buffer
    try {
      old = execFileSync('git', ['show', `${ref}:${rel}`], { cwd: repo, maxBuffer: 64 << 20 })
    } catch {
      lines.push(`${rel}: new (not in ${ref})`)
      continue
    }
    const now = readFileSync(resolve(repo, rel))
    const r = await pixelDiff(page, old.toString('base64'), now.toString('base64'))
    const regs = r.regions.map((b) => `${b.w}x${b.h}@${b.x},${b.y}`).join(' ')
    lines.push(`${rel}: ${r.size}, ${(r.share * 100).toFixed(2)} % changed, ${r.nRegions} regions${regs ? ': ' + regs : ''}`)
  }
} finally {
  await browser.close()
}
const text = lines.join('\n') + '\n'
if (out) writeFileSync(out, text)
process.stdout.write(text)
