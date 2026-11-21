// Regenerate src/lib/styles/tokens.css from design/tokens.json (UI-BUILD A3).
//   cd desktop && npm run tokens            (or: node scripts/gen-tokens.ts [tokens.json])
// design/ is private (never on the public allowlist); the generated CSS is what ships.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderTokensCss, type TokensJson } from '../src/lib/styles/tokensGen.ts'

const here = dirname(fileURLToPath(import.meta.url))
const src = process.argv[2] ?? resolve(here, '..', '..', 'design', 'tokens.json')
const out = resolve(here, '..', 'src', 'lib', 'styles', 'tokens.css')
const tokens = JSON.parse(readFileSync(src, 'utf8')) as TokensJson
writeFileSync(out, renderTokensCss(tokens))
console.log(`wrote ${out}`)
