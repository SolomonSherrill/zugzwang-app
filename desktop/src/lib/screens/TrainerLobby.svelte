<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { api, sidecar, type TrainerFamilySummary } from '../api'

  interface Props {
    onselect: (family: TrainerFamilySummary) => void
  }
  let { onselect }: Props = $props()

  let loaded = $state(false)
  let indexed = $state(false)
  let indexing = $state(false)
  let progress = $state<{ done: number; total: number } | null>(null)
  let families = $state<TrainerFamilySummary[]>([])
  let error = $state('')
  // Reported by the sidecar off the loaded Polyglot reader. Without a book every
  // family is untrainable, so the list below is 123 dead rows and the screen has
  // to say why rather than let the user work it out.
  let bookAvailable = $state(true)
  let bookPath = $state('')

  let query = $state('')
  let firstMove = $state<'all' | 'e4' | 'd4' | 'other'>('all')
  let sortKey = $state<'popularity' | 'name' | 'eco' | 'mastery'>('popularity')
  let searchEl = $state<HTMLInputElement | null>(null)

  const totalMastered = $derived(families.reduce((s, f) => s + f.mastered, 0))

  // ── search / filter / sort ───────────────────────────────────────────────
  function normMoves(s: string): string {
    return s
      .replace(/\d+\.(\.\.)?/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase()
  }
  const ECO_RE = /^[a-e]\d{0,2}$/i

  function matchesQuery(f: TrainerFamilySummary, q: string): boolean {
    if (!q) return true
    const ql = q.trim().toLowerCase()
    if (!ql) return true
    if (f.name.toLowerCase().includes(ql)) return true
    // ECO code / range overlap, e.g. "c65" → Ruy Lopez (C60–C90)
    if (ECO_RE.test(ql)) {
      const up = ql.toUpperCase()
      const lo = up.padEnd(3, '0')
      const hi = up.padEnd(3, '9')
      if (!(hi < f.ecoLo || lo > f.ecoHi)) return true
    }
    // move sequence, e.g. "1. e4 e5 2. Nf3" or "e4 e5 nf3"
    const qm = normMoves(q)
    if (qm && normMoves(f.sampleMoves).startsWith(qm)) return true
    return false
  }

  const shown = $derived.by(() => {
    const list = families.filter(
      (f) => (firstMove === 'all' || f.firstMove === firstMove) && matchesQuery(f, query),
    )
    const cmp: Record<string, (a: TrainerFamilySummary, b: TrainerFamilySummary) => number> = {
      popularity: (a, b) => b.popularity - a.popularity,
      name: (a, b) => a.name.localeCompare(b.name),
      eco: (a, b) => a.ecoLo.localeCompare(b.ecoLo) || b.popularity - a.popularity,
      mastery: (a, b) => a.mastered - b.mastered || b.popularity - a.popularity,
    }
    return [...list].sort(cmp[sortKey])
  })

  const counts = $derived({
    all: families.length,
    e4: families.filter((f) => f.firstMove === 'e4').length,
    d4: families.filter((f) => f.firstMove === 'd4').length,
    other: families.filter((f) => f.firstMove === 'other').length,
  })

  function rowStatus(f: TrainerFamilySummary): string {
    if (!f.available) return 'Limited coverage'
    if (f.drilled === 0) return 'Not started'
    if (f.mastered > 0) return `${f.mastered} mastered · ${f.drilled} drilled`
    return `${f.drilled} drilled`
  }

  function onSearchKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && query) {
      e.stopPropagation()
      query = ''
    }
  }

  // ── data load + coverage indexing ──────────────────────────────────────────
  async function refresh() {
    const res = await api.trainerLobby()
    indexed = res.indexed
    indexing = res.indexing
    bookAvailable = res.bookAvailable
    bookPath = res.bookPath
    families = res.families
    loaded = true
    // Coverage indexing probes the book for every ECO line, so with no book it
    // is a progress bar over nothing. Skipped rather than run to a zero result.
    if (!indexed && !indexing && bookAvailable) {
      indexing = true
      await api.trainerIndexCoverage()
    }
  }

  const onProgress = (d: Record<string, unknown>) => {
    progress = { done: d.done as number, total: d.total as number }
  }
  const onDone = () => {
    indexing = false
    progress = null
    void refresh()
  }
  const onError = (d: Record<string, unknown>) => {
    error = String(d.message)
    indexing = false
  }

  onMount(() => {
    sidecar.on('trainer_index_progress', onProgress)
    sidecar.on('trainer_index_done', onDone)
    sidecar.on('trainer_index_error', onError)
    void refresh()
  })
  onDestroy(() => {
    sidecar.off('trainer_index_progress', onProgress)
    sidecar.off('trainer_index_done', onDone)
    sidecar.off('trainer_index_error', onError)
  })
