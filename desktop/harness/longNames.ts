/**
 * The longest names the app may be given (BETA-6, FRIENDS.md ruling S7), for the layout checks: with
 * `?names=long` every name the fake sidecar sends is replaced, consistently, by one of the longest allowed:
 *
 *   a Friends handle      20 characters of wide letters (ruling A3's maximum): WWWWWWWWWWWWWWWWWWWW, …
 *   a Chess.com / Lichess username   25 characters: WWWWWWWWWWWWWWWWWWWWWWWW1, …
 *   a player name from an imported game (PGN)   60 characters
 *
 * Names are found by their keys (handle, from_handle, to_handle, white_handle, black_handle; username,
 * chesscom, lichess; white, black, opponent) and every equal string elsewhere in a reply is replaced the
 * same way, so a name shown in a sentence is the long one too. Distinct names stay distinct (the last
 * characters differ), so lists keyed by name keep working.
 */
const HANDLE_KEYS = new Set(['handle', 'from_handle', 'to_handle', 'white_handle', 'black_handle'])
const USER_KEYS = new Set(['username', 'chesscom', 'lichess'])
const PGN_KEYS = new Set(['white', 'black', 'opponent'])
const NOT_NAMES = new Set(['', 'white', 'black', 'White', 'Black', '?', 'random'])
const SUFFIX = 'MQOGDHNUKB0123456789' // no W: a suffix never reads as one of the W's before it

/** n characters: W's, then three characters that tell the i-th name from the others (8,000 of them) */
const longName = (n: number, i: number) => {
  const s = SUFFIX.length
  return 'W'.repeat(n - 3) + SUFFIX[Math.floor(i / (s * s)) % s] + SUFFIX[Math.floor(i / s) % s] + SUFFIX[i % s]
}
/** a name's number from the name itself (FNV-1a), so the same name gets the same long name whatever order the
 *  replies come in (a layout compared with and without a banner must not change its names) */
const hashOf = (v: string) => {
  let h = 0x811c9dc5
  for (let k = 0; k < v.length; k++) h = Math.imul(h ^ v.charCodeAt(k), 0x01000193) >>> 0
  return h % 8000
}
export const LONG = {
  handle: (i: number) => longName(20, i),
  username: (i: number) => longName(25, i),
  pgn: (i: number) => longName(60, i),
}

export function longNamer() {
  const map = new Map<string, string>()
  const taken = new Set<string>()
  const name = (kind: keyof typeof LONG, v: string): string => {
    const had = map.get(v)
    if (had) return had
    let i = hashOf(v)
    while (taken.has(LONG[kind](i))) i = (i + 1) % 8000
    const out = LONG[kind](i)
    taken.add(out)
    map.set(v, out)
    return out
  }
  const collect = (v: unknown, key = ''): void => {
    if (typeof v === 'string') {
      if (NOT_NAMES.has(v)) return
      if (HANDLE_KEYS.has(key)) name('handle', v)
      else if (USER_KEYS.has(key)) name('username', v)
      else if (PGN_KEYS.has(key)) name('pgn', v)
    } else if (Array.isArray(v)) v.forEach((x) => collect(x, key))
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) collect(x, k)
  }
  const replace = (v: unknown): unknown => {
    if (typeof v === 'string') return map.get(v) ?? v
    if (Array.isArray(v)) return v.map(replace)
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, replace(x)]))
    return v
  }
  return {
    map,
    /** a sidecar message (a reply or an event), its names made long */
    message(m: unknown): unknown {
      collect(m)
      return replace(m)
    },
    /** a name the page sends back (a handle in a request), turned back into the fixtures' own */
    original(v: string): string {
      for (const [k, x] of map) if (x === v) return k
      return v
    },
  }
}
