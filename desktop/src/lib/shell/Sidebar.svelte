<script lang="ts">
  /**
   * The left sidebar (DESIGN.md "Shell"): app mark and name, "Search or jump to" with ⌘K,
   * then Home, Play, Puzzles, Openings, Games, Insights (no Coach item, ruling 16); on Review
   * a "Recent games" list; Settings at the foot. A dot on Play while a game runs, on every
   * screen (UI-BUILD-2, Play).
   *
   * Below 1440 px wide it is an icon rail (DESIGN.md fifth rulings, 2; UI-BUILD-4 C): the same
   * icons at 16 px, each label as a tooltip on hover and keyboard focus and as the button's
   * accessible name; "Search or jump to" an icon button opening the same command menu; Recent
   * games hidden. ⌘K is App's and unchanged.
   */
  import { onMount } from 'svelte'
  import type { GameSummary } from '../api'
  import { playState } from '../play/playState.svelte'

  export type NavRoute = 'home' | 'play' | 'puzzles' | 'trainer' | 'games' | 'insights' | 'settings'
  interface Props {
    active: NavRoute | null
    /** the Openings item (the trainer until OPEN-1); hidden in beta builds */
    showOpenings: boolean
    recent?: GameSummary[] | null
    currentGameId?: number | null
    onnav: (r: NavRoute) => void
    onopengame?: (id: number) => void
    onsearch: () => void
  }
  let { active, showOpenings, recent = null, currentGameId = null, onnav, onopengame, onsearch }: Props =
    $props()

  const ICONS: Record<NavRoute, string> = {
    home: '<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5 3.5-5 3.5z"/>',
    puzzles: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/>',
    trainer: '<path d="M2 5h6a4 4 0 0 1 4 4v11a3 3 0 0 0-3-3H2zM22 5h-6a4 4 0 0 0-4 4v11a3 3 0 0 1 3-3h7z"/>',
    games: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    insights: '<path d="M4 20V11M10 20V5M16 20v-8M22 20H2"/>',
    settings:
      '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  }
  const items = $derived<{ route: NavRoute; label: string }[]>([
    { route: 'home', label: 'Home' },
    { route: 'play', label: 'Play' },
    { route: 'puzzles', label: 'Puzzles' },
    ...(showOpenings ? [{ route: 'trainer' as NavRoute, label: 'Openings' }] : []),
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
    <span class="logo" aria-hidden="true"
      ><svg viewBox="0 0 45 45" width="16" height="16"
        ><path
          d="M22 10c10.5 1 16.5 8 16 29H15c0-9 10-6.5 8-21"
          fill="currentColor"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
        /><path
          d="M24 18c.38 2.91-5.55 7.37-8 9-3 2-2.82 4.34-5 4-1.04-.94 1.41-3.04 0-3-1 0 .19 1.23-1 2-1 0-4 1-4-4 0-2 6-12 6-12s1.89-1.9 2-3.5c-.73-1-.5-2-.5-3 1-1 3 2.5 3 2.5h2s.78-1.99 2.5-3c1 0 1 3 1 3"
          fill="currentColor"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
        /></svg
      ></span>
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
      aria-label={rail ? (it.route === 'play' && playState.inGame ? 'Play, game in progress' : it.label) : undefined}
      onclick={() => onnav(it.route)}
    >
      <svg width={iconSize} height={iconSize} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"
        >{@html ICONS[it.route]}</svg
      >{#if rail}<span class="tip" aria-hidden="true">{it.label}</span>{:else}{it.label}{/if}{#if it.route === 'play' && playState.inGame}<span class="live" role="img" aria-label="Game in progress"></span>{/if}
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
        <span class="grow">{opponent(g)}{#if o}<span class="sr">, {RESULT_WORD[o]}</span>{/if}</span>
        <span class="date">{when(g.playedAt)}</span>
      </button>
    {/each}
  {/if}
  <div class="spacer"></div>
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
  .logo {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    background: var(--text);
    color: var(--primary-ink);
    display: flex;
    align-items: center;
    justify-content: center;
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
