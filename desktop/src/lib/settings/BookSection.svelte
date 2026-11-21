<script lang="ts">
  /** Settings → Opening book (BOOK-DL, owner ruling D; DESIGN.md "Settings"): the three hosted
   *  books with their floors and sizes, In use or Download. The flow is BOOK-DL's, unchanged:
   *  nothing downloads without a click; a failed download leaves the book in use; a switch
   *  backs the database up, then marks the book moves in every analysed game. */
  import { onDestroy, onMount } from 'svelte'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import { sidecar, api, type BookDoneEvent, type BookJob, type BooksStatus } from '../api'
  import { jobFraction, jobText } from '../books'
  import { BOOK_SWITCH_LINE, bookFloor, bookSize } from './settingsModel'

  let status = $state<BooksStatus | null>(null)
  let readError = $state<string | null>(null)
  let job = $state<BookJob | null>(null)
  let failed = $state<{ id: string; message: string } | null>(null)
  let done = $state<string | null>(null)

  async function refresh() {
    try {
      status = await api.booksStatus()
      job = status.job
      readError = null
    } catch (e) {
      readError = e instanceof Error ? e.message : String(e)
    }
  }

  async function use(id: string) {
    failed = null
    done = null
    try {
      await api.bookUse(id)
      job = { id, phase: 'download', done: 0, total: 0 }
    } catch (e) {
      failed = { id, message: e instanceof Error ? e.message : String(e) }
    }
  }

  const name = (id: string) => status?.books.find((b) => b.id === id)?.label ?? id
  const onProgress = (d: BookJob) => (job = d)
  const onDone = (d: BookDoneEvent) => {
    job = null
    done = `${name(d.id)} is in use. ${d.labelsChanged.toLocaleString('en-US')} moves in your games are now marked as book.`
    void refresh()
  }
  const onError = (d: { id: string; message: string }) => {
    job = null
    failed = { id: d.id, message: d.message }
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

{#if readError && !status}
  <EmptyState tone="error" sentence="The opening books could not be read." sub={readError} action={{ label: 'Try again', run: refresh }} />
{:else if !status}
  <p class="quiet">Reading the opening books…</p>
{:else}
  {#if !status.active && !job}
    <p class="none">No book is installed, so no move in your games is marked as book and the opening trainer has no lines.</p>
  {/if}
  <ul class="books" aria-label="Opening books">
    {#each status.books as b (b.id)}
      <li class:active={b.active} aria-current={b.active ? 'true' : undefined}>
        <span class="radio" class:on={b.active} aria-hidden="true"></span>
        <span class="what"><span class="label">{b.label}</span> <span class="floor">{bookFloor(b)}</span></span>
        <span class="size">{bookSize(b.bytes)}</span>
        <span class="act">
          {#if b.active}
            <span class="inuse"><span class="dot" aria-hidden="true"></span>In use</span>
          {:else}
            <Button size="sm" disabled={!!job} onclick={() => use(b.id)}>{b.installed ? 'Use' : 'Download and use'}</Button>
          {/if}
        </span>
      </li>
    {/each}
  </ul>
  {#if job}
    <EmptyState
      sentence={jobText(job, status.books)}
      sub={job.phase === 'download' ? 'The book in use stays until the new one is downloaded and checked.' : 'A backup was taken first; this runs to the end.'}
      progress={jobFraction(job)}
      action={job.phase === 'download' ? { label: 'Cancel download', run: () => void api.bookCancel() } : null}
    />
  {:else if failed}
    <EmptyState
      tone="error"
      sentence={`${name(failed.id)} could not be put in use.`}
      sub={`${failed.message} The book you had is still in use.`}
      action={{ label: 'Try again', run: () => use(failed!.id) }}
    />
  {:else if done}
    <p class="quiet">{done}</p>
  {/if}
  <p class="quiet">{BOOK_SWITCH_LINE}</p>
{/if}

<style>
  .books {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    overflow: hidden;
  }
  li {
    display: grid;
    grid-template-columns: 14px minmax(0, 1fr) 72px auto;
    gap: var(--space-4);
    align-items: center;
    padding: 10px 12px;
    min-height: 26px;
  }
  li + li {
    border-top: 1px solid var(--divider);
  }
  li.active {
    background: var(--surface);
  }
  .radio {
    width: 12px;
    height: 12px;
    border-radius: 6px;
    border: 1.5px solid var(--disabled);
    box-sizing: border-box;
  }
  .radio.on {
    border: 4px solid var(--text);
  }
  .label {
    font-weight: 500;
  }
  .floor {
    color: var(--text-3);
    font: var(--secondary);
  }
  .size {
    text-align: right;
    color: var(--text-2);
  }
  .act {
    display: flex;
    justify-content: flex-end;
  }
  .inuse {
    display: flex;
    align-items: center;
    gap: 6px;
    font: var(--secondary);
    color: var(--text);
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 3px;
    background: var(--win);
  }
  .none {
    margin: 0;
  }
  .quiet {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
