<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte'
  import { api, sidecar, type GameSummary } from '../api'
  import type {
    SyncStatus,
    SyncProgressEvent,
    SyncDoneEvent,
    SyncErrorEvent,
    SyncWarningEvent,
    GameSource,
    ImportIssue,
    ImportResult,
  } from '../api'
  import { importSummary } from '../importReport'
  import { matchesSearch } from '../gameSearch'
  import { pickPgn } from '../pick'
  import { accounts } from '../settings.svelte'
  import { analysisDepth } from '../settings.svelte'
  import { analyseMoreLabel, analyseMoreStep, pendingButtonLabel, pendingSplit } from '../pendingLabel'
  import { addSyncWarning, syncWarningLines, type SyncWarning } from '../syncWarnings'
  import {
    gamesFilter as f,
    clearFilters,
    filtersActive,
    lastSynced,
    markSynced,
    relativeTime,
  } from '../gamesFilter.svelte'

  interface Props {
    onopen: (gameId: number) => void
    onfen: (fen: string) => void
    onnav: (route: 'settings' | 'play') => void
  }
  let { onopen, onfen, onnav }: Props = $props()

  let games = $state<GameSummary[]>([])
  let loaded = $state(false)
  let drawer = $state<'pgn' | 'fen' | 'more' | null>(null)
  let pgnText = $state('')
  let fenText = $state('')
  let drawerError = $state('')
  let importIssues = $state<ImportIssue[]>([])
  let importNote = $state('')
  // Only set on the file route: with the textarea the user can see what they
  // imported, from a file they cannot.
  let importedFrom = $state('')
  let importing = $state(false)
  let scrollEl = $state<HTMLElement>()

  // Progressive rendering: the full library lives in `games` (so filters/sort see
  // everything), but we only mount a window of the filtered+sorted rows and grow
  // it as the user nears the bottom. Keeps the DOM light at 1000s of games.
  const PAGE = 50
  const ROW_H = 64 // approx row height, used only to restore a saved scroll offset
  let renderLimit = $state(PAGE)

  const SPEED_LABEL: Record<string, string> = {
    bullet: 'Bullet',
    blitz: 'Blitz',
    rapid: 'Rapid',
    classical: 'Classical',
  }
  const SOURCE_LABEL: Record<GameSource, string> = {
    local: 'Stockfish',
    chesscom: 'Chess.com',
    lichess: 'Lichess',
    imported: 'Imported',
  }
  const SORT_LABEL: Record<string, string> = {
    recent: 'Most recent',
    accuracy_low: 'Lowest accuracy',
    accuracy_high: 'Highest accuracy',
    opening: 'By opening',
  }

  // ── derived helpers ────────────────────────────────────────────────────────
  function resultClass(g: GameSummary): 'win' | 'loss' | 'draw' | 'other' {
    if (g.result === '1/2-1/2') return 'draw'
    if (g.result === '*') return 'other'
    if (g.source === 'imported') return 'other'
    if (g.playerColor === null) return 'other' // side unknown: neither a win nor a loss
    const won =
      (g.result === '1-0' && g.playerColor === 'white') ||
      (g.result === '0-1' && g.playerColor === 'black')
    return won ? 'win' : 'loss'
  }

  // A game whose side is unknown (playerColor null, FIXPLAN O5) is shown neutrally:
  // White first, Black second, nobody's accuracy credited as "yours".
  function mySide(g: GameSummary): 'white' | 'black' {
    return g.playerColor ?? 'white'
  }
  function playerAccuracy(g: GameSummary): number | null {
    if (g.playerColor === null) return null
    return g.playerColor === 'white' ? g.whiteAccuracy : g.blackAccuracy
  }

  function opponentName(g: GameSummary): string {
    // A level from before the ladder was recorded is not the level of the same
    // name today — F5 respread them over the engine's whole range, so the old
    // Level 10 is roughly the new Level 5. Say so rather than let the number
    // be compared with a current one.
    if (g.source === 'local')
      return g.ladderVersion === null
        ? `Stockfish · Level ${g.skillLevel} (old scale)`
        : `Stockfish · Level ${g.skillLevel}`
    if (g.playerColor === null) return g.black && g.black.trim() ? g.black : 'Black'
    const opp = g.playerColor === 'white' ? g.black : g.white
    return opp && opp.trim() ? opp : 'Unknown'
  }

  // Your own display name — header name for platform games, "You" otherwise.
  function playerName(g: GameSummary): string {
    if (g.source === 'local') return 'You'
    if (g.playerColor === null) return g.white && g.white.trim() ? g.white : 'White'
    const me = g.playerColor === 'white' ? g.white : g.black
    return me && me.trim() ? me : 'You'
  }
  function oppColor(g: GameSummary): 'white' | 'black' {
    return mySide(g) === 'white' ? 'black' : 'white'
  }
  function playerElo(g: GameSummary): number | null {
    return mySide(g) === 'white' ? g.whiteElo : g.blackElo
  }
  function opponentElo(g: GameSummary): number | null {
    return mySide(g) === 'white' ? g.blackElo : g.whiteElo
  }

  // The small game-type glyph + its short label (mirrors Chess.com's icon cell).
  type GameKind = 'bullet' | 'blitz' | 'rapid' | 'classical' | 'engine' | 'other'
  function gameKind(g: GameSummary): GameKind {
    if (g.source === 'local') return 'engine'
    if (g.speed) return g.speed
    return 'other'
  }
  function gameLabel(g: GameSummary): string {
    if (g.source === 'local') return 'Engine'
    if (g.speed) return SPEED_LABEL[g.speed]
    return SOURCE_LABEL[g.source]
  }

  // Opponent accuracy = the side you didn't play.
  function oppAccuracy(g: GameSummary): number | null {
    if (g.playerColor === null) return null
    return g.playerColor === 'white' ? g.blackAccuracy : g.whiteAccuracy
  }
  // Subtle warm/green tint on your accuracy number — high reads green, low warm.
  function accClass(v: number | null): '' | 'good' | 'bad' {
    if (v == null) return ''
    if (v >= 80) return 'good'
    if (v < 60) return 'bad'
    return ''
  }

  function fmtDate(iso: string): string {
    const d = new Date(iso)
    const opts: Intl.DateTimeFormatOptions =
      d.getFullYear() === new Date().getFullYear()
        ? { month: 'short', day: 'numeric' }
        : { month: 'short', day: 'numeric', year: 'numeric' }
    return d.toLocaleDateString(undefined, opts)
  }

  const record = $derived.by(() => {
    let win = 0, loss = 0, draw = 0
    for (const g of games) {
      const r = resultClass(g)
      if (r === 'win') win++
      else if (r === 'loss') loss++
      else if (r === 'draw') draw++
    }
    return { win, loss, draw }
  })

  // ── filtering + sorting ────────────────────────────────────────────────────
  function dateCutoff(): number | null {
    const now = Date.now()
    const day = 86_400_000
    if (f.date === 'week') return now - 7 * day
    if (f.date === 'month') return now - 30 * day
    if (f.date === '3months') return now - 90 * day
    return null
  }

  function passesDate(g: GameSummary): boolean {
    const t = new Date(g.playedAt).getTime()
    if (f.date === 'custom') {
      if (f.customFrom) {
        const from = new Date(f.customFrom).getTime()
        if (!Number.isNaN(from) && t < from) return false
      }
      if (f.customTo) {
        const to = new Date(f.customTo).getTime() + 86_400_000 // inclusive end-of-day
        if (!Number.isNaN(to) && t >= to) return false
      }
      return true
    }
    const cut = dateCutoff()
    return cut === null || t >= cut
  }

  function passesSearch(g: GameSummary): boolean {
    // An exact game id (platform or app, `gameSearch.ts`) or a substring of the text.
    return matchesSearch(f.search, g, [
      opponentName(g),
      g.openingName ?? '',
      g.openingEco ?? '',
      fmtDate(g.playedAt),
      g.playedAt,
    ])
  }

  // Enter in the search box opens the game when the search leaves exactly one.
  function searchKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && f.search.trim() && visible.length === 1) open(visible[0])
  }

  function passesOpening(g: GameSummary): boolean {
    const q = f.opening.trim().toLowerCase()
    if (!q) return true
    return (
      (g.openingName ?? '').toLowerCase().includes(q) ||
      (g.openingEco ?? '').toLowerCase().includes(q)
    )
  }

  const visible = $derived.by(() => {
    const out = games.filter((g) => {
      if (f.result !== 'all' && resultClass(g) !== f.result) return false
      if (f.color !== 'all' && g.playerColor !== f.color) return false
      if (f.source !== 'all' && g.source !== f.source) return false
      if (f.speed !== 'all' && g.speed !== f.speed) return false
      if (f.rated === 'rated' && g.rated !== true) return false
      if (f.rated === 'casual' && g.rated !== false) return false
      if (f.analysis === 'analyzed' && !g.analyzed) return false
      if (f.analysis === 'unanalyzed' && g.analyzed) return false
      if (!passesDate(g)) return false
      if (!passesOpening(g)) return false
      if (!passesSearch(g)) return false
      return true
    })

    const accSort = (a: GameSummary, b: GameSummary, dir: 1 | -1) => {
      const aa = playerAccuracy(a)
      const ba = playerAccuracy(b)
      // unanalyzed (null) always sinks to the bottom regardless of direction
      if (aa === null && ba === null) return tcmp(b, a)
      if (aa === null) return 1
      if (ba === null) return -1
      if (aa !== ba) return (aa - ba) * dir
      return tcmp(b, a)
    }
    const tcmp = (a: GameSummary, b: GameSummary) =>
      new Date(a.playedAt).getTime() - new Date(b.playedAt).getTime()

    const sorted = [...out]
    if (f.sort === 'recent') sorted.sort((a, b) => tcmp(b, a))
    else if (f.sort === 'accuracy_low') sorted.sort((a, b) => accSort(a, b, 1))
    else if (f.sort === 'accuracy_high') sorted.sort((a, b) => accSort(a, b, -1))
    else if (f.sort === 'opening')
      sorted.sort((a, b) =>
        (a.openingName ?? '~').localeCompare(b.openingName ?? '~') || tcmp(b, a),
      )
    return sorted
  })

  const active = $derived(filtersActive())

  // The window actually rendered. Reset to one page whenever the filtered/sorted
  // set could change, so narrowing the list doesn't leave a huge window mounted.
  const shown = $derived(visible.slice(0, renderLimit))
  const filterSig = $derived(
    [
      f.result, f.color, f.source, f.speed, f.rated, f.analysis,
      f.date, f.customFrom, f.customTo, f.opening, f.search, f.sort,
    ].join('|'),
  )
  $effect(() => {
    filterSig // re-run on any filter/sort change
    renderLimit = PAGE
  })

  function onScroll() {
    if (!scrollEl || !loaded) return
    const { scrollTop, clientHeight, scrollHeight } = scrollEl
    if (scrollHeight - (scrollTop + clientHeight) < 800 && renderLimit < visible.length) {
      renderLimit = Math.min(renderLimit + PAGE, visible.length)
    }
  }

  // ── empty-state reasoning (only consulted when visible.length === 0) ────────
  // A source filter pointing at a platform with no connected account is a
  // dead-end the user can fix in Settings.
  const unconnectedSource = $derived.by<string | null>(() => {
    if (f.source === 'lichess' && !hasLichess) return 'Lichess'
    if (f.source === 'chesscom' && !hasChesscom) return 'Chess.com'
    return null
  })
  // "Unanalyzed" filter when literally nothing is pending.
  const allAnalyzed = $derived(
    f.analysis === 'unanalyzed' && games.length > 0 && games.every((g) => g.analyzed),
  )

  // ── data loading ───────────────────────────────────────────────────────────
  onMount(() => {
    void refresh().then(async () => {
      // Grow the window to cover a restored scroll offset before applying it,
      // otherwise the short initial page clamps scrollTop back to the top.
      if (f.scrollTop > 0) {
        renderLimit = Math.min(visible.length, Math.max(PAGE, Math.ceil((f.scrollTop + 800) / ROW_H)))
      }
      await tick()
      if (scrollEl) scrollEl.scrollTop = f.scrollTop
    })
    sidecar.on('sync_progress', onSyncProgress)
    sidecar.on('sync_done', onSyncDone)
    sidecar.on('sync_finished', onSyncFinished)
    sidecar.on('sync_cancelled', onSyncFinished)
    sidecar.on('sync_error', onSyncError)
    sidecar.on('sync_warning', onSyncWarning)
    void refreshSync()
  })
  onDestroy(() => {
    sidecar.off('sync_progress', onSyncProgress)
    sidecar.off('sync_done', onSyncDone)
    sidecar.off('sync_finished', onSyncFinished)
    sidecar.off('sync_cancelled', onSyncFinished)
    sidecar.off('sync_error', onSyncError)
    sidecar.off('sync_warning', onSyncWarning)
  })

  async function refresh() {
    try {
      games = (await api.listGames()).games
    } finally {
      loaded = true
    }
  }

  function open(g: GameSummary) {
    if (scrollEl) f.scrollTop = scrollEl.scrollTop
    onopen(g.id)
  }

  // ── sync ───────────────────────────────────────────────────────────────────
  let syncStatus = $state<SyncStatus | null>(null)
  let syncing = $state(false)
  let syncSource = $state<GameSource | null>(null)
  let syncProgress = $state<SyncProgressEvent | null>(null)
  let syncError = $state<string | null>(null)
  let syncWarnings = $state<SyncWarning[]>([])

  const hasLichess = $derived(accounts.lichess.length > 0)
  const hasChesscom = $derived(accounts.chesscom.length > 0)
  const hasAccount = $derived(hasLichess || hasChesscom)
  const pendingTotal = $derived(
    (syncStatus?.lichess.pending ?? 0) + (syncStatus?.chesscom.pending ?? 0),
  )
  const pendingLabel = $derived(
    syncStatus ? pendingButtonLabel(pendingSplit(syncStatus.lichess, syncStatus.chesscom)) : null,
  )

  // "Analyse more" (BETA-PUB Q4): a sync analyses the 100 most recent games of each account;
  // the rest wait here, newest first, in a step the user picks or all.
  let moreStepText = $state('100')
  const moreStep = $derived(analyseMoreStep(moreStepText, pendingTotal))

  async function refreshSync() {
    try {
      syncStatus = await api.syncStatus(analysisDepth.value)
      syncing = syncStatus.syncing
    } catch {
      /* sidecar may not be ready */
    }
  }

  async function syncNow(source: 'lichess' | 'chesscom') {
    if (syncing) return
    syncError = null
    syncWarnings = []
    syncSource = source
    syncing = true
    syncProgress = { phase: 'fetching', source, done: 0, total: 0 }
    try {
      await api.startSync(
        source === 'lichess' ? accounts.lichess : '',
        source === 'chesscom' ? accounts.chesscom : '',
        analysisDepth.value,
      )
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e)
      syncing = false
      syncSource = null
      syncProgress = null
    }
  }

  // Analyse already-synced games that still lack a run, with no re-fetch.
  // Reuses the sync event stream (sync_progress / sync_done / sync_finished).
  async function analyzePending(source?: 'lichess' | 'chesscom', count?: number) {
    if (syncing) return
    if (drawer === 'more') drawer = null
    syncError = null
    syncWarnings = []
    syncSource = source ?? null
    syncing = true
    syncProgress = { phase: 'analyzing', source, done: 0, total: 0 }
    try {
      await api.analyzePending(source, analysisDepth.value, count)
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e)
      syncing = false
      syncSource = null
      syncProgress = null
    }
  }

  function onSyncProgress(d: SyncProgressEvent) {
    syncProgress = d
    syncing = true
    if (d.source) syncSource = d.source
  }
  function onSyncDone(d: SyncDoneEvent) {
    if (d.source === 'lichess' || d.source === 'chesscom') markSynced(d.source)
    void refreshSync()
  }
  function onSyncFinished() {
    syncing = false
    syncSource = null
    syncProgress = null
    void refreshSync()
    void refresh()
  }
  function onSyncWarning(d: SyncWarningEvent) {
    syncWarnings = addSyncWarning(syncWarnings, d)
  }
  function onSyncError(d: SyncErrorEvent) {
    syncError = d.source ? `${SOURCE_LABEL[d.source]}: ${d.message}` : d.message
    void refreshSync()
  }

  // ── drawers (PGN import / position analysis) ───────────────────────────────
  function toggleDrawer(which: 'pgn' | 'fen' | 'more') {
    drawer = drawer === which ? null : which
    drawerError = ''
    importIssues = []
    importNote = ''
    importedFrom = ''
  }

  async function doImportFile() {
    const path = await pickPgn()
    if (path === null) return
    importedFrom = path.split('/').pop() ?? path
    await runImport((usernames) => api.importPgnFile(path, usernames))
  }

  const doImport = () => {
    importedFrom = ''
    return runImport((usernames) => api.importPgn(pgnText, usernames))
  }

  async function runImport(call: (usernames: string[]) => Promise<ImportResult>) {
    importing = true
    drawerError = ''
    importIssues = []
    importNote = ''
    try {
      const usernames = [accounts.lichess, accounts.chesscom].filter((u) => u.length > 0)
      const res = await call(usernames)
      pgnText = ''
      if (res.issues.length > 0) {
        // Stay put. Jumping straight to the board would bury the one moment the
        // user can still act on a truncated or skipped game.
        importIssues = res.issues
        importNote = importSummary(res.count, res.issues)
        await refresh()
        return
      }
      drawer = null
      onopen(res.gameId)
    } catch (e) {
      drawerError = e instanceof Error ? e.message : String(e)
    } finally {
      importing = false
    }
  }

  function doFen() {
    const fen = fenText.trim()
    if (!fen) return
    onfen(fen)
  }
