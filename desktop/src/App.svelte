<script lang="ts">
  import { onMount } from 'svelte'
  import { Chess } from 'chess.js'
  import HomeScreen from './lib/screens/HomeScreen.svelte'
  import PlayScreen from './lib/screens/PlayScreen.svelte'
  import GamesScreen from './lib/screens/GamesScreen.svelte'
  import ReviewScreen from './lib/screens/ReviewScreen.svelte'
  import PuzzlesScreen from './lib/screens/PuzzlesScreen.svelte'
  import TrainerScreen from './lib/screens/TrainerScreen.svelte'
  import SettingsScreen from './lib/screens/SettingsScreen.svelte'
  import InsightsScreen from './lib/screens/InsightsScreen.svelte'
  import {
    api,
    sidecar,
    type SidecarStatus,
    type RelabelStatus,
    type RelabelResult,
  } from './lib/api'
  import { theme, toggleTheme, applyTheme } from './lib/theme.svelte'
  import { BETA } from './lib/build'
  import UpdateCheck from './lib/UpdateCheck.svelte'

  type Route = 'home' | 'play' | 'games' | 'review' | 'puzzles' | 'trainer' | 'insights' | 'settings'
  type NavItem = { label: string; route: Route }

  const ALL_NAV: NavItem[] = [
    { label: 'Play', route: 'play' },
    { label: 'Puzzles', route: 'puzzles' },
    { label: 'Opening Trainer', route: 'trainer' },
    { label: 'Past Games', route: 'games' },
    { label: 'Insights', route: 'insights' },
  ]
  // Beta builds hide the opening trainer: there is no book (W20; BETA scope 2).
  const NAV = BETA ? ALL_NAV.filter((n) => n.route !== 'trainer') : ALL_NAV

  let route = $state<Route>('home')
  let reviewTarget = $state<{ gameId?: number; fen?: string; ply?: number } | null>(null)
  // where a Back from the review/analysis screen should return to
  let reviewOrigin = $state<Route>('games')
  let spawnError = $state('')
  let backend = $state<SidecarStatus>('starting')
  let play: PlayScreen | undefined = $state()
  // deep-link: an opening picked from Insights to train directly
  let trainerOpening = $state<{ eco: string; name: string } | null>(null)

  // ── FEN analysis modal (the Analysis front door) ──────────────────────────
  const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  let fenModal = $state(false)
  let fenInput = $state('')
  let fenError = $state('')

  applyTheme()

  function openReview(gameId: number) {
    reviewOrigin = 'games'
    reviewTarget = { gameId }
    route = 'review'
  }
  // R6: a ply behind an Insights pattern, opened in Review; Back returns to Insights.
  function openReviewAt(gameId: number, ply: number) {
    reviewOrigin = 'insights'
    reviewTarget = { gameId, ply }
    route = 'review'
  }
  function openFenReview(fen: string, origin: Route = 'games') {
    reviewOrigin = origin
    reviewTarget = { fen }
    route = 'review'
  }
  function playFromFen(fen: string) {
    route = 'play'
    play?.startFromFen(fen)
  }
  function navTo(r: Route) {
    route = r
    if (r !== 'review') reviewTarget = null
  }

  function openFenModal() {
    fenInput = ''
    fenError = ''
    fenModal = true
  }
  function focusOnMount(node: HTMLInputElement) {
    node.focus()
  }
  function submitFen(fen: string) {
    const trimmed = fen.trim()
    try {
      new Chess(trimmed)
    } catch {
      fenError = 'That doesn’t look like a valid FEN.'
      return
    }
    fenModal = false
    openFenReview(trimmed, 'home')
  }

  function railActive(item: NavItem): boolean {
    if (item.route === 'games') return route === 'games' || route === 'review'
    return item.route === route
  }

  // Tell the sidecar which screen is on view: its engine budget reserves live play
  // while Play is open and the FEN path while Review or Puzzles is, and gives bulk
  // analysis the rest. Re-sent whenever the backend comes (back) up, since a
  // respawned sidecar starts with no screen.
  $effect(() => {
    if (backend === 'up') api.setActiveScreen(route).catch(() => {})
  })

  // ── relabel on update (BETA item 5) ──────────────────────────────────────
  // The sidecar relabels runs an older classifier wrote, on open, in the background.
  // Its events can fire before this subscribes, so the state is also asked for.
  let relabel = $state<RelabelStatus | null>(null)
  let relabelDismissed = $state(false)
  $effect(() => {
    if (backend !== 'up') return
    api.relabelStatus().then((r) => (relabel = r)).catch(() => {})
  })
  const onRelabelProgress = (d: { done: number; total: number }) =>
    (relabel = { state: 'running', done: d.done, total: d.total, result: null, error: null })
  const onRelabelDone = (d: RelabelResult) =>
    (relabel = { state: 'done', done: d.runs, total: d.runs, result: d, error: null })
  const onRelabelError = (d: { message: string }) =>
    (relabel = { state: 'error', done: 0, total: 0, result: null, error: d.message })

  onMount(() => {
    sidecar.on('relabel_progress', onRelabelProgress)
    sidecar.on('relabel_done', onRelabelDone)
    sidecar.on('relabel_error', onRelabelError)
    const unsubscribe = sidecar.onStatus((s) => (backend = s))
    sidecar.start().catch((e) => (spawnError = String(e)))
    return unsubscribe
  })
