<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import {
    accounts,
    saveAccounts,
    validateUsername,
    analysisDepth,
    saveAnalysisDepth,
    DEPTH_PRESETS,
  } from '../settings.svelte'
  import { sidecar, api } from '../api'
  import type {
    SyncStatus,
    SyncProgressEvent,
    SyncDoneEvent,
    SyncErrorEvent,
    SyncWarningEvent,
    EngineStatus,
  } from '../api'
  import { pickEngine } from '../pick'
  import { BETA } from '../build'
  import AboutBuild from '../AboutBuild.svelte'
  import { pendingSummary } from '../pendingLabel'
  import { addSyncWarning, syncWarningLines, type SyncWarning } from '../syncWarnings'

  // Local draft state so edits aren't persisted until Save.
  let lichess = $state(accounts.lichess)
  let chesscom = $state(accounts.chesscom)
  let saved = $state(false)

  const lichessError = $derived(validateUsername(lichess))
  const chesscomError = $derived(validateUsername(chesscom))
  const valid = $derived(lichessError === null && chesscomError === null)
  const dirty = $derived(lichess.trim() !== accounts.lichess || chesscom.trim() !== accounts.chesscom)

  function save() {
    if (!valid) return
    saveAccounts(lichess, chesscom)
    // reflect the trimmed canonical values back into the inputs
    lichess = accounts.lichess
    chesscom = accounts.chesscom
    saved = true
  }

  function onInput() {
    saved = false
  }

  // ── engine ──────────────────────────────────────────────────────────────────
  let engine = $state<EngineStatus | null>(null)
  let locating = $state(false)
  let locateError = $state('')
  let locatedName = $state('')

  async function refreshEngine() {
    try {
      engine = await api.engineStatus()
    } catch {
      /* sidecar may not be ready yet */
    }
  }

  async function locateEngine() {
    locateError = ''
    locatedName = ''
    const path = await pickEngine()
    if (path === null) return
    locating = true
    try {
      const res = await api.setStockfishPath(path)
      locatedName = res.name || path
      await refreshEngine()
    } catch (e) {
      locateError = e instanceof Error ? e.message : String(e)
    } finally {
      locating = false
    }
  }

  // ── game sync ───────────────────────────────────────────────────────────────
  let status = $state<SyncStatus | null>(null)
  let syncing = $state(false)
  let progress = $state<SyncProgressEvent | null>(null)
  let syncError = $state<string | null>(null)
  let syncWarnings = $state<SyncWarning[]>([])

  const hasAccount = $derived(accounts.lichess.length > 0 || accounts.chesscom.length > 0)
  // Sync uses the *saved* usernames (accounts.*), not the draft inputs, so block
  // it while there are unsaved edits — otherwise a stale saved handle gets synced
  // while the box shows the new one (e.g. fetching Lichess with an old username).
  const canSync = $derived(hasAccount && !syncing && !dirty)

  async function refreshStatus() {
    try {
      // Pass the chosen depth so the pending counts reflect which
      // games this depth would (re)analyze, not just the never-analyzed ones.
      status = await api.syncStatus(analysisDepth.value)
      syncing = status.syncing
    } catch {
      /* sidecar may not be ready yet */
    }
  }

  async function startSync() {
    if (!canSync) return
    syncError = null
    syncWarnings = []
    progress = { phase: 'fetching', done: 0, total: 0 }
    syncing = true
    try {
      await api.startSync(accounts.lichess, accounts.chesscom, analysisDepth.value)
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e)
      syncing = false
      progress = null
    }
  }

  function pickDepth(depth: number) {
    saveAnalysisDepth(depth)
    // Recompute the awaiting-analysis count for the new depth.
    refreshStatus()
  }

  function sourceLabel(s?: string): string {
    if (s === 'lichess') return 'Lichess'
    if (s === 'chesscom') return 'Chess.com'
    return ''
  }

  // ── color repair ──────────────────────────────────────────────────────────
  // Re-derives the player's side for synced/imported games by matching saved
  // usernames against the PGN headers. Fixes games stored before a username was
  // set (which defaulted to white). No re-fetch or re-analysis needed.
  let repairing = $state(false)
  let repairMsg = $state<string | null>(null)

  async function repairColors() {
    if (repairing) return
    repairMsg = null
    repairing = true
    try {
      const { changed } = await api.repairColors(accounts.lichess, accounts.chesscom)
      repairMsg = changed > 0 ? `Fixed ${changed} game${changed === 1 ? '' : 's'}.` : 'Colors already correct.'
    } catch (e) {
      repairMsg = e instanceof Error ? e.message : String(e)
    } finally {
      repairing = false
    }
  }

  function onProgress(data: SyncProgressEvent) {
    progress = data
    syncing = true
  }
  function onDone(_data: SyncDoneEvent) {
    // One platform finished; refresh counts but keep the spinner until
    // sync_finished signals the whole run is complete.
    refreshStatus()
  }
  function onFinished() {
    syncing = false
    progress = null
    refreshStatus()
  }
  function onError(data: SyncErrorEvent) {
    syncError = data.source
      ? `${sourceLabel(data.source)}: ${data.message}`
      : data.message
    refreshStatus()
  }

  function onWarning(data: SyncWarningEvent) {
    syncWarnings = addSyncWarning(syncWarnings, data)
  }

  onMount(() => {
    sidecar.on('sync_warning', onWarning)
    sidecar.on('sync_progress', onProgress)
    sidecar.on('sync_done', onDone)
    sidecar.on('sync_finished', onFinished)
    sidecar.on('sync_cancelled', onFinished)
    sidecar.on('sync_error', onError)
    refreshStatus()
    refreshEngine()
  })
  onDestroy(() => {
    sidecar.off('sync_warning', onWarning)
    sidecar.off('sync_progress', onProgress)
    sidecar.off('sync_done', onDone)
    sidecar.off('sync_finished', onFinished)
    sidecar.off('sync_cancelled', onFinished)
    sidecar.off('sync_error', onError)
  })
