import { describe, expect, it } from 'vitest'
import { PUZZLE_WAIT_EXPLAIN_MS, puzzleWaitCaption } from './puzzleWait'

describe('puzzleWaitCaption', () => {
  it('says nothing unusual for a normal load', () => {
    expect(puzzleWaitCaption(0)).toEqual({ sentence: 'Finding a puzzle…', sub: null })
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS - 1).sub).toBeNull()
  })

  it('explains the wait once it is long enough to read as a hang', () => {
    // 27 s of an unchanging spinner is the app's most likely "it hung" moment.
    const c = puzzleWaitCaption(27_000)
    expect(c.sentence).toMatch(/puzzle database/i)
    expect(c.sub).toMatch(/first search/i)
    expect(c.sub).toMatch(/half a minute/i)
  })

  it('switches exactly at the threshold, not one tick later', () => {
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS).sub).not.toBeNull()
  })

  it('promises the slowness is one-off, since that is the reassurance', () => {
    expect(puzzleWaitCaption(PUZZLE_WAIT_EXPLAIN_MS).sub).toMatch(/later ones/i)
  })
})
