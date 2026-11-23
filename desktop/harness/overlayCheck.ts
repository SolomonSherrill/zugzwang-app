/**
 * BETA-6's layout checks (FRIENDS.md "BETA-6: the spec", B), measured in the page:
 *
 * - topmost(selector): every popover, dialog, menu and banner is the topmost element at its centre and at each
 *   corner (document.elementFromPoint; the corner points sit inside the border radius, so a rounded corner's
 *   empty pixel is not mistaken for something on top), and every one of those points is inside the window.
 * - names(): with the longest names allowed (harness ?names=long, longNames.ts), no two text boxes overlap (each
 *   text node's rendered boxes, clipped by every ancestor that clips and by the window; boxes in different layers,
 *   such as a popover over the page, are not compared), and every name cut short ends in "…" (text-overflow:
 *   ellipsis on the box that clips it) and carries its full text in a tooltip (a title on it or an ancestor).
 *   A name whose text runs out of the window with nothing clipping it is reported too.
 */
import type { Page } from 'playwright'

export interface PointHit { at: string; x: number; y: number; ok: boolean; hit: string }
export interface TopmostResult { selector: string; found: boolean; box: number[] | null; points: PointHit[]; failures: string[] }
export interface NamesResult { texts: number; names: number; cut: number; overlaps: string[]; failures: string[] }

export async function topmost(page: Page, selector: string): Promise<TopmostResult> {
  return page.evaluate((sel) => {
    const describe = (el: Element | null): string => {
      if (!el) return 'nothing'
      let s = el.tagName.toLowerCase()
      const cls = [...el.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 2)
      if (cls.length) s += '.' + cls.join('.')
      const role = el.getAttribute('role')
      if (role) s += '[role=' + role + ']'
      return s
    }
    const el = [...document.querySelectorAll(sel)].find((e) => {
      const r = e.getBoundingClientRect()
      return r.width > 0 && r.height > 0
    })
    if (!el) return { selector: sel, found: false, box: null, points: [], failures: ['not shown: ' + sel] }
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    const radius = Math.max(...[cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomLeftRadius, cs.borderBottomRightRadius].map((v) => parseFloat(v) || 0))
    const inset = Math.max(2, Math.ceil(radius * 0.3) + 1)
    const pts: [string, number, number][] = [
      ['centre', r.left + r.width / 2, r.top + r.height / 2],
      ['top left', r.left + inset, r.top + inset],
      ['top right', r.right - inset, r.top + inset],
      ['bottom left', r.left + inset, r.bottom - inset],
      ['bottom right', r.right - inset, r.bottom - inset],
    ]
    const vw = document.documentElement.clientWidth
    const vh = document.documentElement.clientHeight
    const points = pts.map(([at, x, y]) => {
      const inside = x >= 0 && y >= 0 && x < vw && y < vh
      const hit = inside ? document.elementFromPoint(x, y) : null
      const ok = inside && !!hit && el.contains(hit)
      return { at, x: Math.round(x), y: Math.round(y), ok, hit: inside ? describe(hit) : 'outside the window' }
    })
    return {
      selector: sel,
      found: true,
      box: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
      points,
      failures: points.filter((p) => !p.ok).map((p) => `${describe(el)} ${p.at} (${p.x}, ${p.y}): ${p.hit} is on top`),
    }
  }, selector)
}

