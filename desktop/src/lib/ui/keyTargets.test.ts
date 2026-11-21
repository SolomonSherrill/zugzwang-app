import { describe, expect, it } from 'vitest'
import { alreadyHandled, ownsEnter } from './keyTargets'

const el = (tagName: string, role: string | null = null, isContentEditable = false) => ({
  tagName,
  isContentEditable,
  getAttribute: (n: string) => (n === 'role' ? role : null),
})

describe('ownsEnter (UI-BUILD-3 B6)', () => {
  it('buttons, links, fields and choices keep Enter', () => {
    for (const t of [el('BUTTON'), el('A'), el('INPUT'), el('TEXTAREA'), el('SELECT'), el('DIV', 'radio'), el('DIV', 'switch'), el('svg', 'slider'), el('DIV', null, true)])
      expect(ownsEnter(t)).toBe(true)
  })
  it('the page itself does not', () => {
    expect(ownsEnter(el('BODY'))).toBe(false)
    expect(ownsEnter(el('DIV'))).toBe(false)
    expect(ownsEnter(null)).toBe(false)
  })
})

describe('alreadyHandled (UI-BUILD-3 B6)', () => {
  it('skips a key a focused control handled', () => {
    expect(alreadyHandled({ defaultPrevented: true, target: el('svg', 'slider') as unknown as EventTarget })).toBe(true)
  })
  it('skips typing in a field', () => {
    expect(alreadyHandled({ defaultPrevented: false, target: el('INPUT') as unknown as EventTarget })).toBe(true)
    expect(alreadyHandled({ defaultPrevented: false, target: el('DIV', null, true) as unknown as EventTarget })).toBe(true)
  })
  it('lets a key on the page through', () => {
    expect(alreadyHandled({ defaultPrevented: false, target: el('BODY') as unknown as EventTarget })).toBe(false)
    expect(alreadyHandled({ defaultPrevented: false, target: null })).toBe(false)
  })
})
