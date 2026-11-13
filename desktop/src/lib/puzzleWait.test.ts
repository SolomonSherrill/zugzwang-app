import { describe, expect, it } from 'vitest'
import { PUZZLE_WAIT_EXPLAIN_MS, puzzleWaitCaption } from './puzzleWait'

describe('puzzleWaitCaption', () => {
  it('says nothing unusual for a normal load', () => {
    expect(puzzleWaitCaption(0)).toBe('Setting up puzzle…')
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS - 1)).toBe('Setting up puzzle…')
  })

  it('explains the wait once it is long enough to read as a hang', () => {
    // 27 s of an unchanging spinner is the app's most likely "it hung" moment.
    const caption = puzzleWaitCaption(27_000)
    expect(caption).not.toBe('Setting up puzzle…')
    expect(caption).toMatch(/first search/i)
  })

  it('switches exactly at the threshold, not one tick later', () => {
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS)).not.toBe('Setting up puzzle…')
  })

  it('promises the slowness is one-off, since that is the reassurance', () => {
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS)).toMatch(/later ones are not/i)
  })
})