</script>

<div class="games" bind:this={scrollEl} onscroll={onScroll}>
  <div class="inner">
    <header class="head">
      <p class="eyebrow">Library</p>
      <div class="head-row">
        <h1 class="title">Past Games</h1>
        {#if loaded && (record.win || record.loss || record.draw)}
          <div class="record" title="overall record">
            <span class="rec win"><b>{record.win}</b>W</span>
            <span class="rec loss"><b>{record.loss}</b>L</span>
            <span class="rec draw"><b>{record.draw}</b>D</span>
          </div>
        {/if}
      </div>
      <p class="lead">Browse, filter and review every game — analysis opens inline.</p>
    </header>

    <!-- search -->
    <div class="searchbar">
      <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
      </svg>
      <input
        type="text"
        bind:value={f.search}
        placeholder="Search opponent, opening, ECO, date or game id…"
        title="A chess.com or Lichess game id, or the app's id (#483), finds that game; Enter opens it."
        spellcheck="false"
        onkeydown={searchKey}
      />
      {#if f.search}
        <button class="search-clear" onclick={() => (f.search = '')} aria-label="Clear search">×</button>
      {/if}
    </div>

    <!-- filter bar -->
    <div class="filterbar">
      <div class="chips">
        <div class="group" role="group" aria-label="Result">
          {#each [['all', 'All'], ['win', 'Win'], ['draw', 'Draw'], ['loss', 'Loss']] as [val, lbl] (val)}
            <button class="chip" class:on={f.result === val} onclick={() => (f.result = val as typeof f.result)}>{lbl}</button>
          {/each}
        </div>
        <div class="group" role="group" aria-label="Color">
          {#each [['all', 'All'], ['white', 'White'], ['black', 'Black']] as [val, lbl] (val)}
            <button class="chip" class:on={f.color === val} onclick={() => (f.color = val as typeof f.color)}>{lbl}</button>
          {/each}
        </div>
        <div class="group" role="group" aria-label="Source">
          {#each [['all', 'All'], ['local', 'Stockfish'], ['chesscom', 'Chess.com'], ['lichess', 'Lichess'], ['imported', 'Imported']] as [val, lbl] (val)}
            <button class="chip" class:on={f.source === val} onclick={() => (f.source = val as typeof f.source)}>{lbl}</button>
          {/each}
        </div>
      </div>

      <div class="bar-right">
        <button class="more" class:on={f.moreOpen} onclick={() => (f.moreOpen = !f.moreOpen)}>
          More filters
          <svg class="caret" class:flip={f.moreOpen} viewBox="0 0 24 24"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <label class="sort">
          <span>Sort</span>
          <select bind:value={f.sort}>
            {#each Object.entries(SORT_LABEL) as [val, lbl] (val)}
              <option value={val}>{lbl}</option>
            {/each}
          </select>
        </label>
      </div>
    </div>

    {#if f.moreOpen}
      <div class="more-panel">
        <div class="mf">
          <span class="mf-label">Time control</span>
          <div class="group">
            {#each [['all', 'All'], ['bullet', 'Bullet'], ['blitz', 'Blitz'], ['rapid', 'Rapid'], ['classical', 'Classical']] as [val, lbl] (val)}
              <button class="chip" class:on={f.speed === val} onclick={() => (f.speed = val as typeof f.speed)}>{lbl}</button>
            {/each}
          </div>
        </div>
        <div class="mf">
          <span class="mf-label">Rated</span>
          <div class="group">
            {#each [['all', 'All'], ['rated', 'Rated'], ['casual', 'Casual']] as [val, lbl] (val)}
              <button class="chip" class:on={f.rated === val} onclick={() => (f.rated = val as typeof f.rated)}>{lbl}</button>
            {/each}
          </div>
        </div>
        <div class="mf">
          <span class="mf-label">Opening</span>
          <input
            class="mf-text"
            type="text"
            bind:value={f.opening}
            placeholder="e.g. sicilian or B20"
            spellcheck="false"
          />
        </div>
        <div class="mf">
          <span class="mf-label">Date</span>
          <div class="group">
            {#each [['all', 'All time'], ['week', 'Last week'], ['month', 'Last month'], ['3months', 'Last 3 months'], ['custom', 'Custom']] as [val, lbl] (val)}
              <button class="chip" class:on={f.date === val} onclick={() => (f.date = val as typeof f.date)}>{lbl}</button>
            {/each}
          </div>
          {#if f.date === 'custom'}
            <div class="date-range">
              <input type="date" bind:value={f.customFrom} aria-label="From date" />
              <span class="dash">—</span>
              <input type="date" bind:value={f.customTo} aria-label="To date" />
            </div>
          {/if}
        </div>
        <div class="mf">
          <span class="mf-label">Analysis</span>
          <div class="group">
            {#each [['all', 'All'], ['analyzed', 'Analyzed'], ['unanalyzed', 'Unanalyzed']] as [val, lbl] (val)}
              <button class="chip" class:on={f.analysis === val} onclick={() => (f.analysis = val as typeof f.analysis)}>{lbl}</button>
            {/each}
          </div>
        </div>
      </div>
    {/if}

    <!-- sync status -->
    {#if hasAccount}
      <div class="sync-row">
        {#if hasLichess}
          {@render syncCell('lichess', 'Lichess', syncStatus?.lichess.synced ?? 0, lastSynced.lichess)}
        {/if}
        {#if hasChesscom}
          {@render syncCell('chesscom', 'Chess.com', syncStatus?.chesscom.synced ?? 0, lastSynced.chesscom)}
        {/if}
        {#if syncError}<span class="sync-err">{syncError}</span>{/if}
        {#each syncWarningLines(syncWarnings, (s) => SOURCE_LABEL[s as GameSource] ?? '') as line, i (i)}
          <span class="sync-warn">{line}</span>
        {/each}
      </div>
    {/if}

    <!-- toolbar: count + actions -->
    <div class="toolbar">
      {#if loaded}
        <span class="count">
          {visible.length}
          {#if active && visible.length !== games.length}of {games.length}{/if}
          {visible.length === 1 ? 'game' : 'games'}
        </span>
      {/if}
      {#if active}
        <button class="clear-link" onclick={clearFilters}>Clear filters</button>
      {/if}
      <div class="actions">
        {#if pendingTotal > 0}
          <!-- Secondary, not primary (owner ruling, W15): one click can queue hours of
               re-analysis, and a primary button invites the click regardless of label. -->
          <button
            class="btn btn-quiet"
            class:open={drawer === 'more'}
            disabled={syncing}
            onclick={() => toggleDrawer('more')}
            title="Games with no analysis, and games analysed below the depth selected in Settings, which are re-analysed at that depth."
          >
            {syncing && syncProgress?.phase === 'analyzing'
              ? `Analysing ${syncProgress.done}/${syncProgress.total}…`
              : 'Analyse more…'}
          </button>
        {/if}
        <button class="btn btn-quiet" class:open={drawer === 'fen'} onclick={() => toggleDrawer('fen')}>
          Analyse a position
        </button>
        <button class="btn btn-quiet" class:open={drawer === 'pgn'} onclick={() => toggleDrawer('pgn')}>
          Import PGN
        </button>
      </div>
    </div>

    {#if drawer === 'pgn'}
      <div class="drawer">
        <textarea bind:value={pgnText} rows="5" placeholder="Paste a PGN…" spellcheck="false"></textarea>
        <div class="drawer-row">
          <button class="btn btn-accent" onclick={doImport} disabled={importing || !pgnText.trim()}>
            {importing ? 'Importing…' : 'Import'}
          </button>
          <button class="btn btn-quiet" onclick={doImportFile} disabled={importing}>
            Choose file…
          </button>
          {#if importedFrom}<span class="drawer-note">From {importedFrom}</span>{/if}
          {#if drawerError}<span class="drawer-error">{drawerError}</span>{/if}
          {#if importNote}<span class="drawer-note">{importNote}</span>{/if}
        </div>
        {#if importIssues.length > 0}
          <ul class="issues">
            {#each importIssues as issue (issue.index)}
              <li class:kept={issue.imported}>
                <span class="issue-where">Game {issue.index} — {issue.label}</span>
                <span class="issue-why">
                  {issue.imported ? 'stored incomplete' : 'skipped'}: {issue.reason}
                </span>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {:else if drawer === 'more'}
      <div class="drawer">
        <span class="drawer-note">
          {pendingLabel} — newest first. A sync analyses your 100 most recent games on its own;
          older ones wait until you ask.
        </span>
        <div class="drawer-row">
          <label class="drawer-note" for="more-step">Analyse the next</label>
          <input
            id="more-step"
            class="step"
            type="number"
            min="1"
            max={pendingTotal}
            bind:value={moreStepText}
          />
          <span class="drawer-note">games</span>
          <button
            class="btn btn-accent"
            disabled={syncing || moreStep == null}
            onclick={() => moreStep != null && analyzePending(undefined, moreStep)}
          >
            {analyseMoreLabel(moreStep, pendingTotal)}
          </button>
          <button class="btn btn-quiet" disabled={syncing} onclick={() => analyzePending()}>
            All {pendingTotal.toLocaleString('en-US')}
          </button>
        </div>
      </div>
    {:else if drawer === 'fen'}
      <div class="drawer">
        <div class="drawer-row">
          <input
            type="text"
            bind:value={fenText}
            placeholder="Paste a FEN to analyse any position…"
            spellcheck="false"
            onkeydown={(e) => e.key === 'Enter' && doFen()}
          />
          <button class="btn btn-accent" onclick={doFen} disabled={!fenText.trim()}>Analyse</button>
        </div>
      </div>
    {/if}

    <!-- list -->
    {#if !loaded}
      <div class="table skeletons" aria-hidden="true">
        <div class="list">
          {#each Array(6) as _, i (i)}
            <div class="row skel-row">
              <span class="skel sk-result"></span>
              <span class="skel sk-game"></span>
              <span class="skel-main">
                <span class="skel sk-primary"></span>
                <span class="skel sk-meta"></span>
              </span>
              <span class="skel sk-acc"></span>
              <span class="skel sk-moves"></span>
              <span class="skel sk-date"></span>
              <span></span>
            </div>
          {/each}
        </div>
      </div>
    {:else if games.length === 0}
      <div class="empty">
        <p class="empty-title">No games yet</p>
        <p class="empty-sub">
          Connect your Chess.com or Lichess account to import your games, or play
          a game to get started.
        </p>
        <div class="empty-actions">
          <button class="btn btn-accent" onclick={() => onnav('settings')}>Connect an account</button>
          <button class="btn btn-quiet" onclick={() => onnav('play')}>Play a game</button>
        </div>
      </div>
    {:else if visible.length === 0 && unconnectedSource}
      <div class="empty">
        <p class="empty-title">No {unconnectedSource} games</p>
        <p class="empty-sub">
          Connect your {unconnectedSource} account in Settings to see these games.
        </p>
        <div class="empty-actions">
          <button class="btn btn-accent" onclick={() => onnav('settings')}>Open Settings</button>
          <button class="btn btn-quiet" onclick={clearFilters}>Clear filters</button>
        </div>
      </div>
    {:else if visible.length === 0 && allAnalyzed}
      <div class="empty">
        <p class="empty-title">All your games have been analyzed</p>
        <p class="empty-sub">There are no games pending analysis.</p>
        <button class="btn btn-quiet" onclick={clearFilters}>Clear filters</button>
      </div>
    {:else if visible.length === 0}
      <div class="empty">
        <p class="empty-title">No games match these filters</p>
        <button class="btn btn-accent" onclick={clearFilters}>Clear filters</button>
      </div>
    {:else}
      <div class="table">
        <div class="thead" aria-hidden="true">
          <span></span>
          <span>Game</span>
          <span>Opening</span>
          <span class="c">Accuracy</span>
          <span class="c">Moves</span>
          <span class="r">Date</span>
          <span></span>
        </div>
        <div class="list">
          {#each shown as g (g.id)}
            {@const you = playerAccuracy(g)}
            {@const opp = oppAccuracy(g)}
            <button class="row" onclick={() => open(g)} aria-label="Review game vs {opponentName(g)}">
              <span class="result">{@render resultIcon(resultClass(g))}</span>
              <span class="game">
                {@render gameIcon(gameKind(g))}
                <span class="game-label">{gameLabel(g)}</span>
                {#if g.rated === false}<span class="casual" title="Casual (unrated) game">Casual</span>{/if}
              </span>
              <span class="main">
                <span class="primary">
                  <span class="opening">{g.openingName ?? 'Unknown opening'}</span>
                  {#if g.openingEco}<span class="eco">{g.openingEco}</span>{/if}
                </span>
                <span class="players">
                  <span class="prow">
                    <span class="cdot {mySide(g)}"
                      title={g.playerColor === null ? 'White — your side is unknown' : `you played ${g.playerColor}`}></span>
                    <span class="pname">{playerName(g)}</span>
                    {#if playerElo(g) != null}<span class="pelo">{playerElo(g)}</span>{/if}
                  </span>
                  <span class="prow">
                    <span class="cdot {oppColor(g)}"
                      title={g.playerColor === null ? 'Black' : `opponent played ${oppColor(g)}`}></span>
                    <span class="pname">{opponentName(g)}</span>
                    {#if opponentElo(g) != null}<span class="pelo">{opponentElo(g)}</span>{/if}
                  </span>
                </span>
              </span>
              <span class="acc">
                {#if g.analyzed}
                  <span class="acc-you {accClass(you)}">{you?.toFixed(1) ?? '–'}</span>
                  <span class="acc-opp">{opp?.toFixed(1) ?? '–'}</span>
                {:else}
                  <span class="analyse" title="not analyzed yet — opens analysis">Analyse</span>
                {/if}
              </span>
              <span class="moves">{g.moveCount}</span>
              <span class="date">{fmtDate(g.playedAt)}</span>
              <span class="chev" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
              </span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>

{#snippet syncCell(source: 'lichess' | 'chesscom', label: string, count: number, last: string | null)}
  {@const pending = source === 'lichess' ? (syncStatus?.lichess.pending ?? 0) : (syncStatus?.chesscom.pending ?? 0)}
  <div class="sync-cell">
    <span class="sync-label">{label}</span>
    <span class="sync-count">{count} {count === 1 ? 'game' : 'games'}</span>
    {#if syncing && syncSource === source}
      <span class="sync-meta">
        {#if syncProgress?.phase === 'analyzing'}
          analyzing {syncProgress.done}/{syncProgress.total}
        {:else}
          fetching…
        {/if}
      </span>
    {:else}
      <span class="sync-meta">{relativeTime(last) ? `synced ${relativeTime(last)}` : 'never synced'}</span>
      <button class="sync-now" disabled={syncing} onclick={() => syncNow(source)}>Sync now</button>
      {#if pending > 0}
        <button class="sync-now analyze" disabled={syncing} onclick={() => analyzePending(source)}>
          Analyse {pending} pending
        </button>
      {/if}
    {/if}
  </div>
{/snippet}

<!-- Result glyph — Chess.com's square-fill family, knocked out with evenodd so the
     row background shows through the +/−/= mark. -->
{#snippet resultIcon(kind: 'win' | 'loss' | 'draw' | 'other')}
  <svg class="ricon {kind}" viewBox="0 0 24 24" aria-hidden="true">
    {#if kind === 'win'}
      <path
        fill-rule="evenodd"
        d="M17.03,22 l-10.07,0 c-3.67,0,-4.97,-1.3,-4.97,-4.97 l0,-10.07 c0,-3.67,1.3,-4.97,4.97,-4.97 l10.07,0 c3.67,0,4.97,1.3,4.97,4.97 l0,10.07 c0,3.67,-1.3,4.97,-4.97,4.97 Z M10.5,17.53 c0,1.07,0.4,1.47,1.43,1.47 l0.1,0 c1.07,0,1.47,-0.4,1.47,-1.43 l0,-4.07 l4.07,0 c1.03,0,1.43,-0.4,1.43,-1.47 l0,-0.1 c0,-1.03,-0.4,-1.43,-1.47,-1.43 l-4.03,0 l0,-4.03 c0,-1.07,-0.4,-1.47,-1.43,-1.47 l-0.1,0 c-1.07,0,-1.47,0.4,-1.47,1.43 l0,4.07 l-4.07,0 c-1.03,0,-1.43,0.4,-1.43,1.47 l0,0.1 c0,1.03,0.4,1.43,1.47,1.43 l4.03,0 Z"
      />
    {:else if kind === 'loss'}
      <path
        fill-rule="evenodd"
        d="M17.03,22 l-10.07,0 c-3.67,0,-4.97,-1.3,-4.97,-4.97 l0,-10.07 c0,-3.67,1.3,-4.97,4.97,-4.97 l10.07,0 c3.67,0,4.97,1.3,4.97,4.97 l0,10.07 c0,3.67,-1.3,4.97,-4.97,4.97 Z M5,11.97 l0,0.1 c0,1.03,0.4,1.43,1.47,1.43 l11.1,0 c1.03,0,1.43,-0.4,1.43,-1.47 l0,-0.1 c0,-1.03,-0.4,-1.43,-1.47,-1.43 l-11.1,0 c-1.03,0,-1.43,0.4,-1.43,1.47 Z"
      />
    {:else if kind === 'draw'}
      <path
        fill-rule="evenodd"
        d="M17.03,22 l-10.07,0 c-3.67,0,-4.97,-1.3,-4.97,-4.97 l0,-10.07 c0,-3.67,1.3,-4.97,4.97,-4.97 l10.07,0 c3.67,0,4.97,1.3,4.97,4.97 l0,10.07 c0,3.67,-1.3,4.97,-4.97,4.97 Z M5,8.15 l0,0.1 c0,1.03,0.4,1.43,1.47,1.43 l11.1,0 c1.03,0,1.43,-0.4,1.43,-1.47 l0,-0.1 c0,-1.03,-0.4,-1.43,-1.47,-1.43 l-11.1,0 c-1.03,0,-1.43,0.4,-1.43,1.47 Z M5,12.95 l0,0.1 c0,1.03,0.4,1.43,1.47,1.43 l11.1,0 c1.03,0,1.43,-0.4,1.43,-1.47 l0,-0.1 c0,-1.03,-0.4,-1.43,-1.47,-1.43 l-11.1,0 c-1.03,0,-1.43,0.4,-1.43,1.47 Z"
      />
    {:else}
      <path
        d="M17.03,22 l-10.07,0 c-3.67,0,-4.97,-1.3,-4.97,-4.97 l0,-10.07 c0,-3.67,1.3,-4.97,4.97,-4.97 l10.07,0 c3.67,0,4.97,1.3,4.97,4.97 l0,10.07 c0,3.67,-1.3,4.97,-4.97,4.97 Z"
      />
    {/if}
  </svg>
{/snippet}

<!-- Game-type glyph: speed bucket for platform games, a CPU mark for Stockfish. -->
{#snippet gameIcon(kind: GameKind)}
  {#if kind === 'blitz'}
    <svg class="gicon fill" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13 2 5 13h5l-1 9 8-12h-5z" />
    </svg>
  {:else if kind === 'bullet'}
    <svg class="gicon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <circle class="dot" cx="12" cy="12" r="3" />
    </svg>
  {:else if kind === 'rapid' || kind === 'classical'}
    <svg class="gicon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7.5v4.5l3 2" />
    </svg>
  {:else if kind === 'engine'}
    <svg class="gicon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="7.5" y="7.5" width="9" height="9" rx="1.6" />
      <path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3" />
    </svg>
  {:else}
    <svg class="gicon" viewBox="0 0 24 24" aria-hidden="true">
      <circle class="dot" cx="12" cy="12" r="3" />
    </svg>
  {/if}
{/snippet}

<style>
  .games {
    height: 100%;
    overflow-y: auto;
    position: relative;
  }
  .games::before {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(120% 80% at 12% -10%, var(--accent-soft) 0%, transparent 55%);
  }
  .inner {
    position: relative;
    max-width: 900px;
    margin: 0 auto;
    padding: 48px 32px 48px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* ── header ── */
  .head {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .eyebrow {
    margin: 0;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .head-row {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }
  .title {
    margin: 0;
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }
  .record {
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }
  .rec {
    display: inline-flex;
    align-items: baseline;
    gap: 3px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 4px 8px;
    font-variant-numeric: tabular-nums;
  }
  .rec b {
    font-size: 15px;
    font-weight: 700;
  }
  .rec.win b {
    color: var(--win);
  }
  .rec.loss b {
    color: var(--danger);
  }
  .rec.draw b {
    color: var(--text);
  }
  .lead {
    margin: 2px 0 0;
    font-size: 13.5px;
    color: var(--text-muted);
  }

  /* ── search ── */
  .searchbar {
    position: relative;
    display: flex;
    align-items: center;
  }
  .search-icon {
    position: absolute;
    left: 12px;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-muted);
    stroke-width: 2;
    stroke-linecap: round;
    pointer-events: none;
  }
  .searchbar input {
    width: 100%;
    padding: 10px 34px;
    font-size: 13.5px;
    user-select: text;
  }
  .search-clear {
    position: absolute;
    right: 8px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    color: var(--text-muted);
    font-size: 16px;
    line-height: 1;
  }
  .search-clear:hover {
    color: var(--text);
    background: var(--bg-raised);
  }

  /* ── filter bar ── */
  .filterbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .chips {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }
  .group {
    display: inline-flex;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 2px;
    gap: 2px;
  }
  .chip {
    padding: 5px 11px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--text-muted);
    border-radius: calc(var(--radius-sm) - 2px);
    white-space: nowrap;
    transition: color 100ms ease, background-color 100ms ease;
  }
  .chip:hover {
    color: var(--text);
  }
  .chip.on {
    color: var(--accent-ink, #fff);
    background: var(--accent);
  }
  .bar-right {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-left: auto;
  }
  .more {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 11px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--text-muted);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    transition: color 100ms ease, border-color 100ms ease;
  }
  .more:hover,
  .more.on {
    color: var(--text);
    border-color: var(--text-muted);
  }
  .caret {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 140ms ease;
  }
  .caret.flip {
    transform: rotate(180deg);
  }
  .sort {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .sort select {
    padding: 6px 8px;
    font-size: 12.5px;
    color: var(--text);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }

  /* ── more-filters panel ── */
  .more-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px 16px;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    box-shadow: var(--shadow-tile);
    animation: rise 200ms cubic-bezier(0.2, 0.7, 0.2, 1) backwards;
  }
  .mf {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .mf-label {
    width: 92px;
    flex-shrink: 0;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .mf-text {
    flex: 1;
    min-width: 200px;
    padding: 7px 11px;
    font-size: 13px;
    user-select: text;
  }
  .date-range {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .date-range input {
    padding: 6px 9px;
    font-size: 12.5px;
    color: var(--text);
    background: var(--bg-raised);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    user-select: text;
  }
  .dash {
    color: var(--text-muted);
  }

  /* ── sync row ── */
  .sync-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .sync-cell {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    font-size: 12.5px;
  }
  .sync-label {
    font-weight: 600;
    color: var(--text);
  }
  .sync-count {
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .sync-meta {
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .sync-meta::before {
    content: '· ';
  }
  .sync-now {
    margin-left: 2px;
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
  }
  .sync-now:hover {
    text-decoration: underline;
  }
  .sync-now:disabled {
    color: var(--text-muted);
    cursor: default;
    text-decoration: none;
  }
  .sync-now.analyze::before {
    content: '· ';
    color: var(--text-muted);
  }
  .sync-err {
    font-size: 12px;
    color: var(--danger);
  }
  .sync-warn {
    font-size: 12px;
    color: var(--text-muted);
  }

  /* ── toolbar ── */
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 2px;
  }
  .count {
    font-size: 12.5px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .clear-link {
    font-size: 12.5px;
    color: var(--accent);
  }
  .clear-link:hover {
    text-decoration: underline;
  }
  .actions {
    margin-left: auto;
    display: flex;
    gap: 8px;
  }
  .actions .btn.open {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }

  /* ── drawers ── */
  .drawer {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    box-shadow: var(--shadow-tile);
    animation: rise 240ms cubic-bezier(0.2, 0.7, 0.2, 1) backwards;
  }
  textarea {
    resize: vertical;
    background: var(--bg-raised);
    color: var(--text);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 8px 10px;
    font-family: var(--font-ui);
    font-size: 12.5px;
    user-select: text;
  }
  .drawer-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .drawer-row input {
    flex: 1;
    user-select: text;
  }
  .drawer-row input.step {
    flex: 0 0 88px;
  }
  .drawer-error {
    font-size: 12.5px;
    color: var(--danger);
  }
  .drawer-note {
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .issues {
    margin: 10px 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 180px;
    overflow-y: auto;
  }
  .issues li {
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-size: 12px;
    border-left: 2px solid var(--danger);
    padding-left: 8px;
  }
  /* A game that was stored, just not whole — a weaker warning than one that was
     dropped entirely, and the border is the only thing saying so. */
  .issues li.kept {
    border-left-color: var(--accent);
  }
  .issue-where {
    color: var(--text);
  }
  .issue-why {
    color: var(--text-muted);
  }

  /* ── states ── */
  .empty {
    margin-top: 48px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    text-align: center;
  }
  .empty-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }
  .empty-sub {
    margin: 4px 0 0;
    max-width: 380px;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.5;
  }
  .empty-actions {
    display: flex;
    gap: 8px;
    margin-top: 4px;
  }

  /* ── loading skeletons ── */
  .skeletons {
    pointer-events: none;
  }
  .skel-row {
    cursor: default;
  }
  .skel {
    display: block;
    border-radius: var(--radius-sm);
    background: linear-gradient(
      90deg,
      var(--bg-raised) 0%,
      color-mix(in srgb, var(--bg-raised) 40%, var(--divider)) 50%,
      var(--bg-raised) 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.3s ease-in-out infinite;
  }
  .sk-result {
    width: 17px;
    height: 17px;
  }
  .sk-game {
    width: 64px;
    height: 12px;
  }
  .skel-main {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sk-primary {
    width: 58%;
    height: 12px;
  }
  .sk-meta {
    width: 78%;
    height: 10px;
  }
  .sk-acc {
    width: 34px;
    height: 16px;
    justify-self: center;
  }
  .sk-moves {
    width: 22px;
    height: 11px;
    justify-self: center;
  }
  .sk-date {
    width: 46px;
    height: 11px;
    justify-self: end;
  }
  @keyframes shimmer {
    from {
      background-position: 200% 0;
    }
    to {
      background-position: -200% 0;
    }
  }

  /* ── table ── */
  .table {
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    overflow: hidden;
  }
  .thead,
  .row {
    display: grid;
    grid-template-columns: 26px 104px minmax(0, 1fr) 64px 46px 64px 14px;
    align-items: center;
    gap: 12px;
  }
  .thead {
    padding: 9px 16px;
    border-bottom: 1px solid var(--divider);
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .thead .c {
    text-align: center;
  }
  .thead .r {
    text-align: right;
  }

  .list {
    display: flex;
    flex-direction: column;
  }
  .row {
    width: 100%;
    padding: 10px 16px;
    border-bottom: 1px solid var(--divider);
    text-align: left;
    transition: background-color 120ms ease;
  }
  .row:last-child {
    border-bottom: none;
  }
  .row:hover {
    background: var(--bg-raised);
  }

  /* result icon */
  .result {
    display: grid;
    place-items: center;
  }
  .ricon {
    width: 17px;
    height: 17px;
  }
  .ricon.win {
    fill: var(--win);
  }
  .ricon.loss {
    fill: var(--danger);
  }
  .ricon.draw {
    fill: var(--text-muted);
  }
  .ricon.other {
    fill: var(--text-muted);
    opacity: 0.4;
  }

  /* game type */
  .game {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    color: var(--text-muted);
    transition: color 120ms ease;
  }
  .row:hover .game {
    color: var(--text);
  }
  .gicon {
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .gicon.fill {
    fill: currentColor;
    stroke: none;
  }
  .gicon .dot {
    fill: currentColor;
    stroke: none;
  }
  .game-label {
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-variant-numeric: tabular-nums;
  }
  .casual {
    flex-shrink: 0;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    background: var(--bg-raised);
    border: 1px solid var(--divider);
    border-radius: 4px;
    padding: 0 4px;
  }

  /* main column */
  .main {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .primary {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
  }
  .cdot {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    border: 1px solid var(--text-muted);
  }
  .cdot.white {
    background: var(--side-white);
  }
  .cdot.black {
    background: var(--side-black);
  }
  .opening {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .eco {
    flex-shrink: 0;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
    background: var(--bg-raised);
    border: 1px solid var(--divider);
    border-radius: 4px;
    padding: 0 4px;
  }
  .players {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .prow {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .pname {
    font-size: 11.5px;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .prow:first-child .pname {
    color: var(--text);
    font-weight: 500;
  }
  .pelo {
    flex-shrink: 0;
    font-size: 11px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  /* accuracy */
  .acc {
    display: flex;
    flex-direction: column;
    align-items: center;
    line-height: 1.15;
  }
  .acc-you {
    font-size: 14px;
    font-weight: 700;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .acc-you.good {
    color: color-mix(in srgb, var(--win) 64%, var(--text));
  }
  .acc-you.bad {
    color: color-mix(in srgb, var(--danger) 64%, var(--text));
  }
  .acc-opp {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .analyse {
    font-size: 11px;
    font-weight: 600;
    color: var(--accent);
    border: 1px solid var(--accent-line);
    border-radius: var(--radius-sm);
    padding: 3px 9px;
    white-space: nowrap;
    transition: background-color 100ms ease;
  }
  .row:hover .analyse {
    background: var(--accent-soft);
  }

  /* moves / date */
  .moves {
    text-align: center;
    font-size: 12.5px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .date {
    text-align: right;
    font-size: 12px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  /* chevron */
  .chev {
    display: grid;
    place-items: center;
    color: var(--text-muted);
    opacity: 0.35;
    transition: opacity 120ms ease, transform 120ms ease, color 120ms ease;
  }
  .chev svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .row:hover .chev {
    opacity: 1;
    color: var(--accent);
    transform: translateX(2px);
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(12px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .more-panel,
    .drawer {
      animation: none;
    }
    .skel {
      animation: none;
    }
    .row:hover .chev {
      transform: none;
    }
  }
</style>
