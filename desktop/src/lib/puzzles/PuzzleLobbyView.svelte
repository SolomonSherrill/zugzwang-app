<script lang="ts">
  /**
   * The Puzzles lobby (UI-BUILD-2 E2; DESIGN.md "Puzzles", ruling 19): the stats row (rating
   * with its trend and a new-peak line only on the day, solved with the share of tries, Rush
   * bests, Survival best), the Rated, Rush and Survival cards, recent sessions. Figures come
   * from puzzle_status and puzzle_summary; a figure with no data is not drawn.
   *
   * The puzzle database (FIX-B6 B, ruling PZ1): "Download puzzles from Lichess" when there are none;
   * afterwards a line with the copy's date and count and "Check for new puzzles"; "Import a file"
   * for offline use. A download or an update shows its progress in MB with Cancel; the previous
   * set stays usable until the new one is in, so an update runs beside the lobby.
   */
  import { onDestroy, onMount } from 'svelte'
  import Button from '../ui/Button.svelte'
  import Chip from '../ui/Chip.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import SegmentedControl from '../ui/SegmentedControl.svelte'
  import {
    api,
    sidecar,
    PUZZLE_RATING_RANGES,
    PUZZLE_RATING_RANGE_DEFAULT,
    PUZZLE_RUSH_TIMES,
    type PuzzleMode,
    type PuzzleStatus,
    type PuzzleSummary,
    type PuzzleUpdateInfo,
  } from '../api'
  import { pickPuzzleCsv } from '../pick'
  import { registerCommands } from '../shell/commands.svelte'
  import { dayWord, sparkline } from '../home/homeModel'
  import {
    RATED_THEMES, RATED_THEMES_SHOWN, ratingSubLine, rushBest, sessionModeLabel, sessionRatingText,
    sessionSolvedText, shareOfTries, themeLabel,
    copyLine, doneLine, progressLine, progressShare, updateLine, type ImportDone, type ImportProgress,
  } from './puzzlesModel'

  interface Props {
    onstart: (config: PuzzleMode) => void
  }
  let { onstart }: Props = $props()

  let status = $state<PuzzleStatus | null>(null)
  let summary = $state<PuzzleSummary | null>(null)
  let error = $state<string | null>(null)
  let importing = $state(false)
  let importProgress = $state<ImportProgress | null>(null)
  let finishing = $state(false)
  let importError = $state('')
  /** what to retry after a failure: the download, or the file picked */
  let lastImport = $state<{ kind: 'lichess' } | { kind: 'file'; path: string } | null>(null)
  let importDone = $state<ImportDone | null>(null)
  let checking = $state(false)
  let update = $state<PuzzleUpdateInfo | null>(null)
  let checkError = $state('')

  let range = $state(String(PUZZLE_RATING_RANGES[PUZZLE_RATING_RANGE_DEFAULT]))
  let rush = $state(String(PUZZLE_RUSH_TIMES[0][0]))
  let themes = $state<string[]>([])
  let allThemes = $state(false)
  let noThemePuzzles = $state(false)
  let starting = $state(false)

  async function refresh() {
    error = null
    try {
      status = await api.puzzleStatus()
      importing = status.importing
      summary = status.imported ? await api.puzzleSummary() : null
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  function begin(kind: 'lichess' | 'file') {
    importError = ''
    importDone = null
    update = null
    finishing = false
    // Set before the call: the first progress event comes after the first batch.
    importing = true
    importProgress = { kind, bytes: 0, totalBytes: null, imported: 0 }
  }
  async function run(start: () => Promise<unknown>) {
    try {
      await start()
    } catch (e) {
      importError = e instanceof Error ? e.message : String(e)
      importing = false
      importProgress = null
    }
  }
  async function startDownload() {
    lastImport = { kind: 'lichess' }
    begin('lichess')
    await run(() => api.downloadPuzzles())
  }
  async function startImport(csvPath: string) {
    lastImport = { kind: 'file', path: csvPath }
    begin('file')
    await run(() => api.importPuzzles(csvPath))
  }
  async function chooseFile() {
    const path = await pickPuzzleCsv()
    if (path === null) return
    await startImport(path)
  }
  function retry() {
    if (lastImport?.kind === 'file') void startImport(lastImport.path)
    else void startDownload()
  }
  async function checkForNew() {
    checking = true
    checkError = ''
    update = null
    try {
      update = await api.puzzleCheckUpdate()
    } catch (e) {
      checkError = e instanceof Error ? e.message : String(e)
    } finally {
      checking = false
    }
  }

  function toggleTheme(tag: string) {
    themes = themes.includes(tag) ? themes.filter((t) => t !== tag) : [...themes, tag]
    noThemePuzzles = false
  }
  async function startRated() {
    if (starting) return
    const ratingRange = Number(range)
    if (themes.length) {
      starting = true
      try {
        const res = await api.countThemePuzzles(themes, ratingRange)
        if (res.count === 0) {
          noThemePuzzles = true
          return
        }
      } finally {
        starting = false
      }
      onstart({ mode: 'theme', themes: [...themes], rushSeconds: 180, ratingRange })
    } else {
      onstart({ mode: 'rated', themes: [], rushSeconds: 180, ratingRange })
    }
  }
  const startRush = (secs = Number(rush)) => onstart({ mode: 'rush', themes: [], rushSeconds: secs, ratingRange: 100 })
  const startSurvival = () => onstart({ mode: 'survival', themes: [], rushSeconds: 180, ratingRange: 50 })

  const ready = $derived(!!status && status.imported && !!summary)
  const sub = $derived(summary ? ratingSubLine(summary) : null)
  const series = $derived((summary?.rating?.series ?? []).map((p) => p.rating))
  const spark = $derived(sparkline(series, 194, 36))
  const rush3 = $derived(summary ? rushBest(summary, 180) : null)
  const rush5 = $derived(summary ? rushBest(summary, 300) : null)
  const rushSel = $derived(summary ? rushBest(summary, Number(rush)) : null)
  const cells = $derived(
    1 + (summary && summary.tries > 0 ? 1 : 0) + (rush3 !== null || rush5 !== null ? 1 : 0) + (summary?.survivalBest != null ? 1 : 0),
  )
  const shownThemes = $derived(
    allThemes ? RATED_THEMES : [...RATED_THEMES.slice(0, RATED_THEMES_SHOWN), ...themes.filter((t) => !RATED_THEMES.slice(0, RATED_THEMES_SHOWN).includes(t))],
  )
  const hiddenCount = $derived(RATED_THEMES.length - shownThemes.length)
  const anyInferred = $derived(!!summary?.sessions.some((s) => s.inferred))
  const share = $derived(finishing ? null : progressShare(importProgress))
  const fmt = (n: number) => n.toLocaleString('en-US')

  const onProgress = (d: Record<string, unknown>) => {
    importing = true
    importProgress = d as unknown as ImportProgress
  }
  const onFinishing = () => {
    finishing = true
  }
  const onDone = (d: Record<string, unknown>) => {
    importing = false
    finishing = false
    importProgress = null
    importDone = d as unknown as ImportDone
    void refresh()
  }
  const onCancelled = () => {
    importing = false
    finishing = false
    importProgress = null
    void refresh()
  }
  const onError = (d: Record<string, unknown>) => {
    importError = String(d.message)
    importing = false
    finishing = false
    importProgress = null
  }

  function onKey(e: KeyboardEvent) {
    if (!ready || e.defaultPrevented || e.key !== 'Enter' || e.metaKey || e.ctrlKey || e.altKey) return
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'BUTTON' || t.closest('[role="dialog"]'))) return
    e.preventDefault()
    void startRated()
  }

  let off: (() => void) | null = null
  onMount(() => {
    sidecar.on('puzzle_import_progress', onProgress)
    sidecar.on('puzzle_import_finishing', onFinishing)
    sidecar.on('puzzle_import_done', onDone)
    sidecar.on('puzzle_import_cancelled', onCancelled)
    sidecar.on('puzzle_import_error', onError)
    void refresh()
    off = registerCommands('puzzles', () =>
      ready
        ? [
            { id: 'pz-rated', group: 'Actions', label: 'Start rated puzzles', kbd: '↵', run: () => void startRated() },
            ...PUZZLE_RUSH_TIMES.map(([s, l]) => ({ id: `pz-rush-${s}`, group: 'Actions', label: `Start a ${l} rush`, run: () => startRush(s) })),
            { id: 'pz-survival', group: 'Actions', label: 'Start survival', run: startSurvival },
          ]
        : [],
    )
  })
  onDestroy(() => {
    sidecar.off('puzzle_import_progress', onProgress)
    sidecar.off('puzzle_import_finishing', onFinishing)
    sidecar.off('puzzle_import_done', onDone)
    sidecar.off('puzzle_import_cancelled', onCancelled)
    sidecar.off('puzzle_import_error', onError)
    off?.()
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="page">
  <header>
    <h1>Puzzles</h1>
    <span class="hint">From the Lichess puzzle database</span>
  </header>

  <main>
    {#if error}
      <EmptyState tone="error" sentence="Puzzles could not load." sub={error} action={{ label: 'Try again', run: refresh }} />
    {:else if !status}
      <EmptyState sentence="Opening the puzzle database…" />
    {:else if !status.imported && importing}
      <EmptyState
        sentence={progressLine(importProgress, finishing)}
        sub="You can use the rest of the app while it runs."
        progress={share}
        action={finishing ? null : { label: 'Cancel', run: () => void api.cancelPuzzleImport() }}
      />
    {:else if !status.imported}
      {#if importError}
        <EmptyState
          tone="error"
          sentence={lastImport?.kind === 'file' ? 'The puzzle import stopped. No puzzles were added.' : 'The download stopped. No puzzles were added.'}
          sub={importError}
          action={{ label: 'Try again', run: retry, primary: true }}
          secondary={{ label: 'Import a file…', run: () => void chooseFile() }}
        />
      {:else}
        <EmptyState
          sentence="No puzzles yet."
          sub="Zugzwang downloads Lichess's puzzle database (free, CC0) and imports it as it arrives. Without a connection, import the file (lichess_db_puzzle.csv.zst or the .csv) instead."
          action={{ label: 'Download puzzles from Lichess', run: () => void startDownload(), primary: true }}
          secondary={{ label: 'Import a file…', run: () => void chooseFile() }}
        />
      {/if}
    {:else if !summary}
      <EmptyState sentence="Opening the puzzle database…" />
    {:else}
      <dl class="stats" style:grid-template-columns="minmax(0, 1.6fr) repeat({cells - 1}, minmax(0, 1fr))">
        <div class="cell rating">
          <div>
            <dt>Puzzle rating</dt>
            <dd class="metric">{summary.rating?.rating ?? Math.round(status.rating)}</dd>
            {#if sub}<dd class="sub" class:win={sub.tone === 'win'} class:loss={sub.tone === 'loss'}>{sub.text}</dd>{/if}
          </div>
          {#if spark}
            {@const last = spark.split(' ').at(-1)!.split(',')}
            <svg width="200" height="40" viewBox="-3 -2 200 40" aria-hidden="true">
              <polyline points={spark} fill="none" stroke="var(--chart-opponent)" stroke-width="1.5" stroke-linejoin="round" />
              <circle cx={last[0]} cy={last[1]} r="3" fill={summary.rating?.newPeak ? 'var(--win)' : 'var(--text)'} />
            </svg>
          {/if}
        </div>
        {#if summary.tries > 0}
          <div class="cell">
            <dt>Solved</dt>
            <dd class="metric">{fmt(summary.solved)}</dd>
            <dd class="sub">{shareOfTries(summary.solved, summary.tries)}</dd>
          </div>
        {/if}
        {#if rush3 !== null || rush5 !== null}
          <div class="cell">
            <dt>Rush best</dt>
            <dd class="metric">{rush3 ?? '–'} <span class="small">/ {rush5 ?? '–'}</span></dd>
            <dd class="sub">3 min / 5 min</dd>
          </div>
        {/if}
        {#if summary.survivalBest != null}
          <div class="cell">
            <dt>Survival best</dt>
            <dd class="metric">{summary.survivalBest}</dd>
            <dd class="sub">In a row</dd>
          </div>
        {/if}
      </dl>

      <div class="cards">
        <section class="card" aria-labelledby="rated-h">
          <div class="ch"><h2 id="rated-h">Rated</h2><span class="hint">Moves your rating</span></div>
          <div class="cb">
            <p>Puzzles near your rating. Each result adjusts it.</p>
            <div class="field">
              <span class="lbl">Difficulty</span>
              <SegmentedControl
                label="Difficulty"
                options={PUZZLE_RATING_RANGES.map((r) => ({ value: String(r), label: `±${r}` }))}
                bind:value={range}
                onchange={() => (noThemePuzzles = false)}
              />
            </div>
            <div class="field top">
              <span class="lbl">Themes</span>
              <div class="chips" role="group" aria-label="Themes">
                {#each shownThemes as t (t)}
                  <Chip selected={themes.includes(t)} onclick={() => toggleTheme(t)}>{themeLabel(t)}</Chip>
                {/each}
                {#if hiddenCount > 0}
                  <button type="button" class="more" onclick={() => (allThemes = true)}>{hiddenCount} more</button>
                {/if}
              </div>
            </div>
            {#if noThemePuzzles}
              <EmptyState
                sentence={`No puzzles have all of ${themes.length === 1 ? 'this theme' : 'these themes'} within ±${range} of your rating.`}
                sub="Choose fewer themes or a wider difficulty."
                action={{ label: 'Clear themes', run: () => { themes = []; noThemePuzzles = false } }}
              />
            {/if}
          </div>
          <div class="cf"><Button variant="primary" kbd="↵" disabled={starting} onclick={() => void startRated()}>Start rated</Button></div>
        </section>

        <section class="card" aria-labelledby="rush-h">
          <div class="ch"><h2 id="rush-h">Rush</h2>{#if rushSel !== null}<span class="hint">Best {rushSel}</span>{/if}</div>
          <div class="cb">
            <p>Solve as many as you can against the clock.</p>
            <div class="wide">
              <SegmentedControl label="Length" options={PUZZLE_RUSH_TIMES.map(([s, l]) => ({ value: String(s), label: l }))} bind:value={rush} />
            </div>
          </div>
          <div class="cf"><Button onclick={() => startRush()}>Start rush</Button></div>
        </section>

        <section class="card" aria-labelledby="surv-h">
          <div class="ch"><h2 id="surv-h">Survival</h2>{#if summary.survivalBest != null}<span class="hint">Best {summary.survivalBest}</span>{/if}</div>
          <div class="cb"><p>One mistake ends the run. Difficulty climbs as you go.</p></div>
          <div class="cf"><Button onclick={startSurvival}>Start survival</Button></div>
        </section>
      </div>

      {#if summary.sessions.length}
        <section aria-labelledby="sess-h">
          <div class="rh"><h2 id="sess-h">Recent sessions</h2></div>
          <div class="table">
            <div class="thead" aria-hidden="true">
              <span>Date</span><span>Mode</span><span class="r">Solved</span><span class="r">Rating</span>
            </div>
            <ul>
              {#each summary.sessions as s, i (s.id ?? `i${i}`)}
                {@const rt = sessionRatingText(s)}
                <li class="row">
                  <span class="date">{dayWord(s.startedAt)}</span>
                  <span class="mode">{sessionModeLabel(s)}</span>
                  <span class="r">{sessionSolvedText(s)}</span>
                  <span class="r" class:win={rt?.tone === 'win'} class:loss={rt?.tone === 'loss'}>{rt?.text ?? ''}</span>
                </li>
              {/each}
            </ul>
          </div>
          {#if anyInferred}
            <p class="foot">Puzzles played before sessions were recorded are grouped by time: a gap of over {summary.sessionGapMin} minutes starts a new session.</p>
          {/if}
        </section>
      {/if}

      <section class="db" aria-labelledby="db-h">
        <div class="rh"><h2 id="db-h">Puzzle database</h2></div>
        <div class="dbbox">
          {#if importing}
            <p class="dbline">{progressLine(importProgress, finishing)}</p>
            <p class="dbsub">Your puzzles stay as they are until the new ones are in.</p>
            {#if share !== null}
              <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(share * 100)}>
                <span style:width="{Math.round(share * 100)}%"></span>
              </div>
            {/if}
            {#if !finishing}
              <div class="dbact"><Button size="sm" onclick={() => void api.cancelPuzzleImport()}>Cancel</Button></div>
            {/if}
          {:else}
            <p class="dbline">{copyLine(status)}</p>
            {#if importDone}<p class="dbsub">{doneLine(importDone)}</p>{/if}
            {#if importError}<p class="dbsub loss" role="alert">{lastImport?.kind === 'file' ? 'The import stopped' : 'The download stopped'}; your puzzles are as they were. {importError}</p>{/if}
            {#if checkError}<p class="dbsub loss" role="alert">{checkError}</p>{/if}
            {#if update}<p class="dbsub">{updateLine(update)}</p>{/if}
            <div class="dbact">
              {#if update?.newer}
                <Button size="sm" variant="primary" onclick={() => void startDownload()}>Download the new puzzles</Button>
              {:else}
                <Button size="sm" disabled={checking} onclick={() => void checkForNew()}>{checking ? 'Checking…' : 'Check for new puzzles'}</Button>
              {/if}
              <Button size="sm" variant="ghost" onclick={() => void chooseFile()}>Import a file…</Button>
            </div>
          {/if}
        </div>
      </section>
    {/if}
  </main>
</div>

<style>
  .page {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }
  header {
    height: var(--header-height);
    flex: none;
    box-sizing: border-box;
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
  .hint {
    color: var(--text-3);
    font: var(--secondary);
  }
  main {
    padding: var(--space-7) var(--space-8) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-7);
    max-width: 1140px;
    width: 100%;
    box-sizing: border-box;
  }
  .stats {
    margin: 0;
    display: grid;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .cell {
    padding: 14px 18px;
    min-width: 0;
  }
  .cell + .cell {
    border-left: 1px solid var(--border);
  }
  .cell.rating {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 200px;
    align-items: end;
    gap: 12px;
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
    font-variant-numeric: tabular-nums;
  }
  .small {
    font-size: 15px;
    color: var(--text-2);
  }
  .sub {
    margin-top: 2px;
    color: var(--text-2);
    font: var(--secondary);
  }
  .win {
    color: var(--win);
  }
  .loss {
    color: var(--loss);
  }
  .cards {
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-7);
  }
  .card {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
  }
  .ch {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
  }
  .cb {
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .cb p {
    margin: 0;
    color: var(--text-2);
  }
  .field {
    display: grid;
    grid-template-columns: 72px minmax(0, 1fr);
    align-items: center;
    gap: 12px;
  }
  .field.top {
    align-items: start;
  }
  .field :global(.seg) {
    display: flex;
  }
  .field :global(.seg button),
  .wide :global(.seg button) {
    flex: 1;
  }
  .wide :global(.seg) {
    display: flex;
  }
  .lbl {
    color: var(--text-3);
    font: var(--secondary);
  }
  .field.top .lbl {
    padding-top: 4px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .more {
    padding: 3px 10px;
    font: var(--secondary);
    color: var(--text-2);
    background: transparent;
    border: 1px dashed var(--border-control);
    border-radius: var(--radius-control);
    cursor: pointer;
  }
  .more:hover {
    color: var(--text);
  }
  .more:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .cf {
    margin-top: auto;
    padding: 0 16px 16px;
    display: flex;
  }
  .cf :global(.btn) {
    flex: 1;
  }
  .rh {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .table {
    /* a block: Tailwind's `table` utility would make it display: table, shrink-to-fit (BETA-4 C) */
    display: block;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .thead,
  .row {
    display: grid;
    grid-template-columns: 120px minmax(0, 1fr) 120px 96px;
    gap: 16px;
    align-items: center;
  }
  .thead {
    padding: 8px 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .row {
    padding: 9px 16px;
    border-top: 1px solid var(--divider);
    font-variant-numeric: tabular-nums;
  }
  .date {
    color: var(--text-3);
  }
  .mode {
    font-weight: 500;
  }
  .r {
    text-align: right;
  }
  .dbbox {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .dbline {
    margin: 0;
  }
  .dbsub {
    margin: 0;
    color: var(--text-2);
    font: var(--secondary);
  }
  .dbsub.loss {
    color: var(--loss);
  }
  .dbact {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .bar {
    height: 4px;
    border-radius: 2px;
    background: var(--raised);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--text);
    transition: width 120ms linear;
  }
  .foot {
    margin: 8px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
