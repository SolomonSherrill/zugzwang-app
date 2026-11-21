<script lang="ts">
  /**
   * Openings: the families the trainer can drill (UI-BUILD-2 E3). Not mocked: the redesign draws
   * a family already chosen ("Openings / Scandinavian Defense"); this list is how one is chosen,
   * in the approved style (decided, for the owner to confirm). Until OPEN-1 the Openings screen
   * is the trainer (ruling 22). Words from the record only (ruling 18).
   */
  import { onDestroy, onMount } from 'svelte'
  import { api, sidecar, type TrainerFamilySummary } from '../api'
  import EmptyState from '../ui/EmptyState.svelte'
  import { familyMovesText } from './trainerModel'

  interface Props {
    onselect: (f: TrainerFamilySummary) => void
    onsettings: () => void
  }
  let { onselect, onsettings }: Props = $props()

  let loaded = $state(false)
  let error = $state<string | null>(null)
  let families = $state<TrainerFamilySummary[]>([])
  let indexed = $state(false)
  let indexing = $state(false)
  let progress = $state<{ done: number; total: number } | null>(null)
  let bookAvailable = $state(true)
  let bookId = $state<string | null>(null)
  let query = $state('')
  let first = $state<'all' | 'e4' | 'd4' | 'other'>('all')

  const shown = $derived(
    families
      .filter((f) => (first === 'all' || f.firstMove === first) && (!query.trim() || matches(f, query.trim().toLowerCase())))
      .sort((a, b) => Number(b.available) - Number(a.available) || b.popularity - a.popularity),
  )
  function matches(f: TrainerFamilySummary, q: string): boolean {
    if (f.name.toLowerCase().includes(q)) return true
    if (/^[a-e]\d{0,2}$/.test(q)) {
      const up = q.toUpperCase()
      return !(up.padEnd(3, '9') < f.ecoLo || up.padEnd(3, '0') > f.ecoHi)
    }
    const bare = (s: string) => s.toLowerCase().replace(/\d+\.(\.\.)?\s*/g, '')
    return bare(f.sampleMoves).startsWith(bare(q)) || bare(f.sharedMoves ?? '').startsWith(bare(q))
  }
  function status(f: TrainerFamilySummary): string {
    if (!f.available) return 'Too few book lines'
    if (f.mastered > 0) return `${f.mastered} mastered · ${f.drilled} finished`
    if (f.drilled > 0) return `${f.drilled} finished`
    return 'Not tried'
  }

  async function refresh() {
    error = null
    try {
      const res = await api.trainerLobby()
      indexed = res.indexed
      indexing = res.indexing
      bookAvailable = res.bookAvailable
      bookId = (res as { bookId?: string | null }).bookId ?? null
      families = res.families
      loaded = true
      api.booksStatus().then((s) => (bookName = s.books.find((b) => b.id === bookId)?.label ?? null)).catch(() => {})
      if (!indexed && !indexing && bookAvailable) {
        indexing = true
        await api.trainerIndexCoverage()
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }
  const onProgress = (d: Record<string, unknown>) => (progress = { done: d.done as number, total: d.total as number })
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
  let bookName = $state<string | null>(null)
</script>

<div class="fams">
  <header>
    <h1>Openings</h1>
    {#if bookAvailable && bookName}<span class="meta">Book: {bookName}</span>{/if}
  </header>
  <main>
    {#if error}
      <EmptyState tone="error" sentence="The opening book could not be read." sub={error} action={{ label: 'Try again', run: refresh }} />
    {:else if !loaded}
      <EmptyState sentence="Loading the opening book…" />
    {:else if !bookAvailable}
      <EmptyState
        sentence="Opening training needs an opening book, and none is installed."
        sub="Download one of the three books in Settings; the trainer plays its replies from it."
        action={{ label: 'Open Settings', run: onsettings, primary: true }}
      />
    {:else if indexing}
      <EmptyState
        sentence="Indexing the opening book. This happens once."
        sub={progress ? `${progress.done.toLocaleString('en-US')} of ${progress.total.toLocaleString('en-US')} lines` : null}
        progress={progress && progress.total ? progress.done / progress.total : null}
      />
    {:else}
      <div class="bar">
        <div class="seg" role="group" aria-label="First move">
          {#each [['all', 'All'], ['e4', '1.e4'], ['d4', '1.d4'], ['other', 'Other']] as [v, l] (v)}
            <button type="button" aria-pressed={first === v} onclick={() => (first = v as typeof first)}>{l}</button>
          {/each}
        </div>
        <input type="search" placeholder="Name, ECO or moves" aria-label="Find an opening" bind:value={query} />
        <span class="n">{shown.length.toLocaleString('en-US')} families</span>
      </div>
      <div class="list">
        <div class="row head" aria-hidden="true"><span>Opening</span><span>Moves</span><span class="r">Lines</span><span>Progress</span></div>
        {#each shown as f (f.name)}
          <button type="button" class="row" disabled={!f.available} onclick={() => onselect(f)}>
            <span class="nm">{f.name}<span class="eco">{f.ecoLo === f.ecoHi ? f.ecoLo : `${f.ecoLo}–${f.ecoHi}`}</span></span>
            <span class="mv" class:several={!f.sharedMoves}>{familyMovesText(f)}</span>
            <span class="r">{f.lineCount}</span>
            <span class="st">{status(f)}</span>
          </button>
        {:else}
          <p class="none">No opening matches “{query}”.</p>
        {/each}
      </div>
    {/if}
  </main>
</div>

<style>
  .fams {
    display: flex;
    flex-direction: column;
    min-height: 100%;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .meta,
  .n {
    color: var(--text-3);
    font: var(--secondary);
  }
  main {
    padding: 24px 28px 32px;
    max-width: 1140px;
    box-sizing: border-box;
    width: 100%;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
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
  input {
    width: 240px;
    padding: 5px 10px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    color: var(--text);
    font: var(--secondary);
  }
  input:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .list {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 2fr) 56px minmax(0, 1.2fr);
    gap: 16px;
    align-items: center;
    width: 100%;
    padding: 9px 16px;
    border: 0;
    border-top: 1px solid var(--divider);
    background: transparent;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .row.head {
    border-top: 0;
    color: var(--text-3);
    font: var(--secondary);
    cursor: default;
  }
  button.row:hover:not(:disabled) {
    background: var(--surface);
  }
  button.row:disabled {
    cursor: default;
    color: var(--text-3);
  }
  .nm {
    font: var(--body-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  button.row:disabled .nm {
    font-weight: 400;
  }
  .eco {
    margin-left: 0.4em;
    color: var(--text-3);
    font-weight: 400;
  }
  .mv,
  .st {
    color: var(--text-2);
    font: var(--secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mv.several {
    color: var(--text-3);
  }
  .r {
    text-align: right;
  }
  .none {
    margin: 0;
    padding: 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
