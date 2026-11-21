/// <reference types="node" />
import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { renderTokensCss, type TokensJson } from './tokensGen'

// design/ is private: the public export carries desktop/ without it, so there the
// staleness check has nothing to compare against and is skipped (the CSS still ships).
const SOURCE = new URL('../../../../design/tokens.json', import.meta.url)
const tokens: TokensJson | null = existsSync(SOURCE) ? JSON.parse(readFileSync(SOURCE, 'utf8')) : null
const css = { file: readFileSync(new URL('./tokens.css', import.meta.url), 'utf8') }

describe('tokens.css', () => {
  it.skipIf(!tokens)('is generated from design/tokens.json and not stale (npm run tokens)', () => {
    expect(css.file).toBe(renderTokensCss(tokens!))
  })

  it.skipIf(!tokens)('names every colour token exactly', () => {
    const out = css.file
    for (const t of tokens!.color.tokens) expect(out).toContain(`--${t.name}: ${t.value};`)
    expect(out).toContain('--q-blunder: #f87171;')
    expect(out).toContain('--radius-panel: 8px;')
    expect(out).toContain('--text-3: #85858f;')
  })

  it('renders a type style as one font shorthand', () => {
    const t: TokensJson = {
      name: 'x', version: 1,
      color: { tokens: [{ name: 'bg', value: '#000' }] },
      type: {
        families: { sans: 'Geist, sans-serif' },
        groups: [{ name: 'Text', family: 'sans', styles: [
          { name: 'metric', fontSize: '24px', lineHeight: '28px', fontWeight: 500, letterSpacing: '-0.01em' },
        ] }],
      },
      spacing: { tokens: [] }, radius: { tokens: [] }, shadow: { tokens: [] }, layout: { tokens: [] },
    }
    const out = renderTokensCss(t)
    expect(out).toContain('--metric: 500 24px/28px var(--sans);')
    expect(out).toContain('--metric-letter-spacing: -0.01em;')
    expect(out).toContain('--bg: #000;')
  })
})
