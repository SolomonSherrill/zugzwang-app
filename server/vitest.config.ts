import { cloudflareTest, readD1Migrations } from '@cloudflare/vitest-plugin'
import { defineConfig } from 'vitest/config'

// The Workers runtime, locally (Miniflare): the tests touch no network (FRIENDS.md ruling V5). The
// outbound calls to Lichess and Chess.com are answered by test/outbound.ts's stubs.
export default defineConfig(async () => {
  const migrations = await readD1Migrations('./migrations')
  return {
    plugins: [
      cloudflareTest({
        wrangler: { configPath: './wrangler.toml' },
        miniflare: { bindings: { TEST_MIGRATIONS: migrations, LINK_SECRET: 'test-link-secret' } },
      }),
    ],
    test: { setupFiles: ['./test/apply-migrations.ts'] },
  }
})
