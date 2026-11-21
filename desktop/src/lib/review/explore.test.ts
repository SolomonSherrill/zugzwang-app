import { describe, expect, it } from 'vitest'
import { emptyTree, getNode, type MoveInput } from '../variations'
import {
  applyMoves,
  branchLines,
  branchPoints,
  linesByRoot,
  nodeAt,
  nodePly,
  onMain,
  onVariation,
  placeFen,
  placeOn,
  placeUci,
  placement,
  plyBaseOf,
  step,
  type ExploreState,
  type MainMove,
} from './explore'

const mv = (uci: string): MoveInput => ({ uci, san: uci.toUpperCase(), fen: `fen-${uci}` })
/** A four-move main line: a1a2 b1b2 c1c2 d1d2. */
const MAIN: MainMove[] = ['a1a2', 'b1b2', 'c1c2', 'd1d2'].map(mv)
const start = (cur = 2): ExploreState => ({ tree: emptyTree(), main: MAIN, place: onMain(cur) })
const play = (s: ExploreState, ucis: string[], extendable = false) => applyMoves(s, ucis.map(mv), extendable)

describe('a move played on the board', () => {
  it("that is the main line's next move steps along the main line", () => {
    const s = play(start(1), ['b1b2'])
    expect(s.place).toEqual(onMain(2))
    expect(s.tree.nodes.size).toBe(0)
  })

  it('that differs starts a variation off the position on the board', () => {
    const s = play(start(2), ['e2e4', 'e7e5'])
    expect(onVariation(s.place)).toBe(true)
    expect(s.place.cur).toBe(2)
    expect(s.place.at).toBe(2)
    expect(nodeAt(s.tree, s.place)?.uci).toBe('e7e5')
    expect(getNode(s.tree, s.place.path[0])?.rootPly).toBe(2)
  })

  it('an engine line that follows the main line first steps along it, then branches', () => {
    const s = play(start(1), ['b1b2', 'c1c2', 'h7h6'])
    expect(s.place.cur).toBe(3)
    expect(s.place.at).toBe(1)
    expect(nodeAt(s.tree, s.place)?.uci).toBe('h7h6')
  })

  it("at the end of Analyse a position's line extends it; in a game it starts a variation", () => {
    const ext = play(start(4), ['e2e4'], true)
    expect(ext.main.map((m) => m.uci)).toEqual([...MAIN.map((m) => m.uci), 'e2e4'])
    expect(ext.place).toEqual(onMain(5))
    const game = play(start(4), ['e2e4'], false)
    expect(game.main).toBe(MAIN)
    expect(onVariation(game.place)).toBe(true)
  })

  it('replaying an explored move reuses it: nothing is duplicated or removed', () => {
    const once = play(start(2), ['e2e4', 'e7e5'])
    const twice = play({ ...once, place: onMain(2) }, ['e2e4', 'e7e5'])
    expect(twice.tree.nodes.size).toBe(2)
    expect(twice.place).toEqual(once.place)
  })

  it('a different move from inside a variation branches it, keeping the old continuation', () => {
    const a = play(start(2), ['e2e4', 'e7e5', 'g1f3'])
    const back = { ...a, place: { ...a.place, at: 1 } }
    const b = play(back, ['c7c5'])
    expect(b.tree.nodes.size).toBe(4)
    expect(b.place.path.map((id) => getNode(b.tree, id)!.uci)).toEqual(['e2e4', 'c7c5'])
  })
})

describe('placement', () => {
  it('names where each kind of move goes', () => {
    expect(placement(MAIN, onMain(0), 'a1a2', false)).toEqual({ kind: 'main' })
    expect(placement(MAIN, onMain(0), 'h2h4', false)).toEqual({ kind: 'tree', parent: null, rootPly: 0 })
    expect(placement(MAIN, onMain(4), 'h2h4', true)).toEqual({ kind: 'extend' })
    const s = play(start(2), ['e2e4'])
    expect(placement(MAIN, s.place, 'e7e5', false)).toEqual({ kind: 'tree', parent: s.place.path[0], rootPly: 2 })
  })
})

