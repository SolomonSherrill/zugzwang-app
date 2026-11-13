<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { api, sidecar } from '../api'
  import { hasAnyAccount } from '../settings.svelte'
  import FirstRun from '../FirstRun.svelte'
  import { BETA } from '../build'

  type Mode = 'play' | 'analysis' | 'puzzles' | 'trainer' | 'games'

  interface Props {
    onnav: (mode: Exclude<Mode, 'analysis'>) => void
    onanalyze: () => void
  }
  let { onnav, onanalyze }: Props = $props()

  // ── live stats ────────────────────────────────────────────────────────────
  let games = $state<number | null>(null)
  let winRate = $state<number | null>(null)
  let decisive = $state(0)
  let puzzleRating = $state<number | null>(null)
  let puzzlesImported = $state<boolean | null>(null)
  let mastered = $state<number | null>(null)

  function loadStats() {
    api
      .listGames()
      .then((r) => {
        const gs = r.games
        games = gs.length
        const dec = gs.filter(
          (g) => g.source === 'local' && (g.result === '1-0' || g.result === '0-1'),
        )
        decisive = dec.length
        const wins = dec.filter(
          (g) =>
            (g.result === '1-0' && g.playerColor === 'white') ||
            (g.result === '0-1' && g.playerColor === 'black'),
        ).length
        winRate = dec.length ? Math.round((100 * wins) / dec.length) : null
      })
      .catch(() => {})
    api
      .puzzleStatus()
      .then((r) => {
        puzzlesImported = r.imported
        puzzleRating = Math.round(r.rating)
      })
      .catch(() => {})
    if (!BETA) api
      .trainerLobby()
      .then((r) => {
        mastered = (r.families ?? []).reduce((a, f) => a + (f.mastered || 0), 0)
      })
      .catch(() => {})
  }

  const onReady = () => loadStats()

  onMount(() => {
    loadStats()
    sidecar.on('ready', onReady)
  })
  onDestroy(() => sidecar.off('ready', onReady))

  const showFirstRun = !hasAnyAccount()

  // ── greeting ──────────────────────────────────────────────────────────────
  const greeting = (() => {
    const h = new Date().getHours()
    if (h < 5) return 'Late night'
    if (h < 12) return 'Good morning'
    if (h < 18) return 'Good afternoon'
    return 'Good evening'
  })()

  // ── tiles ─────────────────────────────────────────────────────────────────
  type Tile = {
    id: Mode
    name: string
    desc: string
    stat: () => { value: string; label: string }
  }

  const allTiles: Tile[] = [
    {
      id: 'play',
      name: 'Play',
      desc: 'Challenge Stockfish at any strength',
      stat: () =>
        winRate === null
          ? { value: games === null ? '—' : 'New', label: 'no decided games yet' }
          : { value: `${winRate}%`, label: `win rate · ${decisive} games` },
    },
    {
      id: 'analysis',
      name: 'Analysis',
      desc: 'Study any position with the engine',
      stat: () => ({ value: 'FEN', label: 'paste a position' }),
    },
    {
      id: 'puzzles',
      name: 'Puzzles',
      desc: 'Sharpen tactics from Lichess puzzles',
      stat: () =>
        puzzlesImported === false
          ? { value: 'Set up', label: 'import the puzzle set' }
          : { value: puzzleRating === null ? '—' : `${puzzleRating}`, label: 'puzzle rating' },
    },
    {
      id: 'trainer',
      name: 'Opening Trainer',
      desc: 'Drill and master your repertoire',
      stat: () => ({
        value: mastered === null ? '—' : `${mastered}`,
        label: mastered === 1 ? 'line mastered' : 'lines mastered',
      }),
    },
    {
      id: 'games',
      name: 'Past Games',
      desc: 'Revisit and review your games',
      stat: () => ({
        value: games === null ? '—' : `${games}`,
        label: games === 1 ? 'saved game' : 'saved games',
      }),
    },
  ]

  // Beta builds hide the opening trainer (no book, W20).
  const tiles = BETA ? allTiles.filter((t) => t.id !== 'trainer') : allTiles

  function activate(id: Mode) {
    if (id === 'analysis') onanalyze()
    else onnav(id)
  }
</script>

