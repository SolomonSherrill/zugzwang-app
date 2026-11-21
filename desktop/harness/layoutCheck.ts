/**
 * The small-windows layout check (UI-BUILD-4 C, DESIGN.md fifth rulings, 2): run in the same
 * Playwright page as a sizes/ shot, it measures what a screenshot would show by eye. Each check
 * is a DOM measurement, so a re-run gives the same figures:
 *
 * - overflow: a horizontal scrollbar on the document, the content column, or any scroll box
 *   (scrollWidth > clientWidth);
 * - board: every visible board (cg-board) inside the viewport, and the board column's strips and
 *   navigator inside it too (nothing below the fold, nothing clipped by the column); the board
 *   drawn at the size of its box (.board), so strips, bar and navigator line up with it;
 * - sidebar: its width, and whether it is the icon rail;
 * - overlap: two visible interactive elements, neither inside the other, whose rects intersect
 *   where both are on view (each is hit at its own centre, so nothing under a dialog counts) and
 *   the hit test at the overlap finds one of them;
 * - unreachable: a control wholly below the window with no scroll box (nor the page) to reach it;
 * - wraps: a toolbar (role=toolbar) whose controls run onto a second line;
 * - clipped: an element with overflow hidden whose own text is wider than its box: "ellipsis" with a
 *   title (on it or a parent) is fine and not listed; ellipsis without a title, or a hard cut, is.
 */
import type { Page } from 'playwright'

export interface Rect { x: number; y: number; w: number; h: number }
export interface LayoutResult {
  viewport: { w: number; h: number }
  overflow: string[]
  board: { ok: boolean; notes: string[] }
  sidebar: { width: number; rail: boolean }
  overlaps: string[]
  /** controls wholly below the window in no box that scrolls */
  unreachable: string[]
  /** a toolbar whose controls run onto a second line */
  wraps: string[]
  clipped: string[]
  /** the layout blocks' horizontal geometry (for the 1440 x 900 vs 1440 x 940 comparison) */
  blocks: Record<string, Rect>
  scroll: { content: number; contentClient: number }
}

