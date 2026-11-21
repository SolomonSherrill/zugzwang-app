/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// DESIGN.md fifth rulings, 2 (UI-BUILD-4 C): the smallest supported window is 1280 x 720. The
// beta build merges tauri.beta*.conf.json over tauri.conf.json; none of them may bring back a
// smaller window, and the size a window opens at is never below the minimum.
type Win = { width?: number; height?: number; minWidth?: number; minHeight?: number }
const read = (f: string) =>
  JSON.parse(readFileSync(new URL(`../../../src-tauri/${f}`, import.meta.url), 'utf8')) as { app?: { windows?: Win[] } }
const FILES = ['tauri.conf.json', 'tauri.beta.conf.json', 'tauri.beta.macos.conf.json', 'tauri.beta.windows.conf.json']

describe('the window size (fifth rulings, 2)', () => {
  it('the dev configuration sets the minimum to 1280 x 720 and opens at least that big', () => {
    const wins = read('tauri.conf.json').app?.windows ?? []
    expect(wins.length).toBeGreaterThan(0)
    for (const w of wins) {
      expect(w.minWidth).toBe(1280)
      expect(w.minHeight).toBe(720)
      expect(w.width).toBeGreaterThanOrEqual(1280)
      expect(w.height).toBeGreaterThanOrEqual(720)
    }
  })
  it('no beta configuration overrides the window with a smaller one', () => {
    for (const f of FILES.slice(1)) {
      const wins = read(f).app?.windows
      if (!wins) continue // inherits tauri.conf.json's window
      for (const w of wins) {
        expect(w.minWidth, f).toBe(1280)
        expect(w.minHeight, f).toBe(720)
        expect(w.width ?? 1280, f).toBeGreaterThanOrEqual(1280)
        expect(w.height ?? 720, f).toBeGreaterThanOrEqual(720)
      }
    }
  })
})
