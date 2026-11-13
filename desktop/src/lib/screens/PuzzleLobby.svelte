<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import {
    api,
    sidecar,
    PUZZLE_RATING_RANGES,
    PUZZLE_RATING_RANGE_DEFAULT,
    PUZZLE_RUSH_TIMES,
    PUZZLE_THEMES,
    type PuzzleMode,
    type PuzzleStatus,
  } from '../api'
  import { pickPuzzleCsv } from '../pick'
  import { BETA } from '../build'

  interface Props {
    onstart: (config: PuzzleMode) => void
  }
  let { onstart }: Props = $props()

  let status = $state<PuzzleStatus | null>(null)
  let importing = $state(false)
  let importProgress = $state<{ imported: number; total: number } | null>(null)
  let importError = $state('')

  let rangeIdx = $state(PUZZLE_RATING_RANGE_DEFAULT)
  let rushIdx = $state(0)
  let themesOpen = $state(false)
  let selectedThemes = $state<Set<string>>(new Set())
  let themeError = $state('')

  let bests = $state<{ survival: string; rush3: string; rush5: string }>({
    survival: '—',
    rush3: '—',
    rush5: '—',
  })
  let board = $state<{ key: string; title: string; entries: { score: number; date: string }[] } | null>(null)

  async function refresh() {
    status = await api.puzzleStatus()
    importing = status.importing
    const [sv, r3, r5] = await Promise.all([
      api.puzzleLeaderboard('survival', null, 1),
      api.puzzleLeaderboard('rush', 180, 1),
      api.puzzleLeaderboard('rush', 300, 1),
    ])
    bests = {
      survival: sv.entries[0] ? String(sv.entries[0].score) : '—',
      rush3: r3.entries[0] ? String(r3.entries[0].score) : '—',
      rush5: r5.entries[0] ? String(r5.entries[0].score) : '—',
    }
  }

  async function startImport(csvPath?: string) {
    importError = ''
    // Set before the call, not on the first progress event: the first event only
    // arrives after 5 000 rows have been kept, and a button that looks unpressed
    // until then is the frozen window.
    importing = true
    importProgress = { imported: 0, total: 1 }
    try {
      await api.importPuzzles(csvPath)
    } catch (e) {
      importError = e instanceof Error ? e.message : String(e)
      importing = false
      importProgress = null
    }
  }

  async function chooseCsv() {
    const path = await pickPuzzleCsv()
    if (path === null) return
    await startImport(path)
  }

  async function toggleLeaderboard(key: string, title: string, mode: string, tls: number | null) {
    if (board?.key === key) {
      board = null
      return
    }
    const lb = await api.puzzleLeaderboard(mode, tls, 10)
    board = { key, title, entries: lb.entries }
  }

  function toggleTheme(tag: string) {
    const next = new Set(selectedThemes)
    if (next.has(tag)) next.delete(tag)
    else next.add(tag)
    selectedThemes = next
    themeError = ''
  }

  async function startThemeMode() {
    const themes = [...selectedThemes]
    if (themes.length === 0) return
    const res = await api.countThemePuzzles(themes, PUZZLE_RATING_RANGES[rangeIdx])
    if (res.count === 0) {
      themeError = 'No puzzles found for the selected themes in your rating range.'
      return
    }
    onstart({
      mode: 'theme',
      themes,
      rushSeconds: 180,
      ratingRange: PUZZLE_RATING_RANGES[rangeIdx],
    })
  }

  const onProgress = (d: Record<string, unknown>) => {
    importProgress = { imported: d.imported as number, total: d.total as number }
  }
  const onDone = () => {
    importing = false
    importProgress = null
    void refresh()
  }
  const onCancelled = () => {
    importing = false
    importProgress = null
    void refresh()
  }
  const onError = (d: Record<string, unknown>) => {
    importError = String(d.message)
    importing = false
    importProgress = null
  }

  onMount(() => {
    sidecar.on('puzzle_import_progress', onProgress)
    sidecar.on('puzzle_import_done', onDone)
    sidecar.on('puzzle_import_cancelled', onCancelled)
    sidecar.on('puzzle_import_error', onError)
    void refresh()
  })
  onDestroy(() => {
    sidecar.off('puzzle_import_progress', onProgress)
    sidecar.off('puzzle_import_done', onDone)
    sidecar.off('puzzle_import_cancelled', onCancelled)
    sidecar.off('puzzle_import_error', onError)
  })
