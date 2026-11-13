<script lang="ts">
  interface Props {
    /** SAN strings in ply order, starting from the first move played */
    sans: string[]
    /** ply currently in view (number of plies played up to the shown position).
     *  Defaults to the latest ply so live play highlights the last move. */
    currentPly?: number
    /** jump the board to the position after the clicked ply. Omit for a
     *  read-only list (e.g. puzzles). */
    onselect?: (ply: number) => void
    /** fullmove number of the first SAN — for lines that don't start at move 1
     *  (puzzles begin mid-game). */
    startNumber?: number
    /** the first SAN is a black move — renders a "…" placeholder in the white
     *  column of the opening row. */
    blackFirst?: boolean
  }
  let { sans, currentPly, onselect, startNumber = 1, blackFirst = false }: Props = $props()

  let container: HTMLElement | undefined = $state()

  const ply = $derived(currentPly ?? sans.length)
  const interactive = $derived(!!onselect)

  const rows = $derived.by(() => {
    const out: { num: number; white: string | null; whiteIdx: number; black: string | null; blackIdx: number }[] = []
    let i = 0
    let num = startNumber
    if (blackFirst && sans.length) {
      out.push({ num, white: null, whiteIdx: -1, black: sans[0] ?? null, blackIdx: 0 })
      i = 1
      num++
    }
    for (; i < sans.length; i += 2) {
      out.push({ num, white: sans[i] ?? null, whiteIdx: i, black: sans[i + 1] ?? null, blackIdx: i + 1 })
      num++
    }
    return out
  })

  $effect(() => {
    void ply
    const el = container?.querySelector('.san.current') as HTMLElement | null
    if (el) el.scrollIntoView({ block: 'nearest' })
    else if (container) container.scrollTop = container.scrollHeight
  })
</script>

<div class="movelist" bind:this={container}>
  {#each rows as row (row.num)}
    <span class="num">{row.num}</span>
    <button
      class="san"
      class:current={ply === row.whiteIdx + 1}
      class:static={!interactive}
      disabled={!row.white}
      onclick={() => onselect?.(row.whiteIdx + 1)}
      >{row.white ?? (row.whiteIdx === -1 ? '…' : '')}</button>
    <button
      class="san"
      class:current={ply === row.blackIdx + 1}
      class:static={!interactive}
      disabled={!row.black}
      onclick={() => onselect?.(row.blackIdx + 1)}>{row.black ?? ''}</button>
  {/each}
</div>

<style>
  .movelist {
    display: grid;
    grid-template-columns: 34px 1fr 1fr;
    align-content: start;
    overflow-y: auto;
    font-size: 13px;
    line-height: 26px;
  }
  .num {
    color: var(--text-muted);
    padding-left: 14px;
    font-variant-numeric: tabular-nums;
    font-size: 12px;
  }
  .san {
    padding: 0 6px;
    margin-right: 6px;
    border-radius: var(--radius-sm);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    text-align: left;
    background: transparent;
    color: inherit;
    cursor: pointer;
    transition: background-color 100ms ease;
  }
  .san:hover:not(:disabled):not(.current):not(.static) {
    background: var(--bg-raised);
  }
  .san:disabled {
    cursor: default;
  }
  .san.static {
    cursor: default;
  }
  .san.current {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
</style>
