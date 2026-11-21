/**
 * The ⌘K command menu's registry (DESIGN.md ruling 9: ⌘K is global). A screen registers a
 * provider while it is mounted; the menu asks every provider for commands matching what is
 * typed. A provider sees the query, so "34" can become "Go to move 34" on Review.
 */
import type { QualityClass } from '../ui/moveQuality'

export interface Command {
  id: string
  group: string
  label: string
  /** a muted phrase after the label ("you, a blunder") */
  detail?: string
  icon?: QualityClass
  kbd?: string
  run: () => void
}

export type Provider = (query: string) => Command[]

const providers = new Map<string, Provider>()
export const commandMenu = $state({ open: false, version: 0 })

export function registerCommands(id: string, p: Provider): () => void {
  providers.set(id, p)
  commandMenu.version++
  return () => {
    if (providers.get(id) === p) providers.delete(id)
    commandMenu.version++
  }
}

/** Every provider's commands for a query, in registration order, filtered by words. */
export function commandsFor(query: string): Command[] {
  const q = query.trim().toLowerCase()
  const out: Command[] = []
  for (const p of providers.values()) {
    for (const c of p(query)) {
      // A move number ("34") lists that move and keeps the screen's actions in view.
      const keepActions = c.group === 'Actions' && parseMoveQuery(query) !== null
      if (!q || c.group === 'Go to move' || keepActions || matches(c, q)) out.push(c)
    }
  }
  return out
}

export function matches(c: Command, q: string): boolean {
  const hay = `${c.label} ${c.detail ?? ''} ${c.group}`.toLowerCase()
  return q.split(/\s+/).every((w) => hay.includes(w))
}

/** "34", "34.", "34...", "34…" → { move: 34, side?: 'white' | 'black' }; else null. */
export function parseMoveQuery(query: string): { move: number; side: 'white' | 'black' | null } | null {
  const m = /^\s*(\d{1,3})\s*(\.{3}|…|\.)?\s*$/.exec(query)
  if (!m) return null
  const move = Number(m[1])
  if (!move) return null
  return { move, side: m[2] === '.' ? 'white' : m[2] ? 'black' : null }
}
