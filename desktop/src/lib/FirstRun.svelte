<script lang="ts">
  /** The first-run path (BETA item 3): no account yet → enter a handle, and one button
   *  saves it, fetches the games and starts analysing them, with nothing else to set up.
   *  Shown on Home while no account is connected; it stays up to report progress once a
   *  sync it started is running. The same accounts and sync as Settings — no new state. */
  import { onMount, onDestroy } from 'svelte'
  import { accounts, saveAccounts, validateUsername } from './settings.svelte'
  import { api, sidecar, type SyncProgressEvent, type SyncErrorEvent } from './api'

  interface Props {
    onopengames: () => void
  }
  let { onopengames }: Props = $props()

  let lichess = $state(accounts.lichess)
  let chesscom = $state(accounts.chesscom)
  let started = $state(false)
  let finished = $state(false)
  let progress = $state<SyncProgressEvent | null>(null)
  let error = $state('')

  const lichessError = $derived(validateUsername(lichess))
  const chesscomError = $derived(validateUsername(chesscom))
  const canStart = $derived(
    !started && lichessError === null && chesscomError === null &&
      (lichess.trim().length > 0 || chesscom.trim().length > 0),
  )

  async function start() {
    if (!canStart) return
    error = ''
    saveAccounts(lichess, chesscom)
    started = true
    finished = false
    progress = { phase: 'fetching', done: 0, total: 0 }
    try {
      await api.startSync(accounts.lichess, accounts.chesscom)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      started = false
      progress = null
    }
  }

  function sourceLabel(s?: string): string {
    return s === 'lichess' ? 'Lichess' : s === 'chesscom' ? 'Chess.com' : 'your account'
  }

  const onProgress = (d: SyncProgressEvent) => (progress = d)
  const onFinished = () => {
    finished = true
    progress = null
  }
  const onError = (d: SyncErrorEvent) => {
    error = d.source ? `${sourceLabel(d.source)}: ${d.message}` : d.message
  }

  onMount(() => {
    sidecar.on('sync_progress', onProgress)
    sidecar.on('sync_finished', onFinished)
    sidecar.on('sync_cancelled', onFinished)
    sidecar.on('sync_error', onError)
  })
  onDestroy(() => {
    sidecar.off('sync_progress', onProgress)
    sidecar.off('sync_finished', onFinished)
    sidecar.off('sync_cancelled', onFinished)
    sidecar.off('sync_error', onError)
  })
</script>

<section class="first-run" aria-label="Get started">
  <div class="head">
    <h2 class="title">Start with your own games</h2>
    <p class="sub">
      Enter your Lichess or Chess.com username. Zugzwang fetches your games and analyses
      each one with Stockfish on this computer. Games appear in Past Games once fetched, and each
      game's review as soon as its analysis finishes. Nothing is uploaded.
    </p>
  </div>

  {#if !started}
    <div class="fields">
      <label class="field">
        <span>Lichess username</span>
        <input type="text" spellcheck="false" autocomplete="off" bind:value={lichess}
               placeholder="optional" />
        {#if lichessError}<span class="error">{lichessError}</span>{/if}
      </label>
      <label class="field">
        <span>Chess.com username</span>
        <input type="text" spellcheck="false" autocomplete="off" bind:value={chesscom}
               placeholder="optional" />
        {#if chesscomError}<span class="error">{chesscomError}</span>{/if}
      </label>
    </div>
    <div class="actions">
      <button class="btn btn-accent" disabled={!canStart} onclick={start}>
        Connect and analyse my games
      </button>
    </div>
  {:else}
    <p class="status" role="status">
      {#if finished}
        Done. Your games are in Past Games. Your 100 most recent games on each account are
        analysed; older ones can be analysed from Past Games with <em>Analyse more</em>.
      {:else if progress?.phase === 'analyzing'}
        Analysing your most recent {sourceLabel(progress.source)} games, newest first:
        {progress.done} of {progress.total}.
        You can use the app meanwhile.
      {:else}
        Fetching your games from {sourceLabel(progress?.source)}…
      {/if}
    </p>
    <div class="actions">
      <button class="btn btn-accent" onclick={onopengames}>Open Past Games</button>
    </div>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .first-run {
    position: relative;
    margin-bottom: 28px;
    padding: 22px 24px;
    background: var(--bg-surface);
    border: 1px solid var(--accent);
    border-radius: var(--radius-lg);
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .sub,
  .status {
    margin: 6px 0 0;
    font-size: 13.5px;
    color: var(--text-muted);
    line-height: 1.45;
  }
  .fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
  }
  .field input {
    padding: 8px 12px;
    font-weight: 400;
    user-select: text;
  }
  .actions {
    display: flex;
    gap: 12px;
  }
  .error {
    margin: 0;
    font-size: 12.5px;
    color: var(--danger);
  }
</style>
