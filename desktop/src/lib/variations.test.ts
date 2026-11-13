import { describe, expect, it } from 'vitest'
import {
  addMove,
  childrenOf,
  emptyTree,
  firstLineFrom,
  getNode,
  pathOnto,
  type MoveInput,
  type NodeId,
  type VarNode,
  type VarTree,
} from './variations'

const mv = (uci: string): MoveInput => ({ uci, san: uci, fen: `fen-${uci}` })

/** Play a line from the mainline at `rootPly`, returning the last node's id. */
function play(tree: VarTree, rootPly: number, ucis: string[]): { tree: VarTree; id: string } {
  let id: string | null = null
  for (const uci of ucis) {
    const r = addMove(tree, id, rootPly, mv(uci))
    tree = r.tree
    id = r.id
  }
  return { tree, id: id! }
}

/** Root-to-node path. The module does not export this; the screen keeps the path
 *  it is displaying, so walking parents is only ever needed to check a tree. */
function path(tree: VarTree, id: NodeId): VarNode[] {
  const out: VarNode[] = []
  let cur = getNode(tree, id)
  while (cur) {
    out.push(cur)
    cur = cur.parent === null ? null : getNode(tree, cur.parent)
  }
  return out.reverse()
}

function siblings(tree: VarTree, id: NodeId): VarNode[] {
  const node = getNode(tree, id)
  if (!node) return []
  return childrenOf(tree, node.parent, node.rootPly).filter((n) => n.id !== id)
}

describe('an empty tree', () => {
  it('has no nodes', () => {
    expect(emptyTree().nodes.size).toBe(0)
  })
})

describe('playing a move from an earlier point in the line', () => {
  it('branches instead of truncating', () => {
    // The bug this module replaces: the forward moves were silently discarded.
    const first = play(emptyTree(), 4, ['e2e4', 'e7e5', 'g1f3'])
    const root = path(first.tree, first.id)[0]

    const { tree } = addMove(first.tree, root.id, 4, mv('b8c6'))

    expect(getNode(tree, first.id)).not.toBeNull()
    expect(path(tree, first.id).map((n) => n.uci)).toEqual(['e2e4', 'e7e5', 'g1f3'])
    expect(childrenOf(tree, root.id, 4).map((n) => n.uci).sort()).toEqual(['b8c6', 'e7e5'])
  })

  it('offers both continuations as siblings of each other', () => {
    const first = play(emptyTree(), 0, ['e2e4', 'e7e5'])
    const root = path(first.tree, first.id)[0]
    const second = addMove(first.tree, root.id, 0, mv('c7c5'))

    expect(siblings(second.tree, second.id).map((n) => n.uci)).toEqual(['e7e5'])
    expect(siblings(second.tree, first.id).map((n) => n.uci)).toEqual(['c7c5'])
  })
})

describe('replaying a move that is already there', () => {
  it('returns the existing node rather than a duplicate', () => {
    const first = addMove(emptyTree(), null, 2, mv('e2e4'))
    const again = addMove(first.tree, null, 2, mv('e2e4'))

    expect(again.id).toBe(first.id)
    expect(again.tree.nodes.size).toBe(1)
    expect(again.tree).toBe(first.tree)
  })

  it('makes exploring the same line twice idempotent', () => {
    const once = play(emptyTree(), 3, ['e2e4', 'e7e5', 'g1f3'])
    const twice = play(once.tree, 3, ['e2e4', 'e7e5', 'g1f3'])

    expect(twice.id).toBe(once.id)
    expect(twice.tree.nodes.size).toBe(3)
  })
})

describe('rootPly', () => {
  it('is inherited by children, however deep', () => {
    const { tree, id } = play(emptyTree(), 11, ['e2e4', 'e7e5', 'g1f3', 'b8c6'])
    expect(path(tree, id).map((n) => n.rootPly)).toEqual([11, 11, 11, 11])
  })

  it('is answerable in O(1) from a node deep in a branch', () => {
    // What makes "which move did this line leave from" cheap enough to ask on
    // every render, rather than a walk back to the root.
    const { tree, id } = play(emptyTree(), 11, ['e2e4', 'e7e5', 'g1f3'])
    expect(getNode(tree, id)?.rootPly).toBe(11)
  })

  it('keeps branches off different mainline plies from being siblings', () => {
    const a = addMove(emptyTree(), null, 4, mv('e2e4'))
    const b = addMove(a.tree, null, 9, mv('d2d4'))

    expect(childrenOf(b.tree, null, 4).map((n) => n.uci)).toEqual(['e2e4'])
    expect(childrenOf(b.tree, null, 9).map((n) => n.uci)).toEqual(['d2d4'])
    expect(siblings(b.tree, a.id)).toEqual([])
  })

  it('lets the same move branch off two different plies independently', () => {
    const a = addMove(emptyTree(), null, 4, mv('e2e4'))
    const b = addMove(a.tree, null, 9, mv('e2e4'))

    expect(b.id).not.toBe(a.id)
    expect(b.tree.nodes.size).toBe(2)
  })
})

