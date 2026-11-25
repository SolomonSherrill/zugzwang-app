<script lang="ts">
  /**
   * The left sidebar (DESIGN.md "Shell"): app mark (the ℤ tile, LOGO-1) and name, "Search or jump to" with ⌘K,
   * then Home, Play, Puzzles, Openings, Coach, Games, Insights (Coach after Openings: COACH.md ruling 6); on Review
   * a "Recent games" list; Settings at the foot. A dot on Play while a game runs, on every
   * screen (UI-BUILD-2, Play).
   *
   * Below 1440 px wide it is an icon rail (DESIGN.md fifth rulings, 2; UI-BUILD-4 C): the same
   * icons at 16 px, each label as a tooltip on hover and keyboard focus and as the button's
   * accessible name; "Search or jump to" an icon button opening the same command menu; Recent
   * games hidden. ⌘K is App's and unchanged.
   *
   * At the very bottom, while anything runs in the background, the activity line (COACH-2 D, ruling CB1).
   */
  import { onMount } from 'svelte'
  import type { GameSummary } from '../api'
  import { playState } from '../play/playState.svelte'
  import ActivityLine from './ActivityLine.svelte'
  import type { JobTarget } from '../background/jobsModel'
  // the app mark (LOGO-1): the TeX \mathbb{Z} on the light tile, design/logo/
  import logoMark from '../../assets/logo/zugzwang-mark.png'

  export type NavRoute = 'home' | 'play' | 'puzzles' | 'trainer' | 'coach' | 'games' | 'insights' | 'friends' | 'settings'
  interface Props {
    active: NavRoute | null
    /** the Openings item (the trainer until OPEN-1); hidden in beta builds */
    showOpenings: boolean
    /** Friends, near Settings at the foot (FRIENDS.md ruling S1); hidden in beta builds (L4) */
    showFriends?: boolean
    /** incoming friend requests, shown on the Friends item */
    friendsCount?: number
    /** Practice positions due today, shown on the Coach item (COACH.md ruling 6; COACH-2 C) */
    coachCount?: number
    recent?: GameSummary[] | null
    currentGameId?: number | null
    onnav: (r: NavRoute) => void
    onopengame?: (id: number) => void
    onsearch: () => void
    /** COACH-2 D (ruling CB1): the activity line's click: open what a background job is about */
    onopenjob?: (t: JobTarget) => void
  }
  let { active, showOpenings, showFriends = false, friendsCount = 0, coachCount = 0, recent = null, currentGameId = null, onnav, onopengame, onsearch, onopenjob }: Props =
    $props()

  const ICONS: Record<NavRoute, string> = {
    home: '<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5 3.5-5 3.5z"/>',
    puzzles: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/>',
    trainer: '<path d="M2 5h6a4 4 0 0 1 4 4v11a3 3 0 0 0-3-3H2zM22 5h-6a4 4 0 0 0-4 4v11a3 3 0 0 1 3-3h7z"/>',
    coach: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12h.01"/>',
    games: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    insights: '<path d="M4 20V11M10 20V5M16 20v-8M22 20H2"/>',
    friends: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="17" cy="9" r="2.8"/><path d="M16.5 14.6c2.6.2 4.4 1.9 5 5.4"/>',
    settings:
      '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  }
  const items = $derived<{ route: NavRoute; label: string }[]>([
    { route: 'home', label: 'Home' },
    { route: 'play', label: 'Play' },
    { route: 'puzzles', label: 'Puzzles' },
    ...(showOpenings ? [{ route: 'trainer' as NavRoute, label: 'Openings' }] : []),
    { route: 'coach', label: 'Coach' },
    { route: 'games', label: 'Games' },
    { route: 'insights', label: 'Insights' },
  ])

  function outcome(g: GameSummary): 'win' | 'loss' | 'draw' | null {
    if (!g.playerColor) return null
    if (g.result === '1/2-1/2') return 'draw'
    if (g.result === '1-0') return g.playerColor === 'white' ? 'win' : 'loss'
    if (g.result === '0-1') return g.playerColor === 'black' ? 'win' : 'loss'
    return null
  }
  function opponent(g: GameSummary): string {
    if (g.source === 'local') return 'Stockfish'
    const name = g.playerColor === 'black' ? g.white : g.black
    return name ?? 'Unknown'
  }
  function when(iso: string): string {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return ''
    const now = new Date()
    const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
    if (same(d, now)) return 'Today'
    const y = new Date(now)
    y.setDate(now.getDate() - 1)
    if (same(d, y)) return 'Yesterday'
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  }
  const RESULT_WORD = { win: 'Won', loss: 'Lost', draw: 'Drawn' }

  /** the window width below which the sidebar is a rail (ruling 2: "below 1440 wide") */
  const RAIL_QUERY = '(max-width: 1439.98px)'
  let rail = $state(typeof window !== 'undefined' && !!window.matchMedia?.(RAIL_QUERY).matches)
  onMount(() => {
    const mq = window.matchMedia?.(RAIL_QUERY)
    if (!mq) return
    const on = () => (rail = mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  })
  const iconSize = $derived(rail ? 16 : 15)
</script>

<nav class="sidebar" class:rail aria-label="Sidebar">
  <div class="mark">
    <img class="logo" src={logoMark} alt="" width="20" height="20" aria-hidden="true" />
    <span class="name">Zugzwang</span>
  </div>
  <button type="button" class="search" onclick={onsearch} aria-label={rail ? 'Search or jump to' : undefined} aria-keyshortcuts="Meta+K">
    <svg width={rail ? 16 : 14} height={rail ? 16 : 14} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"
      ><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg
    >
    {#if rail}
      <span class="tip" aria-hidden="true">Search or jump to <kbd>⌘K</kbd></span>
    {:else}
      <span class="grow">Search or jump to</span>
      <kbd>⌘K</kbd>
    {/if}
  </button>
  {#each items as it (it.route)}
    <button
      type="button"
      class="item"
      class:active={active === it.route}
      aria-current={active === it.route ? 'page' : undefined}
      aria-label={rail
        ? it.route === 'play' && playState.inGame
          ? 'Play, game in progress'
          : it.route === 'coach' && coachCount
            ? `Coach, ${coachCount} to practise`
            : it.label
        : undefined}
      onclick={() => onnav(it.route)}
    >
      <svg width={iconSize} height={iconSize} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"
        >{@html ICONS[it.route]}</svg
      >{#if rail}<span class="tip" aria-hidden="true">{it.label}</span>{:else}{it.label}{/if}{#if it.route === 'play' && playState.inGame}<span class="live" role="img" aria-label="Game in progress"></span>{/if}{#if it.route === 'coach' && coachCount}<span
          class="count"
          data-testid="coach-due"
          aria-label="{coachCount} positions to practise">{coachCount}</span
        >{/if}
    </button>
  {/each}
  {#if !rail && recent && recent.length}
    <div class="section">Recent games</div>
    {#each recent as g (g.id)}
      {@const o = outcome(g)}
      <button
        type="button"
        class="item game"
        class:current={g.id === currentGameId}
        onclick={() => onopengame?.(g.id)}
      >
        <span class="dot {o ?? 'none'}" aria-hidden="true"></span>
        <span class="grow" title={opponent(g)}>{opponent(g)}{#if o}<span class="sr">, {RESULT_WORD[o]}</span>{/if}</span>
        <span class="date">{when(g.playedAt)}</span>
      </button>
    {/each}
  {/if}
  <div class="spacer"></div>
  {#if showFriends}
    <button
      type="button"
      class="item"
      class:active={active === 'friends'}
      aria-current={active === 'friends' ? 'page' : undefined}
      aria-label={rail ? (friendsCount ? `Friends, ${friendsCount} requests` : 'Friends') : undefined}
      onclick={() => onnav('friends')}
    >
      <svg width={iconSize} height={iconSize} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"
        >{@html ICONS.friends}</svg
      >{#if rail}<span class="tip" aria-hidden="true">Friends</span>{:else}Friends{/if}{#if friendsCount}<span
          class="count"
          aria-label="{friendsCount} friend requests">{friendsCount}</span
        >{/if}
    </button>
  {/if}
  <button
    type="button"
    class="item"
    class:active={active === 'settings'}
    aria-current={active === 'settings' ? 'page' : undefined}
    aria-label={rail ? 'Settings' : undefined}
    onclick={() => onnav('settings')}
  >
    <svg width={iconSize} height={iconSize} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"
      >{@html ICONS.settings}</svg
    >{#if rail}<span class="tip" aria-hidden="true">Settings</span>{:else}Settings{/if}
  </button>
  <ActivityLine {rail} onopen={(t) => (onopenjob ? onopenjob(t) : t.route === 'review' ? onopengame?.(t.gameId) : onnav(t.route))} />
</nav>

<style>
  .sidebar {
    width: var(--sidebar-width);
    flex: none;
    box-sizing: border-box;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
  }
  .mark {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px 12px;
  }
  /* the PNG is the whole tile (light, rounded corners, transparent outside them) */
  .logo {
    width: 20px;
    height: 20px;
    flex: none;
    display: block;
  }
  .name {
    font-weight: 600;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    margin-bottom: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    color: var(--text-3);
    text-align: left;
    font: var(--body);
    cursor: pointer;
  }
  kbd {
    font: var(--kbd);
    font-family: inherit;
    color: var(--text-3);
    border: 1px solid var(--border-control);
    border-radius: 4px;
    padding: 0 5px;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 8px;
    border-radius: var(--radius-control);
    color: var(--text-2);
    background: transparent;
    border: 0;
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .item:hover {
    color: var(--text);
    background: var(--surface);
  }
  .item.active {
    color: var(--text);
    background: var(--raised);
  }
  .item.game.current {
    color: var(--text);
    background: var(--surface);
  }
  .item:focus-visible,
  .search:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .section {
    padding: 18px 8px 6px;
    font: var(--secondary);
    color: var(--text-3);
  }
  .grow {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 4px;
    margin: 0 4px;
    flex: none;
  }
  .dot.win {
    background: var(--win);
  }
  .dot.loss {
    background: var(--loss);
  }
  .dot.draw,
  .dot.none {
    background: var(--draw);
  }
  .date {
    color: var(--text-3);
    font: var(--secondary);
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  /* a game is running (Play), as the mockup draws it: a 6px dot in the win green */
  .live {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-round);
    background: var(--win);
    margin-left: auto;
    margin-right: 4px;
  }
  .spacer {
    flex: 1;
    min-height: 24px;
  }
  /* the request count on Friends (ruling S1), as MinimalFriends.html draws it */
  .count {
    margin-left: auto;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    box-sizing: border-box;
    border-radius: 9px;
    background: var(--selected);
    color: var(--text);
    font: var(--secondary);
    font-size: 11px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .rail .count {
    position: absolute;
    top: 2px;
    right: 0;
    min-width: 16px;
    height: 16px;
    font-size: 10px;
    padding: 0 4px;
  }

  /* ── the icon rail, below 1440 wide (fifth rulings, 2) ── */
  .sidebar.rail {
    width: var(--rail-width);
    padding: 12px 8px;
    align-items: center;
    gap: 4px;
    /* the tooltips reach past the rail's edge; the rail's eight buttons fit 720 px with room */
    overflow: visible;
    position: relative;
    z-index: 30;
  }
  .rail .mark {
    padding: 4px 0 12px;
  }
  .rail .name {
    display: none;
  }
  .rail .search,
  .rail .item {
    position: relative;
    width: 36px;
    height: 36px;
    padding: 0;
    gap: 0;
    justify-content: center;
    flex: none;
  }
  .rail .search {
    margin-bottom: 10px;
    color: var(--text-2);
  }
  .rail .search:hover {
    color: var(--text);
  }
  .rail .live {
    position: absolute;
    top: 7px;
    right: 6px;
    margin: 0;
  }
  .tip {
    position: absolute;
    left: calc(100% + 10px);
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 9px;
    white-space: nowrap;
    font: var(--secondary);
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    box-shadow: var(--shadow-popover);
    pointer-events: none;
    opacity: 0;
    visibility: hidden;
    transition: opacity 80ms ease-out;
    z-index: 40;
  }
  .rail .item:hover .tip,
  .rail .item:focus-visible .tip,
  .rail .search:hover .tip,
  .rail .search:focus-visible .tip {
    opacity: 1;
    visibility: visible;
  }
</style>
