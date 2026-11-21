/**
 * design/tokens.json → CSS custom properties, named exactly as the tokens (`--bg`,
 * `--text-3`, `--q-blunder`, `--radius-panel`). Pure, so the staleness test and the
 * generator script (`scripts/gen-tokens.ts`, `npm run tokens`) share it.
 *
 * Type styles become one `font` shorthand each (`font: var(--heading)`), plus
 * `--<style>-letter-spacing` where the token gives one. The family is `--sans`.
 */

export interface TokenEntry {
  name: string
  value: string
  usage?: string
}
export interface TypeStyle {
  name: string
  fontSize: string
  lineHeight: string
  fontWeight: number
  usage?: string
  letterSpacing?: string
}
export interface TokensJson {
  name: string
  version: number
  color: { tokens: TokenEntry[] }
  type: {
    families: Record<string, string>
    groups: { name: string; family: string; styles: TypeStyle[] }[]
  }
  spacing: { tokens: TokenEntry[] }
  radius: { tokens: TokenEntry[] }
  shadow: { tokens: TokenEntry[] }
  layout: { tokens: TokenEntry[] }
}

export const TOKENS_HEADER =
  '/* Generated from design/tokens.json by desktop/scripts/gen-tokens.ts (npm run tokens).\n' +
  ' * Do not edit by hand: src/lib/styles/tokens.test.ts fails when this file is stale. */'

function comment(usage: string | undefined): string {
  return usage ? ` /* ${usage.replace(/\*\//g, '* /')} */` : ''
}

function block(title: string, entries: TokenEntry[]): string[] {
  return [`  /* ${title} */`, ...entries.map((t) => `  --${t.name}: ${t.value};${comment(t.usage)}`)]
}

export function renderTokensCss(t: TokensJson): string {
  const lines: string[] = [TOKENS_HEADER, ':root {']
  lines.push(...block('colour', t.color.tokens))
  lines.push('  /* type */')
  for (const [name, value] of Object.entries(t.type.families)) lines.push(`  --${name}: ${value};`)
  for (const group of t.type.groups) {
    for (const s of group.styles) {
      lines.push(
        `  --${s.name}: ${s.fontWeight} ${s.fontSize}/${s.lineHeight} var(--${group.family});${comment(s.usage)}`,
      )
      if (s.letterSpacing) lines.push(`  --${s.name}-letter-spacing: ${s.letterSpacing};`)
    }
  }
  lines.push(...block('spacing', t.spacing.tokens))
  lines.push(...block('radius', t.radius.tokens))
  lines.push(...block('shadow', t.shadow.tokens))
  lines.push(...block('layout', t.layout.tokens))
  lines.push('}', '')
  return lines.join('\n')
}
