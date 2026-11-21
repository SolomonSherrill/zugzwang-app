/**
 * The small-windows shots (UI-BUILD-4 C, DESIGN.md fifth rulings, 2): every screen at the four
 * window sizes the ruling names, into review/scratch/ui/sizes/<width>x<height>/<screen>-app.png,
 * each with the DOM layout check (harness/layoutCheck.ts) run in the same page; the results go to
 * review/scratch/ui/sizes/layout_check.out. Each reuses the act of the screen's own shot.
 *
 *   cd desktop && ZUGZWANG_HARNESS_PORT=5201 node harness/shoot.ts sizes/
 */
import type { Shot } from './shots.ts'

export const SIZES = [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]

/** screen name in sizes/ -> the shot (dir/name) whose url, storage and act it reuses */
const SCREENS: [string, string][] = [
  ['home', 'home/home'],
  ['games', 'games/games'],
  ['review-report', 'review/report'],
  ['review-moves', 'review/moves'],
  ['analyse', 'analyse/analyse'],
  ['insights', 'insights/insights'],
  ['play-setup', 'play/setup'],
  ['play-game', 'play/game'],
  ['puzzles-lobby', 'puzzles/puzzles'],
  ['puzzles-session', 'puzzles/session-first'],
  ['trainer-choose', 'trainer/choose'],
  ['trainer-train', 'trainer/train'],
  ['settings', 'settings/settings'],
]

export function sizesShots(all: Shot[]): Shot[] {
  const find = (id: string) => {
    const s = all.find((x) => `${x.dir}/${x.name}` === id)
    if (!s) throw new Error(`sizes: no shot ${id}`)
    return s
  }
  const out: Shot[] = []
  for (const size of SIZES) {
    const dir = `sizes/${size.width}x${size.height}`
    const list = [...SCREENS, ...(size.width === 1280 ? ([['command-menu', 'review/command-menu']] as [string, string][]) : [])]
    for (const [name, id] of list) {
      const b = find(id)
      out.push({ dir, name, url: b.url, storage: b.storage, before: b.before, act: b.act, waitMs: b.waitMs, size, check: true })
    }
  }
  // Below the smallest window (the app cannot get here; a browser can): Home and Insights in one
  // column, to show the breakpoint works (1248 px, DESIGN.md fifth rulings' build notes).
  const narrow = { width: 1200, height: 720 }
  for (const [name, id] of [['home', 'home/home'], ['insights', 'insights/insights']]) {
    const b = find(id)
    out.push({ dir: 'sizes/below-min-1200x720', name, url: b.url, storage: b.storage, act: b.act, size: narrow, check: true })
  }
  return out
}
