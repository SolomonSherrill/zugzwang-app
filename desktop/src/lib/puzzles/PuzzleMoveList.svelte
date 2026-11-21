<script lang="ts">
  /**
   * A puzzle's move list (UI-BUILD-3 J; DESIGN.md fourth rulings, 11): from the opponent's setup
   * move, each move played, a wrong try struck beside the move it was tried for, and the rest of
   * the solution in grey once it is shown. Styled as Play's plain move list; the steppers are
   * Review's |‹ ‹ › ›|. Cells and steppers do not take focus on a click, so ← → and ↵ keep
   * working for the session after one (a focused button would keep ↵ for itself).
   */
  import type { PuzzleMoveRow, Step } from './puzzlesModel'

  interface Props {
    rows: PuzzleMoveRow[]
    /** index of the ply on the board */
    shown: number
    /** the last ply index */
    last: number
    onselect: (index: number) => void
    onstep: (step: Step) => void
  }
  let { rows, shown, last, onselect, onstep }: Props = $props()

  let list: HTMLElement | undefined = $state()
  // keep the move on the board in sight
  $effect(() => {
    void shown
    void rows
    const sel = list?.querySelector<HTMLElement>('.cell.sel')
    if (!list || !sel) return
    const top = sel.offsetTop - list.offsetTop
    if (top < list.scrollTop) list.scrollTop = top - 8
    else if (top + sel.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = top + sel.offsetHeight - list.clientHeight + 8
  })
  const noFocus = (e: MouseEvent) => e.preventDefault()
</script>

<div class="moves">
  <div class="mh">
    <span class="cap">Moves</span>
    <div class="nav">
      <button type="button" aria-label="The setup move" title="The setup move (Home)" disabled={shown <= 0} onmousedown={noFocus} onclick={() => onstep('start')}>|‹</button>
      <button type="button" aria-label="Previous move" title="Previous move (←)" disabled={shown <= 0} onmousedown={noFocus} onclick={() => onstep(-1)}>‹</button>
      <button type="button" aria-label="Next move" title="Next move (→)" disabled={shown >= last} onmousedown={noFocus} onclick={() => onstep(1)}>›</button>
      <button type="button" aria-label="The last move" title="The last move (End)" disabled={shown >= last} onmousedown={noFocus} onclick={() => onstep('end')}>›|</button>
    </div>
  </div>
  <div class="list" role="grid" aria-label="Moves" bind:this={list}>
    {#each rows as r (r.number)}
      <div class="mrow" role="row">
        <span class="num" role="rowheader">{r.number}.</span>
        {#each [r.white, r.black] as c, k (k)}
          {#if c && c.san !== null}
            {@const sel = c.index === shown}
            <button
              type="button"
              role="gridcell"
              class="cell"
              class:sel
              class:sol={c.kind === 'solution'}
              aria-selected={sel}
              tabindex="-1"
              onmousedown={noFocus}
              onclick={() => onselect(c.index)}
            >
              {#each c.tries as t, j (j)}<s class="try" title="Tried: not the move">{t}</s>{/each}<span>{c.san}</span>
            </button>
          {:else if c}
            <span class="cell pending" role="gridcell">
              {#each c.tries as t, j (j)}<s class="try" title="Tried: not the move">{t}</s>{/each}
            </span>
          {:else}
            <span class="cell empty" role="gridcell">{k === 0 ? '…' : ''}</span>
          {/if}
        {/each}
      </div>
    {/each}
  </div>
</div>

<style>
  .moves {
    flex: none;
    border-bottom: 1px solid var(--border);
    padding: 12px 20px 8px 12px;
  }
  .mh {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0 6px 8px;
  }
  .cap {
    color: var(--text-3);
    font: var(--secondary);
  }
  .nav {
    display: flex;
    gap: 4px;
  }
  .nav button {
    width: 28px;
    height: 26px;
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    color: var(--text-2);
    cursor: pointer;
    font: var(--body);
    padding: 0;
  }
  .nav button:hover:not(:disabled) {
    color: var(--text);
    background: var(--surface);
  }
  .nav button:disabled {
    color: var(--disabled);
    cursor: default;
  }
  .list {
    max-height: 152px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border-control) transparent;
  }
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
    font-variant-numeric: tabular-nums;
  }
  .cell {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
    padding: 4px 8px;
    border-radius: var(--radius-control);
    background: transparent;
    border: 0;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
  }
  .cell:hover {
    background: var(--raised);
  }
  .cell.sel {
    background: var(--selected);
    box-shadow: inset 0 0 0 1px var(--border-strong);
    font-weight: 600;
  }
  .cell.sol {
    color: var(--text-3);
  }
  .cell.sol.sel {
    color: var(--text-2);
  }
  .cell.empty,
  .cell.pending {
    color: var(--text-3);
    cursor: default;
  }
  .cell.empty:hover,
  .cell.pending:hover {
    background: transparent;
  }
  .try {
    color: var(--loss);
    font-weight: 400;
    text-decoration-thickness: 1px;
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
