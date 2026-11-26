<script lang="ts">
  /**
   * Games, rebuilt (UI-BUILD-3 E; DESIGN.md fourth rulings, 7; mockups
   * design/mockups/MinimalGames.html, -import.html, -position.html): every game, filtered and
   * searched in the sidecar (games_page), fifty at a time under a header per month with that
   * month's record over every game the filters keep; accuracies from the depth-14 run. Rows are
   * stacked (UI-BUILD-4 B, fifth rulings 5): White's line over Black's, each with its rating and
   * accuracy; below 1440 px the Time and Source columns are hidden (fifth rulings 2). Sync now as Settings does it, "N waiting for analysis · Analyse now" as Home
   * does it, Import PGN and Analyse a position as popovers. J / K move, Enter opens, / searches.
   */
  import { onDestroy, onMount, tick } from 'svelte'
  import {
    api,
    sidecar,
    type GamesItem,
    type GamesPage,
    type GamesSort,
    type GamesSpeed,
    type ImportResult,
    type SyncDoneEvent,
    type SyncErrorEvent,
    type SyncProgressEvent,
    type SyncStatus,
    type SyncWarningEvent,
  } from '../api'
  import EmptyState from '../ui/EmptyState.svelte'
  import Kbd from '../ui/Kbd.svelte'
  import SegmentedControl from '../ui/SegmentedControl.svelte'
  import { alreadyHandled, ownsEnter } from '../ui/keyTargets'
  import { commandMenu, registerCommands } from '../shell/commands.svelte'
  import { accounts } from '../settings.svelte'
  import { lastSynced, markSynced } from '../gamesFilter.svelte'
  import { addSyncWarning, syncWarningLines, type SyncWarning } from '../syncWarnings'
  import { RunGuard } from '../background/runGuard'
  import { jobs, analysisStarted } from '../background/jobs.svelte'
  import { SOURCE_NAME, connected, finishedText, progressFraction, progressText, type Source } from '../settings/settingsModel'
  import {
    PAGE,
    SORT_LABEL,
    countText,
    dateText,
    filtersActive,
    moreFiltersSet,
    monthLabel,
    analysisNote,
    opponentCell,
    playerLines,
    pageParams,
    recordText,
    shortOpening,
    resultCell,
    runText,
    SOURCE_LABEL,
    step,
    syncedText,
    timeText,
    toggleSpeed,
    withMonths,
    appendPage,
  } from './gamesModel'
  import { clearFilters, gamesView } from './gamesState.svelte'
  import ImportPopover from './ImportPopover.svelte'
  import PositionPopover from './PositionPopover.svelte'

  interface Props {
    onopen: (gameId: number) => void
    /** Analyse a position: App opens the position's analysis */
    onfen: (fen: string) => void
    /** Play it vs Stockfish: App starts a game from the position */
    onplayfen: (fen: string) => void
    onnav: (route: 'settings' | 'play') => void
  }
  let { onopen, onfen, onplayfen, onnav }: Props = $props()

  const f = $derived(gamesView.filters)

  // ── the page ────────────────────────────────────────────────────────────────
  let page = $state<GamesPage | null>(null)
  let games = $state<GamesItem[]>([])
  let error = $state<string | null>(null)
  let reloading = $state(false)
  let loadingMore = $state(false)
  let scroller: HTMLElement | undefined = $state()
  let searchEl: HTMLInputElement | undefined = $state()
  let token = 0

  async function load(mode: 'reset' | 'more' | 'refresh' | 'restore') {
    const my = ++token
    const offset = mode === 'more' ? games.length : 0
    const limit =
      mode === 'restore' ? Math.max(PAGE, gamesView.loaded) : mode === 'refresh' ? Math.max(PAGE, games.length) : PAGE
    if (mode === 'more') loadingMore = true
    else reloading = page !== null
    try {
      const r = await api.gamesPage(pageParams(gamesView.filters, offset, limit))
      if (my !== token) return
      error = null
      page = r
      games = mode === 'more' ? appendPage(games, r.games) : r.games
      gamesView.loaded = games.length
      if (mode === 'reset') gamesView.selected = -1
    } catch (e) {
      if (my !== token) return
      error = e instanceof Error ? e.message : String(e)
    } finally {
      if (my === token) {
        reloading = false
        loadingMore = false
      }
    }
  }

  // Any filter change reloads from the top; typing waits a moment for the next key.
  const sig = $derived(JSON.stringify(gamesView.filters))
  let lastSig: string | null = null
  let debounce: ReturnType<typeof setTimeout> | null = null
  $effect(() => {
    const s = sig
    if (lastSig === null) {
      lastSig = s
      return
    }
    if (s === lastSig) return
    lastSig = s
    if (debounce) clearTimeout(debounce)
    debounce = setTimeout(() => void load('reset'), 180)
  })

  const entries = $derived(page ? withMonths(games, page.months, f.sort) : [])
  const filtered = $derived(filtersActive(f))
  const more = $derived(page ? Math.max(0, page.total - games.length) : 0)

  function open(i: number) {
    const g = games[i]
    if (!g) return
    gamesView.selected = i
    gamesView.scrollTop = scroller?.scrollTop ?? 0
    onopen(g.id)
  }
  async function select(i: number) {
    gamesView.selected = i
    await tick()
    scroller?.querySelector(`[data-index="${i}"]`)?.scrollIntoView({ block: 'nearest' })
  }
  async function move(delta: 1 | -1) {
    if (delta === 1 && gamesView.selected === games.length - 1 && more > 0 && !loadingMore) {
      await load('more')
    }
    await select(step(gamesView.selected, delta, games.length))
  }

  // ── filters ─────────────────────────────────────────────────────────────────
  const SPEEDS: { value: GamesSpeed; label: string }[] = [
    { value: 'bullet', label: 'Bullet' },
    { value: 'blitz', label: 'Blitz' },
    { value: 'rapid', label: 'Rapid' },
    { value: 'classical', label: 'Classical' },
    { value: 'daily', label: 'Daily' },
  ]
  let sortOpen = $state(false)
  function setSort(s: GamesSort) {
    gamesView.filters.sort = s
    sortOpen = false
  }
  function searchKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      ;(e.currentTarget as HTMLInputElement).blur()
    } else if (e.key === 'Enter' && page?.total === 1 && games.length === 1) {
      // the search names one game (an id, usually): Enter opens it, as the old screen did
      e.preventDefault()
      open(0)
    }
  }

  // ── sync, Analyse now, the imported games' analysis: one bulk run at a time ─────
  let status = $state<SyncStatus | null>(null)
  type Run = {
    kind: 'sync' | 'analyse'
    phase: 'running' | 'finished' | 'failed'
    progress: SyncProgressEvent | null
    done: SyncDoneEvent[]
    errors: string[]
    retry: () => void
  }
  let run = $state<Run | null>(null)
  let warnings = $state<SyncWarning[]>([])
  const sources = $derived(connected(accounts))
  const pending = $derived(status ? (status.chesscom?.pending ?? 0) + (status.lichess?.pending ?? 0) : 0)
  // COACH-2 D (ruling CB2): a status never revives a run whose end was announced, and one saying nothing runs closes
  // a card still showing one
  const guard = new RunGuard()
  const running = $derived(run?.phase === 'running' || guard.live(status ? { running: status.syncing, run: status.run } : null))
  const synced = $derived(syncedText(lastSynced, sources))
  const label = (s: string) => SOURCE_NAME[s as Source] ?? SOURCE_LABEL[s as keyof typeof SOURCE_LABEL] ?? ''

  async function refreshStatus() {
    const asked = guard.ask()
    try {
      status = await api.syncStatus()
      const v = guard.verdict({ running: status.syncing, run: status.run }, asked, run?.phase === 'running')
      if (v === 'revive') {
        guard.started()
        run = { kind: 'sync', phase: 'running', progress: null, done: [], errors: [], retry: syncNow }
      } else if (v === 'close' && run?.phase === 'running') {
        run = { ...run, phase: run.errors.length ? 'failed' : 'finished', progress: null }
      }
    } catch {
      /* the strip waits for the next refresh */
    }
  }
  async function begin(kind: Run['kind'], retry: () => void, call: () => Promise<unknown>) {
    if (running) return
    warnings = []
    run = { kind, phase: 'running', progress: kind === 'sync' ? { phase: 'fetching', done: 0, total: 0 } : null, done: [], errors: [], retry }
    guard.started()
    try {
      await call()
    } catch (e) {
      run = { ...run, phase: 'failed', progress: null, errors: [e instanceof Error ? e.message : String(e)] }
    }
  }
  function syncNow() {
    if (sources.length === 0) return onnav('settings')
    void begin('sync', syncNow, () => api.startSync(accounts.lichess, accounts.chesscom))
  }
  function analyseNow() {
    void begin('analyse', analyseNow, () => api.analyzePending())
  }
  function analyseImported(ids: number[]) {
    void begin('analyse', () => analyseImported(ids), () => api.analyzeGames(ids))
  }
  const onProgress = (d: SyncProgressEvent) => {
    if (run?.phase === 'running') run.progress = d
    else {
      guard.started()
      run = { kind: d.phase === 'fetching' ? 'sync' : 'analyse', phase: 'running', progress: d, done: [], errors: [], retry: syncNow }
    }
  }
  const onDone = (d: SyncDoneEvent) => {
    if (run) run.done = [...run.done, d]
    if (run?.kind === 'sync' && (d.source === 'lichess' || d.source === 'chesscom')) markSynced(d.source)
    void refreshStatus()
    void load('refresh')
  }
  const onError = (d: SyncErrorEvent) => {
    if (run) run.errors = [...run.errors, d.source ? `${label(d.source)}: ${d.message}` : d.message]
  }
  const onWarning = (d: SyncWarningEvent) => (warnings = addSyncWarning(warnings, d))
  const onFinished = (d?: { run?: number }) => {
    guard.end(d?.run)
    if (run?.phase === 'running') run = { ...run, phase: run.errors.length ? 'failed' : 'finished', progress: null }
    void refreshStatus()
    void load('refresh')
  }
  const onCancelled = (d?: { run?: number }) => {
    guard.end(d?.run)
    run = null
    void refreshStatus()
  }
  const runSentence = $derived.by(() => {
    if (!run) return ''
    if (run.phase === 'running') return runText(run.kind, run.progress, progressText(run.progress))
    if (run.phase === 'failed') return run.kind === 'sync' ? 'The sync stopped.' : 'The analysis stopped.'
    if (run.kind === 'sync') return finishedText(run.done)
    const n = run.done.reduce((a, d) => a + d.analyzed, 0)
    return `Analysis finished: ${n.toLocaleString('en-US')} ${n === 1 ? 'game' : 'games'} analysed at depth 14.`
  })

  // ── one game's Analyse (Review's: analyze_game at 14), one at a time, the rest queued ───
  let rowRun = $state<{ id: number; done: number; total: number } | null>(null)
  let rowQueue = $state<number[]>([])
  let rowErrors = $state<Record<number, string>>({})
  function analyseRow(id: number) {
    delete rowErrors[id]
    if (rowRun) {
      if (rowRun.id !== id && !rowQueue.includes(id)) rowQueue = [...rowQueue, id]
      return
    }
    void startRow(id)
  }
  async function startRow(id: number) {
    rowRun = { id, done: 0, total: 0 }
    try {
      const r = await api.analyzeGame(id, 14)
      analysisStarted({ gameId: id, runId: r.runId, depth: r.depth })
    } catch (e) {
      rowErrors[id] = e instanceof Error ? e.message : String(e)
      rowRun = null
      nextRow()
    }
  }
  function nextRow() {
    const [id, ...rest] = rowQueue
    rowQueue = rest
    if (id !== undefined) void startRow(id)
  }
  const gid = (d: Record<string, unknown>) => (d as { gameId?: number }).gameId
  const onPly = (d: Record<string, unknown>) => {
    const e = d as { gameId: number; ply: number; total: number }
    if (rowRun && e.gameId === rowRun.id) rowRun = { id: e.gameId, done: e.ply + 1, total: e.total }
  }
  const onRowDone = (d: Record<string, unknown>) => {
    if (!rowRun || gid(d) !== rowRun.id) return
    rowRun = null
    void load('refresh')
    void refreshStatus()
    nextRow()
  }
  const onRowError = (d: Record<string, unknown>) => {
    if (!rowRun || (gid(d) !== undefined && gid(d) !== rowRun.id)) return
    rowErrors[rowRun.id] = String((d as { message?: string }).message ?? 'The analysis stopped.')
    rowRun = null
    nextRow()
  }
  const onRowCancelled = (d: Record<string, unknown>) => {
    if (!rowRun || gid(d) !== rowRun.id) return
    rowRun = null
    nextRow()
  }

  // ── popovers ────────────────────────────────────────────────────────────────
  let popover = $state<'import' | 'position' | null>(null)
  function imported(res: ImportResult, stay: boolean) {
    if (!stay) popover = null
    void load('refresh')
    if (res.gameIds.length) analyseImported(res.gameIds)
  }

  // ── keys ────────────────────────────────────────────────────────────────────
  function onKey(e: KeyboardEvent) {
    if (commandMenu.open || popover || sortOpen) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (alreadyHandled(e)) return
    if (e.key === '/') {
      searchEl?.focus()
    } else if (e.key === 'j' || e.key === 'J') {
      void move(1)
    } else if (e.key === 'k' || e.key === 'K') {
      void move(-1)
    } else if (e.key === 'Enter') {
      // a focused button or link acts on its own Enter; this is the selected row's
      if (ownsEnter(e.target as HTMLElement | null) || gamesView.selected < 0) return
      open(gamesView.selected)
    } else return
    e.preventDefault()
  }

  let off: (() => void) | null = null
  onMount(() => {
    void load('restore').then(async () => {
      await tick()
      if (scroller) scroller.scrollTop = gamesView.scrollTop
    })
    void refreshStatus()
    sidecar.on('sync_progress', onProgress)
    sidecar.on('sync_done', onDone)
    sidecar.on('sync_error', onError)
    sidecar.on('sync_warning', onWarning)
    sidecar.on('sync_finished', onFinished)
    sidecar.on('sync_cancelled', onCancelled)
    sidecar.on('analysis_ply', onPly)
    sidecar.on('analysis_done', onRowDone)
    sidecar.on('analysis_error', onRowError)
    sidecar.on('analysis_cancelled', onRowCancelled)
    off = registerCommands('games', () => [
      { id: 'games-search', group: 'Actions', label: 'Search games', kbd: '/', run: () => searchEl?.focus() },
      { id: 'games-import', group: 'Actions', label: 'Import PGN', run: () => (popover = 'import') },
      { id: 'games-position', group: 'Actions', label: 'Analyse a position', run: () => (popover = 'position') },
      ...(running ? [] : [{ id: 'games-sync', group: 'Actions', label: 'Sync now', run: syncNow }]),
      ...(pending > 0 && !running ? [{ id: 'games-analyse-now', group: 'Actions', label: `Analyse ${pending} waiting games`, run: analyseNow }] : []),
    ])
  })
  onDestroy(() => {
    if (debounce) clearTimeout(debounce)
    off?.()
    sidecar.off('sync_progress', onProgress)
    sidecar.off('sync_done', onDone)
    sidecar.off('sync_error', onError)
    sidecar.off('sync_warning', onWarning)
    sidecar.off('sync_finished', onFinished)
    sidecar.off('sync_cancelled', onCancelled)
    sidecar.off('analysis_ply', onPly)
    sidecar.off('analysis_done', onRowDone)
    sidecar.off('analysis_error', onRowError)
    sidecar.off('analysis_cancelled', onRowCancelled)
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="games">
  <header>
    <h1>Games</h1>
    <div class="actions">
      {#if synced}<span class="synced">{synced}</span>{/if}
      <button type="button" class="zq" aria-haspopup="dialog" aria-expanded={popover === 'position'} onclick={() => (popover = popover === 'position' ? null : 'position')}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M3 9h18M3 15h18M9 3v18M15 3v18"></path></svg>Analyse a position
      </button>
      <button type="button" class="zq" aria-haspopup="dialog" aria-expanded={popover === 'import'} onclick={() => (popover = popover === 'import' ? null : 'import')}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M4 21h16"></path></svg>Import PGN
      </button>
      <span class="div" aria-hidden="true"></span>
      <button
        type="button"
        class="sync"
        disabled={running}
        title={sources.length === 0 ? 'Add your Chess.com or Lichess username in Settings to sync' : undefined}
        onclick={syncNow}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4"></path></svg>Sync now
      </button>
    </div>
  </header>

  <div class="scroll" bind:this={scroller}>
    <main>
      <div class="bar" role="toolbar" aria-label="Filters">
        <label class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
          <input
            bind:this={searchEl}
            type="text"
            bind:value={gamesView.filters.search}
            placeholder="Opponent, opening, game id or link"
            aria-label="Search games"
            title="A Chess.com or Lichess game id or link, or the app's id (#483), finds that game; Enter opens it."
            spellcheck="false"
            onkeydown={searchKey}
          />
        </label>
        <SegmentedControl
          label="Result"
          bind:value={gamesView.filters.result}
          options={[
            { value: 'all', label: 'All' },
            { value: 'win', label: 'Won' },
            { value: 'draw', label: 'Drawn' },
            { value: 'loss', label: 'Lost' },
          ]}
        />
        <SegmentedControl
          label="Your colour"
          bind:value={gamesView.filters.color}
          options={[
            { value: 'all', label: 'Both' },
            { value: 'white', label: 'White' },
            { value: 'black', label: 'Black' },
          ]}
        />
        <div class="zseg" role="group" aria-label="Time control">
          {#each SPEEDS as s (s.value)}
            <button type="button" aria-pressed={f.speeds.includes(s.value)} onclick={() => (gamesView.filters.speeds = toggleSpeed(f.speeds, s.value))}>{s.label}</button>
          {/each}
        </div>
        <button type="button" class="zq small boxed" class:zon={gamesView.moreOpen} aria-expanded={gamesView.moreOpen} onclick={() => (gamesView.moreOpen = !gamesView.moreOpen)}>
          More filters{moreFiltersSet(f) ? ` · ${moreFiltersSet(f)}` : ''}
          <svg class="caret" class:flip={gamesView.moreOpen} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>
        </button>
        <span class="grow"></span>
        <div class="sortwrap">
          <button type="button" class="zq small" aria-haspopup="menu" aria-expanded={sortOpen} onclick={() => (sortOpen = !sortOpen)}>
            {SORT_LABEL[f.sort]}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>
          </button>
          {#if sortOpen}
            <button type="button" class="veil" aria-label="Close the sort menu" tabindex="-1" onclick={() => (sortOpen = false)}></button>
            <div
              class="menu"
              role="menu"
              tabindex="-1"
              aria-label="Sort"
              onkeydown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault()
                  sortOpen = false
                }
              }}
            >
              {#each Object.entries(SORT_LABEL) as [value, text] (value)}
                <button type="button" role="menuitemradio" aria-checked={f.sort === value} onclick={() => setSort(value as GamesSort)}>{text}</button>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      {#if gamesView.moreOpen}
        <div class="more" role="group" aria-label="More filters">
          <div class="mf">
            <span class="mfl">Source</span>
            <SegmentedControl
              label="Source"
              bind:value={gamesView.filters.source}
              options={[
                { value: 'all', label: 'All' },
                { value: 'chesscom', label: 'Chess.com' },
                { value: 'lichess', label: 'Lichess' },
                { value: 'local', label: 'Played here' },
                { value: 'imported', label: 'Imported' },
              ]}
            />
          </div>
          <div class="mf">
            <span class="mfl">Rated</span>
            <SegmentedControl
              label="Rated"
              bind:value={gamesView.filters.rated}
              options={[
                { value: 'all', label: 'All' },
                { value: 'rated', label: 'Rated' },
                { value: 'casual', label: 'Casual' },
              ]}
            />
          </div>
          <div class="mf">
            <span class="mfl">Date</span>
            <SegmentedControl
              label="Date"
              bind:value={gamesView.filters.date}
              options={[
                { value: 'all', label: 'All time' },
                { value: 'week', label: 'Last week' },
                { value: 'month', label: 'Last month' },
                { value: '3months', label: 'Last 3 months' },
                { value: 'custom', label: 'Custom' },
              ]}
            />
            {#if f.date === 'custom'}
              <input class="date" type="date" bind:value={gamesView.filters.customFrom} aria-label="From" />
              <span class="dash">–</span>
              <input class="date" type="date" bind:value={gamesView.filters.customTo} aria-label="To" />
            {/if}
          </div>
          <div class="mf">
            <span class="mfl">Analysis</span>
            <SegmentedControl
              label="Analysis"
              bind:value={gamesView.filters.analysis}
              options={[
                { value: 'all', label: 'All' },
                { value: 'analyzed', label: 'Analysed' },
                { value: 'unanalyzed', label: 'Not analysed' },
              ]}
            />
          </div>
          <div class="mf">
            <span class="mfl">Opening</span>
            <input class="text" type="text" bind:value={gamesView.filters.opening} placeholder="Name or ECO, e.g. Sicilian or B20" aria-label="Opening" spellcheck="false" />
          </div>
          {#if filtered}
            <div class="mf"><span class="mfl"></span><button type="button" class="link" onclick={clearFilters}>Clear filters</button></div>
          {/if}
        </div>
      {/if}

      {#if page}
        <div class="countline">
          <span>{countText(page.total, page.all, filtered)}</span>
          {#if filtered && !gamesView.moreOpen}<button type="button" class="link quiet" onclick={clearFilters}>Clear filters</button>{/if}
          {#if pending > 0 && !running}
            <span class="vr" aria-hidden="true"></span>
            <span class="waiting">{pending.toLocaleString('en-US')} waiting for analysis</span>
            <button type="button" class="link" onclick={analyseNow}>Analyse now</button>
          {/if}
        </div>
      {/if}

      {#if run}
        {#if run.phase === 'running'}
          <EmptyState
            sentence={runSentence}
            sub="You can keep using the app; new games appear as they are analysed."
            progress={progressFraction(run.progress)}
            action={{ label: 'Cancel', run: () => void api.cancelSync() }}
          />
        {:else if run.phase === 'failed'}
          <EmptyState
            tone="error"
            sentence={runSentence}
            sub={[...run.errors, ...syncWarningLines(warnings, label)].join(' ')}
            action={{ label: 'Try again', run: run.retry }}
          />
        {:else}
          <EmptyState sentence={runSentence} sub={syncWarningLines(warnings, label).join(' ') || null} action={{ label: 'Dismiss', run: () => (run = null) }} />
        {/if}
      {/if}

      {#if error && !page}
        <EmptyState tone="error" sentence="Your games could not be loaded." sub={error} action={{ label: 'Try again', run: () => void load('reset') }} />
      {:else if !page}
        <EmptyState sentence="Loading your games…" />
      {:else if page.all === 0}
        <EmptyState
          sentence="No games yet."
          sub="Connect a Chess.com or Lichess account to sync your games, or play one against Stockfish."
          action={{ label: 'Connect an account', run: () => onnav('settings'), primary: true }}
        />
      {:else if page.total === 0}
        <EmptyState sentence="No games match these filters." sub={error} action={{ label: 'Clear filters', run: clearFilters }} />
      {:else}
        <div class="table" class:dim={reloading}>
          <div class="zg head" aria-hidden="true">
            <span>Result</span><span>Players</span><span class="r">Accuracy</span><span>Opening</span>
            <span class="tc">Time</span><span class="src">Source</span><span class="r">Date</span><span></span>
          </div>
          <ul>
            {#each entries as entry (entry.kind === 'month' ? `m${entry.month.month}` : `g${entry.game.id}`)}
              {#if entry.kind === 'month'}
                <li class="month">
                  <span class="mname">{monthLabel(entry.month.month)}</span>
                  <span class="mrec">{recordText(entry.month)}</span>
                </li>
              {:else}
                {@const g = entry.game}
                {@const i = entry.index}
                {@const res = resultCell(g)}
                {@const opp = opponentCell(g)}
                {@const lines = playerLines(g)}
                {@const note = analysisNote(g, rowRun, rowQueue, rowErrors[g.id], jobs.now.analysis)}
                <li class="zg row" class:sel={gamesView.selected === i} data-index={i}>
                  <button
                    type="button"
                    class="open"
                    aria-label={`Open the review: ${res.word} against ${opp.name}, ${dateText(g.playedAt)}`}
                    onclick={() => open(i)}
                  ></button>
                  <span class="res"><span class="dot {res.tone ?? 'none'}" aria-hidden="true"></span>{res.word}</span>
                  <span class="stack players">
                    {#each lines as l (l.color)}
                      <span class="pl el">
                        <span class="sq {l.color}" role="img" aria-label={l.color === 'white' ? 'White' : 'Black'}></span>
                        <span class="el" title={l.name}><span class="pname {l.nameTone}">{l.name}</span>{#if l.detail}{' '}<span class="muted">{l.detail}</span>{/if}</span>
                      </span>
                    {/each}
                  </span>
                  <span class="stack r">
                    {#each lines as l (l.color)}
                      <span class="acc {l.accTone}" title={l.accTone === 'off' ? undefined : `${l.you ? 'Your' : l.name + "'s"} accuracy`}>{l.accuracy}</span>
                    {/each}
                  </span>
                  <span class="stack">
                    <span class="el t2" title={g.openingName ?? undefined}>{shortOpening(g.openingName)}{#if g.openingEco}{' '}<span class="muted">{g.openingEco}</span>{/if}</span>
                    {#if note}
                      <span class="note">
                        <span class="nt" class:not={note.canAnalyse} title={rowErrors[g.id] ?? note.text}>{note.text}</span>
                        {#if note.canAnalyse}<button type="button" class="an" onclick={() => analyseRow(g.id)}>Analyse</button>{/if}
                      </span>
                    {/if}
                  </span>
                  <span class="t2 tc">{timeText(g.timeControl)}</span>
                  <span class="el muted src">{SOURCE_LABEL[g.source]}</span>
                  <span class="r muted">{dateText(g.playedAt)}</span>
                  <svg class="go" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
                </li>
              {/if}
            {/each}
          </ul>
          {#if more > 0}
            <div class="morerow">
              <button type="button" class="zq small" disabled={loadingMore} onclick={() => void load('more')}>
                {loadingMore ? 'Loading…' : `Show ${Math.min(PAGE, more)} more`}
              </button>
            </div>
          {/if}
        </div>
        {#if error}<p class="loaderr" role="alert">The list could not be refreshed: {error}</p>{/if}
      {/if}

      <div class="hints">
        <span><Kbd keys="J" /> <Kbd keys="K" /> move through games</span>
        <span><Kbd keys="Enter" /> open the review</span>
        <span><Kbd keys="/" /> search</span>
      </div>
    </main>
  </div>

  {#if popover}
    <button type="button" class="veil" aria-label="Close" tabindex="-1" onclick={() => (popover = null)}></button>
    <div class="anchor {popover}">
      {#if popover === 'import'}
        <ImportPopover onimported={imported} oncancel={() => (popover = null)} />
      {:else}
        <PositionPopover
          onanalyse={(fen) => {
            popover = null
            onfen(fen)
          }}
          onplay={(fen) => {
            popover = null
            onplayfen(fen)
          }}
          oncancel={() => (popover = null)}
        />
      {/if}
    </div>
  {/if}
</div>

<style>
  .games {
    position: relative;
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .synced {
    color: var(--text-3);
    font: var(--secondary);
    margin-right: 8px;
  }
  .div {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 8px;
  }
  button {
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  button:focus-visible,
  input:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .zq {
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 0;
    border-radius: var(--radius-control);
    padding: 5px 8px;
    color: var(--text-2);
  }
  .zq:hover:not(:disabled),
  .zq.zon {
    background: var(--raised);
    color: var(--text);
  }
  .zq:disabled {
    color: var(--disabled);
    cursor: default;
  }
  .small {
    font: var(--secondary);
  }
  .boxed {
    border: 1px solid var(--border);
    padding: 4px 8px;
  }
  .caret.flip {
    transform: rotate(180deg);
  }
  .sync {
    display: flex;
    align-items: center;
    gap: 8px;
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 5px 10px;
    color: var(--text);
  }
  .sync:hover:not(:disabled) {
    background: var(--surface);
  }
  .sync:disabled {
    color: var(--disabled);
    border-color: var(--border);
    cursor: default;
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  main {
    padding: 20px 28px 28px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-width: 1180px;
    box-sizing: border-box;
  }
  .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 250px;
    box-sizing: border-box;
    padding: 5px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    background: var(--surface);
    color: var(--text-3);
  }
  .search:focus-within {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .search input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: 0;
    outline: none;
    color: var(--text);
    font: var(--secondary);
    padding: 0;
    user-select: text;
  }
  .search input::placeholder {
    color: var(--text-3);
  }
  .zseg {
    display: flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .zseg button {
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 2px 9px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .zseg button:hover {
    color: var(--text);
  }
  .zseg button[aria-pressed='true'] {
    background: var(--border);
    color: var(--text);
  }
  .grow {
    flex: 1;
  }
  .sortwrap {
    position: relative;
  }
  .menu {
    position: absolute;
    right: 0;
    top: calc(100% + 4px);
    z-index: 6;
    min-width: 200px;
    background: var(--raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    padding: 4px;
    display: flex;
    flex-direction: column;
  }
  .menu button {
    text-align: left;
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 6px 8px;
    color: var(--text-2);
  }
  .menu button:hover,
  .menu button[aria-checked='true'] {
    background: var(--selected);
    color: var(--text);
  }
  .veil {
    position: fixed;
    inset: 0;
    z-index: 4;
    background: transparent;
    border: 0;
    cursor: default;
  }
  .sortwrap .veil {
    z-index: 5;
  }
  .more {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .mf {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .mfl {
    width: 72px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .text,
  .date {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    color: var(--text);
    font: var(--secondary);
    padding: 4px 8px;
    user-select: text;
  }
  .text {
    width: 250px;
  }
  .date {
    color-scheme: dark;
  }
  .dash {
    color: var(--text-3);
  }
  .countline {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .vr {
    width: 1px;
    height: 12px;
    background: var(--border);
  }
  .waiting {
    color: var(--text-2);
  }
  .link {
    background: transparent;
    border: 0;
    padding: 0;
    color: var(--text);
    font: var(--secondary);
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-color: var(--disabled);
  }
  .link.quiet {
    color: var(--text-2);
  }
  .table {
    /* a block: Tailwind's `table` utility would make it display: table, shrink-to-fit (BETA-4 C) */
    display: block;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
    transition: opacity 120ms;
  }
  .table.dim {
    opacity: 0.6;
  }
  /* the mockup's .zg2: Result, Players, Accuracy, Opening, Time, Source, Date, the arrow */
  .zg {
    display: grid;
    grid-template-columns: 84px minmax(0, 1.15fr) 52px minmax(0, 1.6fr) 64px 96px 64px 14px;
    gap: 24px;
    align-items: center;
    padding: 0 16px;
  }
  /* fifth rulings 2: a window under 1440 px wide drops Time and Source (the window's width, as the
     sidebar's icon rail switches at the same width) */
  @media (max-width: 1439px) {
    .zg {
      grid-template-columns: 84px minmax(0, 1.15fr) 52px minmax(0, 1.6fr) 64px 14px;
    }
    .tc,
    .src {
      display: none;
    }
  }
  .head {
    height: 32px;
    color: var(--text-3);
    font: var(--secondary);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .month {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 14px 16px 6px;
    border-top: 1px solid var(--border);
    background: var(--bg);
  }
  .mname {
    font-weight: 500;
  }
  .mrec {
    color: var(--text-3);
    font: var(--secondary);
  }
  .row {
    position: relative;
    padding-top: 8px;
    padding-bottom: 8px;
    border-top: 1px solid var(--divider);
  }
  .row:hover {
    background: var(--surface);
  }
  .row.sel {
    background: var(--raised);
    box-shadow: inset 2px 0 0 var(--focus);
  }
  .row > :not(.open) {
    position: relative;
    pointer-events: none;
  }
  .open {
    position: absolute;
    inset: 0;
    background: transparent;
    border: 0;
    padding: 0;
  }
  .open:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }
  .res {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .stack.r {
    align-items: flex-end;
  }
  .pl {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .pname.bright {
    font-weight: 500;
    color: var(--text);
  }
  .pname.dim {
    font-weight: 400;
    color: var(--text-2);
  }
  .acc.bright {
    color: var(--text);
  }
  .acc.dim {
    color: var(--text-3);
  }
  .acc.off {
    color: var(--disabled);
  }
  .note {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-3);
    font: var(--secondary);
    min-width: 0;
  }
  .note .nt {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 4px;
    flex: none;
  }
  .dot.win {
    background: var(--win);
  }
  .dot.loss {
    background: var(--loss);
  }
  .dot.draw {
    background: var(--draw);
  }
  .dot.none {
    background: transparent;
    border: 1px solid var(--draw);
    box-sizing: border-box;
  }
  .sq {
    width: 9px;
    height: 9px;
    border-radius: 2px;
    box-sizing: border-box;
    flex: none;
  }
  .sq.white {
    background: var(--text);
    border: 1px solid var(--text);
  }
  .sq.black {
    background: var(--bg);
    border: 1px solid var(--draw);
  }
  .el {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .t2 {
    color: var(--text-2);
  }
  .muted {
    color: var(--text-3);
  }
  .r {
    text-align: right;
  }
  /* the row's Analyse: shown on hover and on keyboard focus of the row (its open button or the
     Analyse button itself), "Not analysed" otherwise, as drawn */
  .an {
    display: none;
    pointer-events: auto;
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 0 8px;
    color: var(--text);
    font: var(--secondary);
  }
  .row:hover .an,
  .row:focus-within .an {
    display: inline-block;
  }
  .row:hover .not,
  .row:focus-within .not {
    display: none;
  }
  .go {
    opacity: 0;
  }
  .row:hover .go,
  .row.sel .go {
    opacity: 1;
  }
  .morerow {
    display: flex;
    justify-content: center;
    padding: 10px;
    border-top: 1px solid var(--border);
  }
  .loaderr {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .hints {
    color: var(--text-3);
    font: var(--secondary);
    display: flex;
    gap: 16px;
  }
  .anchor {
    position: absolute;
    top: 44px;
    z-index: 5;
  }
  .anchor.import {
    right: 112px;
  }
  .anchor.position {
    right: 220px;
  }
  @media (prefers-reduced-motion: no-preference) {
    .zq,
    .row,
    .zseg button {
      transition:
        background-color 0.12s,
        color 0.12s;
    }
  }
</style>
