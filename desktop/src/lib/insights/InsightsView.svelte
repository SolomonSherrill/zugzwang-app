<script lang="ts">
  /**
   * Insights, rebuilt (UI-BUILD-2 C; DESIGN.md "Insights", ruling 14; mockups
   * design/mockups/MinimalInsights*.html). One filter bar (time frame; Bullet, Blitz, Rapid,
   * Classical, Daily; colour; rated or casual; games vs Stockfish, off by default; Reset), then
   * the stats strip with 12-month trends, accuracy over time, patterns (the R6 sentences
   * verbatim behind their links), move quality, by phase (Accuracy / Move quality; phases from
   * each game's own division), openings (As White / As Black), how your games end, when you
   * play best, castling. Every figure comes from core/insights_v2.py over depth-14 runs only
   * (RUNS-DEPTH); a part with no data is not drawn.
   */
  import { api, type InsightsRated, type InsightsSpeedV2, type InsightsV2 } from '../api'
  import EmptyState from '../ui/EmptyState.svelte'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import { QUALITY } from '../ui/moveQuality'
  import PatternsPanel from './PatternsPanel.svelte'
  import ChartReadout from '../ui/ChartReadout.svelte'
  import { dayText, monthText } from '../ui/readoutModel'
  import {
    PHASE_NAME, QUALITY_ORDER, TIMEFRAMES, changeOver, chartPoints, fmtInt, fmtPct, heatOpacity, series,
    sinceFor, sparkCoords, sparkPoints, statValueText, type MonthKey, type Timeframe,
  } from './insightsModel'

  interface Props {
    onconnect: () => void
    onopen?: (gameId: number, ply: number) => void
  }
  let { onconnect, onopen }: Props = $props()

  // ── filters ─────────────────────────────────────────────────────────────
  const SPEEDS: { value: InsightsSpeedV2; label: string }[] = [
    { value: 'bullet', label: 'Bullet' },
    { value: 'blitz', label: 'Blitz' },
    { value: 'rapid', label: 'Rapid' },
    { value: 'classical', label: 'Classical' },
    { value: 'daily', label: 'Daily' },
  ]
  let timeframe = $state<Timeframe>('all')
  let speeds = $state<InsightsSpeedV2[]>([])
  let color = $state<'all' | 'white' | 'black'>('all')
  let rated = $state<InsightsRated>('all')
  let includeLocal = $state(false)
  const filtered = $derived(timeframe !== 'all' || speeds.length > 0 || color !== 'all' || rated !== 'all' || includeLocal)
  function reset() {
    timeframe = 'all'
    speeds = []
    color = 'all'
    rated = 'all'
    includeLocal = false
  }
  function toggleSpeed(s: InsightsSpeedV2) {
    speeds = speeds.includes(s) ? speeds.filter((x) => x !== s) : [...speeds, s]
  }

  // ── data ────────────────────────────────────────────────────────────────
  let data = $state<InsightsV2 | null>(null)
  let error = $state<string | null>(null)
  let loading = $state(true)
  let everHad = $state(false)
  let token = 0
  async function load() {
    const my = ++token
    loading = true
    error = null
    try {
      const r = await api.insightsV2({ color, speeds, since: sinceFor(timeframe), rated, includeLocal })
      if (my !== token || 'superseded' in r) return
      data = r
      if (r.overview.total > 0) everHad = true
    } catch (e) {
      if (my === token) error = e instanceof Error ? e.message : String(e)
    } finally {
      if (my === token) loading = false
    }
  }
  $effect(() => {
    void [timeframe, speeds, color, rated, includeLocal]
    void load()
  })

  let pendingStarted = $state(false)
  async function analyseNow() {
    pendingStarted = true
    try {
      await api.analyzePending()
    } catch {
      pendingStarted = false
    }
  }

  // ── derived ─────────────────────────────────────────────────────────────
  type StatDef = { label: string; key: MonthKey; value: string; unit?: string; sub: string | null; tone: 'win' | 'loss' | null }
  const stats = $derived.by<StatDef[]>(() => {
    if (!data) return []
    const s = data.summary
    const acc = changeOver(series(data.monthly, 'accuracy'))
    const bl = changeOver(series(data.monthly, 'blundersPerGame'), 2)
    return [
      { label: 'Accuracy', key: 'accuracy', value: s.accuracy === null ? '–' : s.accuracy.toFixed(1), sub: acc?.text ?? null,
        tone: acc ? (acc.delta > 0 ? 'win' : acc.delta < 0 ? 'loss' : null) : null },
      { label: 'Win rate', key: 'winRate', value: s.winRate === null ? '–' : s.winRate.toFixed(1), unit: s.winRate === null ? '' : '%',
        sub: includeLocal ? 'Including Stockfish games' : 'Not counting Stockfish', tone: null },
      { label: 'Games', key: 'games', value: fmtInt(s.games), sub: `${fmtInt(s.analysed)} analysed`, tone: null },
      { label: 'Blunders per game', key: 'blundersPerGame', value: s.blundersPerGame === null ? '–' : s.blundersPerGame.toFixed(2),
        sub: bl?.text ?? null, tone: bl ? (bl.delta < 0 ? 'win' : bl.delta > 0 ? 'loss' : null) : null },
    ]
  })

  const points = $derived(data ? chartPoints(data, timeframe) : [])
  const byDay = $derived(timeframe === '7d' || timeframe === '30d')
  const CH = { w: 470, h: 190, top: 14, plot: 118, barTop: 142, barH: 28, left: 20, right: 40 }
  const chart = $derived.by(() => {
    const accs = points.map((p) => p.accuracy).filter((a): a is number => a !== null)
    if (accs.length === 0) return null
    let lo = Math.floor(Math.min(...accs) / 5) * 5
    let hi = Math.ceil(Math.max(...accs) / 5) * 5
    if (hi === lo) hi = lo + 5
    const n = points.length
    const x = (i: number) => CH.left + (n === 1 ? (CH.w - CH.left - CH.right) / 2 : (i / (n - 1)) * (CH.w - CH.left - CH.right))
    const y = (a: number) => CH.top + (1 - (a - lo) / (hi - lo)) * CH.plot
    const maxG = Math.max(1, ...points.map((p) => p.games))
    const line = points
      .map((p, i) => (p.accuracy === null ? null : `${x(i).toFixed(1)},${y(p.accuracy).toFixed(1)}`))
      .filter(Boolean)
      .join(' ')
    const ticks = [] as number[]
    for (let t = lo; t <= hi; t += 5) ticks.push(t)
    const bw = Math.max(2, Math.min(18, ((CH.w - CH.left - CH.right) / Math.max(1, n)) * 0.6))
    const last = [...points.keys()].reverse().find((i) => points[i].accuracy !== null) ?? null
    const every = Math.max(1, Math.ceil(n / 6))
    return { x, y, line, ticks, maxG, bw, last, every }
  })

  // The accuracy chart's readout (ruling 12 of 2026-11-20, fourth): the months (days) with a figure.
  const accIdx = $derived(points.flatMap((p, i) => (p.accuracy === null ? [] : [i])))
  let accShown = $state<number | null>(null)

  let phaseMode = $state<'accuracy' | 'quality'>('accuracy')
  let openingSide = $state<'white' | 'black'>('white')
  $effect(() => {
    if (color === 'white' || color === 'black') openingSide = color
  })
  const openings = $derived(data ? data.openings[openingSide] : [])
  let showAllOpenings = $state(false)
  const OPENINGS_SHOWN = 6

  const heatRange = $derived.by(() => {
    const vs = (data?.heat.cells ?? []).map((c) => c.accuracy).filter((a): a is number => a !== null)
    return vs.length ? [Math.min(...vs), Math.max(...vs)] : [0, 0]
  })
  const qualityName = (c: string) => QUALITY[c as keyof typeof QUALITY]?.name ?? c
