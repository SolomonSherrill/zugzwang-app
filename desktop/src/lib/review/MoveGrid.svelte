<script lang="ts">
  /**
   * The move list (DESIGN.md "Review: moves", ruling 4): number, White's and Black's moves
   * with their icons and evals. Variations (exploring, UI-BUILD-3 C) sit under the move they
   * leave from, indented and in secondary text, a deeper line further in; each move is a
   * button. Shared by the Moves tab and Analyse a position.
   */
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import type { NodeId } from '../variations'
  import type { VarLine } from './explore'
  import { lineTokens, type MoveRow } from './reviewModel'

  interface Props {
    rows: MoveRow[]
    /** the main-line ply selected (the position after it is on the board), or null */
    selectedPly: number | null
    /** variations by the main-line position they leave from */
    lines: Map<number, VarLine[]>
    selectedNode: NodeId | null
    /** absolute ply index of ply 0, for numbering (1 when Black moves first) */
    base: number
    onjump: (position: number) => void
    onnode: (id: NodeId) => void
  }
  let { rows, selectedPly, lines, selectedNode, base, onjump, onnode }: Props = $props()

  /** Which variation blocks follow which row: a block leaving position r sits under the row
   *  holding ply r − 1 (before the first row for r = 0, after the last past the end). */
  const blocks = $derived.by(() => {
    const before: VarLine[] = []
    const after = new Map<number, VarLine[]>()
    const last = rows.length - 1
    for (const [root, ls] of [...lines.entries()].sort((a, b) => a[0] - b[0])) {
      if (root === 0 || rows.length === 0) {
        before.push(...ls)
        continue
      }
      let at = rows.findIndex((r) => r.white?.ply === root - 1 || r.black?.ply === root - 1)
      if (at < 0) at = last
      after.set(at, [...(after.get(at) ?? []), ...ls])
    }
    return { before, after }
  })

  /** A variation line's tokens: move numbers, and each move with its node. */
  function tokens(l: VarLine) {
    let i = -1
    return lineTokens(base + l.firstPly, l.nodes.map((n) => n.san), true).map((t) =>
      t.san ? { san: t.san, node: l.nodes[++i] } : { num: t.num! },
    )
  }
</script>

{#snippet variation(ls: VarLine[])}
  <div role="row" class="vrow">
    <div role="gridcell" class="vcell">
      {#each ls as l, li (li)}
        <div class="vline" style:padding-left="{l.depth * 14}px">
          {#each tokens(l) as t, i (i)}
            {#if 'node' in t && t.node}
              <button
                type="button"
                class="vmove"
                data-node={t.node.id}
                aria-current={t.node.id === selectedNode ? 'true' : undefined}
                onclick={() => onnode(t.node!.id)}>{t.san}</button
              >
            {:else}
              <span class="vnum">{t.num}</span>
            {/if}
          {/each}
        </div>
      {/each}
    </div>
  </div>
{/snippet}

<div role="grid" aria-label="Moves">
  {#if blocks.before.length}{@render variation(blocks.before)}{/if}
  {#each rows as r, ri (r.number)}
    <div role="row" class="mrow">
      <span role="rowheader" class="num">{r.number}.</span>
      {#each [r.white, r.black] as c, j (j)}
        {#if c}
          <button
            type="button"
            role="gridcell"
            class="cell"
            data-ply={c.ply}
            aria-selected={c.ply === selectedPly}
            onclick={() => onjump(c.ply + 1)}
          >
            {#if c.cls}<MoveQualityIcon cls={c.cls} />{/if}
            <span class="san">{c.san}</span>
            {#if c.eval}<span class="cev">{c.eval}</span>{/if}
          </button>
        {:else}
          <span role="gridcell" class="cell empty">{j === 0 ? '…' : ''}</span>
        {/if}
      {/each}
    </div>
    {#if blocks.after.has(ri)}{@render variation(blocks.after.get(ri)!)}{/if}
  {/each}
</div>

<style>
  .mrow {
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
    gap: 4px;
    min-height: 30px;
  }
  .num {
    color: var(--text-3);
    padding-left: 8px;
  }
  .cell {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    border-radius: var(--radius-control);
    background: transparent;
    border: 0;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }
  .cell:hover {
    background: var(--surface);
  }
  .cell[aria-selected='true'] {
    background: var(--selected);
    box-shadow: inset 0 0 0 1px var(--border-strong);
    font-weight: 500;
  }
  .cell:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .cell.empty {
    cursor: default;
    color: var(--text-3);
  }
  .cev {
    margin-left: auto;
    color: var(--text-3);
    font: var(--secondary);
  }
  .cell[aria-selected='true'] .cev {
    color: var(--text-2);
  }
  .vrow {
    margin: 2px 0 4px 38px;
    padding: 4px 0 4px 10px;
    border-left: 1px solid var(--border-control);
  }
  .vline {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 4px;
    line-height: 24px;
  }
  .vnum {
    color: var(--text-3);
    font: var(--secondary);
    line-height: 24px;
  }
  .vmove {
    padding: 0 5px;
    background: transparent;
    border: 0;
    border-radius: var(--radius-control);
    color: var(--text-2);
    font: var(--body);
    line-height: 24px;
    cursor: pointer;
  }
  .vmove:hover {
    background: var(--surface);
    color: var(--text);
  }
  .vmove[aria-current='true'] {
    background: var(--selected);
    box-shadow: inset 0 0 0 1px var(--border-strong);
    color: var(--text);
    font-weight: 500;
  }
  .vmove:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
