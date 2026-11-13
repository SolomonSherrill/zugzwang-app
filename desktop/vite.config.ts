import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

const here = dirname(fileURLToPath(import.meta.url))

/** Absolute path to the sidecar entry point, baked in at build time for the dev run.
 *  Derived from this config file's own location so a clone anywhere works
 *  without editing source; `ZUGZWANG_SIDECAR` overrides it for an unusual
 *  layout. The beta build does not use it: it spawns the bundled externalBin. */
const sidecarScript =
  process.env.ZUGZWANG_SIDECAR ?? resolve(here, '..', 'sidecar', 'main.py')

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [svelte(), tailwindcss()],
  define: {
    __SIDECAR_SCRIPT__: JSON.stringify(sidecarScript),
    /** The one build setting (BETA item 4): `vite build --mode beta`, which
     *  `src-tauri/tauri.beta.conf.json` runs. It spawns the bundled sidecar, hides the
     *  opening trainer, and shows "flag this", the version and the updater. Any other
     *  mode — the owner's `npm run tauri dev` — is unchanged. */
    __BETA__: JSON.stringify(mode === 'beta'),
    /** The local updater proof only (BETA item 8; src/lib/build.ts). */
    __UPDATE_AUTOCONFIRM__: JSON.stringify(process.env.ZUGZWANG_UPDATE_AUTOCONFIRM === '1'),
  },
  // Tauri dev settings
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
}))