<div class="home">
  <div class="inner">
    <header class="head">
      <p class="greeting">{greeting}</p>
      <h1 class="title">What would you like to work on?</h1>
      <p class="sub">Zugzwang is your complete chess workshop — every tool, one move away.</p>
    </header>

    <!-- First run (BETA item 3): no account connected yet. Captured once, so the card
         keeps reporting the sync it started after the account is saved. -->
    {#if showFirstRun}<FirstRun onopengames={() => onnav('games')} />{/if}

    <div class="tiles" class:four={tiles.length === 4}>
      {#each tiles as t, i (t.id)}
        {@const s = t.stat()}
        <button
          class="tile"
          class:action={t.id === 'analysis'}
          style="--i: {i}"
          onclick={() => activate(t.id)}
        >
          <span class="chip" aria-hidden="true">
            {#if t.id === 'play'}
              <svg viewBox="0 0 24 24"><path d="M8 5.5 18 12 8 18.5z" /></svg>
            {:else if t.id === 'analysis'}
              <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.2" /><line x1="15.6" y1="15.6" x2="20" y2="20" /></svg>
            {:else if t.id === 'puzzles'}
              <svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.6" /><rect x="13" y="4" width="7" height="7" rx="1.6" /><rect x="4" y="13" width="7" height="7" rx="1.6" /><rect class="fill" x="13" y="13" width="7" height="7" rx="1.6" /></svg>
            {:else if t.id === 'trainer'}
              <svg viewBox="0 0 24 24"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15.5H5.5A1.5 1.5 0 0 1 4 18z" /><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v15.5h5.5A1.5 1.5 0 0 0 20 18z" /></svg>
            {:else}
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M12 7.5V12l3 1.8" /></svg>
            {/if}
          </span>

          <span class="body">
            <span class="name">{t.name}</span>
            <span class="desc">{t.desc}</span>
          </span>

          <span class="stat">
            <span class="value">{s.value}</span>
            <span class="label">{s.label}</span>
          </span>
        </button>
      {/each}
    </div>
  </div>
</div>

<style>
  .home {
    height: 100%;
    overflow-y: auto;
    position: relative;
  }
  /* warm depth: a soft amber glow anchored top-left, very subtle */
  .home::before {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(
      120% 80% at 12% -10%,
      var(--accent-soft) 0%,
      transparent 55%
    );
  }
  .inner {
    position: relative;
    max-width: 920px;
    margin: 0 auto;
    padding: 72px 40px 56px;
  }

  .head {
    margin-bottom: 36px;
  }
  .greeting {
    margin: 0 0 6px;
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
    line-height: 1.15;
  }
  .sub {
    margin: 10px 0 0;
    font-size: 14px;
    color: var(--text-muted);
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 16px;
  }
  /* row 1: three tiles; row 2: two tiles, centred */
  .tiles > :nth-child(1) {
    grid-column: 1 / 3;
  }
  .tiles > :nth-child(2) {
    grid-column: 3 / 5;
  }
  .tiles > :nth-child(3) {
    grid-column: 5 / 7;
  }
  .tiles > :nth-child(4) {
    grid-column: 2 / 4;
  }
  .tiles > :nth-child(5) {
    grid-column: 4 / 6;
  }
  /* beta: four tiles, two rows of two */
  .tiles.four > :nth-child(n) {
    grid-column: span 3;
  }

  .tile {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 18px;
    min-height: 168px;
    padding: 20px;
    text-align: left;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    cursor: pointer;
    transition:
      transform 160ms ease,
      border-color 160ms ease,
      background-color 160ms ease;
    animation: rise 420ms cubic-bezier(0.2, 0.7, 0.2, 1) backwards;
    animation-delay: calc(var(--i) * 55ms + 60ms);
  }
  .tile:hover {
    transform: translateY(-3px);
    border-color: var(--accent-line);
    background: var(--bg-raised);
  }
  .tile:active {
    transform: translateY(-1px);
  }
  .tile:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .chip {
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    color: var(--text-muted);
    transition:
      color 160ms ease,
      background-color 160ms ease,
      border-color 160ms ease;
  }
  .tile:hover .chip {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }
  .chip svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .tile:not(.action) .chip svg path[d^='M8 5.5'] {
    fill: currentColor;
    stroke: none;
  }
  .chip svg rect.fill {
    fill: var(--accent);
    stroke: none;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: auto;
  }
  .name {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .desc {
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--text-muted);
  }

  .stat {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding-top: 14px;
    border-top: 1px solid var(--divider);
  }
  .value {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    line-height: 1;
    color: var(--text);
  }
  .label {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .tile.action .value {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--accent);
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(12px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (max-width: 760px) {
    .tiles {
      grid-template-columns: 1fr 1fr;
    }
    .tiles > * {
      grid-column: auto !important;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .tile {
      animation: none;
    }
  }
</style>
