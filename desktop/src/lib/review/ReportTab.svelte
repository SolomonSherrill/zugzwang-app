<script lang="ts">
  /**
   * Review: Report (ruling 2, "Report interprets"): the headline and meta line, the chart
   * (Eval / Material / Time) with the game's own phases, accuracy by player and by phase,
   * tactical errors as "N of M" (ruling 3; never "Positional", ruling 1 of 2026-11-20), and the key moments, each opening to its
   * existing explanation, Try it and Show the best move. Every sentence shown is one the
   * report already states; nothing is written here.
   */
  import type { GameDetail, ReportMoment, ReviewExtras } from '../api'
  import type { AnalysedReport, TryVerdict } from '../report'
  import { canTry, replyHidden, spentText, verdictText } from '../report'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import SegmentedControl from '../ui/SegmentedControl.svelte'
  import Button from '../ui/Button.svelte'
  import EvalChart, { type ChartMode } from './EvalChart.svelte'
  import { moveReadout } from '../ui/readoutModel'
  import {
    evalAfter, formatEval, lineEval, moveLabel, phaseBands, swingWords, type PhaseBand, type Side,
  } from './reviewModel'
  import { isQualityClass } from '../ui/moveQuality'
  import FlagThis from '../FlagThis.svelte'

  interface Props {
    game: GameDetail
    report: AnalysedReport
    extras: ReviewExtras | null
    names: Record<Side, string>
    you: Side | null
    meta: string[]
    current: number
    material: number[]
    engineOk: boolean
    trying: ReportMoment | null
    verdict: TryVerdict | null
    openPly: number | null
    onjump: (position: number) => void
    ontoggle: (ply: number) => void
    ontry: (m: ReportMoment) => void
    onstoptry: () => void
    onretry: () => void
    onshowbest: (m: ReportMoment) => void
    oncounts: () => void
  }
  let {
    game, report, extras, names, you, meta, current, material, engineOk, trying, verdict, openPly,
    onjump, ontoggle, ontry, onstoptry, onretry, onshowbest, oncounts,
  }: Props = $props()

  let mode = $state<ChartMode>('eval')
  const startsWhite = $derived(!game.startFen.includes(' b '))
  const hasClocks = $derived(!!extras?.clock.clocks.length)
  const bands: PhaseBand[] = $derived(
    extras ? phaseBands(extras.phases.middlegame, extras.phases.endgame, game.plies.length + 1) : [],
  )
  const momentDots = $derived(
    report.moments.shown
      .filter((m) => isQualityClass(m.classification))
      .map((m) => ({ position: m.ply + 1, cls: m.classification as never })),
  )
  const byPly = $derived(new Map((game.analysis?.moves ?? []).map((m) => [m.ply, m])))
  const kinds = $derived(new Map((extras?.errors ?? []).map((e) => [e.ply, e.kind])))

  // The chart's readout (ruling 12 of 2026-11-20, fourth): the move and its value in this mode.
  const sans = $derived(game.plies.map((p) => p.san))
  const readout = $derived((position: number) =>
    moveReadout({
      position, sans, moves: byPly, startsWhite, kind: mode, material, spent: extras?.clock.spent ?? [],
    }),
  )

  // Columns: you first, then the opponent (the mockup's order); White, Black when the
  // user's side is not known.
  const cols: Side[] = $derived(you ? [you, you === 'white' ? 'black' : 'white'] : ['white', 'black'])
  const colName = (s: Side) => (s === you ? 'You' : names[s])
  const acc = (s: Side) => (s === 'white' ? game.analysis?.whiteAccuracy : game.analysis?.blackAccuracy) ?? null
  const phaseAcc = (s: Side, ph: 'opening' | 'middlegame' | 'endgame') => extras?.accuracyByPhase?.[s][ph] ?? null
  const reached = $derived(new Set(bands.map((b) => b.phase.toLowerCase())))

  /** An opened key moment scrolls into the panel's view, its buttons included (BETA-4 C: at
   *  720 px high they sat below the panel's bottom edge). */
  function reveal(node: HTMLElement) {
    requestAnimationFrame(() => node.closest('li')?.scrollIntoView({ block: 'nearest' }))
  }
  function initial(s: Side): string {
    return (names[s].trim()[0] ?? '?').toUpperCase()
  }
  function moveEval(m: ReportMoment): { played: string; best: string; line: string } | null {
    const a = byPly.get(m.ply)
    if (!a) return null
    const best = a.lines[0]
    return {
      played: formatEval(evalAfter(a, startsWhite)),
      best: best ? formatEval(lineEval(m.ply, best, startsWhite)) : '',
      line: best && m.bestSan !== m.san ? best.san.slice(0, 5).join(' ') : '',
    }
  }
</script>

