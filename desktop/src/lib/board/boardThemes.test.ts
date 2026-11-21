import { describe, expect, it } from 'vitest'
import { BOARD_THEMES, DEFAULT_BOARD_THEME, boardTheme, isLightSquare, lastMoveClasses } from './boardThemes'

describe('board themes (ruling 20)', () => {
  it('are the six ruled themes with the ruled square colours, Stone first and default', () => {
    expect(BOARD_THEMES.map((t) => [t.name, t.light, t.dark])).toEqual([
      ['Stone', '#D9D5CC', '#8F897D'],
      ['Slate', '#C8CFD8', '#6F7C8C'],
      ['Olive', '#DADCC9', '#7F8C6C'],
      ['Green', '#DDE3CF', '#6E8F5E'],
      ['Blue', '#DCE3EA', '#6B87A8'],
      ['Walnut', '#E0CFB4', '#9C7A57'],
    ])
    expect(DEFAULT_BOARD_THEME).toBe('stone')
    expect(boardTheme('nonsense').id).toBe('stone')
  })

  it('keep the approved last-move tints (Green, Blue, Walnut: ruling 9, 2026-11-20 third)', () => {
    expect(BOARD_THEMES.map((t) => [t.id, t.lastMoveLight, t.lastMoveDark])).toEqual([
      ['stone', '#E2D7A6', '#ADA073'],
      ['slate', '#D8D3A2', '#9C9670'],
      ['olive', '#E3DDA2', '#A8A56A'],
      ['green', '#E4E2A8', '#A3A65E'],
      ['blue', '#E2DFB2', '#A39F78'],
      ['walnut', '#EAD99A', '#B39A55'],
    ])
  })

  it('colour squares as a real board: a1 and h8 dark, h1 and a8 light', () => {
    expect(isLightSquare('a1')).toBe(false)
    expect(isLightSquare('h8')).toBe(false)
    expect(isLightSquare('h1')).toBe(true)
    expect(isLightSquare('a8')).toBe(true)
    expect(isLightSquare('e4')).toBe(true)
  })

  it('tint each last-move square by its own colour', () => {
    expect([...lastMoveClasses(['g1', 'f3'])]).toEqual([
      ['g1', 'lm-dark'],
      ['f3', 'lm-light'],
    ])
    expect(lastMoveClasses(null).size).toBe(0)
  })
})
