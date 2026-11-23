<script lang="ts">
  /**
   * Settings, rebuilt (UI-BUILD-2 E1; DESIGN.md "Settings", rulings 17 and 20; mockup
   * design/mockups/MinimalSettings.html): Accounts, Game sync, Engine, Opening book,
   * Appearance, then the existing features the mockup leaves out (Maintenance, About) at the
   * foot in the same language. Every figure is read from sync_status, engine_status,
   * books_status or the last-sync stamps; a part with no data is not drawn.
   */
  import { onDestroy, onMount } from 'svelte'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import { accounts, saveAccounts, validateUsername } from '../settings.svelte'
  import { lastSynced, markSynced } from '../gamesFilter.svelte'
  import { pickEngine } from '../pick'
  import { registerCommands } from '../shell/commands.svelte'
  import {
    sidecar,
    api,
    type EngineStatus,
    type SyncDoneEvent,
    type SyncErrorEvent,
    type SyncProgressEvent,
    type SyncStatus,
    type SyncWarningEvent,
  } from '../api'
  import { addSyncWarning, syncWarningLines, type SyncWarning } from '../syncWarnings'
  import {
    DEPTH_LINE,
    SOURCE_NAME,
    attentionLine,
    checkLine,
    checksAnswered,
    checksFailed,
    checksStarted,
    connected,
    engineSource,
    engineTitle,
    finishedText,
    importedLine,
    progressFraction,
    progressText,
    waitingLine,
    type CheckState,
    type Source,
  } from './settingsModel'
  import BookSection from './BookSection.svelte'
  import AppearanceSection from './AppearanceSection.svelte'
  import AboutSection from './AboutSection.svelte'
  import FriendsSection from './FriendsSection.svelte'
  import { SHOW_FRIENDS } from '../build'

  interface Props {
    onnav?: (route: 'games') => void
  }
  let { onnav }: Props = $props()

  // ── accounts: a draft, saved on Save ────────────────────────────────────────
  let chesscom = $state(accounts.chesscom)
  let lichess = $state(accounts.lichess)
  let saved = $state(false)
  let chesscomInput: HTMLInputElement | undefined = $state()
  const errors = $derived({ chesscom: validateUsername(chesscom), lichess: validateUsername(lichess) })
  const valid = $derived(errors.chesscom === null && errors.lichess === null)
  const dirty = $derived(lichess.trim() !== accounts.lichess || chesscom.trim() !== accounts.chesscom)
  function save() {
    if (!valid || !dirty) return
    saveAccounts(lichess, chesscom)
    lichess = accounts.lichess
    chesscom = accounts.chesscom
    saved = true
    void refreshSync()
    void checkSaved()
  }

  // ── the username check (UI-BUILD-3 G, ruling 5): after the save, never before it ──
  let checks = $state<Record<Source, CheckState | null>>({ chesscom: null, lichess: null })
  // the names the checks are about: a field edited since shows no stale answer
  let checkedNames = $state({ chesscom: '', lichess: '' })
  let checkToken = 0
  async function checkSaved() {
    const names = { chesscom: accounts.chesscom, lichess: accounts.lichess }
    const token = ++checkToken
    const started = checksStarted(names)
    checks = started
    checkedNames = names
    if (!started.chesscom && !started.lichess) return
    try {
      const reply = await api.checkUsernames(names)
      if (token === checkToken) checks = checksAnswered(started, reply)
    } catch (e) {
      if (token === checkToken) checks = checksFailed(started, e instanceof Error ? e.message : String(e))
    }
  }
  const lines = $derived({
    chesscom: chesscom.trim() === checkedNames.chesscom ? checkLine('chesscom', checkedNames.chesscom, checks.chesscom) : null,
    lichess: lichess.trim() === checkedNames.lichess ? checkLine('lichess', checkedNames.lichess, checks.lichess) : null,
  })

  // ── game sync ───────────────────────────────────────────────────────────────
  let status = $state<SyncStatus | null>(null)
  let statusError = $state<string | null>(null)
  type Phase = 'idle' | 'running' | 'finished' | 'failed'
  let phase = $state<Phase>('idle')
  let progress = $state<SyncProgressEvent | null>(null)
  let runDone = $state<SyncDoneEvent[]>([])
  let runErrors = $state<string[]>([])
  let warnings = $state<SyncWarning[]>([])
  const sources = $derived(connected(accounts))
  const canSync = $derived(sources.length > 0 && !dirty && phase !== 'running' && !status?.syncing)

  async function refreshSync() {
    try {
      status = await api.syncStatus()
      statusError = null
      if (status.syncing && phase !== 'running') phase = 'running'
    } catch (e) {
      statusError = e instanceof Error ? e.message : String(e)
    }
  }

  async function syncNow() {
    if (!canSync) return
    runDone = []
    runErrors = []
    warnings = []
    progress = { phase: 'fetching', done: 0, total: 0 }
    phase = 'running'
    try {
      await api.startSync(accounts.lichess, accounts.chesscom)
    } catch (e) {
      runErrors = [e instanceof Error ? e.message : String(e)]
      phase = 'failed'
      progress = null
    }
  }

  const label = (s: string) => SOURCE_NAME[s as Source] ?? ''
  const onProgress = (d: SyncProgressEvent) => {
    progress = d
    phase = 'running'
  }
  const onDone = (d: SyncDoneEvent) => {
    runDone = [...runDone, d]
    if (d.source === 'lichess' || d.source === 'chesscom') markSynced(d.source)
    void refreshSync()
  }
  const onError = (d: SyncErrorEvent) => {
    runErrors = [...runErrors, d.source ? `${label(d.source)}: ${d.message}` : d.message]
  }
  const onWarning = (d: SyncWarningEvent) => (warnings = addSyncWarning(warnings, d))
  const onFinished = () => {
    if (phase === 'running') phase = runErrors.length ? 'failed' : 'finished'
    progress = null
    void refreshSync()
  }
  const onCancelled = () => {
    phase = 'idle'
    progress = null
  }

  // ── engine ──────────────────────────────────────────────────────────────────
  let engine = $state<EngineStatus | null>(null)
  let engineError = $state<string | null>(null)
  let picking = $state(false)
  let pickError = $state<string | null>(null)
  let pickNote = $state<string | null>(null)
  async function refreshEngine() {
    try {
      engine = await api.engineStatus()
      engineError = null
    } catch (e) {
      engineError = e instanceof Error ? e.message : String(e)
    }
  }
  async function chooseEngine() {
    pickError = null
    pickNote = null
    const path = await pickEngine()
    if (path === null) return
    picking = true
    try {
      const res = await api.setStockfishPath(path)
      await refreshEngine()
      // find_stockfish ranks the bundled binary ahead of a saved pick (CLAUDE.md), so say so
      // rather than show a choice that analysis will not use.
      if (engine?.path && engine.path !== res.path)
        pickNote = `Saved ${res.name || path}. The bundled Stockfish comes first while it is present, so analysis keeps using it.`
    } catch (e) {
      pickError = e instanceof Error ? e.message : String(e)
    } finally {
      picking = false
    }
  }

  let off: (() => void) | null = null
  onMount(() => {
    sidecar.on('sync_progress', onProgress)
    sidecar.on('sync_done', onDone)
    sidecar.on('sync_error', onError)
    sidecar.on('sync_warning', onWarning)
    sidecar.on('sync_finished', onFinished)
    sidecar.on('sync_cancelled', onCancelled)
    void refreshSync()
    void refreshEngine()
    off = registerCommands('settings', () => [
      ...(canSync ? [{ id: 'settings-sync', group: 'Actions', label: 'Sync now', run: syncNow }] : []),
      { id: 'settings-engine', group: 'Actions', label: 'Use a different Stockfish binary', run: chooseEngine },
    ])
  })
  onDestroy(() => {
    sidecar.off('sync_progress', onProgress)
    sidecar.off('sync_done', onDone)
    sidecar.off('sync_error', onError)
    sidecar.off('sync_warning', onWarning)
    sidecar.off('sync_finished', onFinished)
    sidecar.off('sync_cancelled', onCancelled)
    off?.()
  })

  // ── maintenance: fix game colours (kept from the old screen) ────────────────
  let repairing = $state(false)
  let repairMsg = $state<string | null>(null)
  async function repairColors() {
    repairing = true
    repairMsg = null
    try {
      const { changed } = await api.repairColors(accounts.lichess, accounts.chesscom)
      repairMsg = changed > 0 ? `Fixed the side you played in ${changed} ${changed === 1 ? 'game' : 'games'}.` : 'Every game already has the right side.'
    } catch (e) {
      repairMsg = e instanceof Error ? e.message : String(e)
    } finally {
      repairing = false
    }
  }
