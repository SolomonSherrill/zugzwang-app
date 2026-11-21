/**
 * A pixel diff of two PNGs, computed in a headless browser page (no image library): the share of
 * pixels whose largest channel differs by more than 32 (of 255), and the boxes of the regions where
 * they cluster (16 px cells holding 4 or more such pixels, joined when they touch), the largest
 * first. Shared by harness/browserCompare.ts (UI-BUILD-4 E) and harness/pixelDiff.ts (BETA-4).
 */
import type { Page } from 'playwright'
import type { Box } from './domProbe.ts'

export interface PixelResult { size: string; share: number; regions: Box[]; nRegions: number }
export async function pixelDiff(page: Page, a: string, b: string): Promise<PixelResult> {
  return page.evaluate(
    async ([a64, b64]) => {
      const load = async (s: string) => {
        const bin = Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
        const bmp = await createImageBitmap(new Blob([bin], { type: 'image/png' }))
        const c = new OffscreenCanvas(bmp.width, bmp.height)
        const g = c.getContext('2d')!
        g.drawImage(bmp, 0, 0)
        return { w: bmp.width, h: bmp.height, d: g.getImageData(0, 0, bmp.width, bmp.height).data }
      }
      const [x, y] = await Promise.all([load(a64), load(b64)])
      const w = Math.min(x.w, y.w)
      const h = Math.min(x.h, y.h)
      const C = 16
      const cw = Math.ceil(w / C)
      const ch = Math.ceil(h / C)
      const cells = new Uint16Array(cw * ch)
      let diff = 0
      for (let j = 0; j < h; j++)
        for (let i = 0; i < w; i++) {
          const p = (j * x.w + i) * 4
          const q = (j * y.w + i) * 4
          const m = Math.max(Math.abs(x.d[p] - y.d[q]), Math.abs(x.d[p + 1] - y.d[q + 1]), Math.abs(x.d[p + 2] - y.d[q + 2]))
          if (m > 32) {
            diff++
            cells[Math.floor(j / C) * cw + Math.floor(i / C)]++
          }
        }
      // pixels of one image outside the other's size count as differing
      const total = Math.max(x.w, y.w) * Math.max(x.h, y.h)
      diff += total - w * h
      const seen = new Uint8Array(cw * ch)
      const regions: { x: number; y: number; w: number; h: number; n: number }[] = []
      for (let s = 0; s < cells.length; s++) {
        if (cells[s] < 4 || seen[s]) continue
        let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1, n = 0
        const stack = [s]
        seen[s] = 1
        while (stack.length) {
          const t = stack.pop()!
          const ci = t % cw, cj = Math.floor(t / cw)
          x0 = Math.min(x0, ci); y0 = Math.min(y0, cj); x1 = Math.max(x1, ci); y1 = Math.max(y1, cj); n++
          for (let dj = -1; dj <= 1; dj++)
            for (let di = -1; di <= 1; di++) {
              const ni = ci + di, nj = cj + dj
              if (ni < 0 || nj < 0 || ni >= cw || nj >= ch) continue
              const u = nj * cw + ni
              if (!seen[u] && cells[u] >= 4) { seen[u] = 1; stack.push(u) }
            }
        }
        regions.push({ x: x0 * C, y: y0 * C, w: (x1 - x0 + 1) * C, h: (y1 - y0 + 1) * C, n })
      }
      regions.sort((p, q) => q.n - p.n)
      return {
        size: x.w === y.w && x.h === y.h ? `${x.w}x${x.h}` : `${x.w}x${x.h} vs ${y.w}x${y.h}`,
        share: diff / total,
        nRegions: regions.length,
        regions: regions.slice(0, 4).map(({ x, y, w, h }) => ({ x, y, w, h })),
      }
    },
    [a, b] as [string, string],
  )
}
