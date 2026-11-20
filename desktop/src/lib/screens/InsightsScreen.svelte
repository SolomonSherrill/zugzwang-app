<script lang="ts">
  import type { ChartConfiguration } from 'chart.js'
  import { api } from '../api'
  import type {
    InsightsResult,
    InsightsOpening,
    InsightsSpeed,
    InsightsRated,
    InsightsPhaseVerdict,
  } from '../api'
  import { theme } from '../theme.svelte'
  import { CLASS_COLORS, CLASS_LABELS } from '../classification'
  import ChartCanvas from './insights/ChartCanvas.svelte'
  import PatternsCard from './insights/PatternsCard.svelte'
  import { coverageText, emptyText } from '../patterns'

  let {
    ontrain,
    onconnect,
    onopen,
  }: {
    ontrain?: (opening: { eco: string; name: string }) => void
    onconnect: () => void
    /** R6: open a game in Review at a ply (the patterns card's links). */
    onopen?: (gameId: number, ply: number) => void
  } = $props()

  let data = $state<InsightsResult | null>(null)
  let loading = $state(true)
  let refreshing = $state(false)
  let error = $state<string | null>(null)
  // Sticky once the account is known to have games; lets the filter controls
  // stay visible even when a filter narrows the result down to zero.
  let everHadGames = $state(false)

  type ColorFilter = 'all' | 'white' | 'black'
  let colorFilter = $state<ColorFilter>('all')

  // Time-control multiselect — empty means "all speeds".
  const SPEED_OPTS: { k: InsightsSpeed; l: string }[] = [
    { k: 'bullet', l: 'Bullet' },
    { k: 'blitz', l: 'Blitz' },
    { k: 'rapid', l: 'Rapid' },
    { k: 'classical', l: 'Classical' },
  ]
  let selectedSpeeds = $state<InsightsSpeed[]>([])
  function toggleSpeed(s: InsightsSpeed) {
    selectedSpeeds = selectedSpeeds.includes(s)
      ? selectedSpeeds.filter((x) => x !== s)
      : [...selectedSpeeds, s]
  }

  // Rated vs. casual — 'all' includes both.
  const RATED_OPTS: { k: InsightsRated; l: string }[] = [
    { k: 'all', l: 'All' },
    { k: 'rated', l: 'Rated' },
    { k: 'casual', l: 'Casual' },
  ]
  let ratedFilter = $state<InsightsRated>('all')
  // Games played here against Stockfish. Off by default: the player picks the
  // opponent's strength, so those games say more about the level chosen than
  // about how the player is doing.
  let includeLocal = $state(false)
  // Global timeframe — a start-date lower bound applied server-side to every panel.
  type Timeframe = '7d' | '30d' | '1y' | 'all'
  const TIMEFRAMES: { k: Timeframe; l: string }[] = [
    { k: '7d', l: '7D' },
    { k: '30d', l: '30D' },
    { k: '1y', l: '1Y' },
    { k: 'all', l: 'All' },
  ]
  let timeframe = $state<Timeframe>('all')
  function sinceFor(tf: Timeframe): string | undefined {
    const days = tf === '7d' ? 7 : tf === '30d' ? 30 : tf === '1y' ? 365 : null
    return days == null ? undefined : new Date(Date.now() - days * 86_400_000).toISOString()
  }

  function clearFilters() {
    colorFilter = 'all'
    selectedSpeeds = []
    timeframe = 'all'
    ratedFilter = 'all'
    includeLocal = false
  }

  // ── theming helpers ─────────────────────────────────────────────────────────
  function cssVar(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  }
  function palette() {
    return {
      accent: cssVar('--accent') || '#d4a84b',
      text: cssVar('--text') || '#ece4d2',
      muted: cssVar('--text-muted') || '#8a8073',
      divider: cssVar('--divider') || '#2c2620',
      surface: cssVar('--bg-tile') || '#211c17',
      win: cssVar('--win') || '#6bbf5e',
      danger: cssVar('--danger') || '#d64f40',
    }
  }

  function fmtDate(iso: string): string {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })
  }

  /** Accuracy → performance tier colour (bold, expressive). */
  function perfColor(acc: number): string {
    if (acc >= 80) return 'var(--win)'
    if (acc >= 68) return 'var(--accent)'
    if (acc >= 55) return '#d47b2a'
    return 'var(--danger)'
  }

  const RESULT_GLYPH: Record<string, string> = { win: 'W', draw: 'D', loss: 'L', unknown: '·' }

  // ── floating tooltip for the CSS-drawn bars / heatmap ───────────────────────
  let tip = $state<{ x: number; y: number; html: string } | null>(null)
  function showTip(e: MouseEvent, html: string) {
    tip = { x: e.clientX, y: e.clientY, html }
  }
  function moveTip(e: MouseEvent) {
    if (tip) tip = { ...tip, x: e.clientX, y: e.clientY }
  }
  function hideTip() {
    tip = null
  }

  // ── openings grouped into families ──────────────────────────────────────────
  // Lines arrive ungated; we group by the family name (the part before the first
  // colon), gate at the family level (>= INSIGHTS_MIN_OPENING_GAMES total games),
  // and surface every variant inside a qualifying family — even sub-threshold ones.
  const FAMILY_MIN_GAMES = 5

  type OpeningVariant = InsightsOpening & { variantName: string }
  type OpeningFamily = {
    family: string
    eco: string
    games: number
    accuracy: number
    win: number
    draw: number
    loss: number
    winRate: number
    variants: OpeningVariant[]
  }

  function familyOf(name: string): string {
    const i = name.indexOf(':')
    return (i === -1 ? name : name.slice(0, i)).trim()
  }
  function variantOf(name: string): string {
    const i = name.indexOf(':')
    return i === -1 ? name : name.slice(i + 1).trim()
  }

  let families = $derived.by<OpeningFamily[]>(() => {
    if (!data) return []
    const groups = new Map<string, InsightsOpening[]>()
    for (const op of data.openings) {
      const fam = familyOf(op.name)
      const arr = groups.get(fam)
      if (arr) arr.push(op)
      else groups.set(fam, [op])
    }
    const out: OpeningFamily[] = []
    for (const [family, lines] of groups) {
      const games = lines.reduce((s, l) => s + l.games, 0)
      if (games < FAMILY_MIN_GAMES) continue
      const win = lines.reduce((s, l) => s + l.win, 0)
      const draw = lines.reduce((s, l) => s + l.draw, 0)
      const loss = lines.reduce((s, l) => s + l.loss, 0)
      const accW = lines.reduce((s, l) => s + l.accuracy * l.games, 0) / games
      const variants: OpeningVariant[] = lines
        .map((l) => ({ ...l, variantName: variantOf(l.name) }))
        .sort((a, b) => b.games - a.games)
      out.push({
        family,
        eco: variants[0].eco,
        games,
        accuracy: Math.round(accW * 10) / 10,
        win,
        draw,
        loss,
        winRate: games ? Math.round((1000 * win) / games) / 10 : 0,
        variants,
      })
    }
    out.sort((a, b) => b.games - a.games)
    return out.slice(0, 10)
  })

  // Per-family expand state; resets whenever this screen remounts (per-route).
  let expandedFamilies = $state<Record<string, boolean>>({})
  function toggleFamily(family: string) {
    expandedFamilies = { ...expandedFamilies, [family]: !expandedFamilies[family] }
  }
  function onFamilyKey(e: KeyboardEvent, family: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggleFamily(family)
    }
  }

  // ── derived: move-quality donut for the active colour filter ────────────────
  const QUALITY_ORDER = [
    'brilliant',
    'great',
    'best',
    'excellent',
    'good',
    'book',
    'inaccuracy',
    'mistake',
    'miss',
    'blunder',
  ]
  let quality = $derived.by(() => {
    if (!data) return { total: 0, items: [] as { key: string; color: string; count: number; pct: number }[] }
    const cols =
      colorFilter === 'all'
        ? [data.move_quality.white, data.move_quality.black]
        : [data.move_quality[colorFilter]]
    const counts: Record<string, { color: string; count: number }> = {}
    for (const col of cols)
      for (const it of col.items) {
        const e = (counts[it.key] ??= { color: it.color, count: 0 })
        e.count += it.count
      }
    const total = Object.values(counts).reduce((s, e) => s + e.count, 0)
    const items = QUALITY_ORDER.filter((k) => counts[k]).map((k) => ({
      key: k,
      color: counts[k].color,
      count: counts[k].count,
      pct: total ? +((100 * counts[k].count) / total).toFixed(1) : 0,
    }))
    return { total, items }
  })

  // ── chart configs (rebuilt on theme / filter / data change) ─────────────────
  function rollingAvg(vals: number[], win = 8): (number | null)[] {
    return vals.map((_, i) => {
      const lo = Math.max(0, i - win + 1)
      const slice = vals.slice(lo, i + 1)
      return +(slice.reduce((s, v) => s + v, 0) / slice.length).toFixed(1)
    })
  }

  function trendConfig(): ChartConfiguration {
    const p = palette()
    const pts = data!.trend
    const accs = pts.map((t) => t.accuracy)
    const avg = rollingAvg(accs)
    return {
      type: 'line',
      data: {
        labels: pts.map((t) => fmtDate(t.date)),
        datasets: [
          {
            label: 'Accuracy',
            data: accs,
            borderColor: p.accent,
            backgroundColor: p.accent + '24',
            fill: true,
            tension: 0.3,
            pointRadius: pts.length > 40 ? 0 : 2,
            pointHoverRadius: 5,
            borderWidth: 2,
            order: 2,
          },
          {
            label: 'Trend',
            data: avg,
            borderColor: p.text,
            borderDash: [5, 4],
            borderWidth: 1.5,
            fill: false,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 0,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: p.surface,
            borderColor: p.divider,
            borderWidth: 1,
            titleColor: p.text,
            bodyColor: p.muted,
            padding: 10,
            callbacks: {
              title: (items) => {
                const t = pts[items[0].dataIndex]
                return t ? fmtDate(t.date) : ''
              },
              label: (item) => {
                const t = pts[item.dataIndex]
                if (item.datasetIndex === 1) return `Trend  ${item.formattedValue}%`
                if (!t) return ''
                return [
                  `Accuracy  ${t.accuracy}%`,
                  `Result  ${t.outcome}`,
                  t.opening,
                ]
              },
            },
          },
        },
        scales: {
          y: {
            min: 0,
            max: 100,
            ticks: { color: p.muted, font: { size: 11 } },
            grid: { color: p.divider },
          },
          x: {
            ticks: { color: p.muted, font: { size: 11 }, maxTicksLimit: 8 },
            grid: { display: false },
          },
        },
      },
    }
  }

  function donutConfig(): ChartConfiguration<'doughnut'> {
    const p = palette()
    const q = quality
    return {
      type: 'doughnut',
      data: {
        labels: q.items.map((it) => CLASS_LABELS[it.key] ?? it.key),
        datasets: [
          {
            data: q.items.map((it) => it.count),
            backgroundColor: q.items.map((it) => it.color),
            borderColor: p.surface,
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: p.surface,
            borderColor: p.divider,
            borderWidth: 1,
            titleColor: p.text,
            bodyColor: p.muted,
            padding: 10,
            callbacks: {
              label: (item) => {
                const it = q.items[item.dataIndex]
                return `  ${it.count} moves · ${it.pct}%`
              },
            },
          },
        },
      },
    }
  }

  function moveAccConfig(): ChartConfiguration {
    const p = palette()
    const series = data!.move_accuracy[colorFilter]
    return {
      type: 'line',
      data: {
        labels: series.map((s) => (s.cumulative ? `${s.move}+` : `${s.move}`)),
        datasets: [
          {
            data: series.map((s) => s.accuracy),
            borderColor: p.accent,
            backgroundColor: p.accent + '1f',
            fill: true,
            tension: 0.35,
            // The x-axis thins its labels, so `40+` may not survive as a tick.
            // Marking the point is what actually stops the tail being read as
            // the next move number.
            pointRadius: series.map((s) => (s.cumulative ? 4 : 0)),
            pointHoverRadius: 5,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: p.surface,
            borderColor: p.divider,
            borderWidth: 1,
            titleColor: p.text,
            bodyColor: p.muted,
            padding: 10,
            callbacks: {
              title: (items) => {
                const s = series[items[0].dataIndex]
                return s.cumulative ? `Move ${s.move} and later` : `Move ${s.move}`
              },
              label: (item) => {
                const s = series[item.dataIndex]
                return [`Accuracy  ${s.accuracy}%`, `${s.samples} moves`]
              },
            },
          },
        },
        scales: {
          y: {
            min: 0,
            max: 100,
            ticks: { color: p.muted, font: { size: 11 } },
            grid: { color: p.divider },
          },
          x: {
            ticks: { color: p.muted, font: { size: 11 }, maxTicksLimit: 10 },
            grid: { display: false },
            title: { display: true, text: 'Move number', color: p.muted, font: { size: 11 } },
          },
        },
      },
    }
  }

  const nf = new Intl.NumberFormat()

  // The verdict is computed in the backend, which owns the interval test; this
  // only puts words around it. Null means the phases are too close to separate,
  // which is a real answer and is worded as one — not as "no weakness found".
  function phaseVerdictText(v: InsightsPhaseVerdict | null): string {
    if (!v)
      return 'No phase stands out yet — the differences between them are within what this many games can show.'
    return (
      `Your ${v.phase} is your weakest phase: ${v.rate}% of your ${nf.format(v.total)} ` +
      `${v.phase} moves are blunders, against ${v.comparedRate}% of ${nf.format(v.comparedTotal)} ` +
      `in the ${v.comparedTo}.`
    )
  }

  function phaseConfig(): ChartConfiguration {
    const p = palette()
    const phases = data!.phase_quality
    const labels = phases.map((ph) => ph.phase[0].toUpperCase() + ph.phase.slice(1))
    // pivot: one dataset per classification, stacked across phases
    const present = QUALITY_ORDER.filter((k) => phases.some((ph) => ph.items.some((it) => it.key === k)))
    const datasets = present.map((cls) => ({
      label: CLASS_LABELS[cls] ?? cls,
      data: phases.map((ph) => ph.items.find((it) => it.key === cls)?.pct ?? 0),
      backgroundColor: CLASS_COLORS[cls],
      stack: 'q',
      borderWidth: 0,
      // stash counts for the tooltip
      _counts: phases.map((ph) => ph.items.find((it) => it.key === cls)?.count ?? 0),
      _totals: phases.map((ph) => ph.total),
    }))
    return {
      type: 'bar',
      data: { labels, datasets: datasets as never },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: p.surface,
            borderColor: p.divider,
            borderWidth: 1,
            titleColor: p.text,
            bodyColor: p.muted,
            padding: 10,
            callbacks: {
              label: (item) => {
                const ds = item.dataset as never as {
                  label: string
                  _counts: number[]
                  _totals: number[]
                }
                const n = ds._counts[item.dataIndex]
                const total = ds._totals[item.dataIndex]
                return `  ${ds.label}: ${item.formattedValue}% (${nf.format(n)} of ${nf.format(total)})`
              },
            },
          },
        },
        scales: {
          x: {
            stacked: true,
            min: 0,
            max: 100,
            ticks: { color: p.muted, font: { size: 11 }, callback: (v) => `${v}%` },
            grid: { color: p.divider },
          },
          y: { stacked: true, ticks: { color: p.text, font: { size: 12 } }, grid: { display: false } },
        },
      },
    }
  }

  let firstLoad = true
  async function load() {
    if (firstLoad) loading = true
    else refreshing = true
    error = null
    let superseded = false
    try {
      const res = await api.insights({
        color: colorFilter,
        speeds: selectedSpeeds,
        since: sinceFor(timeframe),
        rated: ratedFilter,
        includeLocal,
      })
      // A newer request overtook this one before the sidecar built it. Its reply
      // is still coming, so keep the current view and stay in the loading state
      // rather than flashing a stale frame and an early spinner-off.
      if (res.superseded) {
        superseded = true
        return
      }
      data = res
      if (data.overview.total > 0) everHadGames = true
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      if (!superseded) {
        loading = false
        refreshing = false
        firstLoad = false
      }
    }
  }

  // Filter changes arrive in bursts — four checkbox clicks is four builds, and a
  // build is ~12 s of Python. The sidecar supersedes *queued* builds, but it
  // cannot cancel the one already running, so the only way to avoid that first
  // wasted build is not to start it. Coalesce a burst into one request.
  const FILTER_DEBOUNCE_MS = 250
  let started = false

  // Re-fetch whenever a server-side filter changes (colour, time controls, or
  // timeframe). This also drives the initial load, which is not debounced —
  // there is no burst to coalesce yet and the screen would just sit empty.
  $effect(() => {
    void colorFilter
    void selectedSpeeds
    void timeframe
    void ratedFilter
    void includeLocal
    if (!started) {
      started = true
      load()
      return
    }
    // Show the indicator while the request is still only pending, so a click
    // does not look like it did nothing, and re-arm on each further change.
    refreshing = true
    const timer = setTimeout(load, FILTER_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  })
</script>

<div class="insights" role="presentation" onmousemove={moveTip}>
  <div class="inner">
    <header class="head">
      <div>
        <p class="eyebrow">Your game</p>
        <h1 class="title">Insights</h1>
      </div>
      {#if everHadGames}
        <div class="head-controls">
          {#if refreshing}<span class="refreshing"><span class="pulse-dot"></span></span>{/if}
          <div class="seg" role="tablist" aria-label="Time frame">
            {#each TIMEFRAMES as opt (opt.k)}
              <button
                class="seg-btn"
                class:on={timeframe === opt.k}
                role="tab"
                aria-selected={timeframe === opt.k}
                onclick={() => (timeframe = opt.k)}>{opt.l}</button
              >
            {/each}
          </div>
          <div class="filter-group" role="group" aria-label="Time controls">
            {#each SPEED_OPTS as opt (opt.k)}
              <button
                class="chip"
                class:on={selectedSpeeds.includes(opt.k)}
                aria-pressed={selectedSpeeds.includes(opt.k)}
                onclick={() => toggleSpeed(opt.k)}>{opt.l}</button
              >
            {/each}
          </div>
          <div class="seg" role="tablist" aria-label="Colour played">
            {#each [{ k: 'all', l: 'Both' }, { k: 'white', l: 'White' }, { k: 'black', l: 'Black' }] as opt (opt.k)}
              <button
                class="seg-btn"
                class:on={colorFilter === opt.k}
                role="tab"
                aria-selected={colorFilter === opt.k}
                onclick={() => (colorFilter = opt.k as ColorFilter)}>{opt.l}</button
              >
            {/each}
          </div>
          <div class="seg" role="tablist" aria-label="Rated or casual">
            {#each RATED_OPTS as opt (opt.k)}
              <button
                class="seg-btn"
                class:on={ratedFilter === opt.k}
                role="tab"
                aria-selected={ratedFilter === opt.k}
                onclick={() => (ratedFilter = opt.k)}>{opt.l}</button
              >
            {/each}
          </div>
        </div>
      {/if}
    </header>

    {#if loading}
      <div class="loading"><span class="pulse-dot"></span> Loading insights…</div>
    {:else if error}
      <span class="error">{error}</span>
    {:else if !data || (data.overview.total === 0 && !everHadGames)}
      <section class="card empty-hero">
        <h2 class="card-title">No games yet</h2>
        <p class="card-sub">
          Connect a Lichess or Chess.com account and sync your games to see insights into
          your openings, accuracy, and move quality.
        </p>
        {#if data && data.overview.excluded > 0}
          <p class="card-sub">
            You have {data.overview.excluded}
            {data.overview.excluded === 1 ? 'game' : 'games'} played here against Stockfish.
            Those are left out because you choose the level, but they can be counted.
          </p>
        {/if}
        <div class="actions">
          <button class="btn btn-accent" onclick={onconnect}>Connect an account</button>
          {#if data && data.overview.excluded > 0}
            <button class="btn btn-quiet" onclick={() => (includeLocal = true)}>
              Count Stockfish games
            </button>
          {/if}
        </div>
      </section>
    {:else if data.overview.total === 0}
      <section class="card empty-hero">
        <h2 class="card-title">No games match these filters</h2>
        <p class="card-sub">
          None of your games fit the selected colour and time controls. Widen the
          selection to see your insights.
        </p>
        <div class="actions">
          <button class="btn btn-accent" onclick={clearFilters}>Clear filters</button>
        </div>
      </section>
    {:else if !data.ready}
      <section class="card empty-hero">
        <div class="analyzing">
          <span class="pulse-dot"></span>
          <h2 class="card-title">Waiting on analysis…</h2>
        </div>
        <p class="card-sub">
          None of your {data.overview.total} games have been analyzed yet. Insights appear as
          soon as the first one is done.
        </p>
        <div class="actions"><button class="btn btn-quiet" onclick={load}>Refresh</button></div>
      </section>
    {:else}
      {#if data.overview.pending > 0}
        <div class="banner">
          <span class="pulse-dot"></span>
          {data.overview.analyzed} of {data.overview.total} games analyzed · {data.overview.pending}
          not analyzed yet
          <button class="link" onclick={load}>Refresh</button>
        </div>
      {/if}

      <!-- ── hero stat strip ────────────────────────────────────────────── -->
      <section class="stat-strip">
        <div class="stat">
          <span class="stat-val accent">{data.summary.avgAccuracy ?? '—'}{data.summary.avgAccuracy != null ? '%' : ''}</span>
          <span class="stat-label">Avg accuracy</span>
        </div>
        <div class="stat">
          <span class="stat-val">{data.summary.winRate}%</span>
          <span class="stat-label">Win rate</span>
        </div>
        <div class="stat">
          <span class="stat-val">{data.summary.gamesAnalyzed}</span>
          <span class="stat-label">Games analyzed</span>
        </div>
      </section>

      {#if data.overview.excluded > 0}
        <p class="source-note">
          {data.overview.excluded}
          {data.overview.excluded === 1 ? 'game' : 'games'} against Stockfish
          {data.overview.excluded === 1 ? 'is' : 'are'} not counted above — you choose the
          level there, so those games measure the setting as much as the play.
          <button class="link" onclick={() => (includeLocal = true)}>Count them too</button>
        </p>
      {:else if includeLocal}
        <p class="source-note">
          Games against Stockfish are counted above.
          <button class="link" onclick={() => (includeLocal = false)}>Leave them out</button>
        </p>
      {/if}

      <!-- ── openings (top 10 most played) ──────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Openings</h2>
            <p class="card-sub">
              Your most-played openings, grouped by family and ordered by how often you play
              them — games, record and average accuracy. Expand a family to see its variants.
              The differences in accuracy between openings are within what {data.summary
                .gamesAnalyzed} analyzed games can show, so this ranks what you play, not what
              you play well.
            </p>
          </div>
        </div>
        {#if families.length === 0}
          <p class="hint">No opening family has 5+ analyzed games yet — keep syncing.</p>
        {:else}
          <div class="otable">
            <div class="orow ohead">
              <span class="oh name">Opening</span>
              <span class="oh num">Games</span>
              <span class="oh wdl">W / D / L</span>
              <span class="oh acc">Accuracy</span>
              <span class="oh act"></span>
            </div>
            {#each families as fam (fam.family)}
              {@const multi = fam.variants.length > 1}
              {@const open = !!expandedFamilies[fam.family]}
              <div class="ofamily">
                <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
                <!-- role and tabindex are set together iff the family is multi-variant -->
                <div
                  class="orow famrow"
                  class:clickable={multi}
                  role={multi ? 'button' : undefined}
                  tabindex={multi ? 0 : undefined}
                  aria-expanded={multi ? open : undefined}
                  onclick={multi ? () => toggleFamily(fam.family) : undefined}
                  onkeydown={multi ? (e) => onFamilyKey(e, fam.family) : undefined}
                >
                  <div class="o-info">
                    <span class="o-name with-chev" title={fam.family}>
                      {#if multi}
                        <svg
                          class="chev"
                          class:open
                          viewBox="0 0 16 16"
                          width="11"
                          height="11"
                          aria-hidden="true"
                        >
                          <path
                            d="M5 3l6 5-6 5"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                          />
                        </svg>
                      {/if}
                      <span class="o-name-txt">{fam.family}</span>
                    </span>
                    <span class="o-eco"
                      >{multi ? `${fam.variants.length} variants` : fam.eco || '—'}</span
                    >
                  </div>
                  <span class="o-games">{fam.games}</span>
                  <div
                    class="wdlbar"
                    role="img"
                    aria-label="{fam.win} wins, {fam.draw} draws, {fam.loss} losses"
                    onmouseenter={(e) =>
                      showTip(
                        e,
                        `<b>${fam.family}</b><br>${fam.win}W · ${fam.draw}D · ${fam.loss}L<br>${fam.winRate}% win rate`,
                      )}
                    onmouseleave={hideTip}
                  >
                    {#if fam.games > 0}
                      <div class="seg-win" style:flex-grow={fam.win}></div>
                      <div class="seg-draw" style:flex-grow={fam.draw}></div>
                      <div class="seg-loss" style:flex-grow={fam.loss}></div>
                    {/if}
                  </div>
                  <div class="o-acc-cell">
                    <div class="o-bar">
                      <div
                        class="o-fill"
                        style:width="{fam.accuracy}%"
                        style:background={perfColor(fam.accuracy)}
                      ></div>
                    </div>
                    <span
                      class="o-acc"
                      style:color={perfColor(fam.accuracy)}
                      title="{fam.accuracy}% average accuracy over {fam.games} {fam.games === 1
                        ? 'game'
                        : 'games'}">{fam.accuracy}%</span
                    >
                  </div>
                  {#if multi || !ontrain}
                    <span class="o-act"></span>
                  {:else}
                    <button
                      class="o-train"
                      title="Train this opening"
                      onclick={(e) => {
                        e.stopPropagation()
                        ontrain?.({ eco: fam.eco, name: fam.variants[0].name })
                      }}>Train →</button
                    >
                  {/if}
                </div>

                {#if multi}
                  <div class="variants" class:open>
                    <div class="variants-inner">
                      {#each fam.variants as v (v.name)}
                        <div class="orow vrow">
                          <div class="o-info">
                            <span class="o-name" title={v.name}>{v.variantName}</span>
                            <span class="o-eco">{v.eco || '—'}</span>
                          </div>
                          <span class="o-games">{v.games}</span>
                          <div
                            class="wdlbar"
                            role="img"
                            aria-label="{v.win} wins, {v.draw} draws, {v.loss} losses"
                            onmouseenter={(e) =>
                              showTip(
                                e,
                                `<b>${v.name}</b><br>${v.win}W · ${v.draw}D · ${v.loss}L<br>${v.winRate}% win rate`,
                              )}
                            onmouseleave={hideTip}
                          >
                            {#if v.games > 0}
                              <div class="seg-win" style:flex-grow={v.win}></div>
                              <div class="seg-draw" style:flex-grow={v.draw}></div>
                              <div class="seg-loss" style:flex-grow={v.loss}></div>
                            {/if}
                          </div>
                          <div class="o-acc-cell">
                            <div class="o-bar">
                              <div
                                class="o-fill"
                                style:width="{v.accuracy}%"
                                style:background={perfColor(v.accuracy)}
                              ></div>
                            </div>
                            <span
                              class="o-acc"
                              style:color={perfColor(v.accuracy)}
                              title="{v.accuracy}% average accuracy over {v.games} {v.games === 1
                                ? 'game'
                                : 'games'}">{v.accuracy}%</span
                            >
                          </div>
                          {#if ontrain}
                            <button
                              class="o-train"
                              title="Train this opening"
                              onclick={() => ontrain({ eco: v.eco, name: v.name })}>Train →</button
                            >
                          {:else}
                            <span class="o-act"></span>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </section>

      <!-- ── accuracy trend + move-quality donut ────────────────────────── -->
      <div class="grid2">
        <section class="card">
          <div class="card-head">
            <div>
              <h2 class="card-title">Accuracy over time</h2>
              <p class="card-sub">Per-game accuracy with an 8-game trend line. Hover for the game.</p>
            </div>
          </div>
          {#if data.trend.length < 2}
            <p class="hint">
              {timeframe === 'all'
                ? 'Sync at least two games to see a trend.'
                : 'Not enough games in this window — try a longer timeframe.'}
            </p>
          {:else}
            <div class="chart-wrap tall">
              <ChartCanvas
                make={trendConfig}
                watch={[theme.mode, colorFilter, data.trend.length]}
              />
            </div>
          {/if}
        </section>

        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Move quality</h2>
            <p class="card-sub">How your moves break down. Hover a slice for counts.</p>
          </div>
          {#if quality.total === 0}
            <p class="hint">No analyzed moves yet.</p>
          {:else}
            <div class="donut-row">
              <div class="chart-wrap donut">
                <ChartCanvas make={donutConfig} watch={[theme.mode, colorFilter, quality.total]} />
              </div>
              <div class="legend">
                {#each quality.items as it (it.key)}
                  <div class="leg-row">
                    <span class="leg-dot" style:background={it.color}></span>
                    <span class="leg-name">{CLASS_LABELS[it.key] ?? it.key}</span>
                    <span class="leg-pct">{it.pct}%</span>
                    <span class="leg-count">{it.count}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </section>
      </div>

      <!-- ── phase quality + accuracy by move number ────────────────────── -->
      <div class="grid2">
        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Move quality by phase</h2>
            <p class="card-sub">
              Your moves split into opening, middlegame and endgame, divided the way Lichess
              divides a game — by the pieces left and how far they've developed, not by move
              number.
            </p>
          </div>
          {#if data.phase_quality.every((p) => p.total === 0)}
            <p class="hint">No analyzed moves yet.</p>
          {:else}
            <div class="chart-wrap phase"><ChartCanvas make={phaseConfig} watch={[theme.mode]} /></div>
            <p class="verdict">{phaseVerdictText(data.phase_verdict)}</p>
          {/if}
        </section>

        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Accuracy by move number</h2>
            <p class="card-sub">
              How your accuracy holds up as a game runs long, counted by move number — not by
              phase. The marked final point is every move from there on, so it covers far more
              moves than any single one before it.
            </p>
          </div>
          {#if data.move_accuracy[colorFilter].length < 2}
            <p class="hint">Not enough analyzed moves yet.</p>
          {:else}
            <div class="chart-wrap tall">
              <ChartCanvas make={moveAccConfig} watch={[theme.mode, colorFilter]} />
            </div>
          {/if}
        </section>
      </div>

      <!-- ── R6: patterns across games (PATTERNS.md §6a), after the phase card ─ -->
      {#if data.patterns}
        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Patterns across your games</h2>
            <p class="card-sub">{coverageText(data.patterns)}</p>
          </div>
          {#if data.patterns.sentences.length === 0}
            <p class="verdict">{emptyText(data.patterns)}</p>
          {:else}
            <PatternsCard patterns={data.patterns} {onopen} />
          {/if}
        </section>
      {/if}

      <!-- ── record + terminations ──────────────────────────────────────── -->
      <div class="grid2">
        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Your record</h2>
            <p class="card-sub">Wins, draws and losses across your synced games.</p>
          </div>
          <div class="records">
            {#each [{ label: 'Overall', r: data.results.overall }, { label: 'As White', r: data.results.white }, { label: 'As Black', r: data.results.black }] as grp (grp.label)}
              <div class="record">
                <div class="rec-head">
                  <span class="rec-label">{grp.label}</span>
                  <span class="rec-meta">{grp.r.total} games · {grp.r.winRate}% won</span>
                </div>
                {#if grp.r.total === 0}
                  <p class="hint">No games.</p>
                {:else}
                  <div
                    class="wdlbar tall-bar"
                    role="img"
                    aria-label="{grp.r.win} wins, {grp.r.draw} draws, {grp.r.loss} losses"
                    onmouseenter={(e) =>
                      showTip(e, `<b>${grp.label}</b><br>${grp.r.win}W · ${grp.r.draw}D · ${grp.r.loss}L`)}
                    onmouseleave={hideTip}
                  >
                    <div class="seg-win" style:flex-grow={grp.r.win}></div>
                    <div class="seg-draw" style:flex-grow={grp.r.draw}></div>
                    <div class="seg-loss" style:flex-grow={grp.r.loss}></div>
                  </div>
                  <div class="wdl-legend">
                    <span><b>{grp.r.win}</b> W</span>
                    <span><b>{grp.r.draw}</b> D</span>
                    <span><b>{grp.r.loss}</b> L</span>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <h2 class="card-title">How your games end</h2>
            <p class="card-sub">The way your wins and losses finish.</p>
          </div>
          <div class="term-cols">
            {#each [{ label: 'Wins', items: data.terminations.win, win: true }, { label: 'Losses', items: data.terminations.loss, win: false }] as grp (grp.label)}
              <div class="term-col">
                <div class="qc-head"><span class="qc-label">{grp.label}</span></div>
                {#if grp.items.length === 0}
                  <p class="hint">None yet.</p>
                {:else}
                  {#each grp.items as it (it.label)}
                    <div class="term-row">
                      <span class="term-name">{it.label}</span>
                      <div class="term-track">
                        <div
                          class="term-fill"
                          style:width="{it.pct}%"
                          style:background={grp.win ? 'var(--win)' : 'var(--danger)'}
                        ></div>
                      </div>
                      <span class="term-count">{it.count}</span>
                    </div>
                  {/each}
                {/if}
              </div>
            {/each}
          </div>
        </section>
      </div>

      <!-- ── castling ───────────────────────────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <h2 class="card-title">Castling</h2>
          <p class="card-sub">Which way you castle, and how you fare each way.</p>
        </div>
        {#if data.castling.every((c) => c.total === 0)}
          <p class="hint">No analyzed games yet.</p>
        {:else}
          <div class="castle-rows">
            {#each data.castling as c (c.side)}
              <div class="castle-row">
                <div class="castle-info">
                  <span class="castle-label">{c.label}</span>
                  <span class="castle-meta">{c.total} games · {c.winRate}% won</span>
                </div>
                <div
                  class="wdlbar"
                  role="img"
                  aria-label="{c.win} wins, {c.draw} draws, {c.loss} losses"
                  onmouseenter={(e) =>
                    showTip(e, `<b>${c.label}</b><br>${c.win}W · ${c.draw}D · ${c.loss}L`)}
                  onmouseleave={hideTip}
                >
                  {#if c.total > 0}
                    <div class="seg-win" style:flex-grow={c.win}></div>
                    <div class="seg-draw" style:flex-grow={c.draw}></div>
                    <div class="seg-loss" style:flex-grow={c.loss}></div>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </section>

      <!-- ── when you play best (heatmap) ───────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <h2 class="card-title">When you play best</h2>
          <p class="card-sub">Accuracy by day of week and time of day. Darker amber = sharper.</p>
        </div>
        {#each [{ label: 'Day of week', cells: data.by_time.dayOfWeek }, { label: 'Time of day', cells: data.by_time.timeOfDay }] as grp (grp.label)}
          <div class="heat-block">
            <span class="qc-label">{grp.label}</span>
            <div class="heat-grid">
              {#each grp.cells as c (c.label)}
                <div
                  class="heat-cell"
                  class:empty={c.games === 0}
                  style:--heat={c.accuracy == null ? 0 : Math.max(0, Math.min(1, (c.accuracy - 45) / 45))}
                  role="img"
                  aria-label="{c.label}: {c.accuracy == null ? 'no games' : c.accuracy + '% accuracy'}"
                  onmouseenter={(e) =>
                    c.games > 0 &&
                    showTip(
                      e,
                      `<b>${c.label}</b><br>${c.accuracy ?? '—'}% accuracy<br>${c.games} games · ${c.winRate}% won`,
                    )}
                  onmouseleave={hideTip}
                >
                  <span class="hc-label">{c.label}</span>
                  <span class="hc-acc">{c.accuracy == null ? '—' : c.accuracy + '%'}</span>
                  <span class="hc-meta">{c.games} games</span>
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </section>
    {/if}
  </div>
</div>

{#if tip}
  <div class="floating-tip" style:left="{tip.x + 14}px" style:top="{tip.y + 14}px">{@html tip.html}</div>
{/if}

<style>
  .insights {
    height: 100%;
    overflow-y: auto;
  }
  .inner {
    max-width: 1080px;
    margin: 0 auto;
    padding: 48px 32px 64px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 4px;
  }
  .eyebrow {
    margin: 0;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .title {
    margin: 0;
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }
  .head-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
  }
  .refreshing {
    display: inline-flex;
    align-items: center;
  }

  /* time-control multiselect chips */
  .filter-group {
    display: inline-flex;
    gap: 6px;
  }
  .chip {
    padding: 6px 11px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-raised);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    transition: color 120ms ease, background 120ms ease, border-color 120ms ease;
  }
  .chip:hover:not(.on) {
    color: var(--text);
  }
  .chip.on {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }

  /* segmented control */
  .seg {
    display: inline-flex;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .seg-btn {
    padding: 6px 13px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-raised);
    transition: color 120ms ease, background 120ms ease;
  }
  .seg-btn + .seg-btn {
    border-left: 1px solid var(--divider);
  }
  .seg-btn.on {
    background: var(--bg-deep);
    color: var(--accent);
  }
  .seg-btn:hover:not(.on) {
    color: var(--text);
  }

  /* cards */
  .card {
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    padding: 22px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .empty-hero {
    gap: 12px;
    align-items: flex-start;
  }
  .analyzing {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .card-head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
  }
  .card-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .card-sub {
    margin: 4px 0 0;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .verdict {
    margin: 10px 0 0;
    font-size: 13px;
    line-height: 1.45;
    color: var(--text);
  }
  .hint {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .source-note {
    margin: -8px 0 0;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .error {
    font-size: 13px;
    color: var(--danger);
  }
  .actions {
    display: flex;
    gap: 12px;
  }
  .link {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--accent);
  }
  .link:hover {
    text-decoration: underline;
  }
  .loading {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-muted);
  }
  .banner {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
    color: var(--text-muted);
    padding: 10px 14px;
    background: var(--accent-soft);
    border: 1px solid var(--accent-line);
    border-radius: var(--radius);
  }

  .grid2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }

  /* stat strip */
  .stat-strip {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
  }
  .stat {
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    box-shadow: var(--shadow-tile);
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .stat-val {
    font-size: 26px;
    font-weight: 700;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .stat-val.accent {
    color: var(--accent);
  }
  .stat-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  /* openings table */
  .otable {
    display: flex;
    flex-direction: column;
  }
  .orow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 56px 120px 150px 64px;
    align-items: center;
    gap: 16px;
    padding: 10px 0;
  }
  .ohead {
    padding: 0 0 8px;
    border-bottom: 1px solid var(--divider);
  }

  /* one opening family: a header row + an animated variant drawer */
  .ofamily {
    border-bottom: 1px solid var(--divider);
  }
  .ofamily:last-child {
    border-bottom: none;
  }
  .famrow.clickable {
    cursor: pointer;
    border-radius: 6px;
    transition: background 120ms ease;
  }
  .famrow.clickable:hover {
    background: var(--bg-surface);
  }
  .famrow.clickable:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  .o-name.with-chev {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .o-name-txt {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chev {
    flex: none;
    color: var(--text-muted);
    transition: transform 200ms ease;
  }
  .chev.open {
    transform: rotate(90deg);
  }

  /* variant drawer: grid-rows 0fr→1fr gives a smooth height transition */
  .variants {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows 220ms ease;
  }
  .variants.open {
    grid-template-rows: 1fr;
  }
  .variants-inner {
    overflow: hidden;
    min-height: 0;
  }
  .vrow {
    background: color-mix(in srgb, var(--bg-surface) 45%, transparent);
  }
  .vrow + .vrow {
    border-top: 1px solid color-mix(in srgb, var(--divider) 50%, transparent);
  }
  .vrow .o-info {
    padding-left: 22px;
  }
  .vrow .o-name {
    font-weight: 400;
  }
  .oh {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-muted);
    text-align: left;
  }
  .oh.num,
  .oh.acc {
    text-align: right;
  }
  .o-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .o-name {
    font-size: 13.5px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .o-eco {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .o-games {
    font-size: 13px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
  }
  .o-acc-cell {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .o-bar {
    flex: 1;
    height: 8px;
    background: var(--bg-surface);
    border-radius: 4px;
    overflow: hidden;
  }
  .o-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 240ms ease;
  }
  .o-acc {
    font-size: 13px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    width: 40px;
    text-align: right;
  }
  .o-train {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-align: right;
    transition: color 120ms ease;
  }
  .o-train:hover {
    color: var(--accent);
  }

  /* shared W/D/L bar */
  .wdlbar {
    display: flex;
    height: 9px;
    border-radius: 5px;
    overflow: hidden;
    background: var(--bg-surface);
    cursor: default;
  }
  .wdlbar.tall-bar {
    height: 11px;
  }
  .seg-win {
    background: var(--win);
  }
  .seg-draw {
    background: var(--text-muted);
  }
  .seg-loss {
    background: var(--danger);
  }

  /* charts */
  .chart-wrap {
    position: relative;
    height: 200px;
  }
  .chart-wrap.tall {
    height: 240px;
  }
  .chart-wrap.phase {
    height: 200px;
  }
  .chart-wrap.donut {
    height: 180px;
    width: 180px;
    flex-shrink: 0;
  }
  .donut-row {
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .legend {
    display: flex;
    flex-direction: column;
    gap: 6px;
    flex: 1;
    min-width: 0;
  }
  .leg-row {
    display: grid;
    grid-template-columns: 12px 1fr 44px 40px;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
  }
  .leg-dot {
    width: 10px;
    height: 10px;
    border-radius: 3px;
  }
  .leg-name {
    color: var(--text);
  }
  .leg-pct {
    text-align: right;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .leg-count {
    text-align: right;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  /* records */
  .records {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .record {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .rec-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .rec-label {
    font-size: 13px;
    font-weight: 600;
  }
  .rec-meta {
    font-size: 12px;
    color: var(--text-muted);
  }
  .wdl-legend {
    display: flex;
    gap: 16px;
    font-size: 12px;
    color: var(--text-muted);
  }
  .wdl-legend b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  /* terminations */
  .term-cols {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  .term-col {
    display: flex;
    flex-direction: column;
    gap: 9px;
  }
  .qc-head {
    padding-bottom: 6px;
    border-bottom: 1px solid var(--divider);
  }
  .qc-label {
    font-size: 13px;
    font-weight: 600;
    text-transform: capitalize;
  }
  .term-row {
    display: grid;
    grid-template-columns: 1fr 70px 26px;
    align-items: center;
    gap: 8px;
  }
  .term-name {
    font-size: 12.5px;
    text-transform: capitalize;
  }
  .term-track {
    height: 6px;
    background: var(--bg-surface);
    border-radius: 3px;
    overflow: hidden;
  }
  .term-fill {
    height: 100%;
    border-radius: 3px;
  }
  .term-count {
    font-size: 12px;
    color: var(--text-muted);
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  /* castling */
  .castle-rows {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .castle-row {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .castle-info {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .castle-label {
    font-size: 13px;
    font-weight: 500;
  }
  .castle-meta {
    font-size: 12px;
    color: var(--text-muted);
  }


  /* heatmap */
  .heat-block {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .heat-block + .heat-block {
    margin-top: 8px;
  }
  .heat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 8px;
  }
  .heat-cell {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--divider);
    background: color-mix(in srgb, var(--accent) calc(var(--heat) * 60%), var(--bg-surface));
    cursor: default;
    transition: transform 120ms ease;
  }
  .heat-cell:hover:not(.empty) {
    transform: translateY(-2px);
    border-color: var(--accent-line);
  }
  .heat-cell.empty {
    opacity: 0.4;
    background: var(--bg-surface);
  }
  .hc-label {
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text);
  }
  .hc-acc {
    font-size: 18px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .hc-meta {
    font-size: 10.5px;
    color: var(--text);
    opacity: 0.75;
  }
  /* empty cells carry no amber fill, so the muted look is safe and de-emphasizes them */
  .heat-cell.empty .hc-label,
  .heat-cell.empty .hc-meta {
    color: var(--text-muted);
    opacity: 1;
  }

  /* floating tooltip */
  .floating-tip {
    position: fixed;
    z-index: 50;
    pointer-events: none;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-pop);
    padding: 8px 11px;
    font-size: 12px;
    color: var(--text);
    line-height: 1.5;
    max-width: 260px;
  }
  .floating-tip :global(b) {
    color: var(--text);
    font-weight: 600;
  }

  @media (max-width: 760px) {
    .grid2 {
      grid-template-columns: 1fr;
    }
    .stat-strip {
      grid-template-columns: repeat(2, 1fr);
    }
    .orow {
      grid-template-columns: minmax(0, 1fr) 70px 56px;
    }
    .orow .o-acc-cell,
    .orow .wdlbar,
    .ohead .acc,
    .ohead .wdl {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .o-fill,
    .heat-cell {
      transition: none;
    }
  }
</style>