</script>

<div class="settings">
  <div class="inner">
    <header class="head">
      <p class="eyebrow">Settings</p>
      <h1 class="title">Settings</h1>
    </header>

    {#if BETA}<AboutBuild />{/if}

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Connected Accounts</h2>
        <p class="card-sub">Link your accounts to sync games into Insights.</p>
      </div>

      <div class="field">
        <label for="lichess">Lichess username</label>
        <input
          id="lichess"
          type="text"
          spellcheck="false"
          autocomplete="off"
          placeholder="e.g. DrNykterstein"
          bind:value={lichess}
          oninput={onInput}
        />
        {#if lichessError}<span class="error">{lichessError}</span>{/if}
      </div>

      <div class="field">
        <label for="chesscom">Chess.com username</label>
        <input
          id="chesscom"
          type="text"
          spellcheck="false"
          autocomplete="off"
          placeholder="e.g. MagnusCarlsen"
          bind:value={chesscom}
          oninput={onInput}
        />
        {#if chesscomError}<span class="error">{chesscomError}</span>{/if}
      </div>

      <div class="actions">
        <button class="btn btn-accent" disabled={!valid || !dirty} onclick={save}>Save</button>
        {#if saved && !dirty}<span class="ok">✓ Saved</span>{/if}
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Engine</h2>
        <p class="card-sub">
          Play, analysis and Insights all need Stockfish. Zugzwang finds it
          automatically when it is bundled or on your PATH; otherwise point it at
          the binary once and it is remembered.
        </p>
      </div>

      {#if engine === null}
        <p class="hint">Checking…</p>
      {:else if engine.ok}
        <code class="path">{engine.path}</code>
      {:else}
        <p class="error">Not found — play and analysis are disabled.</p>
      {/if}
      <div class="actions">
        <button class="btn btn-quiet" disabled={locating} onclick={locateEngine}>
          {locating ? 'Checking…' : engine?.ok ? 'Change…' : 'Locate Stockfish…'}
        </button>
        {#if locateError}<span class="error">{locateError}</span>{/if}
        {#if locatedName}<span class="ok">✓ {locatedName}</span>{/if}
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Analysis Depth</h2>
        <p class="card-sub">
          How deeply Stockfish searches each move during sync. Lower is much
          faster; higher is more accurate. Games already analyzed at this depth
          or deeper are skipped, so raising it re-analyzes, lowering it doesn't.
        </p>
      </div>

      <div class="depth-opts">
        {#each DEPTH_PRESETS as preset (preset.depth)}
          <button
            type="button"
            class="depth-opt"
            class:selected={analysisDepth.value === preset.depth}
            onclick={() => pickDepth(preset.depth)}
          >
            <span class="depth-label">{preset.label}</span>
            <span class="depth-depth">depth {preset.depth}</span>
            <span class="depth-blurb">{preset.blurb}</span>
          </button>
        {/each}
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Game Sync</h2>
        <p class="card-sub">
          Fetch your full game history from each connected platform and classify
          it for Insights.
        </p>
      </div>

      {#if !hasAccount}
        <p class="hint">Add and save a username above to enable syncing.</p>
      {:else}
        {#if status}
          {#if accounts.lichess.length > 0}
            <p class="hint">
              Lichess: {status.lichess.synced} synced{pendingSummary(status.lichess)}
            </p>
          {/if}
          {#if accounts.chesscom.length > 0}
            <p class="hint">
              Chess.com: {status.chesscom.synced} synced{pendingSummary(status.chesscom)}
            </p>
          {/if}
        {/if}

        {#if progress}
          <p class="hint">
            {#if progress.phase === 'fetching'}
              Fetching games from {sourceLabel(progress.source) || 'platform'}…
            {:else}
              Analyzing {sourceLabel(progress.source)} {progress.done} / {progress.total}…
            {/if}
          </p>
        {/if}

        {#if dirty}
          <p class="hint">You have unsaved username changes — save them before syncing.</p>
        {/if}

        {#if syncError}<span class="error">{syncError}</span>{/if}
        {#each syncWarningLines(syncWarnings, sourceLabel) as line, i (i)}
          <p class="hint">{line}</p>
        {/each}

        <div class="actions">
          <button class="btn btn-accent" disabled={!canSync} onclick={startSync}>
            {syncing ? 'Syncing…' : 'Sync games'}
          </button>
          {#if syncing}
            <button class="btn" onclick={() => api.cancelSync()}>Cancel</button>
          {/if}
        </div>

        <div class="actions">
          <button class="btn" disabled={syncing || repairing} onclick={repairColors}>
            {repairing ? 'Fixing…' : 'Fix game colors'}
          </button>
          {#if repairMsg}<span class="ok">{repairMsg}</span>{/if}
        </div>
      {/if}
    </section>
  </div>
</div>

<style>
  .settings {
    height: 100%;
    overflow-y: auto;
    position: relative;
  }
  .inner {
    position: relative;
    max-width: 560px;
    margin: 0 auto;
    padding: 56px 32px 48px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }
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
  .title {
    margin: 0;
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }

  .card {
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .card-head {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .card-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .card-sub {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .field label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
  }
  .field input {
    width: 100%;
    padding: 8px 12px;
    user-select: text;
  }
  .error {
    font-size: 12px;
    color: var(--danger);
  }
  .hint {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .path {
    font-size: 11.5px;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 6px 9px;
    word-break: break-all;
    user-select: text;
    color: var(--text-muted);
  }

  .depth-opts {
    display: flex;
    gap: 10px;
  }
  .depth-opt {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px;
    text-align: left;
    background: var(--bg-base, transparent);
    border: 1px solid var(--divider);
    border-radius: var(--radius-md, 8px);
    cursor: pointer;
    transition: border-color 0.12s ease, background 0.12s ease;
  }
  .depth-opt:hover {
    border-color: var(--accent);
  }
  .depth-opt.selected {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .depth-label {
    font-size: 13px;
    font-weight: 600;
  }
  .depth-depth {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .depth-blurb {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.3;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 2px;
  }
  .ok {
    font-size: 12.5px;
    color: var(--text-muted);
  }
</style>
