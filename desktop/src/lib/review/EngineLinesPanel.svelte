<script lang="ts">
  /**
   * The engine lines, pinned with their depth (DESIGN.md "Review: moves"): the best line
   * expanded, the others one per row and expandable, the played move's line marked. Every
   * move of an open line is a button: clicking it plays the line onto the board up to that
   * move (exploring, UI-BUILD-3 C). Shared by the Moves tab and Analyse a position.
   */
  import EmptyState from '../ui/EmptyState.svelte'
  import type { QualityClass } from '../ui/moveQuality'
  import { lineTokens, numberedLine } from './reviewModel'
  import { wholeTokens } from './wholeTokens'
  import type { LineRow, LinesStatus } from './engineLines'

  interface Props {
    rows: LineRow[]
    status: LinesStatus
    /** ply index of the lines' first move, for numbering */
    ply: number
    startsWhite: boolean
    depth: number | null
    /** "Depth 18 · live" for a live search */
    live?: boolean
    playedCls?: QualityClass | string | null
    onpick?: (ucis: string[]) => void
  }
  let { rows, status, ply, startsWhite, depth, live = false, playedCls = null, onpick }: Props = $props()

  let expanded = $state<Set<string>>(new Set(['l0', 'v0']))
  function toggle(k: string) {
    const s = new Set(expanded)
    if (s.has(k)) s.delete(k)
    else s.add(k)
    expanded = s
  }
  const BAD = ['inaccuracy', 'mistake', 'miss', 'blunder']
  /** The line's tokens, each move with its index in the line (what a click plays up to). */
  function indexed(sans: string[]): { num?: string; san?: string; move: number }[] {
    let m = -1
    return lineTokens(ply, sans, startsWhite).map((t) => (t.san ? { ...t, move: ++m } : { ...t, move: m }))
  }
</script>

<div class="lines" aria-label="Engine lines">
  <div class="lh">
    <span class="t">Engine lines</span>
    {#if depth}<span class="d">Depth {depth}{live ? ' · live' : ''}</span>{/if}
  </div>
  {#if status.kind === 'note'}
    <p class="none">{status.text}</p>
  {:else if status.kind === 'pending'}
    <p class="none"><span class="pulse" aria-hidden="true"></span>Analysing this position…</p>
  {:else if status.kind === 'error'}
    <div class="state">
      <EmptyState tone="error" sentence="The engine stopped on this position." sub={status.text} action={{ label: 'Try again', run: status.retry }} />
    </div>
  {:else if status.kind === 'no-engine'}
    <div class="state">
      <EmptyState
        sentence="Live lines need Stockfish, and none was found."
        sub="You can still play moves on the board."
        action={{ label: 'Open Settings', run: status.onsettings }}
      />
    </div>
  {:else}
    {#each rows as l (l.key)}
      {@const open = expanded.has(l.key)}
      <div class="lw" class:bestw={l.best && open}>
        <button type="button" class="line" aria-expanded={open} onclick={() => toggle(l.key)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={open ? 'var(--text-2)' : 'var(--text-3)'} stroke-width="2.2" aria-hidden="true"
            ><path d={open ? 'm6 9 6 6 6-6' : 'm9 6 6 6-6 6'} /></svg
          >
          <span class="ev" class:strong={l.best}>{l.eval}</span>
          {#if open || l.best}
            <span class="first">{numberedLine(ply, l.sans.slice(0, 1), startsWhite)}</span>
          {:else}
            {@const rest = numberedLine(ply, l.sans.slice(0, 6), startsWhite)}
            <!-- collapsed: as many whole moves as fit on the row (BETA-4 C: no move cut by an
                 ellipsis, as the mockup draws it); the title gives the line whole -->
            <span class="rest" title={rest} use:wholeTokens={rest}
              >{#each lineTokens(ply, l.sans.slice(0, 6), startsWhite) as t, i (i)}{i ? ' ' : ''}<span>{t.num ?? t.san}</span>{/each}</span
            >
          {/if}
          <span class="tag">
            {#if l.best && l.played}Best, played{:else if l.best}Best{:else if l.played}<span
                style:color={playedCls && BAD.includes(playedCls) ? `var(--q-${playedCls})` : undefined}
                >Played</span
              >{/if}
          </span>
        </button>
        {#if open}
          <div class="full">
            {#each indexed(l.sans.slice(0, 10)) as t, i (i)}
              {#if t.num}<span class="num">{t.num}</span>{:else if onpick && l.ucis.length > t.move}
                <button type="button" class="san" title="Play the line to here" onclick={() => onpick(l.ucis.slice(0, t.move + 1))}>{t.san}</button>
              {:else}<span class="san">{t.san}</span>{/if}
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  {/if}
</div>

<style>
  .lines {
    flex: none;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }
  .lh {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 8px 6px;
  }
  .t {
    font-weight: 500;
  }
  .d {
    color: var(--text-3);
    font: var(--secondary);
  }
  .none {
    margin: 0;
    padding: 6px 8px;
    color: var(--text-3);
    font: var(--secondary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .pulse {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-3);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .state {
    padding: 2px 0 4px;
  }
  .lw.bestw {
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  .line {
    width: 100%;
    display: grid;
    grid-template-columns: 12px 44px minmax(0, 1fr) auto;
    gap: 8px;
    align-items: center;
    padding: 7px 10px;
    background: none;
    border: 0;
    border-radius: var(--radius-control);
    text-align: left;
    color: inherit;
    font: var(--body);
    cursor: pointer;
  }
  .line:hover {
    background: var(--surface);
  }
  .line:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .ev {
    color: var(--text-2);
  }
  .ev.strong {
    color: var(--text);
    font-weight: 600;
  }
  .first {
    font-weight: 500;
  }
  .rest {
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    display: flex;
    gap: 0 0.28em;
    min-width: 0;
  }
  .tag {
    color: var(--text-3);
    font: var(--secondary);
  }
  .full {
    padding: 0 10px 10px 74px;
    line-height: 1.8;
    color: var(--chart-line);
    display: flex;
    flex-wrap: wrap;
    gap: 0 6px;
  }
  .full .num {
    color: var(--text-3);
  }
  button.san {
    padding: 0 2px;
    margin: 0 -2px;
    background: none;
    border: 0;
    border-radius: 3px;
    color: inherit;
    font: inherit;
    line-height: inherit;
    cursor: pointer;
  }
  button.san:hover {
    background: var(--raised);
    color: var(--text);
  }
  button.san:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 0;
  }
</style>