</script>

<div class="lobby">
  {#if !status}
    <div class="loading"><span class="pulse-dot"></span> Loading…</div>
  {:else if !status.imported || importing}
    <div class="import-wrap">
      <div class="import-card">
        <span class="import-chip" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3v12" /><path d="M7.5 10.5 12 15l4.5-4.5" /><path d="M4 19h16" /></svg>
        </span>
        <h2>Puzzle database</h2>
        {#if importing && importProgress}
          <p class="muted">
            {importProgress.imported === 0
              ? 'Reading the CSV…'
              : `Importing… ${importProgress.imported.toLocaleString()} puzzles
                 (${Math.min(99, Math.round((importProgress.imported / importProgress.total) * 100))}%)`}
          </p>
          <div class="track" class:indeterminate={importProgress.imported === 0}>
            <div
              class="fill"
              style="width: {Math.min(99, (importProgress.imported / importProgress.total) * 100)}%"
            ></div>
          </div>
          <button class="btn btn-quiet" onclick={() => api.cancelPuzzleImport()}>Cancel</button>
        {:else}
          <p class="muted">
            Zugzwang trains on the Lichess puzzle database (~1.1&nbsp;GB CSV, imported once).
          </p>
          {#if status.csvExists}
            <code class="path">{status.csvPath}</code>
            <button class="btn btn-accent" onclick={() => startImport()}>Import puzzles</button>
            <button class="btn btn-quiet" onclick={chooseCsv}>Choose a different file…</button>
          {:else}
            {#if BETA}
              <p class="muted">
                <strong>Puzzles are optional.</strong> Review, Insights and Play work without
                them. To add them: download <code class="path">lichess_db_puzzle.csv.zst</code>
                from database.lichess.org (the Puzzles section), decompress it to
                <code class="path">lichess_db_puzzle.csv</code> (about 1.1&nbsp;GB) with a
                zstd tool, then choose it below. The import runs once
                and copies the puzzles into Zugzwang's own database, so the CSV can be deleted
                afterwards.
              </p>
            {:else}
              <p class="muted">
                Download <code class="path">lichess_db_puzzle.csv</code> from
                database.lichess.org, decompress it, and point Zugzwang at it.
              </p>
            {/if}
            <button class="btn btn-accent" onclick={chooseCsv}>Choose CSV…</button>
            <p class="hint">
              Looked for it at <code class="path">{status.csvPath}</code>; put it there
              to skip this step next time.
            </p>
          {/if}
          {#if importError}<p class="err">{importError}</p>{/if}
        {/if}
      </div>
    </div>
  {:else}
    <div class="inner">
      <header class="head">
        <p class="eyebrow">Tactics</p>
        <div class="head-row">
          <h1 class="title">Puzzles</h1>
          <div class="rating-box">
            <span class="rating">{status.rating.toFixed(0)}</span>
            <span class="rating-sub">puzzle rating · ±{status.rd.toFixed(0)}</span>
          </div>
        </div>
      </header>

      <div class="range-row">
        <span class="range-label">Difficulty</span>
        <div class="seg">
          {#each PUZZLE_RATING_RANGES as r, i (r)}
            <button class:on={rangeIdx === i} onclick={() => (rangeIdx = i)}>±{r}</button>
          {/each}
        </div>
        <span class="range-hint">applies to Rated &amp; Themes</span>
      </div>

      <div class="cards">
        <div class="card" style="--i: 0">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.2" /><circle cx="12" cy="12" r="3.4" /></svg>
          </span>
          <span class="card-body">
            <span class="card-name">Rated</span>
            <span class="card-desc">Solve puzzles near your rating. Each result adjusts it.</span>
          </span>
          <div class="card-foot">
            <button
              class="btn btn-accent"
              onclick={() =>
                onstart({ mode: 'rated', themes: [], rushSeconds: 180, ratingRange: PUZZLE_RATING_RANGES[rangeIdx] })}
            >
              Start
            </button>
          </div>
        </div>

        <div class="card" class:active={themesOpen} style="--i: 1">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M4 11V5a1 1 0 0 1 1-1h6l9 9-7 7-9-9z" /><circle class="fill" cx="8" cy="8" r="1.5" /></svg>
          </span>
          <span class="card-body">
            <span class="card-name">Themes</span>
            <span class="card-desc">Drill specific motifs — forks, pins, mates…</span>
          </span>
          <div class="card-foot">
            <button class="btn btn-quiet" class:open={themesOpen} onclick={() => (themesOpen = !themesOpen)}>
              {themesOpen ? 'Close' : 'Choose themes'}
            </button>
          </div>
        </div>

        <div class="card" style="--i: 2">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path class="fill" d="M13 3 5 13h5l-1 8 8-10h-5z" /></svg>
          </span>
          <span class="card-body">
            <span class="card-name">Rush</span>
            <span class="card-desc">Solve as many as you can against the clock.</span>
          </span>
          <div class="card-foot col">
            <div class="card-row">
              <div class="seg small">
                {#each PUZZLE_RUSH_TIMES as [secs, label], i (secs)}
                  <button class:on={rushIdx === i} onclick={() => (rushIdx = i)}>{label}</button>
                {/each}
              </div>
              <button
                class="btn btn-accent"
                onclick={() =>
                  onstart({ mode: 'rush', themes: [], rushSeconds: PUZZLE_RUSH_TIMES[rushIdx][0], ratingRange: 100 })}
              >
                Start
              </button>
            </div>
            <button
              class="best"
              onclick={() =>
                toggleLeaderboard(
                  `rush${PUZZLE_RUSH_TIMES[rushIdx][0]}`,
                  `Rush — ${PUZZLE_RUSH_TIMES[rushIdx][1]}`,
                  'rush',
                  PUZZLE_RUSH_TIMES[rushIdx][0],
                )}
            >
              Best {rushIdx === 0 ? bests.rush3 : bests.rush5} · leaderboard
            </button>
          </div>
        </div>

        <div class="card" style="--i: 3">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path class="fill" d="M12 3.5c1.2 2.8 3.8 3.6 3.8 7.2a3.8 3.8 0 0 1-7.6 0c0-1.3.5-2.2 1-2.8.3 1 .9 1.4 1.6 1.4-.6-2.2.3-4 1.2-5.8z" /></svg>
          </span>
          <span class="card-body">
            <span class="card-name">Survival</span>
            <span class="card-desc">One mistake ends the run. Difficulty ramps as you go.</span>
          </span>
          <div class="card-foot col">
            <button
              class="btn btn-accent"
              onclick={() => onstart({ mode: 'survival', themes: [], rushSeconds: 180, ratingRange: 50 })}
            >
              Start
            </button>
            <button class="best" onclick={() => toggleLeaderboard('survival', 'Survival', 'survival', null)}>
              Best {bests.survival} · leaderboard
            </button>
          </div>
        </div>
      </div>

      {#if themesOpen}
        <div class="themes">
          <div class="chips">
            {#each PUZZLE_THEMES as [label, tag] (tag)}
              <button class="theme-chip" class:on={selectedThemes.has(tag)} onclick={() => toggleTheme(tag)}>
                {label}
              </button>
            {/each}
          </div>
          <div class="themes-foot">
            <button class="btn btn-accent" disabled={selectedThemes.size === 0} onclick={startThemeMode}>
              Start themed session
            </button>
            {#if selectedThemes.size > 0}
              <span class="themes-count">{selectedThemes.size} selected</span>
            {/if}
            {#if themeError}<span class="err">{themeError}</span>{/if}
          </div>
        </div>
      {/if}

      {#if board}
        <div class="leaderboard">
          <h4>{board.title} — top 10</h4>
          {#if board.entries.length === 0}
            <p class="muted">No sessions yet.</p>
          {:else}
            {#each board.entries as e, i (i)}
              <div class="lb-row">
                <span class="lb-rank">{i + 1}</span>
                <span class="lb-score">{e.score}</span>
                <span class="lb-date">{e.date}</span>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .lobby {
    height: 100%;
    overflow-y: auto;
    position: relative;
  }
  /* warm depth: a soft amber glow anchored top-left, very subtle */
  .lobby::before {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(120% 80% at 12% -10%, var(--accent-soft) 0%, transparent 55%);
  }
  .inner {
    position: relative;
    max-width: 760px;
    margin: 0 auto;
    padding: 56px 32px 48px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .muted {
    color: var(--text-muted);
  }
  .err {
    color: var(--danger);
    font-size: 12.5px;
  }
  .loading {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text-muted);
  }

  /* ── import state ── */
  .import-wrap {
    height: 100%;
    display: grid;
    place-items: center;
    padding: 24px;
  }
  .import-card {
    position: relative;
    width: 440px;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    padding: 26px;
  }
  .import-chip {
    display: grid;
    place-items: center;
    width: 42px;
    height: 42px;
    border-radius: var(--radius);
    background: var(--accent-soft);
    border: 1px solid var(--accent-line);
    color: var(--accent);
  }
  .import-chip svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .import-card h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .import-card p {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-muted);
  }
  .path {
    align-self: stretch;
    font-size: 11px;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 6px 9px;
    word-break: break-all;
    user-select: text;
    color: var(--text-muted);
  }
  .track {
    align-self: stretch;
    height: 4px;
    border-radius: 2px;
    background: var(--bg-surface);
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 300ms linear;
  }
  /* Before the first progress event there is no count to show, and a 0 %-wide
     bar is indistinguishable from a stalled one. */
  .track.indeterminate {
    background: linear-gradient(90deg, var(--bg-surface) 0 60%, var(--accent) 60% 100%);
    background-size: 250% 100%;
    animation: sweep 1.1s linear infinite;
  }
  @keyframes sweep {
    from {
      background-position: 100% 0;
    }
    to {
      background-position: -60% 0;
    }
  }
  .hint {
    font-size: 11px;
    color: var(--text-muted);
    opacity: 0.75;
    text-align: center;
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
  .rating-box {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    line-height: 1.05;
  }
  .rating {
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
  }
  .rating-sub {
    font-size: 11.5px;
    color: var(--text-muted);
  }

  /* ── difficulty range ── */
  .range-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .range-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .range-hint {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--bg-raised);
  }
  .seg button {
    padding: 5px 12px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    transition: color 120ms ease, background-color 120ms ease;
  }
  .seg button:hover:not(.on) {
    color: var(--text);
  }
  .seg button.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .seg.small button {
    padding: 4px 10px;
    font-size: 12px;
  }

  /* ── mode cards ── */
  .cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  .card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 14px;
    min-height: 158px;
    padding: 18px;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    transition: border-color 160ms ease, background-color 160ms ease;
    animation: rise 420ms cubic-bezier(0.2, 0.7, 0.2, 1) backwards;
    animation-delay: calc(var(--i) * 55ms + 60ms);
  }
  .card:hover,
  .card.active {
    border-color: var(--accent-line);
  }
  .chip {
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    border-radius: var(--radius);
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    color: var(--text-muted);
    transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease;
  }
  .card:hover .chip,
  .card.active .chip {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }
  .chip svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .chip svg .fill {
    fill: currentColor;
    stroke: none;
  }

  .card-body {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .card-name {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .card-desc {
    font-size: 12.5px;
    line-height: 1.4;
    color: var(--text-muted);
  }

  .card-foot {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    margin-top: auto;
  }
  .card-foot.col {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .card-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }
  .card .btn.open {
    color: var(--accent);
    border-color: var(--accent-line);
  }
  .best {
    font-size: 11.5px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
    text-align: left;
    transition: color 120ms ease;
  }
  .best:hover {
    color: var(--accent);
  }

  /* ── themes ── */
  .themes {
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
  }
  .theme-chip {
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-muted);
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: 999px;
    transition: color 100ms ease, border-color 100ms ease, background-color 100ms ease;
  }
  .theme-chip:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }
  .theme-chip.on {
    color: var(--accent-ink);
    background: var(--accent);
    border-color: var(--accent);
  }
  .themes-foot {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .themes-count {
    font-size: 12px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  /* ── leaderboard ── */
  .leaderboard {
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    padding: 16px;
  }
  .leaderboard h4 {
    margin: 0 0 10px;
    font-size: 13px;
    font-weight: 600;
  }
  .lb-row {
    display: flex;
    gap: 14px;
    padding: 4px 0;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  .lb-rank {
    width: 20px;
    color: var(--text-muted);
  }
  .lb-score {
    width: 44px;
    font-weight: 600;
  }
  .lb-date {
    color: var(--text-muted);
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

  @media (max-width: 720px) {
    .cards {
      grid-template-columns: 1fr;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .card {
      animation: none;
    }
  }
</style>
