/**
 * Exploring (UI-BUILD-3 C and D): moves played on the board from any position of a main line
 * become variations, kept as a tree (`../variations`, unchanged from the old Review screen:
 * nothing in it removes a move). This module is the pure part: where the board is, where a
 * move played from there goes, how the arrow keys step, and the lines the move list shows.
 *
 * The main line is the game's moves in Review, and in Analyse a position the first line
 * played from the starting FEN (it grows as moves are played at its end). A variation leaves
 * the main line at a position `rootPly` (0 = the start, i = after the main line's move i−1).
 */
import {
  addMove,
  childrenOf,
  firstLineFrom,
  getNode,
  pathOnto,
  type MoveInput,
  type NodeId,
  type VarNode,
  type VarTree,
} from '../variations'

export type MainMove = MoveInput

/**
 * Where the board is. On the main line: `path` empty, the position `cur`. On a variation:
 * `cur` is the position it leaves the main line from, `path` the variation's displayed line
 * (its root-level move first, then what follows it) and `at` (1..path.length) the move shown.
 */
export interface Place {
  cur: number
  path: NodeId[]
  at: number
}

export const onMain = (cur: number): Place => ({ cur, path: [], at: 0 })

export function onVariation(p: Place): boolean {
  return p.path.length > 0 && p.at > 0
}

/** The variation move on the board, or null on the main line. */
export function nodeAt(tree: VarTree, p: Place): VarNode | null {
  return onVariation(p) ? getNode(tree, p.path[p.at - 1]) : null
}

/** The FEN on the board. */
export function placeFen(tree: VarTree, main: MainMove[], startFen: string, p: Place): string {
  const node = nodeAt(tree, p)
  if (node) return node.fen
  return p.cur === 0 ? startFen : main[p.cur - 1].fen
}

/** The move that led to the board's position (UCI), or null at the start. */
export function placeUci(tree: VarTree, main: MainMove[], p: Place): string | null {
  const node = nodeAt(tree, p)
  if (node) return node.uci
  return p.cur === 0 ? null : (main[p.cur - 1]?.uci ?? null)
}

/** Root-to-node ids. */
export function pathTo(tree: VarTree, id: NodeId): NodeId[] {
  const out: NodeId[] = []
  let n = getNode(tree, id)
  while (n) {
    out.push(n.id)
    n = n.parent === null ? null : getNode(tree, n.parent)
  }
  return out.reverse()
}

/** The ply index (from the main line's start) of a variation move: its root's position plus
 *  its depth in the branch. */
export function nodePly(tree: VarTree, id: NodeId): number {
  const n = getNode(tree, id)
  return n ? n.rootPly + pathTo(tree, id).length - 1 : 0
}

/** The place showing node `id`, with the line continuing past it as it was explored. */
export function placeOn(tree: VarTree, id: NodeId): Place | null {
  const n = getNode(tree, id)
  if (!n) return null
  const path = pathTo(tree, id)
  return { cur: n.rootPly, path: [...path, ...firstLineFrom(tree, id).map((x) => x.id)], at: path.length }
}

export type Step = 'back' | 'forward' | 'start' | 'end'

/**
 * Arrow keys and the navigator. On a variation they step within it: back from its first move
 * returns to the main line at the position it left from; Start goes there too; forward stops
 * at the variation's end (the main line's next move does not continue it). On the main line
 * they step the main line.
 */
export function step(p: Place, how: Step, mainLen: number): Place {
  if (onVariation(p)) {
    switch (how) {
      case 'forward':
        return p.at < p.path.length ? { ...p, at: p.at + 1 } : p
      case 'back':
        return p.at > 1 ? { ...p, at: p.at - 1 } : onMain(p.cur)
      case 'start':
        return onMain(p.cur)
      case 'end':
        return { ...p, at: p.path.length }
    }
  }
  const to = how === 'forward' ? p.cur + 1 : how === 'back' ? p.cur - 1 : how === 'start' ? 0 : mainLen
  return onMain(Math.max(0, Math.min(mainLen, to)))
}

