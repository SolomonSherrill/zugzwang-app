/**
 * A popover placed so no ancestor clips it (BETA-6 B): `use:floating` on the popover's wrapper fixes it to the
 * window at its anchor (the wrapper's parent element when mounted), below the anchor when it fits, otherwise
 * above, otherwise inside the window on the side with more room (over the anchor's row); its right edge on the anchor's, kept 8 px inside the window.
 * `position: fixed` escapes the `overflow: hidden` of the panels it sits in (the friends list's `.panel` clipped
 * the Challenge popover of a friend's row, while its veil still caught every click). It follows scrolling and
 * resizing. `data-side` says where it went (below, above, inside), for the tests.
 */
export interface FloatingOptions {
  /** px between the anchor and the popover */
  gap?: number
  /** px kept between the popover and the window's edges */
  margin?: number
}

export function floating(node: HTMLElement, opts: FloatingOptions = {}) {
  const anchor = node.parentElement
  const gap = opts.gap ?? 4
  const margin = opts.margin ?? 8
  function place() {
    if (!anchor) return
    const a = anchor.getBoundingClientRect()
    const w = node.offsetWidth
    const h = node.offsetHeight
    const vw = document.documentElement.clientWidth
    const vh = document.documentElement.clientHeight
    const below = a.bottom + gap + h <= vh - margin
    const above = a.top - gap - h >= margin
    // neither fits (a 488 px popover by a row mid-window at 720 px): inside the window, on the roomier side
    const roomier = a.top > vh - a.bottom ? margin : vh - margin - h
    const top = below ? a.bottom + gap : above ? a.top - gap - h : Math.max(margin, roomier)
    const left = Math.max(margin, Math.min(vw - margin - w, a.right - w))
    node.style.position = 'fixed'
    node.style.top = `${Math.round(top)}px`
    node.style.left = `${Math.round(left)}px`
    node.style.right = 'auto'
    node.style.bottom = 'auto'
    node.dataset.side = below ? 'below' : above ? 'above' : 'inside'
  }
  place()
  const ro = new ResizeObserver(place)
  ro.observe(node)
  if (anchor) ro.observe(anchor)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', place, true)
  return {
    destroy() {
      ro.disconnect()
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    },
  }
}