</script>

<div class="insights">
  <header>
    <h1>Insights</h1>
    {#if data}<span class="count">{fmtInt(data.overview.analyzed)} analysed games</span>{/if}
  </header>

  <div class="filters" role="toolbar" aria-label="Filters">
    <div class="seg" role="group" aria-label="Time frame">
      {#each TIMEFRAMES as t (t.value)}
        <button type="button" aria-pressed={timeframe === t.value} onclick={() => (timeframe = t.value)}>{t.label}</button>
      {/each}
    </div>
    <span class="vr" aria-hidden="true"></span>
    <div class="chips" role="group" aria-label="Time controls">
      {#each SPEEDS as s (s.value)}
        <button type="button" class="chip" aria-pressed={speeds.includes(s.value)} onclick={() => toggleSpeed(s.value)}>{s.label}</button>
      {/each}
    </div>
    <span class="vr" aria-hidden="true"></span>
    <div class="seg" role="group" aria-label="Colour">
      {#each [['all', 'Both'], ['white', 'White'], ['black', 'Black']] as [v, l] (v)}
        <button type="button" aria-pressed={color === v} onclick={() => (color = v as typeof color)}>{l}</button>
      {/each}
    </div>
    <div class="seg" role="group" aria-label="Rated or casual">
      {#each [['all', 'All'], ['rated', 'Rated'], ['casual', 'Casual']] as [v, l] (v)}
        <button type="button" aria-pressed={rated === v} onclick={() => (rated = v as InsightsRated)}>{l}</button>
      {/each}
    </div>
    <label class="toggle">
      <input type="checkbox" role="switch" bind:checked={includeLocal} />
      <span class="sw" aria-hidden="true"><span></span></span>
      Games vs Stockfish
    </label>
    <button type="button" class="reset" disabled={!filtered} onclick={reset}>Reset</button>
  </div>

  <main>
    {#if error}
      <EmptyState tone="error" sentence="Insights could not be built." sub={error} action={{ label: 'Try again', run: load }} />
    {:else if !data}
      <EmptyState sentence="Reading your games…" />
    {:else if data.overview.total === 0 && !everHad && !filtered}
      <EmptyState
        sentence="No games yet."
        sub="Connect a Chess.com or Lichess account to sync your games, or play one against Stockfish."
        action={{ label: 'Connect an account', run: onconnect, primary: true }}
      />
    {:else if data.overview.total === 0}
      <EmptyState sentence="No games match these filters." action={{ label: 'Reset filters', run: reset }} />
    {:else if data.overview.analyzed === 0}
      <EmptyState
        sentence="Insights appear once your games are analysed."
        sub="{fmtInt(data.overview.pending)} {data.overview.pending === 1 ? 'game is' : 'games are'} waiting for analysis at depth 14."
        action={{ label: pendingStarted ? 'Started' : 'Analyse now', run: analyseNow, primary: true }}
      />
    {:else}
      <div class="body" class:stale={loading}>
        <dl class="strip">
          {#each stats as s (s.label)}
            {@const ser = series(data.monthly, s.key)}
            {@const pts = sparkPoints(ser)}
            <div class="stat">
              <div>
                <dt>{s.label}</dt>
                <dd class="metric">{s.value}{#if s.unit}<span class="unit">{s.unit}</span>{/if}</dd>
                {#if s.sub}<dd class="sub" class:win={s.tone === 'win'} class:loss={s.tone === 'loss'}>{s.sub}</dd>{/if}
              </div>
              {#if pts}
                {@const last = pts.split(' ').pop()!.split(',')}
                {@const xy = sparkCoords(ser)}
                <ChartReadout
                  points={xy.map(([x, y]) => ({ x, y }))}
                  vw={84}
                  vh={28}
                  placement="above"
                  label={(i) => ({ title: monthText(data!.monthly[ser[i][0]].month), value: statValueText(s.key, ser[i][1]) })}
                  keyboard={{ label: `${s.label}, 12 months` }}
                >
                  <!-- overflow visible: the end dot sits on the right edge and was cut in half (BETA-4 C) -->
                  <svg width="84" height="28" viewBox="0 0 84 28" aria-hidden="true" style="overflow: visible"
                    ><polyline points={pts} fill="none" stroke="var(--chart-opponent)" stroke-width="1.5" stroke-linejoin="round" /><circle
                      cx={last[0]} cy={last[1]} r="2.5" fill="var(--text)" /></svg
                  >
                </ChartReadout>
              {/if}
            </div>
          {/each}
        </dl>

        <div class="two">
          <section class="panel" aria-labelledby="acc-h">
            <div class="ph"><h2 id="acc-h">Accuracy over time</h2><span>{byDay ? 'By day' : 'By month'}, games below</span></div>
            {#if chart}
              <figure class="chart">
                <ChartReadout
                  points={accIdx.map((i) => ({ x: chart.x(i), y: chart.y(points[i].accuracy!) }))}
                  vw={CH.w}
                  vh={CH.h}
                  label={(j) => {
                    const p = points[accIdx[j]]
                    return {
                      title: byDay ? dayText(p.date) : monthText(p.date),
                      value: p.accuracy!.toFixed(1),
                      note: `${fmtInt(p.games)} ${p.games === 1 ? 'game' : 'games'}`,
                    }
                  }}
                  labelTop={CH.top}
                  guideTop={CH.top}
                  guideBottom={CH.barTop + CH.barH}
                  keyboard={{ label: `Accuracy ${byDay ? 'by day' : 'by month'}` }}
                  bind:shown={accShown}
                >
                <svg viewBox="0 0 {CH.w} {CH.h}" width="100%" aria-hidden="true">
                  {#each chart.ticks as t (t)}
                    <line x1={CH.left - 6} x2={CH.w - CH.right + 6} y1={chart.y(t)} y2={chart.y(t)} stroke="var(--divider)" />
                    <text x={CH.w - 8} y={chart.y(t) + 3} class="tick" text-anchor="end">{t}</text>
                  {/each}
                  {#each points as p, i (i)}
                    {#if p.games > 0}
                      {@const h = (p.games / chart.maxG) * CH.barH}
                      <rect x={chart.x(i) - chart.bw / 2} y={CH.barTop + CH.barH - h} width={chart.bw} height={h} rx="1" fill="var(--raised)" />
                    {/if}
                    {#if i % chart.every === 0 || i === points.length - 1}
                      <text x={chart.x(i)} y={CH.h - 2} class="tick" text-anchor="middle">{p.label}</text>
                    {/if}
                  {/each}
                  <polyline points={chart.line} fill="none" stroke="var(--chart-line)" stroke-width="1.5" stroke-linejoin="round" />
                  {#each points as p, i (i)}
                    {#if p.accuracy !== null}
                      <circle cx={chart.x(i)} cy={chart.y(p.accuracy)} r="2.5" fill="var(--text)" />
                    {/if}
                  {/each}
                  {#if chart.last !== null && accShown === null}
                    {@const lp = points[chart.last]}
                    <g transform="translate({Math.min(chart.x(chart.last) - 22, CH.w - CH.right - 40)},{chart.y(lp.accuracy!) - 27})">
                      <rect width="40" height="18" rx="4" fill="var(--raised)" stroke="var(--border-control)" />
                      <text x="20" y="13" text-anchor="middle" class="tip">{lp.accuracy!.toFixed(1)}</text>
                    </g>
                  {/if}
                </svg>
                </ChartReadout>
              </figure>
            {:else}
              <p class="quiet">No analysed games in this range.</p>
            {/if}
          </section>

          <section class="panel" aria-labelledby="pat-h">
            <div class="ph"><h2 id="pat-h">Patterns</h2><span>Shown only when the gap holds on these filters</span></div>
            <PatternsPanel patterns={data.patterns} {onopen} />
          </section>
        </div>

        <div class="two">
          <section class="panel" aria-labelledby="mq-h">
            <div class="ph"><h2 id="mq-h">Move quality</h2><span>Share of moves</span></div>
            <div class="mq">
              {#each [['you', 'You'], ['opponents', 'Opponents']] as [who, label] (who)}
                {@const sh = data.moveQuality[who as 'you']}
                <span class="bl">{label}</span>
                <span class="split" aria-hidden="true">
                  {#each QUALITY_ORDER as c (c)}
                    {#if (sh.pct[c] ?? 0) > 0}<span style:width="{sh.pct[c]}%" style:background="var(--q-{c})"></span>{/if}
                  {/each}
                </span>
              {/each}
            </div>
            <table class="qt">
              <thead><tr><th><span class="sr">Move</span></th><th>You</th><th>Opponents</th></tr></thead>
              <tbody>
                {#each QUALITY_ORDER as c (c)}
                  <tr>
                    <th scope="row"><MoveQualityIcon cls={c} size={18} decorative />{qualityName(c)}</th>
                    <td class="you">{fmtPct(data.moveQuality.you.pct[c])}</td>
                    <td>{fmtPct(data.moveQuality.opponents.pct[c])}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </section>

          <section class="panel phase" aria-labelledby="ph-h">
            <div class="ph">
              <h2 id="ph-h">By phase</h2>
              <div class="seg" role="group" aria-label="By phase shows">
                <button type="button" aria-pressed={phaseMode === 'accuracy'} onclick={() => (phaseMode = 'accuracy')}>Accuracy</button>
                <button type="button" aria-pressed={phaseMode === 'quality'} onclick={() => (phaseMode = 'quality')}>Move quality</button>
              </div>
            </div>
            <div class="legend">
              <span><i class="you"></i>You</span><span><i class="them"></i>Opponents</span>
              {#if phaseMode === 'quality'}<span>Right: blunders</span>{/if}
            </div>
            {#each data.byPhase.phases as p (p.phase)}
              {#if p.games > 0}
                <div class="prow">
                  <span class="pn">{PHASE_NAME[p.phase]}</span>
                  <div class="pbars">
                    {#each [['you', 'you'], ['opponents', 'them']] as [who, cls] (who)}
                      {#if phaseMode === 'accuracy'}
                        {@const a = p.accuracy[who as 'you']}
                        <span class="track" aria-hidden="true"><span class="fill {cls}" style:width="{a ?? 0}%"></span></span>
                        <span class="pv" class:dim={who !== 'you'}>{a === null ? '–' : a.toFixed(1)}</span>
                      {:else}
                        {@const sh = p.quality[who as 'you']}
                        <span class="split thin" class:dimmed={who !== 'you'} aria-hidden="true">
                          {#each QUALITY_ORDER as c (c)}
                            {#if (sh.pct[c] ?? 0) > 0}<span style:width="{sh.pct[c]}%" style:background="var(--q-{c})"></span>{/if}
                          {/each}
                        </span>
                        <span class="pv" class:dim={who !== 'you'} class:bad={who === 'you'}>{fmtPct(sh.pct.blunder)}</span>
                      {/if}
                    {/each}
                  </div>
                </div>
              {/if}
            {/each}
            <p class="note">Each game is split as on Lichess: by the pieces left and how far the armies have mixed, not by move number.</p>
          </section>
        </div>

        {#if data.openings.white.length || data.openings.black.length}
          <section class="panel" aria-labelledby="op-h">
            <div class="ph">
              <h2 id="op-h">Openings</h2>
              <div class="seg" role="group" aria-label="Openings as">
                <button type="button" aria-pressed={openingSide === 'white'} disabled={color === 'black'} onclick={() => (openingSide = 'white')}>As White</button>
                <button type="button" aria-pressed={openingSide === 'black'} disabled={color === 'white'} onclick={() => (openingSide = 'black')}>As Black</button>
              </div>
            </div>
            {#if openings.length}
              <div class="orow head"><span>Opening</span><span class="r">Games</span><span>Won, drawn, lost</span><span class="r">Score</span><span class="r">Accuracy</span></div>
              {#each showAllOpenings ? openings : openings.slice(0, OPENINGS_SHOWN) as o (o.name)}
                <div class="orow">
                  <span class="on">{o.name}{#if o.eco}<span class="eco">{o.eco}</span>{/if}</span>
                  <span class="r">{fmtInt(o.games)}</span>
                  <span class="wdl">
                    <span class="bar" aria-hidden="true"
                      ><span style:width="{o.won}%" class="w"></span><span style:width="{o.drawn}%" class="d"></span><span style:width="{o.lost}%" class="l"></span></span
                    >
                    <span class="t">{Math.round(o.won ?? 0)} / {Math.round(o.drawn ?? 0)} / {Math.round(o.lost ?? 0)}</span>
                  </span>
                  <span class="r strong">{fmtPct(o.score)}</span>
                  <span class="r dim">{o.accuracy === null ? '–' : o.accuracy.toFixed(1)}</span>
                </div>
              {/each}
              {#if openings.length > OPENINGS_SHOWN}
                <button type="button" class="more" onclick={() => (showAllOpenings = !showAllOpenings)}
                  >{showAllOpenings ? 'Show fewer' : `Show all ${openings.length}`}</button
                >
              {/if}
            {:else}
              <p class="quiet">No opening with enough games as {openingSide === 'white' ? 'White' : 'Black'} under these filters.</p>
            {/if}
          </section>
        {/if}

        <div class="three">
          <section class="panel" aria-labelledby="end-h">
            <div class="ph"><h2 id="end-h">How your games end</h2>{#if data.ends.draw.pct !== null}<span>Draws {fmtPct(data.ends.draw.pct)}</span>{/if}</div>
            <div class="ends">
              {#each [['win', 'Won'], ['loss', 'Lost']] as [k, label] (k)}
                {@const e = data.ends[k as 'win']}
                {#if e.games > 0}
                  <div>
                    <div class="eh"><span class="strong">{label}</span><span class="dim">{fmtPct(e.pct)}</span></div>
                    <div class="ebar" aria-hidden="true">
                      <span style:width="{e.mate}%" class="m"></span><span style:width="{e.resigned}%" class="rs"></span><span style:width="{e.time}%" class="tm"></span>{#if e.other}<span style:width="{e.other}%" class="ot"></span>{/if}
                    </div>
                    <div class="el">
                      <span>Mate {Math.round(e.mate ?? 0)}%</span><span>Resigned {Math.round(e.resigned ?? 0)}%</span><span>Time {Math.round(e.time ?? 0)}%</span>{#if e.other}<span>Other {Math.round(e.other)}%</span>{/if}
                    </div>
                  </div>
                {/if}
              {/each}
            </div>
          </section>

          <section class="panel" aria-labelledby="when-h">
            <div class="ph"><h2 id="when-h">When you play best</h2><span>Accuracy</span></div>
            <div class="heat">
              <div class="hrow hh" aria-hidden="true"><span></span>{#each data.heat.hours as h (h)}<span>{h}</span>{/each}</div>
              {#each data.heat.days as d, di (d)}
                <div class="hrow">
                  <span class="hd">{d}</span>
                  {#each data.heat.hours as h, bi (h)}
                    {@const c = data.heat.cells.find((x) => x.day === di && x.block === bi)}
                    {@const best = data.heat.best && data.heat.best.day === di && data.heat.best.block === bi}
                    <span
                      class="cell"
                      class:best
                      title="{d} {h}: {c && c.accuracy !== null ? c.accuracy.toFixed(1) + ', ' + fmtInt(c.games) + ' games' : c && c.games ? fmtInt(c.games) + ' games, too few' : 'no games'}"
                      style:background={c && c.accuracy !== null ? `rgba(237,237,239,${heatOpacity(c.accuracy, heatRange[0], heatRange[1]).toFixed(2)})` : 'var(--surface)'}
                    ></span>
                  {/each}
                </div>
              {/each}
              {#if data.heat.best}
                <p class="best">Best: <span class="strong">{data.heat.best.dayName} {data.heat.best.hours}</span>, {data.heat.best.accuracy.toFixed(1)}</p>
              {:else}
                <p class="best">No block has {data.heat.minGames} analysed games yet.</p>
              {/if}
            </div>
          </section>

          <section class="panel" aria-labelledby="cas-h">
            <div class="ph"><h2 id="cas-h">Castling</h2><span>Win rate</span></div>
            <table class="cas">
              <thead><tr><th><span class="sr">Castling</span></th><th>Games</th><th>Won</th></tr></thead>
              <tbody>
                {#each data.castling as c (c.side)}
                  {#if c.games > 0}
                    <tr>
                      <th scope="row">{c.side === 'kingside' ? 'Kingside' : c.side === 'queenside' ? 'Queenside' : "Didn't castle"}</th>
                      <td>{c.share === null ? '–' : Math.round(c.share) + '%'}</td>
                      <td class="strong">{c.winRate === null ? '–' : Math.round(c.winRate) + '%'}</td>
                    </tr>
                  {/if}
                {/each}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    {/if}
  </main>
</div>

<style>
  .insights {
    display: flex;
    flex-direction: column;
    min-height: 100%;
    font: var(--body);
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
    flex: none;
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .count {
    color: var(--text-3);
    font: var(--secondary);
  }
  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
    padding: 10px 28px;
    border-bottom: 1px solid var(--border);
  }
  .vr {
    width: 1px;
    height: 18px;
    background: var(--border);
  }
  .seg {
    display: flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .seg button {
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 3px 9px;
    font: var(--secondary);
    color: var(--text-3);
    cursor: pointer;
  }
  .seg button[aria-pressed='true'] {
    background: var(--border);
    color: var(--text);
  }
  .seg button:disabled {
    color: var(--disabled);
    cursor: default;
  }
  .chips {
    display: flex;
    gap: 4px;
  }
  .chip {
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 3px 9px;
    font: var(--secondary);
    color: var(--text-2);
    cursor: pointer;
  }
  .chip[aria-pressed='true'] {
    background: var(--border);
    border-color: var(--border-strong);
    color: var(--text);
  }
  button:focus-visible,
  .toggle input:focus-visible + .sw {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .toggle {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font: var(--secondary);
    color: var(--text-2);
    cursor: pointer;
  }
  .toggle input {
    position: absolute;
    opacity: 0;
    width: 1px;
    height: 1px;
  }
  .sw {
    position: relative;
    width: 24px;
    height: 14px;
    border-radius: 7px;
    background: var(--border-control);
  }
  .sw span {
    position: absolute;
    left: 2px;
    top: 2px;
    width: 10px;
    height: 10px;
    border-radius: 5px;
    background: var(--text-3);
    transition: left 0.12s;
  }
  .toggle input:checked + .sw {
    background: var(--text-2);
  }
  .toggle input:checked + .sw span {
    left: 12px;
    background: var(--bg);
  }
  .reset {
    margin-left: auto;
    background: transparent;
    border: 0;
    color: var(--text-3);
    font: var(--secondary);
    padding: 3px 6px;
    cursor: pointer;
  }
  .reset:disabled {
    color: var(--disabled);
    cursor: default;
  }
  main {
    padding: 24px 28px 32px;
    max-width: 1140px;
    width: 100%;
    box-sizing: border-box;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: 24px;
    transition: opacity 0.15s;
  }
  .body.stale {
    opacity: 0.6;
  }
  .strip {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .stat {
    padding: 14px 18px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 84px;
    align-items: end;
    gap: 8px;
  }
  .stat + .stat {
    border-left: 1px solid var(--border);
  }
  dt {
    color: var(--text-3);
    font: var(--secondary);
  }
  dd {
    margin: 0;
  }
  .metric {
    margin-top: 6px;
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
  }
  .unit {
    font-size: 15px;
    color: var(--text-2);
  }
  .sub {
    margin-top: 2px;
    font: var(--secondary);
    color: var(--text-2);
  }
  .sub.win {
    color: var(--win);
  }
  .sub.loss {
    color: var(--loss);
  }
  .two {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px;
    align-items: start;
  }
  .three {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 24px;
    align-items: stretch;
  }
  /* One column below 1248 px wide (DESIGN.md fifth rulings, 2; UI-BUILD-4 C), as Home: where the
     1140 px column would narrow. The smallest window (1280) never reaches it; a browser can. The
     four figures go two by two. */
  @media (max-width: 1247.98px) {
    .two,
    .three {
      grid-template-columns: minmax(0, 1fr);
    }
    .strip {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .stat:nth-child(3) {
      border-left: 0;
    }
    .stat:nth-child(n + 3) {
      border-top: 1px solid var(--border);
    }
  }
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    min-width: 0;
  }
  .ph {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 16px;
    min-height: 44px;
    box-sizing: border-box;
    border-bottom: 1px solid var(--border);
  }
  .ph h2 {
    margin: 0;
    font: var(--body-strong);
  }
  .ph > span {
    color: var(--text-3);
    font: var(--secondary);
  }
  .quiet {
    margin: 0;
    padding: 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .chart {
    margin: 0;
    padding: 16px 16px 12px;
  }
  .chart :global(.tick) {
    font: 400 10px var(--sans);
    fill: var(--text-3);
  }
  .chart :global(.tip) {
    font: 500 11px var(--sans);
    fill: var(--text);
  }
  .mq {
    display: grid;
    grid-template-columns: 88px minmax(0, 1fr);
    gap: 10px 12px;
    align-items: center;
    padding: 14px 16px 6px;
  }
  .bl {
    color: var(--text);
    font: var(--secondary);
  }
  .split {
    display: flex;
    gap: 1px;
    height: 8px;
    border-radius: 3px;
    overflow: hidden;
  }
  .split.thin {
    height: 6px;
  }
  .split.dimmed {
    opacity: 0.55;
  }
  .split > span {
    display: block;
    height: 100%;
  }
  table {
    /* the positioned box of the headers' .sr labels (and .toggle the switch's input): with none,
       an absolute .sr sits at its place in the page's own scroll area and makes the document
       taller than the window, so WebKit draws a page scrollbar that narrows the window by 8 px
       and turns the sidebar into the rail at 1440 wide (UI-BUILD-4 E) */
    position: relative;
    width: 100%;
    border-collapse: collapse;
  }
  .qt {
    margin: 4px 0 8px;
  }
  .qt th,
  .qt td,
  .cas th,
  .cas td {
    padding: 5px 16px;
    text-align: right;
    font-weight: 400;
  }
  .qt thead th,
  .cas thead th {
    color: var(--text-3);
    font: var(--secondary);
    padding-top: 10px;
  }
  .qt tbody th,
  .cas tbody th {
    text-align: left;
  }
  .qt tbody th {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .qt td {
    color: var(--text-2);
    width: 90px;
  }
  .qt td.you {
    color: var(--text);
    font-weight: 500;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .legend {
    display: flex;
    justify-content: flex-end;
    gap: 14px;
    padding: 12px 16px 0;
    font: var(--secondary);
    color: var(--text-2);
  }
  .legend i {
    display: inline-block;
    width: 8px;
    height: 3px;
    border-radius: 2px;
    margin-right: 6px;
    vertical-align: middle;
  }
  .legend i.you {
    background: var(--chart-you);
  }
  .legend i.them {
    background: var(--chart-opponent);
  }
  .prow {
    display: grid;
    grid-template-columns: 108px minmax(0, 1fr);
    align-items: center;
    padding: 16px;
    border-bottom: 1px solid var(--divider);
  }
  .pn {
    font: var(--body-strong);
  }
  .pbars {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 56px;
    gap: 10px 12px;
    align-items: center;
  }
  .track {
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    border-radius: 3px;
  }
  .fill.you {
    background: var(--chart-you);
  }
  .fill.them {
    background: var(--chart-opponent);
  }
  .pv {
    text-align: right;
    font-weight: 500;
  }
  .pv.dim {
    color: var(--text-2);
    font-weight: 400;
  }
  .pv.bad {
    color: var(--loss);
  }
  .note {
    margin: 0;
    padding: 14px 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .orow {
    display: grid;
    grid-template-columns: minmax(0, 2.2fr) 64px minmax(0, 1.6fr) 64px 72px;
    gap: 16px;
    align-items: center;
    padding: 9px 16px;
    border-top: 1px solid var(--divider);
  }
  .orow.head {
    border-top: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .orow .r {
    text-align: right;
  }
  .on {
    font: var(--body-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .eco {
    color: var(--text-3);
    font-weight: 400;
    margin-left: 0.35em;
  }
  .wdl {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 72px;
    gap: 10px;
    align-items: center;
  }
  .wdl .bar {
    display: flex;
    gap: 1px;
    height: 6px;
    border-radius: 3px;
    overflow: hidden;
  }
  .wdl .bar span {
    display: block;
  }
  .bar .w {
    background: var(--win);
  }
  .bar .d {
    background: var(--draw);
  }
  .bar .l {
    background: var(--loss);
  }
  .wdl .t {
    color: var(--text-2);
    font: var(--secondary);
  }
  .strong {
    font-weight: 500;
  }
  .dim {
    color: var(--text-2);
  }
  .more {
    display: block;
    width: 100%;
    padding: 10px 16px;
    border: 0;
    border-top: 1px solid var(--divider);
    background: transparent;
    color: var(--text-2);
    font: var(--secondary);
    text-align: left;
    cursor: pointer;
  }
  .more:hover {
    color: var(--text);
  }
  .ends {
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .eh {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .ebar {
    display: flex;
    height: 8px;
    border-radius: 3px;
    overflow: hidden;
    gap: 1px;
  }
  .ebar span {
    display: block;
  }
  .ebar .m {
    background: var(--text);
  }
  .ebar .rs {
    background: #8e8e96;
  }
  .ebar .tm {
    background: var(--disabled);
  }
  .ebar .ot {
    background: var(--raised);
  }
  .el {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    font: var(--secondary);
    color: var(--text-2);
  }
  .heat {
    padding: 12px 16px 14px;
  }
  .hrow {
    display: grid;
    grid-template-columns: 32px repeat(6, minmax(0, 1fr));
    gap: 3px;
    margin-bottom: 3px;
    align-items: center;
  }
  .hrow.hh {
    font-size: 10px;
    color: var(--text-3);
    text-align: center;
  }
  .hd {
    font-size: 11px;
    color: var(--text-3);
  }
  .cell {
    height: 18px;
    border-radius: 3px;
  }
  .cell.best {
    box-shadow: 0 0 0 1.5px var(--text);
  }
  .best {
    margin: 8px 0 0;
    font: var(--secondary);
    color: var(--text-2);
  }
  .best .strong {
    color: var(--text);
  }
  .cas td {
    color: var(--text-2);
  }
  .cas td.strong {
    color: var(--text);
  }
  .cas tbody tr {
    border-top: 1px solid var(--divider);
  }
  .cas tbody th,
  .cas tbody td {
    padding: 9px 16px;
  }
</style>