export async function names(page: Page): Promise<NamesResult> {
  return page.evaluate(() => {
    const known = [...((window as unknown as { __longNames?: Map<string, string> }).__longNames?.values() ?? [])]
    try {
      const acc = JSON.parse(localStorage.getItem('zugzwang-accounts') ?? '{}') as Record<string, string>
      for (const v of Object.values(acc)) if (v) known.push(v)
    } catch {
      /* none */
    }
    const RUN = /W{8,}[A-Z0-9]{0,3}/g // longNames.ts: W's, then three characters that are never W
    const describe = (el: Element | null): string => {
      if (!el) return 'nothing'
      let s = el.tagName.toLowerCase()
      const cls = [...el.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 2)
      if (cls.length) s += '.' + cls.join('.')
      const p = el.parentElement
      if (p) {
        const pc = [...p.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 1)
        s = p.tagName.toLowerCase() + (pc.length ? '.' + pc[0] : '') + ' > ' + s
      }
      return s
    }
    const layerOf = (el: Element): Element | null =>
      el.closest('[role=dialog], [role=alertdialog], [role=menu], [role=listbox], .banners, .popat, .veil')
    const vw = document.documentElement.clientWidth
    const vh = document.documentElement.clientHeight
    type R = { l: number; t: number; r: number; b: number }
    const clipOf = (el: Element): { rect: R; by: Element | null } => {
      let rect: R = { l: 0, t: 0, r: vw, b: vh }
      let by: Element | null = null
      for (let e: Element | null = el; e && e !== document.documentElement; e = e.parentElement) {
        const cs = getComputedStyle(e)
        if (cs.position === 'fixed') break
        if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
          const b = e.getBoundingClientRect()
          const c = { l: b.left + e.clientLeft, t: b.top + e.clientTop, r: b.left + e.clientLeft + e.clientWidth, b: b.top + e.clientTop + e.clientHeight }
          const next = {
            l: cs.overflowX !== 'visible' ? Math.max(rect.l, c.l) : rect.l,
            r: cs.overflowX !== 'visible' ? Math.min(rect.r, c.r) : rect.r,
            t: cs.overflowY !== 'visible' ? Math.max(rect.t, c.t) : rect.t,
            b: cs.overflowY !== 'visible' ? Math.min(rect.b, c.b) : rect.b,
          }
          if (!by && (next.l > rect.l || next.r < rect.r || next.t > rect.t || next.b < rect.b)) by = e
          rect = next
        }
      }
      return { rect, by }
    }
    const boxes: { el: Element; layer: Element | null; r: R; node: number }[] = []
    const failures: string[] = []
    let nameCount = 0
    let cut = 0
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    let i = 0
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.textContent ?? ''
      if (!text.trim()) continue
      const el = n.parentElement
      if (!el || el.closest('script, style, svg, cg-board, coords, [aria-hidden=true] svg')) continue
      if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue
      const range = document.createRange()
      range.selectNodeContents(n)
      const full = [...range.getClientRects()].filter((q) => q.width >= 1 && q.height >= 1)
      if (!full.length) continue
      const { rect: clip, by } = clipOf(el)
      const id = i++
      let visibleW = 0
      let fullW = 0
      for (const q of full) {
        fullW += q.width
        const r = { l: Math.max(q.left, clip.l), t: Math.max(q.top, clip.t), r: Math.min(q.right, clip.r), b: Math.min(q.bottom, clip.b) }
        if (r.r - r.l >= 2 && r.b - r.t >= 2) {
          boxes.push({ el, layer: layerOf(el), r, node: id })
          visibleW += r.r - r.l
        }
      }
      const runs = text.match(RUN)
      if (!runs) continue
      nameCount += runs.length
      const shownAtAll = visibleW > 0
      const isCut = shownAtAll && visibleW < fullW - 1
      const truncatedByCode = /W{8,}…/.test(text)
      if (!isCut && !truncatedByCode) continue
      cut++
      const titleEl = el.closest('[title]')
      const title = titleEl?.getAttribute('title') ?? ''
      for (const run of runs) {
        const fullName = known.find((k) => k.startsWith(run.replace(/…$/, ''))) ?? run
        if (!title.includes(fullName)) failures.push(`${describe(el)} "${run.slice(0, 12)}…": cut short with no tooltip holding the full name`)
      }
      if (isCut) {
        if (!by) failures.push(`${describe(el)} "${runs[0].slice(0, 12)}…": runs out of the window, nothing cuts it with "…"`)
        else if (getComputedStyle(by).textOverflow !== 'ellipsis') failures.push(`${describe(el)} "${runs[0].slice(0, 12)}…": cut by ${describe(by)} without "…" (text-overflow: ${getComputedStyle(by).textOverflow})`)
      }
    }
    const overlaps: string[] = []
    for (let a = 0; a < boxes.length; a++) {
      for (let b = a + 1; b < boxes.length; b++) {
        const A = boxes[a]
        const B = boxes[b]
        if (A.node === B.node || A.layer !== B.layer) continue
        const w = Math.min(A.r.r, B.r.r) - Math.max(A.r.l, B.r.l)
        const h = Math.min(A.r.b, B.r.b) - Math.max(A.r.t, B.r.t)
        if (w > 1 && h > 1) {
          const msg = `${describe(A.el)} "${(A.el.textContent ?? '').trim().slice(0, 24)}" and ${describe(B.el)} "${(B.el.textContent ?? '').trim().slice(0, 24)}" overlap by ${Math.round(w)} x ${Math.round(h)} px`
          if (!overlaps.includes(msg)) overlaps.push(msg)
        }
      }
    }
    return { texts: i, names: nameCount, cut, overlaps, failures: [...failures, ...overlaps] }
  })
}
