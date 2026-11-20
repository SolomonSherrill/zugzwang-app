<script lang="ts">
  import type { ReportMoment } from './api'
  import { CLASS_COLORS } from './classification'
  import FlagThis from './FlagThis.svelte'
  import {
    bandChange,
    basisText,
    canTry,
    momentClock,
    verdictText,
    type TryVerdict,
    momentsHeading,
    replyHidden,
    reportItems,
    type AnalysedReport,
  } from './report'

  interface Props {
    report: AnalysedReport
    /** For "flag this" (BETA): the game the report is about. */
    gameId?: number | null
    /** Board position: 0 = start, i = after ply i-1. */
    current: number
    onseek: (position: number) => void
    onshowmoves: (position: number) => void
    engineOk?: boolean
    /** The moment being tried, if any. */
    tryingPly?: number | null
    verdict?: TryVerdict | null
    ontry?: (m: ReportMoment) => void
    onretry?: () => void
    onstop?: () => void
  }
  let {
    report,
    gameId = null,
    current,
    onseek,
    onshowmoves,
    engineOk = false,
    tryingPly = null,
    verdict = null,
    ontry = () => {},
    onretry = () => {},
    onstop = () => {},
  }: Props = $props()

  const items = $derived(reportItems(report))
  const heading = $derived(momentsHeading(report.moments.total, report.moments.shown.length))
  const standingOf = $derived(
    report.moments.shown[0]?.yours === null ? (report.basis.pov === 'white' ? "White's" : "Black's") : 'your',
  )

  function who(yours: boolean | null, side: 'white' | 'black'): string {
    if (yours === null) return side === 'white' ? 'White' : 'Black'
    return yours ? 'You' : 'Opponent'
  }
</script>