export async function checkLayout(page: Page): Promise<LayoutResult> {
  return page.evaluate(() => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const name = (el: Element): string => {
      const h = el as HTMLElement
      let s = el.tagName.toLowerCase()
      if (h.id) s += '#' + h.id
      const cls = [...el.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 2)
      if (cls.length) s += '.' + cls.join('.')
      const label = el.getAttribute('aria-label') ?? (h.innerText ?? '').trim().split('\n')[0]
      if (label) s += ' "' + label.slice(0, 40) + '"'
      return s
    }
    const r = (el: Element): { x: number; y: number; w: number; h: number } => {
      const b = el.getBoundingClientRect()
      return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }
    }
    const shown = (el: Element): boolean => {
      const b = el.getBoundingClientRect()
      if (b.width < 2 || b.height < 2) return false
      for (let e: Element | null = el; e; e = e.parentElement) {
        const cs = getComputedStyle(e)
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false
      }
      return true
    }
    /** the part of el's rect not cut off by an overflow-clipping ancestor or the viewport */
    const visibleRect = (el: Element) => {
      const b = el.getBoundingClientRect()
      let x0 = b.left, y0 = b.top, x1 = b.right, y1 = b.bottom
      for (let e = el.parentElement; e; e = e.parentElement) {
        const cs = getComputedStyle(e)
        if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
          const c = e.getBoundingClientRect()
          x0 = Math.max(x0, c.left); y0 = Math.max(y0, c.top); x1 = Math.min(x1, c.right); y1 = Math.min(y1, c.bottom)
        }
      }
      x0 = Math.max(x0, 0); y0 = Math.max(y0, 0); x1 = Math.min(x1, vw); y1 = Math.min(y1, vh)
      return { x0, y0, x1, y1, ok: x1 - x0 >= 2 && y1 - y0 >= 2 }
    }

    // overflow
    const overflow: string[] = []
    const de = document.documentElement
    if (de.scrollWidth > de.clientWidth + 1) overflow.push(`document ${de.scrollWidth} > ${de.clientWidth}`)
    for (const el of document.querySelectorAll('body *')) {
      if (el.closest('cg-container, svg, canvas')) continue
      const cs = getComputedStyle(el)
      if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1 && shown(el))
        overflow.push(`${name(el)} scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}`)
    }

    // the board
    const notes: string[] = []
    let ok = true
    const boards = [...document.querySelectorAll('cg-board')].filter(shown)
    for (const b of boards) {
      const q = b.getBoundingClientRect()
      if (q.top < -0.5 || q.left < -0.5 || q.bottom > vh + 0.5 || q.right > vw + 0.5) {
        ok = false
        notes.push(`board ${Math.round(q.width)}px at y ${Math.round(q.top)}..${Math.round(q.bottom)} outside the ${vw}x${vh} viewport`)
      } else notes.push(`board ${Math.round(q.width)}px, y ${Math.round(q.top)}..${Math.round(q.bottom)}`)
      // chessground draws a whole number of pixels per square: a box not a multiple of 8 leaves
      // the strips, the bar and the navigator a few px wider or taller than the board drawn
      const box = b.closest('.board')
      if (box) {
        const w = box.getBoundingClientRect()
        if (Math.abs(w.width - q.width) > 1 || Math.abs(w.height - q.height) > 1) {
          ok = false
          notes.push(`board drawn ${Math.round(q.width)}x${Math.round(q.height)} in a ${Math.round(w.width)}x${Math.round(w.height)} box`)
        }
      }
    }
    const col = document.querySelector('section[aria-label="Board"]')
    if (col && shown(col)) {
      const c = col.getBoundingClientRect()
      if (c.bottom > vh + 0.5) { ok = false; notes.push(`board column ends at ${Math.round(c.bottom)} > ${vh}`) }
      for (const el of col.querySelectorAll('*')) {
        if (el.closest('cg-container, svg')) continue
        if (!shown(el)) continue
        const q = el.getBoundingClientRect()
        if (q.bottom > Math.min(c.bottom, vh) + 0.5 || q.right > c.right + 0.5) {
          ok = false
          notes.push(`${name(el)} cut off (bottom ${Math.round(q.bottom)}, column bottom ${Math.round(c.bottom)})`)
          break
        }
      }
    }
    if (!boards.length) notes.push('no board on screen')

    // sidebar
    const sb = document.querySelector('nav.sidebar')
    const sidebar = { width: sb ? Math.round(sb.getBoundingClientRect().width) : 0, rail: !!sb?.classList.contains('rail') }

    // overlaps between interactive elements
    const SEL = 'button, a[href], input, select, textarea, [role=button], [role=tab], [role=radio], [role=slider], [role=option], [role=menuitem], [role=checkbox], [role=switch], [tabindex]:not([tabindex="-1"])'
    const inter = [...document.querySelectorAll(SEL)].filter((el) => shown(el) && !el.closest('cg-container')).map((el) => ({ el, v: visibleRect(el) })).filter((x) => x.v.ok)
    const overlaps: string[] = []
    const onTop = (el: Element, x: number, y: number) => {
      const hit = document.elementFromPoint(x, y)
      return !!hit && (hit === el || el.contains(hit))
    }
    for (let i = 0; i < inter.length; i++)
      for (let j = i + 1; j < inter.length; j++) {
        const a = inter[i], b = inter[j]
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue
        const x0 = Math.max(a.v.x0, b.v.x0), y0 = Math.max(a.v.y0, b.v.y0)
        const x1 = Math.min(a.v.x1, b.v.x1), y1 = Math.min(a.v.y1, b.v.y1)
        if (x1 - x0 < 1.5 || y1 - y0 < 1.5) continue
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
        // both visible somewhere (not under a dialog), and one drawn over the other here
        const ac = (a.v.x0 + a.v.x1) / 2, ay = (a.v.y0 + a.v.y1) / 2
        const bc = (b.v.x0 + b.v.x1) / 2, by = (b.v.y0 + b.v.y1) / 2
        if (!onTop(a.el, ac, ay) || !onTop(b.el, bc, by)) continue
        if (!onTop(a.el, cx, cy) && !onTop(b.el, cx, cy)) continue
        overlaps.push(`${name(a.el)} x ${name(b.el)}: ${Math.round(x1 - x0)}x${Math.round(y1 - y0)}px at (${Math.round(x0)}, ${Math.round(y0)})`)
      }

    // controls below the fold that no scroll box can bring into view
    const unreachable: string[] = []
    for (const el of document.querySelectorAll(SEL)) {
      if (!shown(el) || el.closest('cg-container')) continue
      const q = el.getBoundingClientRect()
      if (q.top < vh - 1) continue
      let scrolls = false
      for (let e = el.parentElement; e && !scrolls; e = e.parentElement) {
        const cs = getComputedStyle(e)
        if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') && e.scrollHeight > e.clientHeight + 1) scrolls = true
      }
      if (!scrolls && de.scrollHeight <= de.clientHeight + 1) unreachable.push(`${name(el)} at y ${Math.round(q.top)}`)
    }

    // a toolbar (the Games filter bar, Insights' filters) on more than one line
    const wraps: string[] = []
    for (const tb of document.querySelectorAll('[role=toolbar]')) {
      if (!shown(tb)) continue
      const tops = [...tb.children].filter((c) => shown(c)).map((c) => c.getBoundingClientRect().top)
      if (tops.length && Math.max(...tops) - Math.min(...tops) > 6) wraps.push(`${name(tb)}: children from y ${Math.round(Math.min(...tops))} to ${Math.round(Math.max(...tops))}`)
    }

    // clipped text
    const clipped: string[] = []
    for (const el of document.querySelectorAll('body *')) {
      if (el.closest('cg-container, svg, canvas, .sr, .sr-only')) continue
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent ?? '').trim())
      if (!own || !shown(el)) continue
      const cs = getComputedStyle(el)
      const hidden = (v: string) => v === 'hidden' || v === 'clip'
      const h = el as HTMLElement
      if (cs.position === 'absolute' && h.clientWidth <= 1) continue
      const wide = hidden(cs.overflowX) && el.scrollWidth > el.clientWidth + 1
      const tall = hidden(cs.overflowY) && el.scrollHeight > el.clientHeight + 2 && cs.webkitLineClamp === 'none'
      if (!wide && !tall) continue
      if (cs.textOverflow === 'ellipsis' || cs.webkitLineClamp !== 'none') {
        const titled = !!el.closest('[title]') || !!el.getAttribute('aria-label')
        if (titled) continue
        clipped.push(`${name(el)}: ellipsis, no title (${el.scrollWidth} > ${el.clientWidth})`)
      } else clipped.push(`${name(el)}: cut off (${wide ? 'width ' + el.scrollWidth + ' > ' + el.clientWidth : 'height ' + el.scrollHeight + ' > ' + el.clientHeight})`)
    }

    // layout blocks: the sidebar, the content column, and the screen's children two levels down
    const blocks: Record<string, { x: number; y: number; w: number; h: number }> = {}
    if (sb) blocks['sidebar'] = r(sb)
    const main = document.querySelector('main.content')
    if (main) {
      blocks['content'] = r(main)
      const screens = [...main.children].filter(shown)
      screens.forEach((s, i) => {
        blocks[`screen${i} ${name(s).slice(0, 30)}`] = r(s)
        ;[...s.children].filter(shown).forEach((c, k) => {
          blocks[`  ${k} ${name(c).slice(0, 40)}`] = r(c)
          ;[...c.children].filter(shown).slice(0, 6).forEach((d, m) => (blocks[`    ${k}.${m} ${name(d).slice(0, 40)}`] = r(d)))
        })
      })
    }
    const scroller = main as HTMLElement | null
    return {
      viewport: { w: vw, h: vh },
      overflow,
      board: { ok, notes },
      sidebar,
      overlaps,
      unreachable,
      wraps,
      clipped: [...new Set(clipped)],
      blocks,
      scroll: { content: scroller?.scrollHeight ?? 0, contentClient: scroller?.clientHeight ?? 0 },
    }
  })
}

