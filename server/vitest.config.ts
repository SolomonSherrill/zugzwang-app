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
        // FRIENDS-2's times, shortened so the rules that wait (P1, P2, a challenge's expiry) run in seconds
        miniflare: {
          bindings: {
            TEST_MIGRATIONS: migrations, LINK_SECRET: 'test-link-secret',
            FIRST_MOVE_MS: '1500', DISCONNECT_MS: '700', CHALLENGE_MS: '1500', STALE_MS: '60000',
          },
        },
      }),
    ],
    test: { setupFiles: ['./test/apply-migrations.ts'] },
  }
})