describe('firstLineFrom', () => {
  it('is empty at the end of a line', () => {
    const { tree, id } = play(emptyTree(), 0, ['e2e4'])
    expect(firstLineFrom(tree, id)).toEqual([])
  })

  it('restores the whole discarded continuation, not just one move', () => {
    const first = play(emptyTree(), 4, ['e2e4', 'e7e5', 'g1f3', 'b8c6'])
    const root = path(first.tree, first.id)[0]
    const { tree, id } = addMove(first.tree, root.id, 4, mv('c7c5'))

    expect(firstLineFrom(tree, id)).toEqual([])
    expect(firstLineFrom(tree, root.id).map((n) => n.uci)).toEqual(['e7e5', 'g1f3', 'b8c6'])
  })

  it('follows the earliest-explored child when a point has two', () => {
    const first = play(emptyTree(), 0, ['e2e4', 'e7e5'])
    const root = path(first.tree, first.id)[0]
    const { tree } = addMove(first.tree, root.id, 0, mv('c7c5'))

    expect(firstLineFrom(tree, root.id).map((n) => n.uci)).toEqual(['e7e5'])
  })
})

describe('pathOnto — what stays on screen', () => {
  /** A line, plus a second move tried from after its first: the shape the screen is
   *  in when the user has stepped back and branched. */
  function branched() {
    const main = play(emptyTree(), 4, ['e2e4', 'e7e5', 'g1f3', 'b8c6'])
    const mainPath = path(main.tree, main.id).map((n) => n.id)
    const alt = addMove(main.tree, mainPath[0], 4, mv('c7c5'))
    return { tree: alt.tree, mainPath, altId: alt.id }
  }

  it('keeps the whole displayed line when stepping onto the move already shown', () => {
    const { tree, mainPath } = branched()
    // at the branch point, stepping forward onto e7e5 again
    expect(pathOnto(tree, mainPath, 1, mainPath[1])).toBe(mainPath)
  })

  it('switches to the other branch without touching the moves before it', () => {
    const { tree, mainPath, altId } = branched()
    const next = pathOnto(tree, mainPath, 1, altId)

    expect(next[0]).toBe(mainPath[0])
    expect(next.slice(1)).toEqual([altId])
  })

  it('restores a branch with its continuation, not just the one move', () => {
    const { tree, mainPath, altId } = branched()
    // leave the c7c5 branch for the original line, then come back to it
    const onAlt = pathOnto(tree, mainPath, 1, altId)
    const back = pathOnto(tree, onAlt, 1, mainPath[1])

    expect(back).toEqual(mainPath)
  })

  it('never drops a move before the point being stepped from', () => {
    const { tree, mainPath, altId } = branched()
    for (let at = 0; at <= mainPath.length; at++) {
      const next = pathOnto(tree, mainPath, at, altId)
      expect(next.slice(0, at)).toEqual(mainPath.slice(0, at))
    }
  })
})

describe('entering a whole line at once — a clicked engine line', () => {
  /** Add a chain of moves under `parent`, as `enterLine` does probe by probe. */
  function chainOf(tree: VarTree, parent: NodeId | null, rootPly: number, ucis: string[]) {
    const ids: NodeId[] = []
    let cur = parent
    for (const uci of ucis) {
      const r = addMove(tree, cur, rootPly, mv(uci))
      tree = r.tree
      ids.push(r.id)
      cur = r.id
    }
    return { tree, ids }
  }

  /** Step onto each node of the chain in turn. The screen's only multi-step move,
   *  and the reason `pathOnto` has to compose rather than just replace a tail. */
  function enter(tree: VarTree, path: NodeId[], at: number, chain: NodeId[]) {
    let p = path
    let i = at
    for (const id of chain) {
      p = pathOnto(tree, p, i, id)
      i += 1
    }
    return { path: p, idx: i }
  }

  it('shows every move of the line, not just the last', () => {
    const { tree, ids } = chainOf(emptyTree(), null, 6, ['e2e4', 'e7e5', 'g1f3'])
    const got = enter(tree, [], 0, ids)

    expect(got.path).toEqual(ids)
    expect(got.idx).toBe(3)
  })

  it('replaces only from the point clicked from', () => {
    const first = chainOf(emptyTree(), null, 6, ['e2e4', 'e7e5', 'g1f3'])
    const alt = chainOf(first.tree, first.ids[0], 6, ['c7c5', 'g1f3'])
    const got = enter(alt.tree, first.ids, 1, alt.ids)

    expect(got.path).toEqual([first.ids[0], ...alt.ids])
    expect(got.idx).toBe(3)
  })

  it('leaves the line alone when the same one is clicked again', () => {
    const { tree, ids } = chainOf(emptyTree(), null, 6, ['e2e4', 'e7e5', 'g1f3'])
    const once = enter(tree, [], 0, ids)
    const twice = enter(tree, once.path, 0, ids)

    expect(twice.path).toBe(once.path)
    expect(twice.idx).toBe(once.idx)
  })

  it('keeps the rest on screen when a shorter prefix of it is clicked', () => {
    const { tree, ids } = chainOf(emptyTree(), null, 6, ['e2e4', 'e7e5', 'g1f3'])
    const deep = enter(tree, [], 0, ids)
    const shallow = enter(tree, deep.path, 0, ids.slice(0, 1))

    expect(shallow.path).toEqual(ids)
    expect(shallow.idx).toBe(1)
  })
})

describe('a node that is not in the tree', () => {
  it('reads as absent rather than throwing', () => {
    const tree = emptyTree()
    expect(getNode(tree, 'v9')).toBeNull()
    expect(firstLineFrom(tree, 'v9')).toEqual([])
    expect(childrenOf(tree, 'v9', 0)).toEqual([])
  })
})
