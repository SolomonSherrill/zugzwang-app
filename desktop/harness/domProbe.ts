/**
 * DOM measurements of a harness page (UI-BUILD-4 E, the WebKit pass), taken in the same page as a
 * shot so two browsers' renderings of one state can be compared without reading the PNGs: the
 * main regions' boxes, every visible element with its own text (box, computed font, and whether
 * its text is wider than its box), the scroll boxes that overflow, and the fonts the page loaded.
 * Elements are keyed by their path from <body> (tag and index among siblings), the same in both
 * browsers when the DOM is. harness/shoot.ts writes them with ZUGZWANG_HARNESS_DOM=<file.json>;
 * harness/browserCompare.ts compares two such files.
 */
import type { Page } from 'playwright'

export interface Box { x: number; y: number; w: number; h: number }
export interface TextEl extends Box {
  name: string
  font: string
  /** scrollWidth - clientWidth when the text is wider than its box (0 when it fits) */
  over: number
}
export interface DomProbe {
  viewport: { w: number; h: number }
  doc: { sw: number; cw: number; sh: number; ch: number }
  fonts: { faces: string[]; geist: boolean; body: string }
  regions: Record<string, Box>
  texts: Record<string, TextEl>
  /** scroll boxes (overflow auto/scroll) whose content is wider than the box */
  scrollX: string[]
  /** a figure run into a word in the rendered text ("0of 1": Svelte drops a space that starts an element) */
  glued: string[]
}

export async function probeDom(page: Page): Promise<DomProbe> {
  return page.evaluate(() => {
    const round = (n: number) => Math.round(n * 2) / 2
    const box = (el: Element) => {
      const b = el.getBoundingClientRect()
      return { x: round(b.x), y: round(b.y), w: round(b.width), h: round(b.height) }
    }
    const path = (el: Element): string => {
      const parts: string[] = []
      for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
        const p: Element | null = e.parentElement
        const i = p ? [...p.children].indexOf(e) : 0
        parts.push(e.tagName.toLowerCase() + ':' + i)
      }
      return parts.reverse().join('>')
    }
    const name = (el: Element): string => {
      let s = el.tagName.toLowerCase()
      const cls = [...el.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 2)
      if (cls.length) s += '.' + cls.join('.')
      const label = el.getAttribute('aria-label') ?? (el.textContent ?? '').trim().replace(/\s+/g, ' ')
      if (label) s += ' "' + label.slice(0, 32) + '"'
      return s
    }
    const shown = (el: Element): boolean => {
      const b = el.getBoundingClientRect()
      if (b.width < 1 || b.height < 1) return false
      const cs = getComputedStyle(el)
      return cs.visibility !== 'hidden' && cs.display !== 'none' && el.checkVisibility?.({ opacityProperty: true }) !== false
    }
    const regions: Record<string, { x: number; y: number; w: number; h: number }> = {}
    const REGION = 'nav.sidebar, main.content, header, h1, cg-board, .board, section[aria-label], aside, [role=tabpanel], [role=tablist], [role=toolbar], [role=dialog], [role=slider], table, [role=grid]'
    const seen = new Map<string, number>()
    for (const el of document.querySelectorAll(REGION)) {
      if (!shown(el)) continue
      let k = name(el).slice(0, 48)
      const n = seen.get(k) ?? 0
      seen.set(k, n + 1)
      if (n) k += ' #' + (n + 1)
      regions[k] = box(el)
    }
    const texts: Record<string, { x: number; y: number; w: number; h: number; name: string; font: string; over: number }> = {}
    const scrollX: string[] = []
    for (const el of document.querySelectorAll('body *')) {
      if (el.closest('cg-container')) continue
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent ?? '').trim())
      const cs = getComputedStyle(el)
      if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1 && shown(el))
        scrollX.push(name(el) + ' ' + el.scrollWidth + ' > ' + el.clientWidth)
      if (!own || !shown(el)) continue
      const h = el as HTMLElement
      const over = el instanceof SVGElement || cs.display === 'inline' ? 0 : Math.max(0, h.scrollWidth - h.clientWidth)
      texts[path(el)] = {
        ...box(el),
        name: name(el),
        font: [cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), cs.fontSize, cs.fontWeight, cs.fontVariantNumeric].join(' '),
        over: over > 1 ? over : 0,
      }
    }
    const de = document.documentElement
    return {
      viewport: { w: innerWidth, h: innerHeight },
      doc: { sw: de.scrollWidth, cw: de.clientWidth, sh: de.scrollHeight, ch: de.clientHeight },
      fonts: {
        faces: [...document.fonts].map((f) => f.family.replace(/["']/g, '') + ' ' + f.weight + ' ' + f.status).sort(),
        geist: document.fonts.check('13px Geist'),
        body: getComputedStyle(document.body).fontFamily,
      },
      regions,
      texts,
      scrollX,
      glued: [...new Set([...(document.body.innerText.matchAll(/.{0,12}\d(?:of|to|in|out|vs|moves|games)\b.{0,12}/g))].map((m) => m[0]))],
    }
  })
}
