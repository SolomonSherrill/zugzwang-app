// The browser harness (UI-BUILD A5): the app over a fake sidecar, for headless screenshots.
//   npx vite --config vite.harness.config.ts            (http://localhost:5174)
//   node harness/shoot.ts [filter]                      (Playwright: app beside its mockup)
// Fixtures are private (`review/ui_fixtures/`, never published); ZUGZWANG_UI_FIXTURES overrides.
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

const here = dirname(fileURLToPath(import.meta.url))
const fixtures = process.env.ZUGZWANG_UI_FIXTURES ?? resolve(here, '..', 'review', 'ui_fixtures')

export default defineConfig({
  root: resolve(here, 'harness'),
  publicDir: fixtures,
  plugins: [svelte(), tailwindcss()],
  define: {
    __SIDECAR_SCRIPT__: JSON.stringify(''),
    // ZUGZWANG_HARNESS_BETA=1: a beta build's screens ("Flag this", the version line; BETA-4 B)
    __BETA__: JSON.stringify(process.env.ZUGZWANG_HARNESS_BETA === '1'),
    __UPDATE_AUTOCONFIRM__: JSON.stringify(false),
  },
  // ZUGZWANG_HARNESS_PORT lets two worktrees shoot at once (each its own port).
  server: { port: Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5174), strictPort: true, fs: { allow: [here, fixtures] } },
  clearScreen: false,
  logLevel: 'warn',
})