<div class="report">
  <!-- R5 (GR2-12): the headline first — two sentences at most, each clause from a field. -->
  {#if report.headline?.length}
    <p class="headline">
      {#each report.headline as line (line)}
        <span>{line}<FlagThis kind="report headline" {gameId} shown={line} /></span>{' '}
      {/each}
    </p>
  {/if}
  {#if report.slide}
    {@const sl = report.slide}
    <!-- A slow decline has no card to click, so the stretch gets its own way in. -->
    <button class="step" onclick={() => onseek(sl.from)}>Step through the slide</button>
  {/if}


  {#each items as item (item.kind === 'card' ? item.group[0].ply : 'found')}
    {#if item.kind === 'found'}
    {@const f = item.found}
    <!-- GR2-8: the game's one "found it" moment, in game order among the cards, marked ✓
         and not numbered. -->
    <div
      class="card"
      class:current={f.ply + 1 === current}
      role="button"
      tabindex="0"
      onclick={() => onseek(f.ply + 1)}
      onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onseek(f.ply + 1)}
    >
      <span class="num found">✓</span>
      <div class="body">
        <div class="move">
          <button
            class="label"
            onclick={(e) => {
              e.stopPropagation()
              onseek(f.ply + 1)
            }}
          >
            <span class="dot" style="background: {CLASS_COLORS[f.classification]}"></span>
            {f.label}
          </button>
          <span class="who">You · found it</span>
        </div>
        <ul class="explain">
          <li>{f.sentence}<FlagThis kind="report found" {gameId} ply={f.ply}
                                    label={f.classification} shown={f.sentence} /></li>
        </ul>
        <button
          class="to-moves"
          onclick={(e) => {
            e.stopPropagation()
            onshowmoves(f.ply + 1)
          }}>Show in moves</button
        >
      </div>
    </div>
    {:else}
    {@const group = item.group}
    {@const i = item.n - 1}
    {@const at = group[0].ply + 1}
    <!-- The card seeks to the position after its first move, which is where the
         move list puts you too: the played move highlighted, the best move drawn. -->
    <div
      class="card"
      class:current={group.some((m) => m.ply + 1 === current)}
      role="button"
      tabindex="0"
      onclick={() => onseek(at)}
      onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onseek(at)}
    >
      <span class="num" class:yours={group[0].yours === true}>{i + 1}</span>
      <div class="body">
        {#each group as m (m.ply)}
          <div class="move">
            <button
              class="label"
              onclick={(e) => {
                e.stopPropagation()
                onseek(m.ply + 1)
              }}
            >
              <span class="dot" style="background: {CLASS_COLORS[m.classification]}"></span>
              {m.label}
            </button>
            <span class="who">{who(m.yours, m.side)}</span>
            <span class="band">{bandChange(m)}</span>
            <FlagThis kind="report moment" {gameId} ply={m.ply} label={m.classification}
                      shown="{m.label} · {who(m.yours, m.side)} · {bandChange(m)}" />
          </div>
          {@const hiding = tryingPly === m.ply && (verdict === null || verdict.kind === 'judging')}
          {#if (m.bestSan && m.bestSan !== m.san) || momentClock(m)}
            <div class="best">
              <!-- Hidden while this moment is being tried: it is the answer. -->
              {#if m.bestSan && m.bestSan !== m.san && !hiding}<span>Best was {m.bestSan}</span>{/if}
              {#if momentClock(m)}<span class="clock">{momentClock(m)}</span>{/if}
            </div>
          {/if}
          {#if (m.sentences.length || m.qualifier) && !hiding}
            <ul class="explain">
              {#each m.sentences as s (s)}
                <li>{s}<FlagThis kind="report claim" {gameId} ply={m.ply}
                                 label={m.classification} shown={s} /></li>
              {/each}
              {#if m.qualifier}
                <li>{m.qualifier}<FlagThis kind="report qualifier" {gameId} ply={m.ply}
                                           label={m.classification} shown={m.qualifier} /></li>
              {/if}
            </ul>
          {/if}
          <!-- One move, one account (AUDIT-2): the card shows what the Review callout
               shows, descriptions under their own heading as they are there (layer 5). -->
          {#if m.descriptions?.length && !hiding}
            <div class="describe">
              <span class="describe-head">Compared with {m.bestSan ?? 'the engine move'}</span>
              <ul class="explain">
                {#each m.descriptions as d (d)}
                  <li>{d}<FlagThis kind="report description" {gameId} ply={m.ply}
                                   label={m.classification} shown={d}
                                   context="Compared with {m.bestSan ?? 'the engine move'}" /></li>
                {/each}
              </ul>
            </div>
          {/if}
          {#if m.reply && !replyHidden(m, tryingPly, verdict)}
            <!-- GR2-6: the user's reply to an opponent's moment, in the muted line style. -->
            <div class="best"><span>{m.reply}</span><FlagThis kind="report reply" {gameId}
                 ply={m.ply + 1} shown={m.reply} /></div>
          {/if}
          {#if tryingPly === m.ply}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="try" onclick={(e) => e.stopPropagation()}>
              <span class="try-text"
                >{verdict ? verdictText(verdict) : 'Your move — play it on the board.'}</span
              >
              <span class="try-actions">
                {#if verdict && verdict.kind !== 'judging'}
                  <button onclick={onretry}>Try again</button>
                {/if}
                <button onclick={onstop}>Back to the game</button>
              </span>
            </div>
          {:else if canTry(m, engineOk)}
            <button
              class="try-btn"
              onclick={(e) => {
                e.stopPropagation()
                ontry(m)
              }}>Try it</button
            >
          {/if}
        {/each}
        <button
          class="to-moves"
          onclick={(e) => {
            e.stopPropagation()
            onshowmoves(at)
          }}>Show in moves</button
        >
      </div>
    </div>
    {/if}
  {/each}

  <!-- R5: context last — the clock line (the pattern line left with R6-5), then the count. -->
  {#if report.context?.length}
    <ul class="story context">
      {#each report.context as line (line)}
        <li>{line}<FlagThis kind="report line" {gameId} shown={line} /></li>
      {/each}
    </ul>
  {/if}
  {#if heading}
    <!-- The band on each card is one side's standing before → after the move: the
         user's whoever moved, so an opponent's error reads as an improvement. -->
    <div class="heading">
      <span>{heading}</span>
      <span class="pov">{standingOf} standing</span>
    </div>
  {/if}
</div>
<div class="basis">{basisText(report)}<FlagThis kind="report basis" {gameId} shown={basisText(report)} /></div>

<style>
  .report {
    flex: 1;
    overflow-y: auto;
    padding: 10px 14px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .headline {
    margin: 0;
    font-size: 13.5px;
    line-height: 1.5;
  }
  .story {
    margin: 0;
    padding: 0 0 0 16px;
    list-style: disc;
    font-size: 13px;
    line-height: 1.45;
  }
  .story li + li {
    margin-top: 4px;
  }
  .story.context {
    margin-top: 4px;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .step {
    align-self: flex-start;
    padding: 4px 10px;
    font-size: 12px;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
  }
  .step:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .heading {
    display: flex;
    justify-content: space-between;
    margin-top: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .pov {
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: none;
  }
  .card {
    display: flex;
    gap: 10px;
    padding: 9px 11px;
    border-radius: var(--radius);
    border: 1px solid var(--divider);
    background: var(--bg-raised);
    cursor: pointer;
    text-align: left;
  }
  .card:hover {
    border-color: color-mix(in srgb, var(--accent) 45%, var(--divider));
  }
  .card.current {
    border-color: var(--accent);
  }
  .num {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--accent);
    color: var(--bg-surface);
    font-size: 11px;
    font-weight: 700;
  }
  .num.yours {
    background: var(--danger);
  }
  .num.found {
    background: var(--win);
  }
  .body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .move {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 13px;
  }
  .label {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .label:hover {
    color: var(--accent);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
  .who {
    font-size: 12px;
    color: var(--text-muted);
  }
  .band {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-muted);
    white-space: nowrap;
  }
  .best {
    display: flex;
    gap: 8px;
    font-size: 12px;
    color: var(--text-muted);
  }
  .clock {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .explain {
    margin: 2px 0 0;
    padding: 0 0 0 16px;
    list-style: disc;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text-muted);
  }
  .describe {
    margin-top: 4px;
  }
  .describe-head {
    display: block;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-muted);
  }
  .try-btn {
    align-self: flex-start;
    margin-top: 2px;
    padding: 3px 9px;
    font-size: 11.5px;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
  }
  .try-btn:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .try {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 4px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--accent);
    background: var(--bg-tile);
    cursor: default;
  }
  .try-text {
    font-size: 12.5px;
    line-height: 1.45;
  }
  .try-actions {
    display: flex;
    gap: 12px;
  }
  .try-actions button {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .try-actions button:hover {
    color: var(--accent);
  }
  .to-moves {
    align-self: flex-start;
    margin-top: 2px;
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .to-moves:hover {
    color: var(--accent);
  }
  .basis {
    padding: 6px 14px;
    font-size: 11px;
    color: var(--text-muted);
    border-top: 1px solid var(--divider);
  }
</style>
