<script lang="ts">
  /**
   * Review: Moves (ruling 2, "Moves records"): the graph with notable-move dots (ruling 5),
   * the engine lines pinned with their depth (best line expanded, the played move's line
   * marked; a click on a move plays the line to it), the scrolling move list with icons and
   * evals from White's side (ruling 4) and the variations explored from it (UI-BUILD-3 C),
   * the result, and the move counts, vertical, you against the opponent.
   */
  import type { GameDetail } from '../api'
  import { describeTermination } from '../api'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import MovesGraph from './MovesGraph.svelte'
  import { moveReadout } from '../ui/readoutModel'
  import EngineLinesPanel from './EngineLinesPanel.svelte'
  import MoveExplain from './MoveExplain.svelte'
  import MoveGrid from './MoveGrid.svelte'
  import type { LineRow, LinesStatus } from './engineLines'
  import type { VarLine } from './explore'
  import type { NodeId } from '../variations'
  import { QUALITIES, QUALITY } from '../ui/moveQuality'
  import { moveLabel, moveRows, notableDots, sideOfPly, type Side } from './reviewModel'

  interface Props {
    game: GameDetail
    series: (number | null)[]
    names: Record<Side, string>
    you: Side | null
    /** the main-line position (on a variation: the one it leaves from) */
    current: number
    /** the engine lines for the board's position (stored or live), and their state */
    engine: { rows: LineRow[]; status: LinesStatus; depth: number | null; live: boolean; ply: number }
    playedCls: string | null
    /** the variations by the position they leave from, and the variation move on the board */
    lines: Map<number, VarLine[]>
    selectedNode: NodeId | null
    onjump: (position: number) => void
    onnode: (id: NodeId) => void
    onpick: (ucis: string[]) => void
    /** the run shown, for the selected move's explanation (null: the sidecar's default) */
    runId?: number | null
    /** "Flag this" on the selected move's explanation is open (⌘K "Flag this move") */
    flagOpen?: boolean
  }
  let {
    game, series, names, you, current, engine, playedCls, lines, selectedNode, onjump, onnode, onpick,
    runId = null, flagOpen = $bindable(false),
  }: Props = $props()

  const startsWhite = $derived(!game.startFen.includes(' b '))
  const rows = $derived(moveRows(game))
  const who = (s: Side) => (s === you ? 'you' : names[s])
  const dots = $derived(
    notableDots(game).map((d) => ({
      ...d,
      title: `${moveLabel(d.ply, game.plies[d.ply].san, startsWhite)}, ${who(sideOfPly(d.ply, startsWhite))}, ${QUALITY[d.cls].name.toLowerCase()}`,
    })),
  )
  const sans = $derived(game.plies.map((p) => p.san))
  const byPly = $derived(new Map((game.analysis?.moves ?? []).map((m) => [m.ply, m])))
  const readout = $derived((position: number) => moveReadout({ position, sans, moves: byPly, startsWhite, kind: 'eval' }))
  const graphLabel = $derived(
    `Evaluation through the game. ${dots.length} notable moves.${current > 0 ? ` Current position ${moveLabel(current - 1, game.plies[current - 1].san, startsWhite)}.` : ''}`,
  )

  // keep the selected move (or variation move) in view
  let list: HTMLDivElement | undefined = $state()
  $effect(() => {
    const sel = selectedNode ? `[data-node="${selectedNode}"]` : current > 0 ? `[data-ply="${current - 1}"]` : null
    if (!list || !sel) return
    const el = list.querySelector<HTMLElement>(sel)
    if (!el) return
    const box = list.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    // Only when it has left the view; centred, so the moves after it show too.
    if (r.top < box.top || r.bottom > box.bottom) el.scrollIntoView({ block: 'center' })
  })

  const counts = $derived(game.analysis?.summary ?? null)
  const cols: Side[] = $derived(you ? [you, you === 'white' ? 'black' : 'white'] : ['white', 'black'])
  const resultText = $derived(
    `${game.result.replace('1/2-1/2', '½–½').replace('-', '–')}${game.termination ? `, ${describeTermination(game.termination).toLowerCase()}` : ''}`,
  )
</script>

<div class="moves">
  {#if series.some((v) => v !== null)}
    <div class="graph">
      <MovesGraph {series} {dots} {current} label={graphLabel} {readout} {onjump} />
    </div>
  {/if}

  <EngineLinesPanel
    rows={engine.rows}
    status={engine.status}
    ply={engine.ply}
    {startsWhite}
    depth={engine.depth}
    live={engine.live}
    {playedCls}
    {onpick}
  />

  {#if game.analysis && current > 0 && !selectedNode}
    <MoveExplain
      gameId={game.id}
      ply={current - 1}
      label={moveLabel(current - 1, game.plies[current - 1].san, startsWhite)}
      cls={byPly.get(current - 1)?.classification ?? null}
      {runId}
      bind:flagOpen
    />
  {/if}

  <div class="scroll" bind:this={list}>
    <MoveGrid
      {rows}
      selectedPly={selectedNode ? null : current > 0 ? current - 1 : null}
      {lines}
      {selectedNode}
      base={startsWhite ? 0 : 1}
      {onjump}
      {onnode}
    />
    <p class="result">{resultText}</p>

    {#if counts}
      <section id="counts" class="counts" aria-label="Move counts">
        <div class="ch">
          <h2>Move counts</h2>
          {#each cols as s (s)}<span>{s === you ? 'You' : names[s]}</span>{/each}
        </div>
        {#each QUALITIES as q (q.cls)}
          <div class="crow">
            <span class="cname"><MoveQualityIcon cls={q.cls} size={18} decorative />{q.name}</span>
            {#each cols as s (s)}
              {@const n = counts[s]?.counts?.[q.cls] ?? 0}
              <span class:zero={n === 0}>{n}</span>
            {/each}
          </div>
        {/each}
        <!-- ruling D6 (FIX-B8, GAME_REPORT.md): the labels' help, word for word at depth 14 -->
        <p class="cnote" data-testid="labels-help">Move labels come from the depth-{game.analysis?.depth ?? 14} analysis.</p>
      </section>
    {/if}
  </div>
</div>

<style>
  .moves {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
  }
  .graph {
    flex: none;
    padding: 12px 20px 10px;
    border-bottom: 1px solid var(--border);
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 8px 12px 16px;
    scrollbar-width: thin;
    scrollbar-color: var(--border-control) transparent;
  }
  .result {
    margin: 10px 8px 0;
    color: var(--text-2);
  }
  .counts {
    margin: 18px 0 0;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }
  .ch,
  .crow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 72px 72px;
    align-items: center;
    padding: 0 8px;
  }
  .ch {
    margin-bottom: 6px;
  }
  .ch span {
    text-align: right;
    color: var(--text-3);
    font: var(--secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
  }
  .crow {
    min-height: 28px;
    border-top: 1px solid var(--divider);
  }
  .crow > span:not(.cname) {
    text-align: right;
  }
  .cname {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-2);
  }
  .zero {
    color: var(--disabled);
  }
  .cnote {
    margin: 8px 8px 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
