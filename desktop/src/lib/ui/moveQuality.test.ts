import { describe, expect, it } from 'vitest'
import { render } from 'svelte/server'
import MoveQualityIcon from './MoveQualityIcon.svelte'
import { GRAPH_DOT_QUALITIES, QUALITIES, QUALITY, iconMetrics, isQualityClass } from './moveQuality'
import { CLASS_COLORS, CLASS_GLYPHS } from '../classification'

const TEN = ['brilliant', 'great', 'book', 'best', 'excellent', 'good', 'inaccuracy', 'mistake', 'miss', 'blunder']

describe('move-quality classes (ruling 1)', () => {
  it('are exactly the ten classes, in the design system order', () => {
    expect(QUALITIES.map((q) => q.cls)).toEqual(TEN)
  })

  it('name each class in sentence case', () => {
    expect(QUALITIES.map((q) => q.name)).toEqual([
      'Brilliant', 'Great', 'Book', 'Best', 'Excellent', 'Good', 'Inaccuracy', 'Mistake', 'Miss', 'Blunder',
    ])
  })

  it('set the five marks as text and draw the five symbols', () => {
    const marks = Object.fromEntries(QUALITIES.filter((q) => q.mark).map((q) => [q.cls, q.mark]))
    expect(marks).toEqual({ brilliant: '!!', great: '!', inaccuracy: '?!', mistake: '?', blunder: '??' })
    expect(QUALITIES.filter((q) => q.symbol).map((q) => q.cls)).toEqual(['book', 'best', 'excellent', 'good', 'miss'])
    for (const q of QUALITIES) expect(!!q.mark !== !!q.symbol).toBe(true)
  })

  it('never draws excellent as "+" (in notation "+" is check)', () => {
    expect(QUALITY.excellent.mark).toBeUndefined()
    expect(QUALITY.excellent.symbol?.d).toMatch(/^M3\.5 10h3\.5v10/)
    expect(CLASS_GLYPHS.excellent).not.toBe('+')
    expect(CLASS_GLYPHS.excellent).toBe('Excellent') // ruling 7 (2026-11-20, third): no emoji
  })

  it('fill each class from its own token', () => {
    for (const q of QUALITIES) expect(q.fill).toBe(`--q-${q.cls}`)
  })

  it('mirror the design colours in classification.ts (UI-2)', () => {
    expect(CLASS_COLORS).toEqual({
      brilliant: '#34d3d3', great: '#60a5fa', book: '#c4a57a', best: '#4ade80', excellent: '#4ade80',
      good: '#86b89a', inaccuracy: '#facc15', mistake: '#fb923c', miss: '#f472b6', blunder: '#f87171',
    })
  })

  it('size marks and symbols as the mockups (16 → 9px text, 10px symbol)', () => {
    expect(iconMetrics(16)).toEqual({ font: 9, symbol: 10 })
    expect(iconMetrics(18).font).toBeGreaterThan(9)
    expect(iconMetrics(20).symbol).toBeGreaterThan(iconMetrics(18).symbol)
  })

  it('dot only brilliant, great, miss, mistake and blunder on the graph (ruling 5)', () => {
    expect([...GRAPH_DOT_QUALITIES].sort()).toEqual(['blunder', 'brilliant', 'great', 'miss', 'mistake'])
  })

  it('recognise only the ten names', () => {
    expect(isQualityClass('blunder')).toBe(true)
    expect(isQualityClass('forced')).toBe(false)
    expect(isQualityClass(null)).toBe(false)
  })
})

describe('MoveQualityIcon', () => {
  it.each(TEN)('renders %s with its accessible name and fill', (cls) => {
    const { body } = render(MoveQualityIcon, { props: { cls, size: 16 } })
    expect(body).toContain(`aria-label="${QUALITY[cls as keyof typeof QUALITY].name}"`)
    expect(body).toContain(`data-cls="${cls}"`)
    expect(body).toContain(`var(--q-${cls})`)
    expect(body).toContain('width: 16px')
  })

  it('renders a mark as text and a symbol as an svg path', () => {
    expect(render(MoveQualityIcon, { props: { cls: 'blunder' } }).body).toContain('>??<')
    const star = render(MoveQualityIcon, { props: { cls: 'best', size: 20 } }).body
    expect(star).toContain('<svg')
    expect(star).toContain('width="12"')
  })

  it('renders nothing for an unknown class, and hides a decorative icon', () => {
    expect(render(MoveQualityIcon, { props: { cls: 'forced' } }).body).not.toContain('mq')
    const deco = render(MoveQualityIcon, { props: { cls: 'great', decorative: true } }).body
    expect(deco).toContain('aria-hidden="true"')
    expect(deco).not.toContain('aria-label')
  })
})