</script>

<div class="settings">
  <header>
    <h1>Settings</h1>
  </header>

  <main>
    <section aria-labelledby="s-accounts">
      <div class="lead">
        <h2 id="s-accounts">Accounts</h2>
        <p>Your usernames, so your games can be imported.</p>
      </div>
      <div class="body">
        <label class="acct">
          <span class="name">Chess.com</span>
          <input
            bind:this={chesscomInput}
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="Username"
            bind:value={chesscom}
            oninput={() => (saved = false)}
            onkeydown={(e) => e.key === 'Enter' && save()}
          />
          <span class="state" aria-live="polite">
            {#if errors.chesscom}<span class="err">{errors.chesscom}</span>
            {:else if lines.chesscom}<span class="check {lines.chesscom.tone}" title={lines.chesscom.detail}>{lines.chesscom.text}</span>{/if}
          </span>
        </label>
        <label class="acct">
          <span class="name">Lichess</span>
          <input
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="Username"
            bind:value={lichess}
            oninput={() => (saved = false)}
            onkeydown={(e) => e.key === 'Enter' && save()}
          />
          <span class="state" aria-live="polite">
            {#if errors.lichess}<span class="err">{errors.lichess}</span>
            {:else if lines.lichess}<span class="check {lines.lichess.tone}" title={lines.lichess.detail}>{lines.lichess.text}</span>{/if}
          </span>
        </label>
        <div class="row-actions">
          <Button disabled={!valid || !dirty} onclick={save}>Save</Button>
          {#if saved && !dirty}<span class="note">Saved</span>{:else if dirty && valid}<span class="note">Not saved yet</span>{/if}
        </div>
      </div>
    </section>

    {#if SHOW_FRIENDS}
      <section aria-labelledby="s-friends">
        <div class="lead">
          <h2 id="s-friends">Friends</h2>
          <p>Your handle, what friends can see, and chat.</p>
        </div>
        <div class="body"><FriendsSection /></div>
      </section>
    {/if}

    <section aria-labelledby="s-sync">
      <div class="lead">
        <h2 id="s-sync">Game sync</h2>
        <p>Imports new games and analyses them.</p>
      </div>
      <div class="body">
        {#if sources.length === 0}
          <EmptyState
            sentence="No account to sync yet."
            sub="Add your Chess.com or Lichess username above, then Save."
            action={{ label: 'Add a username', run: () => chesscomInput?.focus() }}
          />
        {:else if statusError && !status}
          <EmptyState
            tone="error"
            sentence="Your sync status could not be read."
            sub={statusError}
            action={{ label: 'Try again', run: refreshSync }}
          />
        {:else if !status}
          <p class="quiet">Reading your games…</p>
        {:else}
          <div class="sync-row">
            <div>
              <div class="strong">{waitingLine(status, sources)}</div>
              <div class="sub">{importedLine(status, sources, lastSynced)}</div>
            </div>
            <!-- one primary per screen: with no engine, choosing one is it -->
            <Button variant={engine && !engine.ok ? 'ghost' : 'primary'} disabled={!canSync} onclick={syncNow}>Sync now</Button>
          </div>
          {#if dirty}<p class="quiet">Save your usernames before syncing.</p>{/if}
          {#if attentionLine(status, sources)}<p class="quiet">{attentionLine(status, sources)}</p>{/if}
          {#if phase === 'running'}
            <EmptyState
              sentence={progressText(progress)}
              sub="You can keep using the app; new games appear as they are analysed."
              progress={progressFraction(progress)}
              action={{ label: 'Cancel', run: () => void api.cancelSync() }}
            />
          {:else if phase === 'finished'}
            <EmptyState
              sentence={finishedText(runDone)}
              sub={syncWarningLines(warnings, label).join(' ') || null}
              action={{ label: 'Open Games', run: () => onnav?.('games') }}
            />
          {:else if phase === 'failed'}
            <EmptyState
              tone="error"
              sentence="The sync stopped."
              sub={[...runErrors, ...syncWarningLines(warnings, label)].join(' ')}
              action={{ label: 'Try again', run: syncNow }}
            />
          {/if}
        {/if}
        <p class="quiet">{DEPTH_LINE}</p>
      </div>
    </section>

    <section aria-labelledby="s-engine">
      <div class="lead">
        <h2 id="s-engine">Engine</h2>
        <p>Stockfish plays your games and analyses them.</p>
      </div>
      <div class="body">
        {#if engineError && !engine}
          <EmptyState
            tone="error"
            sentence="The engine's status could not be read."
            sub={engineError}
            action={{ label: 'Try again', run: refreshEngine }}
          />
        {:else if !engine}
          <p class="quiet">Looking for Stockfish…</p>
        {:else if !engine.ok}
          <EmptyState
            tone="error"
            sentence="Stockfish was not found, so play and analysis are off."
            sub="Choose a Stockfish binary on this computer; it is checked before it is used."
            action={{ label: picking ? 'Checking…' : 'Choose a Stockfish binary', run: chooseEngine, primary: true }}
          />
        {:else}
          <div class="engine">
            <div>
              <div class="strong dotted"><span class="dot win" aria-hidden="true"></span>{engineTitle(engine)}</div>
              <div class="sub" title={engine.path ?? ''}>{engineSource(engine)}</div>
            </div>
            <Button size="sm" disabled={picking} onclick={chooseEngine}>{picking ? 'Checking…' : 'Use a different binary'}</Button>
          </div>
        {/if}
        {#if pickError}
          <EmptyState
            tone="error"
            sentence="That file is not a usable Stockfish."
            sub={pickError}
            action={{ label: 'Choose another', run: chooseEngine }}
          />
        {/if}
        {#if pickNote}<p class="quiet">{pickNote}</p>{/if}
      </div>
    </section>

    <section aria-labelledby="s-book">
      <div class="lead">
        <h2 id="s-book">Opening book</h2>
        <p>Labels book moves and runs the opening trainer. Downloads from GitHub.</p>
      </div>
      <div class="body"><BookSection /></div>
    </section>

    <section aria-labelledby="s-appearance">
      <div class="lead">
        <h2 id="s-appearance">Appearance</h2>
        <p>How the board looks everywhere in the app.</p>
      </div>
      <div class="body"><AppearanceSection /></div>
    </section>

    <section aria-labelledby="s-maint">
      <div class="lead">
        <h2 id="s-maint">Maintenance</h2>
        <p>Repairs to games already imported.</p>
      </div>
      <div class="body">
        <div class="sync-row">
          <div>
            <div class="strong">Fix game colours</div>
            <div class="sub">Reads which side you played in each synced game again, from its players' names.</div>
          </div>
          <Button size="sm" disabled={repairing || phase === 'running' || sources.length === 0} onclick={repairColors}>
            {repairing ? 'Fixing…' : 'Fix game colours'}
          </Button>
        </div>
        {#if repairMsg}<p class="quiet">{repairMsg}</p>{/if}
      </div>
    </section>

    <section aria-labelledby="s-about" class="last">
      <div class="lead">
        <h2 id="s-about">About</h2>
        <p>This build, its files and its licences.</p>
      </div>
      <div class="body"><AboutSection /></div>
    </section>
  </main>
</div>

<style>
  .settings {
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
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  main {
    padding: 4px var(--space-8) var(--space-8);
    max-width: 900px;
    width: 100%;
    box-sizing: border-box;
  }
  section {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: 32px;
    padding: var(--space-7) 0;
    border-bottom: 1px solid var(--border);
  }
  section.last {
    border-bottom: 0;
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
  }
  .lead p {
    margin: 4px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .body {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .acct {
    display: grid;
    /* the third column is the mockup's 140px widened for the username check's longer lines
       (UI-BUILD-3 G): "No Chess.com player named …" on one line */
    grid-template-columns: 140px minmax(0, 1fr) 200px;
    align-items: center;
    gap: var(--space-4);
  }
  .name {
    color: var(--text-2);
  }
  input {
    font: var(--body);
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 6px 10px;
    color: var(--text);
    user-select: text;
    min-width: 0;
  }
  input::placeholder {
    color: var(--text-3);
  }
  input:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .state {
    font: var(--secondary);
  }
  .err {
    color: var(--loss);
  }
  /* The check's answer (as the mockup's "Found"): secondary text after a 6px dot, green when
     found, red when the site has no such player, grey when it could not be asked; none while
     checking. */
  .check {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    color: var(--text-2);
  }
  .check::before {
    content: '';
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 3px;
    transform: translateY(-1px);
    background: var(--draw);
  }
  .check.found::before {
    background: var(--win);
  }
  .check.missing::before {
    background: var(--loss);
  }
  .check.checking,
  .check.unreachable {
    color: var(--text-3);
  }
  .check.checking::before {
    display: none;
  }
  .row-actions {
    display: flex;
    align-items: center;
    gap: var(--space-4);
  }
  .note,
  .quiet {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .sync-row,
  .engine {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
  }
  .engine {
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .strong {
    font-weight: 500;
  }
  .sub {
    color: var(--text-3);
    font: var(--secondary);
  }
  .dotted {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 3px;
    flex: none;
  }
  .dot.win {
    background: var(--win);
  }
</style>
