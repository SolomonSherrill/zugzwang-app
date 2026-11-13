<script lang="ts">
  import type { EngineLine } from './api'

  interface Props {
    /** top engine lines, best first; cp/mate are side-to-move POV */
    lines: EngineLine[]
    /** position the lines start from — drives move numbering + White POV */
    fen: string
    /** half-moves of each line to show */
    plies?: number
    /** play a prefix of a line onto the board, as a variation */
    onpick: (ucis: string[]) => void
  }
  let { lines, fen, plies = 6, onpick }: Props = $props()

  const ctx = $derived.by(() => {
    const parts = fen.split(' ')
    return {
      whiteToMove: parts[1] !== 'b',
      moveNo: Number.parseInt(parts[5] ?? '1', 10) || 1,
    }
  })

  /** mover-POV score → White-POV eval string ("+0.39", "-1.20", "M3", "-M2"). */
  function evalText(cp: number | null, mate: number | null): string {
    const flip = ctx.whiteToMove ? 1 : -1
    if (mate !== null) {
      const m = mate * flip
      return m >= 0 ? `M${m}` : `-M${Math.abs(m)}`
    }
    if (cp === null) return '—'
    const pawns = (cp * flip) / 100
    const body = Math.abs(pawns).toFixed(2)
    return pawns >= 0 ? `+${body}` : `-${body}`
  }

  interface Move {
    /** shown where it changes: "1.", a leading "1…", or nothing */
    num: string
    san: string
    /** the line up to and including this move — what clicking it plays */
    ucis: string[]
  }

  /** A line as individually clickable moves, numbered from the root position. */
  function movesOf(line: EngineLine): Move[] {
    const out: Move[] = []
    let n = ctx.moveNo
    let white = ctx.whiteToMove
    for (let i = 0; i < Math.min(plies, line.san.length); i++) {
      out.push({
        num: white ? `${n}.` : i === 0 ? `${n}…` : '',
        san: line.san[i],
        ucis: line.uci.slice(0, i + 1),
      })
      if (!white) n += 1
      white = !white
    }
    return out
  }
</script>

<div class="engine-lines">
  {#if lines.length === 0}
    <div class="pending"><span class="pulse-dot"></span> Analysing…</div>
  {:else}
    {#each lines as line, i (i)}
      <div class="line" class:top={i === 0}>
        <span class="ev">{evalText(line.cp, line.mate)}</span>
        <!-- Every move is clickable, not just the first: the point of showing six
             half-moves is to let the user step into the middle of one. -->
        <span class="moves">
          {#each movesOf(line) as mv, k (k)}
            {#if mv.num}<span class="num">{mv.num}</span>{/if}
            <button class="mv" onclick={() => onpick(mv.ucis)}>{mv.san}</button>
          {/each}
        </span>
      </div>
    {/each}
  {/if}
</div>

<style>
  .engine-lines {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    background: var(--bg-surface);
    overflow: hidden;
    font-variant-numeric: tabular-nums;
  }
  .pending {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    color: var(--text-muted);
    font-size: 13px;
  }
  .line {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 5px 12px;
    font-size: 12px;
    color: var(--text-muted);
    border-top: 1px solid var(--divider);
    white-space: nowrap;
    overflow: hidden;
  }
  .line:first-child {
    border-top: none;
  }
  .line.top {
    font-size: 13.5px;
    color: var(--text);
    font-weight: 600;
    background: var(--accent-soft);
  }
  .ev {
    flex-shrink: 0;
    width: 52px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .line:not(.top) .ev {
    color: var(--text-muted);
  }
  .moves {
    overflow: hidden;
    text-overflow: ellipsis;
    font-feature-settings: 'tnum';
  }
  .num {
    margin-right: 2px;
    color: var(--text-muted);
    font-weight: 400;
  }
  .num:not(:first-child) {
    margin-left: 5px;
  }
  .mv {
    padding: 0 1px;
    border: 0;
    border-radius: 3px;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .mv + .mv {
    margin-left: 5px;
  }
  .mv:hover {
    background: var(--accent);
    color: var(--accent-ink);
  }
</style>
