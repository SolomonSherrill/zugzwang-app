import { describe, expect, it } from 'vitest'
import { commandsFor, matches, parseMoveQuery, registerCommands } from './commands.svelte'

describe('command menu', () => {
  it('reads a move number from what is typed', () => {
    expect(parseMoveQuery('34')).toEqual({ move: 34, side: null })
    expect(parseMoveQuery('34.')).toEqual({ move: 34, side: 'white' })
    expect(parseMoveQuery('34...')).toEqual({ move: 34, side: 'black' })
    expect(parseMoveQuery('34…')).toEqual({ move: 34, side: 'black' })
    expect(parseMoveQuery('flip')).toBeNull()
    expect(parseMoveQuery('0')).toBeNull()
  })
  it('matches every word of the query', () => {
    const c = { id: 'x', group: 'Actions', label: 'Flip the board', run: () => {} }
    expect(matches(c, 'flip')).toBe(true)
    expect(matches(c, 'flip board')).toBe(true)
    expect(matches(c, 'copy')).toBe(false)
  })
  it('asks the registered providers and forgets one when it unregisters', () => {
    const off = registerCommands('t', () => [
      { id: 'a', group: 'Actions', label: 'Flip the board', run: () => {} },
      { id: 'b', group: 'Go to move', label: '34. b5', run: () => {} },
    ])
    expect(commandsFor('flip').map((c) => c.id)).toEqual(['a', 'b'])
    expect(commandsFor('34').map((c) => c.id)).toEqual(['a', 'b'])
    off()
    expect(commandsFor('')).toEqual([])
  })
})
