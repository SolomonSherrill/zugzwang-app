<script lang="ts">
  import { onMount } from 'svelte'
  import PlayView from './lib/play/PlayView.svelte'
  import GamesView from './lib/games/GamesView.svelte'
  import PositionPopover from './lib/games/PositionPopover.svelte'
  import TrainerScreen from './lib/screens/TrainerScreen.svelte'
  import InsightsView from './lib/insights/InsightsView.svelte'
  import {
    api,
    sidecar,
    type SidecarStatus,
    type RelabelStatus,
    type RelabelResult,
  } from './lib/api'
  import Sidebar, { type NavRoute } from './lib/shell/Sidebar.svelte'
  import CommandMenu from './lib/shell/CommandMenu.svelte'
  import { commandMenu, registerCommands } from './lib/shell/commands.svelte'
  import GameReview from './lib/review/GameReview.svelte'
  import PositionAnalysis from './lib/review/PositionAnalysis.svelte'
  import HomeView from './lib/home/HomeView.svelte'
  import SettingsView from './lib/settings/SettingsView.svelte'
  import PuzzlesView from './lib/puzzles/PuzzlesView.svelte'
  import type { GameSummary } from './lib/api'
  import { SHOW_FRIENDS, SHOW_TRAINER } from './lib/build'
  import FriendsView from './lib/friends/FriendsView.svelte'
  import FriendProfile from './lib/friends/FriendProfile.svelte'
  import { friendsApi } from './lib/friends/friendsApi'
  import { incomingCount, startFriends, friendsState } from './lib/friends/friendsState.svelte'
  import ChallengeBanners from './lib/friends/ChallengeBanners.svelte'
  import FriendGame from './lib/play/FriendGame.svelte'
  import { incomingChallenges, live, liveHooks, startLive } from './lib/friends/live.svelte'
  import UpdateCheck from './lib/UpdateCheck.svelte'

  type Route = 'home' | 'play' | 'games' | 'review' | 'puzzles' | 'trainer' | 'insights' | 'friends' | 'friend' | 'settings'


  /** Where the app opens: always Home in the app; the browser harness passes a screen. */
  interface Props {
    initial?: { route: Route; gameId?: number; ply?: number; fen?: string; friend?: string; now?: number }
  }
  let { initial }: Props = $props()

  // svelte-ignore state_referenced_locally
  let route = $state<Route>(initial?.route ?? 'home')
  // svelte-ignore state_referenced_locally
  let reviewTarget = $state<{
    gameId?: number
    fen?: string
    ply?: number
    action?: 'try' | 'best' | 'analyse'
    /** a friend's game analysed on request (FRIENDS.md G1): its moves from the FEN, and a title */
    moves?: string[]
    title?: string
  } | null>(
    initial?.gameId != null ? { gameId: initial.gameId, ply: initial.ply } : initial?.fen ? { fen: initial.fen } : null,
  )
  // Friends (FRIENDS-1): the profile on view
  // svelte-ignore state_referenced_locally
  let friendHandle = $state<string | null>(initial?.friend ?? null)
  // where a Back from the review/analysis screen should return to
  let reviewOrigin = $state<Route>('games')
  let spawnError = $state('')
  let backend = $state<SidecarStatus>('starting')
  let play: PlayView | undefined = $state()
  // deep-link: an opening picked from Insights to train directly
  let trainerOpening = $state<{ eco: string; name: string } | null>(null)

  // ── Analyse a position, as a dialog (Home's "Analyse a game"; UI-BUILD-3 E) ──────
  let positionDialog = $state(false)

  // The app is dark only (DESIGN.md); the old light theme is gone (UI-BUILD A6).
  document.documentElement.removeAttribute('data-theme')

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
  // Home's "Retry a moment": the review opens on the moment and starts Try it or the arrow.
  function openFromHome(gameId: number, ply: number, action: 'try' | 'best') {
    reviewOrigin = 'home'
    reviewTarget = { gameId, ply, action }
    route = 'review'
  }
  function openFromHomeList(gameId: number) {
    reviewOrigin = 'home'
    reviewTarget = { gameId }
    route = 'review'
  }
  // Play: Review opens when the game ends (ruling 15), at its last move, and analyses it at 14.
  function openFromPlay(gameId: number, lastPly: number) {
    reviewOrigin = 'play'
    reviewTarget = { gameId, ply: lastPly, action: 'analyse' }
    route = 'review'
  }
  /** Review the game (a friend game, saved to the library): it is analysed there as any game */
  function openFromPlayFriend(gameId: number, lastPly: number) {
    reviewOrigin = 'play'
    reviewTarget = { gameId, ply: lastPly }
    route = 'review'
  }
  /** The breadcrumb's first word on Analyse a position: where Back returns. */
  const ORIGIN_LABEL: Partial<Record<Route, string>> = {
    home: 'Home', games: 'Games', play: 'Play', puzzles: 'Puzzles', trainer: 'Openings', insights: 'Insights', settings: 'Settings',
    friends: 'Friends', friend: 'Friends',
  }
  function openFenReview(fen: string, origin: Route = 'games') {
    reviewOrigin = origin
    reviewTarget = { fen }
    route = 'review'
  }
  function openFriend(handle: string) {
    friendHandle = handle
    route = 'friend'
  }
  async function analyseFriendGame(id: number, label: string) {
    const g = await friendsApi.game(id)
    reviewOrigin = 'friend'
    reviewTarget = { fen: g.startFen, moves: g.moves, title: label }
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



  // ── shell (UI-BUILD B1): the sidebar's active item, recent games on Review, ⌘K ──
  const sidebarActive = $derived<NavRoute | null>(
    route === 'review' ? (reviewOrigin === 'friend' ? 'friends' : 'games') : route === 'friend' ? 'friends' : (route as NavRoute),
  )
  onMount(() => {
    if (SHOW_FRIENDS) startFriends()
  })
  // FRIENDS-2: the live connection once signed in; a game that starts opens Play
  liveHooks.ongamestart = () => navTo('play')
  $effect(() => {
    if (SHOW_FRIENDS && backend === 'up' && friendsState.status?.signedIn) startLive()
  })
  let recent = $state<GameSummary[] | null>(null)
  $effect(() => {
    if (backend !== 'up' || route !== 'review') return
    api
      .listGames(5)
      .then((r) => (recent = r.games))
      .catch(() => (recent = null))
  })
  const NAV_COMMANDS: { route: Route; label: string }[] = [
    { route: 'home', label: 'Home' },
    { route: 'play', label: 'Play' },
    { route: 'puzzles', label: 'Puzzles' },
    ...(SHOW_TRAINER ? [{ route: 'trainer' as Route, label: 'Openings' }] : []),
    { route: 'games', label: 'Games' },
    { route: 'insights', label: 'Insights' },
    ...(SHOW_FRIENDS ? [{ route: 'friends' as Route, label: 'Friends' }] : []),
    { route: 'settings', label: 'Settings' },
  ]
  onMount(() =>
    registerCommands('nav', () =>
      NAV_COMMANDS.map((c) => ({ id: `nav-${c.route}`, group: 'Go to', label: c.label, run: () => navTo(c.route) })),
    ),
  )
  function onGlobalKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'k') {
      e.preventDefault()
      commandMenu.open = !commandMenu.open
    }
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
  <Sidebar
    active={sidebarActive}
    showOpenings={SHOW_TRAINER}
    showFriends={SHOW_FRIENDS}
    friendsCount={SHOW_FRIENDS ? incomingCount() + incomingChallenges().length : 0}
    recent={route === 'review' ? recent : null}
    currentGameId={reviewTarget?.gameId ?? null}
    onnav={(r) => navTo(r as Route)}
    onopengame={openReview}
    onsearch={() => (commandMenu.open = true)}
  />

  <main class="content">
    {#if spawnError}
      <div class="spawn-error">Could not start the engine sidecar: {spawnError}</div>
    {:else}
      <!-- FRIENDS-2: challenges to you, on any screen (ruling S2); BETA-6 (S6): a floating card, in no screen's flow;
           FIX-B6 (S8): where it would cover a control, a strip at the top of the content instead -->
      {#if SHOW_FRIENDS}<ChallengeBanners screen={route} />{/if}
      <!-- Play stays mounted so a running game (and its clocks) survives navigation -->
      <div class="screen" style:display={route === 'play' && !live.activeId ? '' : 'none'}>
        <PlayView
          bind:this={play}
          onreview={openFromPlay}
          onsettings={() => navTo('settings')}
          onfriends={() => navTo('friends')}
          active={route === 'play' && !live.activeId}
        />
      </div>
      {#if SHOW_FRIENDS && live.activeId}
        <!-- FRIENDS-2: a game against a friend, on Play's screen while it lasts; mounted on every screen so
             its clocks and chat keep up -->
        <div class="screen" style:display={route === 'play' ? '' : 'none'}>
          <FriendGame onreview={openFromPlayFriend} active={route === 'play'} />
        </div>
      {/if}
      {#if route === 'home'}
        <HomeView
          showTrain={SHOW_TRAINER}
          onnav={(r) => navTo(r)}
          onanalyze={() => (positionDialog = true)}
          onopen={openFromHomeList}
          onopenat={openFromHome}
        />
      {:else if route === 'games'}
        <GamesView onopen={openReview} onfen={(fen) => openFenReview(fen, 'games')} onplayfen={playFromFen} onnav={navTo} />
      {:else if route === 'review' && reviewTarget?.gameId != null}
        {#key reviewTarget.gameId}
          <GameReview
            gameId={reviewTarget.gameId}
            ply={reviewTarget.ply ?? null}
            action={reviewTarget.action ?? null}
            onback={() => navTo(reviewOrigin)}
            onsettings={() => navTo('settings')}
          />
        {/key}
      {:else if route === 'review' && reviewTarget?.fen != null}
        <!-- Analyse a position (ruling 8 of 2026-11-20, fourth): Review's Moves layout, no game -->
        {#key reviewTarget.fen}
          <PositionAnalysis
            fen={reviewTarget.fen}
            initialMoves={reviewTarget.moves ?? null}
            title={reviewTarget.title ?? 'Analyse a position'}
            backLabel={ORIGIN_LABEL[reviewOrigin] ?? 'Games'}
            onback={() => navTo(reviewOrigin)}
            onplayfen={playFromFen}
            onsettings={() => navTo('settings')}
          />
        {/key}
      {:else if route === 'puzzles'}
        <PuzzlesView />
      {:else if route === 'trainer' && SHOW_TRAINER}
        <TrainerScreen
          onplayfen={playFromFen}
          openingRequest={trainerOpening}
          onrequesthandled={() => (trainerOpening = null)}
          onsettings={() => navTo('settings')}
        />
      {:else if route === 'insights'}
        <InsightsView onconnect={() => navTo('settings')} onopen={openReviewAt} />
      {:else if route === 'friends' && SHOW_FRIENDS}
        <FriendsView onopen={openFriend} now={initial?.now} />
      {:else if route === 'friend' && SHOW_FRIENDS && friendHandle}
        {#key friendHandle}
          <FriendProfile handle={friendHandle} onback={() => navTo('friends')} onanalyse={analyseFriendGame} now={initial?.now} />
        {/key}
      {:else if route === 'settings'}
        <SettingsView onnav={(r) => navTo(r)} />
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
<CommandMenu />
<svelte:window onkeydown={onGlobalKey} />

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

{#if positionDialog}
  <!-- Home's door to Analyse a position: the Games popover, shown as a dialog -->
  <div class="dialog-veil" role="presentation" onclick={() => (positionDialog = false)}>
    <div class="dialog" role="presentation" onclick={(e) => e.stopPropagation()}>
      <PositionPopover
        onanalyse={(fen) => {
          positionDialog = false
          openFenReview(fen, 'home')
        }}
        onplay={(fen) => {
          positionDialog = false
          playFromFen(fen)
        }}
        oncancel={() => (positionDialog = false)}
      />
    </div>
  </div>
{/if}

<style>
  .shell {
    height: 100vh;
    display: flex;
  }

  .content {
    flex: 1;
    min-width: 0;
    background: var(--bg);
    display: flex;
    flex-direction: column;
    overflow: auto;
  }
  .screen {
    height: 100%;
    flex: 1 1 auto;
    min-height: 0;
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
    border: 1px solid var(--border);
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

  /* ── Analyse a position, as a dialog ── */
  .dialog-veil {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.55);
  }
  @keyframes pop {
    from {
      opacity: 0;
      transform: translateY(8px) scale(0.98);
    }
  }
</style>
