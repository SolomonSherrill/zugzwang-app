<script lang="ts">
  /** Opening books (BOOK-DL, owner ruling D, 2026-11-19): Settings' "Opening book" list, and,
   *  with `compact`, the trainer lobby's no-book prompt. Nothing downloads without a click; a
   *  failed download leaves the book in use; a switch backs the database up, then marks the
   *  book moves in every analysed game from stored data (no engine). */
  import { onMount, onDestroy } from 'svelte'
  import { sidecar, api } from './api'
  import type { BooksStatus, BookJob, BookDoneEvent } from './api'
  import { bookAction, bookLine, formatBytes, jobFraction, jobText } from './books'

  let { compact = false, onchange }: { compact?: boolean; onchange?: () => void } = $props()

  let status = $state<BooksStatus | null>(null)
  let job = $state<BookJob | null>(null)
  let error = $state('')
  let done = $state('')

  const def = $derived(status?.books.find((b) => b.id === status?.defaultId) ?? null)

  async function refresh() {
    try {
      status = await api.booksStatus()
      job = status.job
    } catch {
      /* sidecar may not be ready yet */
    }
  }

  async function use(id: string) {
    error = ''
    done = ''
    try {
      await api.bookUse(id)
      job = { id, phase: 'download', done: 0, total: 0 }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  async function cancel() {
    await api.bookCancel()
  }

  const onProgress = (d: BookJob) => {
    job = d
  }
  const onDone = (d: BookDoneEvent) => {
    job = null
    const name = status?.books.find((b) => b.id === d.id)?.label ?? d.id
    done = `${name} is in use. ${d.labelsChanged} moves in your games are now marked as book.`
    void refresh()
    onchange?.()
  }
  const onError = (d: { id: string; message: string }) => {
    job = null
    error = `${d.message} The book you had is still in use.`
    void refresh()
  }

  onMount(() => {
    sidecar.on('book_progress', onProgress)
    sidecar.on('book_done', onDone)
    sidecar.on('book_error', onError)
    void refresh()
  })
  onDestroy(() => {
    sidecar.off('book_progress', onProgress)
    sidecar.off('book_done', onDone)
    sidecar.off('book_error', onError)
  })
</script>

{#if status}
  {#if job}
    <div class="job">
      <p class="job-text">{jobText(job, status.books)}</p>
      <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
        aria-valuenow={Math.round(jobFraction(job) * 100)}>
        <div class="fill" style:width={`${jobFraction(job) * 100}%`}></div>
      </div>
      {#if job.phase === 'download'}
        <button class="btn btn-quiet" onclick={cancel}>Cancel download</button>
      {/if}
    </div>
  {:else if compact}
    {#if !status.active && def}
      <button class="btn btn-accent" onclick={() => use(def.id)}>
        Download the {def.label.toLowerCase()} book ({formatBytes(def.bytes)})
      </button>
      <p class="hint">Larger books are in Settings → Opening book.</p>
    {/if}
  {:else}
    {#if !status.active}
      <p class="none">
        No opening book is installed, so no move in your games is marked as book and the
        opening trainer has nothing to drill.
      </p>
    {/if}
    <ul class="books">
      {#each status.books as b (b.id)}
        <li class="book" class:active={b.active}>
          <div class="book-text">
            <span class="book-line">{bookLine(b)}</span>
            {#if b.default}<span class="tag">default</span>{/if}
          </div>
          {#if b.active}
            <span class="in-use">✓ In use</span>
          {:else}
            <button class={b.id === status.defaultId && !status.active ? 'btn btn-accent' : 'btn btn-quiet'}
              onclick={() => use(b.id)}>{bookAction(b)}</button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  {#if error}<p class="error">{error}</p>{/if}
  {#if done}<p class="ok">✓ {done}</p>{/if}
{/if}

<style>
  .none {
    margin: 0;
    font-size: 13px;
    color: var(--text);
  }
  .books {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .book {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  .book.active {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .book-text {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }
  .tag {
    font-size: 11px;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 6px;
  }
  .in-use {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
  }
  .job {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
  }
  .job-text {
    margin: 0;
    font-size: 13px;
  }
  .bar {
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--bg-raised);
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 120ms linear;
  }
  .hint {
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--text-muted);
  }
  .error {
    margin: 0;
    font-size: 12px;
    color: var(--danger);
  }
  .ok {
    margin: 0;
    font-size: 12px;
    color: var(--win);
  }
</style>