/** 1440 x 900 against 1440 x 940: the blocks whose x or width moved (height is free to). */
export function compareWidths(a: Record<string, Rect>, b: Record<string, Rect>): string[] {
  const out: string[] = []
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    const p = a[k], q = b[k]
    if (!p || !q) { out.push(`${k.trim()}: only at ${p ? '900' : '940'}`); continue }
    if (Math.abs(p.x - q.x) > 1 || Math.abs(p.w - q.w) > 1) out.push(`${k.trim()}: x ${p.x} w ${p.w} at 900, x ${q.x} w ${q.w} at 940`)
  }
  return out
}

/** One shot's lines in layout_check.out. */
export function formatResult(id: string, res: LayoutResult, vs940?: string[]): string {
  const L: string[] = [`== ${id} (${res.viewport.w}x${res.viewport.h})`]
  L.push(`  sidebar: ${res.sidebar.width}px${res.sidebar.rail ? ' (icon rail)' : ''}`)
  L.push(`  horizontal overflow: ${res.overflow.length ? 'FAIL' : 'none'}`)
  for (const o of res.overflow) L.push(`    ${o}`)
  L.push(`  board: ${res.board.notes.length && res.board.notes[0] === 'no board on screen' ? 'no board' : res.board.ok ? 'fully visible' : 'FAIL'}`)
  for (const n of res.board.notes) if (n !== 'no board on screen') L.push(`    ${n}`)
  L.push(`  content scroll height: ${res.scroll.content} (visible ${res.scroll.contentClient})${res.scroll.content > res.scroll.contentClient + 1 ? ', scrolls' : ''}`)
  L.push(`  overlapping interactive elements: ${res.overlaps.length ? 'FAIL ' + res.overlaps.length : 'none'}`)
  for (const o of res.overlaps) L.push(`    ${o}`)
  L.push(`  controls below the fold with no scroll to reach them: ${res.unreachable.length ? 'FAIL ' + res.unreachable.length : 'none'}`)
  for (const u of res.unreachable) L.push(`    ${u}`)
  L.push(`  toolbars on more than one line: ${res.wraps.length ? 'FAIL ' + res.wraps.length : 'none'}`)
  for (const u of res.wraps) L.push(`    ${u}`)
  L.push(`  clipped text: ${res.clipped.length ? 'FAIL ' + res.clipped.length : 'none'}`)
  for (const c of res.clipped) L.push(`    ${c}`)
  if (vs940) {
    L.push(`  vs 1440x940, x and width: ${vs940.length ? 'CHANGED ' + vs940.length : 'unchanged'}`)
    for (const d of vs940) L.push(`    ${d}`)
  }
  return L.join('\n')
}
