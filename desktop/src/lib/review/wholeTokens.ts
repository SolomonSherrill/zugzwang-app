/**
 * A Svelte action for a one-line row of tokens (a collapsed engine line, BETA-4 C): the children
 * that do not fit whole are hidden, so no move is cut mid-word, and a move number left last is
 * hidden with the move it numbers. Re-fits when the row's width changes and when the parameter (the
 * row's text) changes.
 */
export function fitTokens(node: HTMLElement): number {
  const kids = [...node.children] as HTMLElement[]
  for (const k of kids) k.style.display = ''
  const right = node.getBoundingClientRect().right + 0.5
  let shown = kids.length
  for (let i = 0; i < kids.length; i++) {
    if (kids[i].getBoundingClientRect().right > right) {
      shown = i
      break
    }
  }
  // a number ("35.", "34…") does not end the row without its move
  while (shown > 0 && /^\d+(\.|…)$/.test(kids[shown - 1].textContent ?? '')) shown--
  for (let i = shown; i < kids.length; i++) kids[i].style.display = 'none'
  return shown
}

export function wholeTokens(node: HTMLElement, _text?: string) {
  const ro = new ResizeObserver(() => fitTokens(node))
  ro.observe(node)
  fitTokens(node)
  return {
    update() {
      fitTokens(node)
    },
    destroy() {
      ro.disconnect()
    },
  }
}
