import type { Env } from '../src/app'

declare global {
  namespace Cloudflare {
    interface Env {
      DB: D1Database
      LICHESS_API: string
      CHESSCOM_API: string
      ADMIN_PUBLIC_KEY?: string
      LINK_SECRET?: string
      TEST_MIGRATIONS: import('cloudflare:test').D1Migration[]
    }
  }
}
export type { Env }
