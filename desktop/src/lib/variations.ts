/**
 * A variation tree for board exploration.
 *
 * Tree *shape* lives here, in the webview, because it is a record of what the user
 * clicked — navigation state, not board truth. Node *positions* (`fen`, `san`) are
 * board truth and come from the sidecar; this module never computes them, it only
 * stores what it was handed. See `rpc_probe_move`.
 *
 * **Nothing in here removes a node.** The screen this replaced truncated the line
 * whenever the user played a move from an earlier point, silently discarding every
 * move after it. Replaying a move that already exists returns the existing child
 * instead of creating a duplicate or overwriting a sibling, so exploring the same
 * line twice is idempotent and exploring a different one branches.
 */

export type NodeId = string

export interface VarNode {
  readonly id: NodeId
  /** null = branches straight off the mainline at `rootPly`. */
  readonly parent: NodeId | null
  /** The mainline ply index this whole branch left from. Inherited by children. */
  readonly rootPly: number
  readonly uci: string
  readonly san: string
  readonly fen: string
}

export interface VarTree {
  readonly nodes: ReadonlyMap<NodeId, VarNode>
  readonly nextId: number
}

export interface MoveInput {
  uci: string
  san: string
  fen: string
}

export function emptyTree(): VarTree {
  return { nodes: new Map(), nextId: 1 }
}

export function getNode(tree: VarTree, id: NodeId): VarNode | null {
  return tree.nodes.get(id) ?? null
}

/**
 * Children of `parent`. For root level (`parent === null`) this is scoped to
 * `rootPly`, because two branches off two different mainline plies are unrelated
 * and must not appear as alternatives to each other.
 */
export function childrenOf(tree: VarTree, parent: NodeId | null, rootPly: number): VarNode[] {
  const out: VarNode[] = []
  for (const n of tree.nodes.values()) {
    if (n.parent !== parent) continue
    if (parent === null && n.rootPly !== rootPly) continue
    out.push(n)
  }
  return out
}

/**
 * Add `move` under `parent`, or return the existing child if that move is already
 * there. `rootPly` is only consulted for root-level nodes; a child always inherits
 * its parent's, which is what keeps "which mainline ply does this branch leave
 * from" answerable in O(1) from any node.
 */
export function addMove(
  tree: VarTree,
  parent: NodeId | null,
  rootPly: number,
  move: MoveInput,
): { tree: VarTree; id: NodeId } {
  const ply = parent === null ? rootPly : (tree.nodes.get(parent)?.rootPly ?? rootPly)
  const existing = childrenOf(tree, parent, ply).find((n) => n.uci === move.uci)
  if (existing) return { tree, id: existing.id }

  const id = `v${tree.nextId}`
  const nodes = new Map(tree.nodes)
  nodes.set(id, { id, parent, rootPly: ply, uci: move.uci, san: move.san, fen: move.fen })
  return { tree: { nodes, nextId: tree.nextId + 1 }, id }
}

/**
 * Extend a line past `node` by following the earliest-explored child at each step.
 *
 * This is what makes "nothing is removed" visible rather than merely true: stepping
 * back and taking a different move leaves the old continuation in the tree, and
 * returning to it restores the whole line, not just the one move.
 */
export function firstLineFrom(tree: VarTree, id: NodeId): VarNode[] {
  const out: VarNode[] = []
  let cur = tree.nodes.get(id) ?? null
  while (cur) {
    const next: VarNode | undefined = childrenOf(tree, cur.id, cur.rootPly)[0]
    if (!next) break
    out.push(next)
    cur = next
  }
  return out
}

/**
 * The line to display after stepping onto `id` from depth `at` of `path`.
 *
 * This is the rule that decides what stays on screen, and the one place where a
 * careless slice would lose the user's place. Stepping onto the move already shown
 * at `at` keeps the rest of the displayed line; stepping onto any other move shows
 * that branch instead, extended with whatever was explored past it. Either way the
 * replaced moves only leave the screen — they are still in the tree.
 */
export function pathOnto(tree: VarTree, path: NodeId[], at: number, id: NodeId): NodeId[] {
  if (path[at] === id) return path
  return [...path.slice(0, at), id, ...firstLineFrom(tree, id).map((n) => n.id)]
}