describe('the board', () => {
  it('shows the main line, or the variation move, with its last move', () => {
    const s = play(start(2), ['e2e4'])
    expect(placeFen(s.tree, MAIN, 'start', onMain(0))).toBe('start')
    expect(placeFen(s.tree, MAIN, 'start', onMain(2))).toBe('fen-b1b2')
    expect(placeFen(s.tree, MAIN, 'start', s.place)).toBe('fen-e2e4')
    expect(placeUci(s.tree, MAIN, onMain(0))).toBeNull()
    expect(placeUci(s.tree, MAIN, onMain(3))).toBe('c1c2')
    expect(placeUci(s.tree, MAIN, s.place)).toBe('e2e4')
  })

  it("numbers a variation move by its root and depth", () => {
    const s = play(start(2), ['e2e4', 'e7e5'])
    expect(nodePly(s.tree, s.place.path[0])).toBe(2)
    expect(nodePly(s.tree, s.place.path[1])).toBe(3)
  })
})

describe('step (arrow keys, the navigator)', () => {
  const v = play(start(2), ['e2e4', 'e7e5', 'g1f3'])
  const at = (n: number) => ({ ...v.place, at: n })

  it('steps the main line, clamped', () => {
    expect(step(onMain(2), 'forward', 4)).toEqual(onMain(3))
    expect(step(onMain(4), 'forward', 4)).toEqual(onMain(4))
    expect(step(onMain(0), 'back', 4)).toEqual(onMain(0))
    expect(step(onMain(2), 'start', 4)).toEqual(onMain(0))
    expect(step(onMain(2), 'end', 4)).toEqual(onMain(4))
  })

  it('steps within a variation, one move each press', () => {
    expect(step(at(2), 'forward', 4)).toEqual(at(3))
    expect(step(at(2), 'back', 4)).toEqual(at(1))
    expect(step(at(1), 'end', 4)).toEqual(at(3))
  })

  it("stops at the variation's end: the main line does not continue it", () => {
    expect(step(at(3), 'forward', 4)).toEqual(at(3))
  })

  it('back from its first move, or Start, returns to the main line where it left', () => {
    expect(step(at(1), 'back', 4)).toEqual(onMain(2))
    expect(step(at(3), 'start', 4)).toEqual(onMain(2))
  })
})

describe('the move list', () => {
  it('shows each variation under the position it leaves from, every move once', () => {
    let s = play(start(2), ['e2e4', 'e7e5', 'g1f3'])
    s = play({ ...s, place: { ...s.place, at: 1 } }, ['c7c5', 'd2d4'])   // a branch inside it
    s = play({ ...s, place: onMain(2) }, ['d2d4'])                        // a second variation at 2
    s = play({ ...s, place: onMain(0) }, ['h2h3'])                        // one off the start
    expect(branchPoints(s.tree)).toEqual([0, 2])
    const lines = branchLines(s.tree, 2)
    expect(lines.map((l) => [l.depth, l.firstPly, l.nodes.map((n) => n.uci)])).toEqual([
      [0, 2, ['e2e4', 'e7e5', 'g1f3']],
      [1, 3, ['c7c5', 'd2d4']],
      [0, 2, ['d2d4']],
    ])
    const all = [...linesByRoot(s.tree).values()].flat().flatMap((l) => l.nodes.map((n) => n.id))
    expect(new Set(all).size).toBe(s.tree.nodes.size)
    expect(all.length).toBe(s.tree.nodes.size)
  })

  it('clicking a move in it puts the board there, with the line continuing past it', () => {
    const s = play(start(2), ['e2e4', 'e7e5', 'g1f3'])
    const p = placeOn(s.tree, s.place.path[1])!
    expect(p).toEqual({ cur: 2, path: s.place.path, at: 2 })
    expect(placeOn(s.tree, 'v99')).toBeNull()
  })
})

describe('plyBaseOf', () => {
  it("counts from the FEN's own move number and side to move", () => {
    expect(plyBaseOf('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')).toBe(0)
    expect(plyBaseOf('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1')).toBe(1)
    expect(plyBaseOf('8/8/8/8/8/8/8/K6k w - - 0 23')).toBe(44)
    expect(plyBaseOf('8/8/8/8/8/8/8/K6k b - - 0 23')).toBe(45)
    expect(plyBaseOf('8/8/8/8/8/8/8/K6k w - -')).toBe(0)
  })
})
