/**
 * BETA-5 B: Tauri's macOS webview ignores an `<a download>` link (and so a blob from createObjectURL
 * handed to one): "Save as a file" on the recovery code did nothing in the app. Files are saved through
 * the dialog plugin's save() (lib/pick.ts) and written by the sidecar. This fails if anything under
 * desktop/src goes back to either.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const src = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const self = fileURLToPath(import.meta.url)

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return files(p)
    return /\.(svelte|ts|js|html)$/.test(n) && p !== self ? [p] : []
  })
}

const PATTERNS: [string, RegExp][] = [
  ['an <a download> link', /<a\b[^>]*\sdownload\b/i],
  ['a download attribute set from script', /\.download\s*=|setAttribute\(\s*['"]download['"]/],
  ['URL.createObjectURL', /createObjectURL/],
]

describe('no download links in the webview (BETA-5 B)', () => {
  const all = files(src)
  it('reads the source tree', () => {
    expect(all.length).toBeGreaterThan(100)
    expect(all.some((f) => f.endsWith('RecoveryView.svelte'))).toBe(true)
  })
  for (const [what, re] of PATTERNS) {
    it(`nothing under desktop/src uses ${what}`, () => {
      const hits = all.filter((f) => re.test(readFileSync(f, 'utf8'))).map((f) => relative(src, f))
      expect(hits).toEqual([])
    })
  }
  it('the patterns catch what RecoveryView used to do', () => {
    const old = "const a = document.createElement('a')\na.href = URL.createObjectURL(blob)\na.download = 'x.txt'"
    expect(PATTERNS.filter(([, re]) => re.test(old)).length).toBe(2)
    expect(PATTERNS[0][1].test('<a href="x" download>save</a>')).toBe(true)
  })
})