</script>

<div class="lobby">
  {#if !loaded}
    <div class="loading"><span class="pulse-dot"></span> Loading…</div>
  {:else if indexing}
    <div class="index-wrap">
      <div class="index-card">
        <span class="index-chip" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H12v15H5.5A1.5 1.5 0 0 0 4 20.5z" /><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H12v15h6.5a1.5 1.5 0 0 1 1.5 1.5z" /></svg>
        </span>
        <h2>Opening Trainer</h2>
        <p class="muted">Indexing the opening book — this only happens once.</p>
        <div class="track">
          <div
            class="fill"
            style="width: {progress ? Math.min(99, (progress.done / progress.total) * 100) : 8}%"
          ></div>
        </div>
      </div>
    </div>
  {:else}
    <div class="inner">
      <header class="head">
        <p class="eyebrow">Repertoire</p>
        <div class="head-row">
          <h1 class="title">Opening Trainer</h1>
          <div class="stat-box">
            <span class="stat-num">{totalMastered}</span>
            <span class="stat-sub">{totalMastered === 1 ? 'line' : 'lines'} mastered</span>
          </div>
        </div>
        <p class="lead">
          {#if bookAvailable}
            Drill any of {families.length} opening families against weighted book replies.
          {:else}
            Opening training needs a Polyglot opening book, which is not installed.
          {/if}
        </p>
      </header>

      {#if error}<p class="err">{error}</p>{/if}

      {#if !bookAvailable}
        <div class="no-book">
          <p>
            The trainer plays its replies out of a Polyglot book and uses it to pick which
            lines are worth drilling. Without one there is nothing to drill against, so all
            {families.length} opening families are unavailable.
          </p>
          <p class="no-book-where">Expected at <code>{bookPath}</code></p>
          <p class="no-book-note">
            Everything else that names openings still works — game review labels each
            opening from the ECO data, which is installed.
          </p>
        </div>
      {:else}

      <div class="controls">
        <div class="search">
          <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"
            ><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg
          >
          <input
            bind:this={searchEl}
            bind:value={query}
            onkeydown={onSearchKey}
            type="text"
            placeholder="Search openings, ECO code, or moves…"
            spellcheck="false"
            autocomplete="off"
          />
          {#if query}
            <button class="clear" title="Clear (Esc)" onclick={() => (query = '')} aria-label="Clear search">
              <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          {/if}
        </div>
        <div class="sort">
          <label for="trainer-sort">Sort</label>
          <select id="trainer-sort" bind:value={sortKey}>
            <option value="popularity">Popularity</option>
            <option value="name">Name</option>
            <option value="eco">ECO</option>
            <option value="mastery">Least mastered</option>
          </select>
        </div>
      </div>

      <div class="chips">
        {#each [['all', 'All', counts.all], ['e4', '1.e4', counts.e4], ['d4', '1.d4', counts.d4], ['other', 'Other', counts.other]] as [val, lbl, n] (val)}
          <button
            class="chip"
            class:on={firstMove === val}
            onclick={() => (firstMove = val as typeof firstMove)}
          >
            {lbl} <span class="chip-n">{n}</span>
          </button>
        {/each}
      </div>

      {#if shown.length === 0}
        <div class="empty">
          <p class="empty-title">No openings match “{query}”.</p>
          <button class="empty-clear" onclick={() => { query = ''; firstMove = 'all' }}>Clear filters</button>
        </div>
      {:else}
        <div class="families">
          {#each shown as f (f.name)}
            {#if f.available}
              <button class="fam-row" onclick={() => onselect(f)}>
                <span class="eco-chip">{f.ecoLo}–{f.ecoHi}</span>
                <span class="fam-main">
                  <span class="fam-name">{f.name}</span>
                  <span class="fam-meta">{f.lineCount} line{f.lineCount === 1 ? '' : 's'}</span>
                </span>
                <span class="fam-status" class:started={f.drilled > 0}>{rowStatus(f)}</span>
                <span class="chev" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
                </span>
              </button>
            {:else}
              <div class="fam-row limited" aria-disabled="true">
                <span class="eco-chip">{f.ecoLo}–{f.ecoHi}</span>
                <span class="fam-main">
                  <span class="fam-name">{f.name}</span>
                </span>
                <span class="limited-badge">Limited coverage</span>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
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

  /* ── indexing state ── */
  .index-wrap {
    height: 100%;
    display: grid;
    place-items: center;
    padding: 24px;
  }
  .index-card {
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
  .index-chip {
    display: grid;
    place-items: center;
    width: 42px;
    height: 42px;
    border-radius: var(--radius);
    background: var(--accent-soft);
    border: 1px solid var(--accent-line);
    color: var(--accent);
  }
  .index-chip svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .index-card h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .index-card p {
    margin: 0;
    font-size: 13px;
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
  .stat-box {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    line-height: 1.05;
  }
  .stat-num {
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
  }
  .stat-sub {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .lead {
    margin: 2px 0 0;
    font-size: 13.5px;
    color: var(--text-muted);
  }

  /* ── controls: search + sort ── */
  .controls {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .search {
    position: relative;
    flex: 1;
    display: flex;
    align-items: center;
  }
  .search-icon {
    position: absolute;
    left: 11px;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-muted);
    stroke-width: 2;
    stroke-linecap: round;
    pointer-events: none;
  }
  .search input {
    width: 100%;
    padding: 9px 32px 9px 34px;
    font-size: 13.5px;
    color: var(--text);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    transition: border-color 120ms ease, box-shadow 120ms ease;
  }
  .search input:focus {
    outline: none;
    border-color: var(--accent-line);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .search input::placeholder {
    color: var(--text-muted);
  }
  .clear {
    position: absolute;
    right: 7px;
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    color: var(--text-muted);
    transition: color 120ms ease, background-color 120ms ease;
  }
  .clear:hover {
    color: var(--text);
    background: var(--bg-raised);
  }
  .clear svg {
    width: 13px;
    height: 13px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .sort {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .sort label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .sort select {
    font-size: 13px;
    color: var(--text);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    padding: 8px 10px;
    cursor: pointer;
  }
  .sort select:focus {
    outline: none;
    border-color: var(--accent-line);
  }

  /* ── first-move filter chips ── */
  .chips {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 11px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: 999px;
    transition: all 120ms ease;
  }
  .chip:hover {
    color: var(--text);
    border-color: var(--accent-line);
  }
  .chip.on {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }
  .chip-n {
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    opacity: 0.7;
  }

  /* ── empty state ── */
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 48px 16px;
    color: var(--text-muted);
  }
  .empty-title {
    margin: 0;
    font-size: 14px;
  }
  .empty-clear {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--accent);
    padding: 6px 12px;
    border: 1px solid var(--accent-line);
    border-radius: var(--radius);
    background: var(--accent-soft);
  }

  .no-book {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 22px 24px;
    border: 1px solid var(--divider);
    border-radius: var(--radius);
    background: var(--bg-tile);
    color: var(--text-muted);
    font-size: 13.5px;
    line-height: 1.55;
    max-width: 62ch;
  }
  .no-book p {
    margin: 0;
  }
  /* matches the engine path block in Settings — the app has no mono face */
  .no-book-where code {
    font-size: 11.5px;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 4px 8px;
    word-break: break-all;
    user-select: text;
  }
  .no-book-note {
    padding-top: 12px;
    border-top: 1px solid var(--divider);
    font-size: 12.5px;
  }

  /* ── family list ── */
  .families {
    display: flex;
    flex-direction: column;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    overflow: hidden;
  }
  .fam-row {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 13px 16px;
    text-align: left;
    border-bottom: 1px solid var(--divider);
    transition: background-color 120ms ease;
  }
  .fam-row:last-child {
    border-bottom: none;
  }
  .fam-row:not(.limited):hover {
    background: var(--bg-raised);
  }
  .fam-row.limited {
    opacity: 0.5;
    cursor: default;
  }
  .eco-chip {
    flex-shrink: 0;
    min-width: 72px;
    text-align: center;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 3px 6px;
    transition: color 120ms ease, border-color 120ms ease;
  }
  .fam-row:not(.limited):hover .eco-chip {
    color: var(--accent);
    border-color: var(--accent-line);
  }
  .fam-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .fam-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .fam-meta {
    font-size: 11.5px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .fam-status {
    flex-shrink: 0;
    font-size: 12px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .fam-status.started {
    color: var(--accent);
  }
  .limited-badge {
    flex-shrink: 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
  }
  .chev {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    color: var(--text-muted);
    opacity: 0.5;
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
  .fam-row:not(.limited):hover .chev {
    opacity: 1;
    color: var(--accent);
    transform: translateX(2px);
  }
</style>
