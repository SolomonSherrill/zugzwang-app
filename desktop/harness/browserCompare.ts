/**
 * The WebKit pass's comparison (UI-BUILD-4 E): each shot taken in WebKit against the same shot
 * taken in Chromium, without anyone reading the PNGs. For each pair, in a headless Chromium page:
 * the share of pixels whose largest channel differs by more than 32 (of 255), and the boxes of the
 * regions where they cluster (16 px cells holding 4 or more such pixels, joined when they touch);
 * then the DOM measurements both runs wrote (harness/domProbe.ts): the main regions' boxes, the
 * text elements whose box or computed font differs, text wider than its box in one browser only,
 * scroll boxes that overflow, the fonts loaded, figures run into words.
 *
 *   cd desktop && ZUGZWANG_HARNESS_OUT=<chromium dir> ZUGZWANG_HARNESS_MOCKUPS=0 \
 *     ZUGZWANG_HARNESS_DOM=<chromium.json> node harness/shoot.ts
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_DOM=<webkit.json> node harness/shoot.ts
 *   cd desktop && node harness/browserCompare.ts <chromium.json> <webkit.json> [out]
 *
 * The out file defaults to review/scratch/ui/webkit/compare.out.
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import type { DomProbe, Box } from './domProbe.ts'
import { pixelDiff, type PixelResult } from './pixels.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const [aFile, bFile, outArg] = process.argv.slice(2)
if (!aFile || !bFile) throw new Error('usage: node harness/browserCompare.ts <chromium.json> <webkit.json> [out]')
const out = outArg ?? resolve(repo, 'review', 'scratch', 'ui', 'webkit', 'compare.out')
type Run = { browser: string; root: string; shots: Record<string, DomProbe> }
const A: Run = JSON.parse(readFileSync(aFile, 'utf8'))
const B: Run = JSON.parse(readFileSync(bFile, 'utf8'))

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.setContent('<body></body>')

const pixels = (a: string, b: string): Promise<PixelResult> => pixelDiff(page, a, b)

const fmtBox = (b: Box) => `${b.w}x${b.h}@${b.x},${b.y}`
function domDiff(a: DomProbe, b: DomProbe): string[] {
  const lines: string[] = []
  const reg: string[] = []
  for (const [k, ra] of Object.entries(a.regions)) {
    const rb = b.regions[k]
    if (!rb) { reg.push(`${k}: only in Chromium`); continue }
    const dm = Math.max(Math.abs(ra.x - rb.x), Math.abs(ra.y - rb.y), Math.abs(ra.w - rb.w), Math.abs(ra.h - rb.h))
    if (dm > 1) reg.push(`${k}: ${fmtBox(ra)} -> ${fmtBox(rb)}`)
  }
  for (const k of Object.keys(b.regions)) if (!a.regions[k]) reg.push(`${k}: only in WebKit`)
  if (reg.length) lines.push(`regions (${reg.length}): ` + reg.slice(0, 6).join('; ') + (reg.length > 6 ? '; ...' : ''))
  let moved = 0
  const big: [number, string][] = []
  const fonts = new Set<string>()
  const over: string[] = []
  let onlyA = 0, onlyB = 0
  for (const [k, ta] of Object.entries(a.texts)) {
    const tb = b.texts[k]
    if (!tb) { onlyA++; continue }
    const dw = tb.w - ta.w
    const dm = Math.max(Math.abs(ta.x - tb.x), Math.abs(ta.y - tb.y), Math.abs(dw), Math.abs(ta.h - tb.h))
    if (dm > 1) { moved++; big.push([dm, `${ta.name} ${fmtBox(ta)} -> ${fmtBox(tb)}`]) }
    if (ta.font !== tb.font) fonts.add(`${ta.name}: ${ta.font} -> ${tb.font}`)
    if (!ta.over && tb.over) over.push(`${tb.name} +${tb.over}px`)
    if (ta.over && !tb.over) over.push(`${ta.name} fits in WebKit (Chromium +${ta.over}px)`)
  }
  for (const k of Object.keys(b.texts)) if (!a.texts[k]) onlyB++
  const n = Object.keys(a.texts).length
  big.sort((p, q) => q[0] - p[0])
  lines.push(`text: ${n} elements, ${moved} moved or resized > 1 px` + (onlyA || onlyB ? `, ${onlyA} only in Chromium, ${onlyB} only in WebKit` : '') +
    (big.length ? '; largest: ' + big.slice(0, 3).map((x) => x[1]).join('; ') : ''))
  if (fonts.size) lines.push(`computed font differs: ${[...fonts].slice(0, 4).join('; ')}`)
  if (over.length) lines.push(`text wider than its box in one browser only: ${over.slice(0, 5).join('; ')}`)
  const sa = new Set(a.scrollX), sb = new Set(b.scrollX)
  const sx = [...[...sb].filter((x) => !sa.has(x)).map((x) => 'WebKit ' + x), ...[...sa].filter((x) => !sb.has(x)).map((x) => 'Chromium ' + x)]
  if (sx.length) lines.push(`scroll boxes wider than their box: ${sx.join('; ')}`)
  if (a.doc.sh > a.doc.ch + 1 || b.doc.sh > b.doc.ch + 1 || a.doc.sw > a.doc.cw + 1 || b.doc.sw > b.doc.cw + 1)
    lines.push(`the page itself scrolls (the app scrolls inside its content column): Chromium ${a.doc.sw}x${a.doc.sh} in ${a.doc.cw}x${a.doc.ch}, WebKit ${b.doc.sw}x${b.doc.sh} in ${b.doc.cw}x${b.doc.ch}`)
  else if (a.doc.sw !== b.doc.sw || a.doc.sh !== b.doc.sh) lines.push(`document ${a.doc.sw}x${a.doc.sh} -> ${b.doc.sw}x${b.doc.sh}`)
  if (a.fonts.faces.join() !== b.fonts.faces.join() || a.fonts.geist !== b.fonts.geist)
    lines.push(`fonts: Chromium [${a.fonts.faces.join(', ')}] geist ${a.fonts.geist}; WebKit [${b.fonts.faces.join(', ')}] geist ${b.fonts.geist}`)
  const glued = [...new Set([...(a.glued ?? []), ...(b.glued ?? [])])]
  if (glued.length) lines.push(`figure run into a word: ${glued.map((g) => JSON.stringify(g)).join(', ')}`)
  return lines
}

const rows: string[] = []
let n = 0
const shares: number[] = []
for (const id of Object.keys(B.shots)) {
  const a = A.shots[id]
  const b = B.shots[id]
  const [dir, name] = [id.slice(0, id.lastIndexOf('/')), id.slice(id.lastIndexOf('/') + 1)]
  const pa = resolve(A.root, dir, `${name}-app.png`)
  const pb = resolve(B.root, dir, `${name}-app.png`)
  if (!a || !existsSync(pa) || !existsSync(pb)) { rows.push(`${id}: no Chromium shot to compare`); continue }
  const px = await pixels(readFileSync(pa).toString('base64'), readFileSync(pb).toString('base64'))
  shares.push(px.share)
  n++
  rows.push(
    `${id}  ${px.size}  differing ${(px.share * 100).toFixed(2)} %  regions ${px.nRegions}` +
      (px.regions.length ? ': ' + px.regions.map(fmtBox).join(', ') : '') +
      '\n' + domDiff(a, b).map((l) => '    ' + l).join('\n'),
  )
}
await browser.close()
shares.sort((p, q) => p - q)
const head = [
  `# WebKit against Chromium, ${n} shots (harness/browserCompare.ts, UI-BUILD-4 E).`,
  `# Chromium: ${A.root}`,
  `# WebKit:   ${B.root}`,
  '# Per shot: size; the share of pixels whose largest channel differs by > 32/255; the regions where',
  '# they cluster (w x h @ x,y, the four largest); then DOM differences (none listed = the same).',
  `# Differing share over all shots: median ${(shares[Math.floor(shares.length / 2)] * 100).toFixed(2)} %, max ${(shares[shares.length - 1] * 100).toFixed(2)} %.`,
]
writeFileSync(out, head.join('\n') + '\n\n' + rows.join('\n') + '\n')
console.log(`compare: ${out} (${n} shots)`)