</script>

<div class="shell">
  <nav class="rail">
    <button class="wordmark" class:active={route === 'home'} onclick={() => navTo('home')}>
      Zugzwang
    </button>
    <div class="nav-items">
      {#each NAV as item (item.label)}
        <button class="nav-item" class:active={railActive(item)} onclick={() => navTo(item.route)}>
          {item.label}
        </button>
      {/each}
    </div>
    <button
      class="nav-item nav-item-bottom"
      class:active={route === 'settings'}
      onclick={() => navTo('settings')}
    >
      Settings
    </button>
    <button class="theme-toggle" onclick={toggleTheme} aria-label="Toggle theme">
      {theme.mode === 'dark' ? 'Light theme' : 'Dark theme'}
    </button>
  </nav>

  <main class="content">
    {#if spawnError}
      <div class="spawn-error">Could not start the engine sidecar: {spawnError}</div>
    {:else}
      <!-- PlayScreen stays mounted so a running game survives navigation -->
      <div class="screen" style:display={route === 'play' ? '' : 'none'}>
        <PlayScreen bind:this={play} onreview={openReview} active={route === 'play'} />
      </div>
      {#if route === 'home'}
        <HomeScreen onnav={navTo} onanalyze={openFenModal} />
      {:else if route === 'games'}
        <GamesScreen onopen={openReview} onfen={(fen) => openFenReview(fen, 'games')} onnav={navTo} />
      {:else if route === 'review' && reviewTarget}
        <ReviewScreen
          gameId={reviewTarget.gameId ?? null}
          fen={reviewTarget.fen ?? null}
          ply={reviewTarget.ply ?? null}
          onback={() => navTo(reviewOrigin)}
          onplayfen={playFromFen}
        />
      {:else if route === 'puzzles'}
        <PuzzlesScreen />
      {:else if route === 'trainer' && !BETA}
        <TrainerScreen
          onplayfen={playFromFen}
          openingRequest={trainerOpening}
          onrequesthandled={() => (trainerOpening = null)}
        />
      {:else if route === 'insights'}
        <InsightsScreen
          ontrain={BETA
            ? undefined
            : (op) => {
                trainerOpening = op
                navTo('trainer')
              }}
          onconnect={() => navTo('settings')}
          onopen={openReviewAt}
        />
      {:else if route === 'settings'}
        <SettingsScreen />
      {/if}
    {/if}
  </main>
</div>

<!-- Overlaid rather than placed in the layout: every screen needs the backend,
     so this has to be visible from all of them without any of them reserving
     space for a bar that is almost never there. -->
{#if backend === 'restarting'}
  <div class="backend-banner" role="status">
    <span class="pulse-dot"></span> The engine backend stopped. Restarting…
  </div>
{:else if backend === 'down'}
  <div class="backend-banner down" role="alert">
    The engine backend stopped and could not be restarted. Quit and reopen Zugzwang.
  </div>
{/if}

<UpdateCheck />

<!-- Relabel on update (BETA item 5): at the bottom, so a backend notice stays on top. -->
{#if relabel && !relabelDismissed && (relabel.state === 'running' || relabel.state === 'done' || relabel.state === 'error')}
  <div class="backend-banner relabel" class:down={relabel.state === 'error'} role="status">
    {#if relabel.state === 'running'}
      <span class="pulse-dot"></span>
      Updating move labels to the new classifier: {relabel.done} of {relabel.total} games.
      A backup was taken first; you can keep using the app.
    {:else if relabel.state === 'done'}
      Move labels updated for {relabel.result?.runs ?? 0} games
      ({relabel.result?.labelsChanged ?? 0} labels changed). Backup: {relabel.result?.backup}
      <button class="banner-x" onclick={() => (relabelDismissed = true)}>Dismiss</button>
    {:else}
      Could not update move labels: {relabel.error}. Your games are unchanged where the update
      did not reach them.
      <button class="banner-x" onclick={() => (relabelDismissed = true)}>Dismiss</button>
    {/if}
  </div>
{/if}

{#if fenModal}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="-1"
    onclick={() => (fenModal = false)}
    onkeydown={(e) => e.key === 'Escape' && (fenModal = false)}
  >
    <div
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-label="Analyze a position"
      tabindex="0"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <h2 class="modal-title">Analyze a position</h2>
      <p class="modal-sub">Paste a FEN to open it on the analysis board.</p>
      <input
        type="text"
        bind:value={fenInput}
        placeholder="rnbqkbnr/pppppppp/8/8/…"
        spellcheck="false"
        use:focusOnMount
        oninput={() => (fenError = '')}
        onkeydown={(e) => e.key === 'Enter' && submitFen(fenInput)}
      />
      {#if fenError}<span class="modal-error">{fenError}</span>{/if}
      <div class="modal-actions">
        <button class="btn btn-quiet" onclick={() => submitFen(START_FEN)}>
          Starting position
        </button>
        <button class="btn btn-accent" disabled={!fenInput.trim()} onclick={() => submitFen(fenInput)}>
          Analyze
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .shell {
    height: 100vh;
    display: flex;
  }

  .rail {
    width: 188px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg-surface);
    border-right: 1px solid var(--divider);
    padding: 16px 0 14px;
  }
  .wordmark {
    margin: 0 8px 18px;
    padding: 8px 10px;
    font-weight: 700;
    font-size: 17px;
    letter-spacing: -0.02em;
    text-align: left;
    border-radius: var(--radius-sm);
    transition: background-color 120ms ease;
  }
  .wordmark::first-letter {
    color: var(--accent);
  }
  .wordmark:hover,
  .wordmark.active {
    background: var(--bg-raised);
  }
  .nav-items {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    padding: 0 8px;
  }
  .nav-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    border-radius: var(--radius-sm);
    font-size: 13.5px;
    font-weight: 500;
    color: var(--text-muted);
    text-align: left;
    transition:
      color 120ms ease,
      background-color 120ms ease;
  }
  .nav-item::before {
    content: '';
    width: 3px;
    height: 16px;
    border-radius: 2px;
    background: transparent;
    transition: background-color 120ms ease;
  }
  .nav-item:hover {
    color: var(--text);
    background: var(--bg-raised);
  }
  .nav-item.active {
    color: var(--text);
    background: var(--bg-raised);
  }
  .nav-item.active::before {
    background: var(--accent);
  }
  .nav-item-bottom {
    margin: 0 8px 6px;
  }
  .theme-toggle {
    margin: 0 14px;
    padding: 7px 0;
    font-size: 12px;
    color: var(--text-muted);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    transition:
      color 120ms ease,
      border-color 120ms ease;
  }
  .theme-toggle:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .content {
    flex: 1;
    min-width: 0;
    background: var(--bg-deep);
  }
  .screen {
    height: 100%;
  }
  .spawn-error {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--danger);
    user-select: text;
  }

  .backend-banner {
    position: fixed;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1100;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 16px;
    font-size: 13px;
    color: var(--text);
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-pop);
    animation: pop 160ms cubic-bezier(0.2, 0.7, 0.2, 1);
  }
  .backend-banner.relabel {
    top: auto;
    bottom: 12px;
    max-width: min(760px, calc(100vw - 32px));
    flex-wrap: wrap;
  }
  .banner-x {
    border: none;
    background: none;
    padding: 0 0 0 6px;
    color: var(--accent);
    cursor: pointer;
    font-size: 12.5px;
  }
  .backend-banner.down {
    color: var(--danger);
    border-color: var(--danger);
  }

  /* ── FEN modal ── */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.55);
    animation: fade 140ms ease;
  }
  .modal {
    width: 460px;
    max-width: 90vw;
    padding: 22px;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-pop);
    animation: pop 160ms cubic-bezier(0.2, 0.7, 0.2, 1);
  }
  .modal-title {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .modal-sub {
    margin: 6px 0 14px;
    font-size: 13px;
    color: var(--text-muted);
  }
  .modal input {
    width: 100%;
    user-select: text;
    font-size: 13px;
    padding: 9px 12px;
  }
  .modal-error {
    display: block;
    margin-top: 8px;
    font-size: 12.5px;
    color: var(--danger);
  }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 18px;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: translateY(8px) scale(0.98);
    }
  }
</style>
