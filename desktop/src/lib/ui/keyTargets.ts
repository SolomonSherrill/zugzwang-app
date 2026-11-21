/**
 * Screen-wide key handlers and focused controls (UI-BUILD-3 B6). A key a focused control acts
 * on must not also act on the screen: one press, one action.
 */

interface KeyTarget {
  tagName?: string
  isContentEditable?: boolean
  getAttribute?: (name: string) => string | null
}

const SELF_ACTIVATING_ROLES = new Set(['button', 'link', 'radio', 'checkbox', 'switch', 'option', 'tab', 'menuitem', 'slider'])

/** True when Enter or Space on this element already does something of its own (a button, a link,
 *  a choice, a text field), so a screen's window handler must leave the key alone. */
export function ownsEnter(t: KeyTarget | null | undefined): boolean {
  if (!t) return false
  const tag = (t.tagName ?? '').toUpperCase()
  if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (t.isContentEditable) return true
  const role = t.getAttribute?.('role')
  return role != null && SELF_ACTIVATING_ROLES.has(role)
}

/** True when a window handler should ignore this key event: a focused control already handled it
 *  (it called preventDefault), or the key is typing in a text field. */
export function alreadyHandled(e: { defaultPrevented: boolean; target: EventTarget | null }): boolean {
  if (e.defaultPrevented) return true
  const t = e.target as KeyTarget | null
  const tag = (t?.tagName ?? '').toUpperCase()
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || !!t?.isContentEditable
}