/** Where a move played from `p` goes: the main line's own next move steps along it; at the
 *  end of an extendable main line (Analyse a position) the move extends it; anything else is
 *  a variation move under the node on the board (or off the main line at `cur`). */
export type Placement =
  | { kind: 'main' }
  | { kind: 'extend' }
  | { kind: 'tree'; parent: NodeId | null; rootPly: number }

export function placement(main: MainMove[], p: Place, uci: string, extendable: boolean): Placement {
  if (!onVariation(p)) {
    if (p.cur < main.length && main[p.cur].uci === uci) return { kind: 'main' }
    if (p.cur === main.length && extendable) return { kind: 'extend' }
    return { kind: 'tree', parent: null, rootPly: p.cur }
  }
  return { kind: 'tree', parent: p.path[p.at - 1], rootPly: p.cur }
}

export interface ExploreState {
  tree: VarTree
  main: MainMove[]
  place: Place
}

/** Play `moves` (each already checked legal, with its SAN and FEN) one after another from
 *  the board's place. A move already in the tree is reused, never duplicated. */
export function applyMoves(s: ExploreState, moves: MoveInput[], extendable: boolean): ExploreState {
  let { tree, main, place } = s
  for (const m of moves) {
    const pl = placement(main, place, m.uci, extendable)
    if (pl.kind === 'main') {
      place = onMain(place.cur + 1)
    } else if (pl.kind === 'extend') {
      main = [...main, m]
      place = onMain(place.cur + 1)
    } else {
      const r = addMove(tree, pl.parent, pl.rootPly, m)
      tree = r.tree
      const base = onVariation(place) ? place.path : []
      const at = onVariation(place) ? place.at : 0
      place = { cur: place.cur, path: pathOnto(tree, base, at, r.id), at: at + 1 }
    }
  }
  return { tree, main, place }
}

/** One line of the move list's variations: `depth` 0 leaves the main line, deeper ones leave
 *  a variation; `firstPly` is the ply index (from the main line's start) of its first move. */
export interface VarLine {
  depth: number
  firstPly: number
  nodes: VarNode[]
}

/**
 * Every variation leaving the main line at `rootPly`, as lines in the order they were
 * explored: each line follows its earliest-explored continuation, and the other moves tried
 * along it follow it as deeper lines. Every move in the tree appears exactly once.
 */
export function branchLines(tree: VarTree, rootPly: number): VarLine[] {
  const out: VarLine[] = []
  const emit = (start: VarNode, depth: number, firstPly: number) => {
    const nodes = [start, ...firstLineFrom(tree, start.id)]
    out.push({ depth, firstPly, nodes })
    nodes.forEach((n, i) => {
      const next = nodes[i + 1]
      if (!next) return
      for (const alt of childrenOf(tree, n.id, n.rootPly)) if (alt.id !== next.id) emit(alt, depth + 1, firstPly + i + 1)
    })
  }
  for (const c of childrenOf(tree, null, rootPly)) emit(c, 0, rootPly)
  return out
}

/** The main-line positions that have variations, ascending. */
export function branchPoints(tree: VarTree): number[] {
  const s = new Set<number>()
  for (const n of tree.nodes.values()) if (n.parent === null) s.add(n.rootPly)
  return [...s].sort((a, b) => a - b)
}

/** The variations by the position they leave from, for the move list. */
export function linesByRoot(tree: VarTree): Map<number, VarLine[]> {
  return new Map(branchPoints(tree).map((r) => [r, branchLines(tree, r)]))
}

/** Absolute ply index of the first move after a FEN: (fullmove − 1) × 2, +1 with Black to move.
 *  Numbers Analyse a position's moves from the FEN's own move number. */
export function plyBaseOf(fen: string): number {
  const parts = fen.trim().split(/\s+/)
  const full = Math.max(1, Number.parseInt(parts[5] ?? '1', 10) || 1)
  return (full - 1) * 2 + (parts[1] === 'b' ? 1 : 0)
}
