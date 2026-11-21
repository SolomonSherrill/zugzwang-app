/**
 * Board colours (DESIGN.md "Board themes", owner ruling 20). Stone is the default; the six
 * are chosen in Settings → Appearance. Last-move tints: Stone's are approved; Slate's and
 * Olive's are the mockup's board-theme switch (recorded in DESIGN.md "for reference");
 * Green's, Blue's and Walnut's were approved by ruling 9 of 2026-11-20 (third).
 */
import type { Key } from 'chessground/types'

export type BoardThemeId = 'stone' | 'slate' | 'olive' | 'green' | 'blue' | 'walnut'

export interface BoardTheme {
  id: BoardThemeId
  name: string
  light: string
  dark: string
  lastMoveLight: string
  lastMoveDark: string
}

export const BOARD_THEMES: BoardTheme[] = [
  { id: 'stone', name: 'Stone', light: '#D9D5CC', dark: '#8F897D', lastMoveLight: '#E2D7A6', lastMoveDark: '#ADA073' },
  { id: 'slate', name: 'Slate', light: '#C8CFD8', dark: '#6F7C8C', lastMoveLight: '#D8D3A2', lastMoveDark: '#9C9670' },
  { id: 'olive', name: 'Olive', light: '#DADCC9', dark: '#7F8C6C', lastMoveLight: '#E3DDA2', lastMoveDark: '#A8A56A' },
  { id: 'green', name: 'Green', light: '#DDE3CF', dark: '#6E8F5E', lastMoveLight: '#E4E2A8', lastMoveDark: '#A3A65E' },
  { id: 'blue', name: 'Blue', light: '#DCE3EA', dark: '#6B87A8', lastMoveLight: '#E2DFB2', lastMoveDark: '#A39F78' },
  { id: 'walnut', name: 'Walnut', light: '#E0CFB4', dark: '#9C7A57', lastMoveLight: '#EAD99A', lastMoveDark: '#B39A55' },
]

export const DEFAULT_BOARD_THEME: BoardThemeId = 'stone'

export function boardTheme(id: string | null | undefined): BoardTheme {
  return BOARD_THEMES.find((t) => t.id === id) ?? BOARD_THEMES[0]
}

/** a1 is dark: a square is light when its file and rank indices differ in parity. */
export function isLightSquare(key: Key): boolean {
  const file = key.charCodeAt(0) - 97
  const rank = key.charCodeAt(1) - 49
  return (file + rank) % 2 === 1
}

/** chessground `highlight.custom` classes for the last move: each square gets the tint of
 *  its own colour (lm-light / lm-dark), which one translucent overlay cannot give exactly. */
export function lastMoveClasses(lastMove: readonly Key[] | null | undefined): Map<Key, string> {
  const m = new Map<Key, string>()
  for (const k of lastMove ?? []) m.set(k, isLightSquare(k) ? 'lm-light' : 'lm-dark')
  return m
}

/** The CSS variables a board wrapper sets for its theme. */
export function boardThemeVars(t: BoardTheme): string {
  return `--sq-light: ${t.light}; --sq-dark: ${t.dark}; --lm-light: ${t.lastMoveLight}; --lm-dark: ${t.lastMoveDark};`
}
