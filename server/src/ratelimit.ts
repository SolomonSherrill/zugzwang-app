/**
 * Rate limits (FRIENDS.md ruling V4). In production the Workers rate-limit bindings count (wrangler.toml:
 * ACCOUNT_LIMITER per account, ANON_LIMITER per connecting address for the unsigned and sign-up routes);
 * the counters are Cloudflare's and this code never writes an address anywhere. Without a binding (the
 * tests, `wrangler dev`), a sliding window in this isolate's memory counts instead, keyed by a hash.
 */
export interface RateLimitBinding {
  limit(options: { key: string }): Promise<{ success: boolean }>
}

export class MemoryLimiter {
  private hits = new Map<string, number[]>()
  constructor(
    readonly limit: number,
    readonly periodMs: number,
  ) {}
  allow(key: string, now: number): boolean {
    const since = now - this.periodMs
    const list = (this.hits.get(key) ?? []).filter((t) => t > since)
    if (list.length >= this.limit) {
      this.hits.set(key, list)
      return false
    }
    list.push(now)
    this.hits.set(key, list)
    if (this.hits.size > 20_000) for (const [k, v] of this.hits) if (!v.some((t) => t > since)) this.hits.delete(k)
    return true
  }
}

export async function allowed(
  binding: RateLimitBinding | undefined,
  fallback: MemoryLimiter,
  key: string,
  now: number,
): Promise<boolean> {
  if (binding && typeof binding.limit === 'function') {
    try {
      return (await binding.limit({ key })).success
    } catch {
      // a limiter that fails open would be no limit; fall back to this isolate's count
    }
  }
  return fallback.allow(key, now)
}