<div class="report">
  <div class="head">
    {#if report.headline?.length}
      <h1>{report.headline[0]}<FlagThis kind="report headline" gameId={game.id} shown={report.headline[0]} /></h1>
      {#each report.headline.slice(1) as s (s)}<p class="sub">{s}<FlagThis kind="report headline" gameId={game.id} shown={s} /></p>{/each}
    {/if}
    <div class="meta">
      {#each meta as m (m)}<span>{m}</span>{/each}
    </div>
  </div>

  <figure>
    <div class="chart-head">
      <SegmentedControl
        label="Chart"
        bind:value={mode}
        options={[
          { value: 'eval', label: 'Eval' },
          { value: 'material', label: 'Material' },
          ...(hasClocks ? [{ value: 'time' as ChartMode, label: 'Time' }] : []),
        ]}
      />
      <span class="hint">Click to jump</span>
    </div>
    <EvalChart
      {mode}
      series={report.series}
      {material}
      spent={extras?.clock.spent ?? []}
      {you}
      {startsWhite}
      {bands}
      dots={momentDots}
      {current}
      {readout}
      {onjump}
    />
  </figure>

  <div class="acc">
    <div class="cols" aria-hidden="true"><span></span>{#each cols as s (s)}<span title={colName(s)}>{colName(s)}</span>{/each}</div>
    <dl>
      <div class="row top">
        <dt>Accuracy</dt>
        {#each cols as s, i (s)}
          <dd class="big" class:opp={i === 1}>
            {#if acc(s) !== null}<button type="button" class="link" title="Move counts" onclick={oncounts}>{acc(s)!.toFixed(1)}</button>{:else}–{/if}
          </dd>
        {/each}
      </div>
      {#if extras?.accuracyByPhase}
        {#each [['opening', 'Opening'], ['middlegame', 'Middlegame'], ['endgame', 'Endgame']] as [ph, label] (ph)}
          {#if reached.has(ph)}
            <div class="row phase">
              <dt>{label}</dt>
              {#each cols as s, i (s)}
                {@const v = phaseAcc(s, ph as 'opening')}
                <dd class:opp={i === 1}>{v === null ? '–' : Math.round(v)}</dd>
              {/each}
            </div>
          {/if}
        {/each}
      {/if}
      {#if extras?.errorCounts}
        <div class="row top err">
          <dt>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="2" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z" /></svg>Tactical errors
          </dt>
          {#each cols as s, i (s)}<dd class:opp={i === 1}>{extras.errorCounts[s].tactical}<span class="of">{' '}of {extras.errorCounts[s].errors}</span></dd>{/each}
        </div>
      {/if}
    </dl>
  </div>

  {#if report.moments.shown.length}
    <section class="moments" aria-label="Key moments">
      <div class="mh"><h2>Key moments</h2><span>{report.moments.shown.length}</span></div>
      <ul>
        {#each report.moments.shown as m (m.ply)}
          {@const open = openPly === m.ply}
          {@const kind = kinds.get(m.ply)}
          {@const hiding = trying?.ply === m.ply && (verdict === null || verdict.kind === 'judging')}
          {@const ev = moveEval(m)}
          <li class:open>
            <!-- FLAG-RESTORE (DESIGN.md "Owner rulings, 2026-11-21", 2): the moment's ⚑ at the row's right (beta only) -->
            <div class="kmrow">
            <button type="button" class="km" aria-expanded={open} onclick={() => ontoggle(m.ply)}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={open ? 'var(--text-2)' : 'var(--text-3)'} stroke-width="2.2" aria-hidden="true"
                ><path d={open ? 'm6 9 6 6 6-6' : 'm9 6 6 6-6 6'} /></svg
              >
              <span class="av" class:you={m.side === you} aria-label={m.side === you ? 'You' : names[m.side]}>{initial(m.side)}</span>
              <span class="mv"><MoveQualityIcon cls={m.classification} />{m.san ? moveLabel(m.ply, m.san, startsWhite) : m.label}</span>
              <span class="sw">{swingWords(m)}</span>
              <span class="kind">
                {#if kind === 'tactical'}<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z" /></svg>Tactic{/if}
              </span>
              <span class="spent">{m.spent !== null ? spentText(m.spent) : ''}</span>
            </button>
            <FlagThis
              kind="report moment"
              gameId={game.id}
              ply={m.ply}
              label={m.classification}
              shown="{m.san ? moveLabel(m.ply, m.san, startsWhite) : m.label} · {swingWords(m)}"
            />
            </div>
            {#if open}
              <div class="body" use:reveal>
                {#if !hiding}
                  {#each m.sentences as s (s)}<p class="say">{s}<FlagThis kind="report claim" gameId={game.id} ply={m.ply} label={m.classification} shown={s} /></p>{/each}
                  {#if m.qualifier}<p class="say">{m.qualifier}<FlagThis kind="report qualifier" gameId={game.id} ply={m.ply} label={m.classification} shown={m.qualifier} /></p>{/if}
                  {#if m.descriptions?.length}
                    <p class="cmp">Compared with {m.bestSan ?? 'the engine move'}</p>
                    {#each m.descriptions as d (d)}<p class="say">{d}<FlagThis
                        kind="report description"
                        gameId={game.id}
                        ply={m.ply}
                        label={m.classification}
                        shown={d}
                        context="Compared with {m.bestSan ?? 'the engine move'}"
                      /></p>{/each}
                  {/if}
                  {#if ev}
                    <div class="evals">
                      <span>Played <b>{ev.played}</b></span>
                      {#if ev.best && m.bestSan !== m.san}<span>Best <b>{ev.best}</b></span>{/if}
                      {#if ev.line}<span class="line">{ev.line}</span>{/if}
                    </div>
                  {/if}
                {/if}
                {#if m.reply && !replyHidden(m, trying?.ply ?? null, verdict)}<p class="reply">{m.reply}<FlagThis kind="report reply" gameId={game.id} ply={m.ply + 1} shown={m.reply} /></p>{/if}
                {#if trying?.ply === m.ply}
                  <p class="verdict" role="status">{verdict ? verdictText(verdict) : 'Your move — play it on the board.'}</p>
                  <div class="acts">
                    {#if verdict && verdict.kind !== 'judging'}<Button onclick={onretry}>Try again</Button>{/if}
                    <Button onclick={onstoptry}>Done</Button>
                  </div>
                {:else}
                  <div class="acts">
                    {#if canTry(m, engineOk)}<Button variant="primary" kbd="T" onclick={() => ontry(m)}>Try it</Button>{/if}
                    {#if m.bestUci && m.bestSan !== m.san}<Button onclick={() => onshowbest(m)}>Show the best move</Button>{/if}
                  </div>
                {/if}
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if report.context?.length}
    <div class="context">
      {#each report.context as c (c)}<p>{c}<FlagThis kind="report line" gameId={game.id} shown={c} /></p>{/each}
    </div>
  {/if}
</div>

<style>
  .report {
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  h1 {
    margin: 0;
    font: var(--heading);
    line-height: 1.4;
  }
  .sub {
    margin: 2px 0 0;
    color: var(--text-2);
  }
  .meta {
    margin-top: 3px;
    display: flex;
    flex-wrap: wrap;
    gap: 2px 14px;
    color: var(--text-3);
    font: var(--secondary);
  }
  figure {
    margin: 0;
  }
  .chart-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .hint {
    color: var(--text-3);
    font: var(--secondary);
  }
  .cols,
  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 60px 60px;
  }
  .cols {
    padding-bottom: 4px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .cols span {
    text-align: right;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  dl {
    margin: 0;
  }
  dd {
    margin: 0;
    text-align: right;
  }
  .opp {
    color: var(--text-2);
  }
  .row {
    padding: 4px 0;
    align-items: baseline;
  }
  .row.top {
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .row.top dt {
    font-weight: 500;
  }
  .row.phase dt {
    color: var(--text-2);
    padding-left: 12px;
  }
  .row.err dt {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 400;
  }
  .of {
    color: var(--text-3);
  }
  .row.err.top {
    padding: 6px 0 4px;
  }
  .big {
    font-size: 17px;
    font-weight: 500;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .link:hover {
    text-decoration: underline;
    text-decoration-color: var(--disabled);
    text-underline-offset: 3px;
  }
  .mh {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }
  h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
  }
  .mh span {
    color: var(--text-3);
    font: var(--secondary);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--border);
  }
  li {
    border-bottom: 1px solid var(--border);
  }
  li.open {
    scroll-margin-bottom: 16px;
    background: var(--surface);
    margin: 0 -10px;
    padding: 0 10px;
  }
  .kmrow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    column-gap: 4px;
  }
  .km {
    flex: 1;
    min-width: 0;
    width: 100%;
    display: grid;
    grid-template-columns: 12px 16px 100px minmax(0, 1fr) auto 36px;
    gap: 8px;
    align-items: center;
    padding: 9px 0;
    background: none;
    border: 0;
    text-align: left;
    color: inherit;
    font: var(--body);
    cursor: pointer;
  }
  .km:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .av {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    background: var(--selected);
    color: var(--text-2);
    font-size: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .av.you {
    background: var(--text);
    color: var(--primary-ink);
    font-weight: 600;
  }
  .mv {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 500;
    white-space: nowrap;
  }
  .sw {
    color: var(--text-2);
  }
  li.open .sw,
  .km:hover .sw {
    color: var(--text);
  }
  .kind {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .spent {
    color: var(--text-3);
    font: var(--secondary);
    text-align: right;
  }
  .body {
    padding: 0 0 12px 44px;
  }
  .say {
    margin: 0 0 6px;
    color: var(--chart-line);
  }
  .cmp {
    margin: 4px 0 2px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .reply {
    margin: 0 0 8px;
    color: var(--text-2);
    font: var(--secondary);
  }
  .evals {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
    font: var(--secondary);
    color: var(--text-3);
    min-width: 0;
  }
  .evals b {
    color: var(--text);
    font-weight: 400;
  }
  .line {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .verdict {
    margin: 0 0 8px;
  }
  .acts {
    display: flex;
    gap: 6px;
  }
  .context p {
    margin: 0 0 4px;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
