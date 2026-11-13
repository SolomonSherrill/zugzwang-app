<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import Board from '../Board.svelte'
  import type { PromotionRequest } from '../Board.svelte'
  import Clock from '../Clock.svelte'
  import MoveList from '../MoveList.svelte'
  import {
    api,
    sidecar,
    describeTermination,
    TIME_CONTROLS,
    TIME_CONTROL_DEFAULT,
    SKILL_DEFAULT,
    type Color,
    type GameEndInfo,
    type EngineMoveEvent,
    type ReadyEvent,
  } from '../api'
  import { pickEngine } from '../pick'

  type Phase = 'boot' | 'setup' | 'playing' | 'thinking' | 'over' | 'error'
  type Role = 'queen' | 'knight' | 'rook' | 'bishop'
  const ROLE_CHAR: Record<Role, string> = { queen: 'q', knight: 'n', rook: 'r', bishop: 'b' }

  const PREFS_KEY = 'zugzwang-play-prefs'

  interface Props {
    onreview: (gameId: number) => void
    /** true while the Play route is visible — gates the arrow-key handler */
    active?: boolean
  }
  let { onreview, active = false }: Props = $props()

  const chess = new Chess()
  let board: Board

  // ── move-history navigation (arrow keys) ────────────────────────────────
  // chess.js history can't be trusted here: engine moves arrive via load(),
  // which wipes its internal history. Track positions/squares in parallel.
  const NO_DESTS = new Map<Key, Key[]>()
  let positions = $state<string[]>([]) // fen after each ply; positions[0] = start
  let moveSquares = $state<[Key, Key][]>([]) // [from,to] per ply
  let viewPly = $state<number | null>(null) // null = following live play

  // ── game state ──────────────────────────────────────────────────────────
  let phase = $state<Phase>('boot')
  let fen = $state(chess.fen())
  let lastMove = $state<[Key, Key] | null>(null)
  let dests = $state<Map<Key, Key[]>>(new Map())
  let check = $state(false)
  let sans = $state<string[]>([])
  let opening = $state('')
  let endInfo = $state<GameEndInfo | null>(null)
  let errorText = $state('')
  let locating = $state(false)
  let locateError = $state('')
  let promotion = $state<PromotionRequest | null>(null)
  let pendingPromotion: { orig: Key; dest: Key } | null = null
  let confirmAction = $state<'resign' | 'draw' | null>(null)
  let confirmTimer: ReturnType<typeof setTimeout> | undefined

  // ── setup prefs (persisted) ─────────────────────────────────────────────
  const saved = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}')
  let playerColor = $state<Color>(saved.color === 'black' ? 'black' : 'white')
  let skill = $state<number>(typeof saved.skill === 'number' ? saved.skill : SKILL_DEFAULT)
  let tcIndex = $state<number>(
    typeof saved.tc === 'number' && TIME_CONTROLS[saved.tc] ? saved.tc : TIME_CONTROL_DEFAULT,
  )
  let sidebarHidden = $state<boolean>(saved.hideSidebar === true)

  function savePrefs() {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({ color: playerColor, skill, tc: tcIndex, hideSidebar: sidebarHidden }),
    )
  }

  // orientation is fixed per game (prefs may change in setup without flipping a finished game)
  let orientation = $state<Color>('white')
  let gameSkill = $state(SKILL_DEFAULT)

  // ── clocks (frontend-owned, as in the Qt app) ───────────────────────────
  let clocks = $state({ white: 0, black: 0 })
  let running = $state<Color | null>(null)
  let incrementMs = 0
  let lastTick = 0
  let ticker: ReturnType<typeof setInterval> | undefined
  let flagInFlight = false

  const turnColor = $derived<Color>(fen.split(' ')[1] === 'w' ? 'white' : 'black')
  const gameActive = $derived(phase === 'playing' || phase === 'thinking')
  const movableColor = $derived(gameActive ? orientation : null)
  const engineColor = $derived<Color>(orientation === 'white' ? 'black' : 'white')
  const inGame = $derived(phase === 'playing' || phase === 'thinking' || phase === 'over')
  // Hiding the sidebar is a play-focus feature; never hide it in setup/boot/
  // error, where the only way back (the restore toggle) is gated on inGame —
  // otherwise the screen is just a board with no escape hatch.
  const collapsed = $derived(sidebarHidden && inGame)

  function toggleSidebar() {
    sidebarHidden = !sidebarHidden
    savePrefs()
  }

  // ── reviewing a past ply vs. following live ─────────────────────────────
  const isLive = $derived(viewPly === null || viewPly >= sans.length)
  const viewFen = $derived(isLive ? fen : (positions[viewPly!] ?? fen))
  const viewLastMove = $derived<[Key, Key] | null>(
    isLive ? lastMove : viewPly! > 0 ? (moveSquares[viewPly! - 1] ?? null) : null,
  )
  const viewTurnColor = $derived<Color>(viewFen.split(' ')[1] === 'w' ? 'white' : 'black')
  const viewCheck = $derived(isLive ? check : new Chess(viewFen).inCheck())
  const viewMovable = $derived(isLive ? movableColor : null)
  const viewDests = $derived(isLive ? dests : NO_DESTS)
  const currentPly = $derived(viewPly === null ? sans.length : viewPly)

  function computeDests(): Map<Key, Key[]> {
    const map = new Map<Key, Key[]>()
    for (const m of chess.moves({ verbose: true })) {
      const arr = map.get(m.from as Key) ?? []
      arr.push(m.to as Key)
      map.set(m.from as Key, arr)
    }
    return map
  }

  function syncFromFen(newFen: string) {
    chess.load(newFen)
    fen = newFen
    check = chess.inCheck()
    dests = phase === 'playing' || phase === 'boot' ? computeDests() : new Map()
  }

  // ── clock machinery ─────────────────────────────────────────────────────
  function clockTick() {
    if (!running || flagInFlight) return
    const now = performance.now()
    clocks[running] = Math.max(0, clocks[running] - (now - lastTick))
    lastTick = now
    if (clocks[running] <= 0) void onFlag(running)
  }

  function switchClock(justMoved: Color | null, next: Color | null) {
    if (justMoved) clocks[justMoved] += incrementMs
    running = next
    lastTick = performance.now()
  }

  async function onFlag(loser: Color) {
    flagInFlight = true
    running = null
    try {
      const res = await api.flag(loser)
      finishGame(res.end)
    } catch (e) {
      fail(e)
    } finally {
      flagInFlight = false
    }
  }

  // ── game lifecycle ──────────────────────────────────────────────────────

  /** Start a game from an arbitrary position (FEN analysis → "Play from here"). */
  export function startFromFen(fen: string) {
    void startGame(fen)
  }

  async function startGame(fenOverride?: string) {
    savePrefs()
    try {
      const res = await api.newGame(playerColor, skill, fenOverride)
      gameLostAt = null
      orientation = playerColor
      gameSkill = skill
      opening = ''
      endInfo = null
      sans = []
      lastMove = null
      promotion = null
      confirmAction = null
      const tc = TIME_CONTROLS[tcIndex]
      incrementMs = tc.incrementS * 1000
      clocks = { white: tc.initialS * 1000, black: tc.initialS * 1000 }
      phase = res.engineToMove ? 'thinking' : 'playing'
      syncFromFen(res.fen)
      positions = [res.fen]
      moveSquares = []
      viewPly = null
      dests = phase === 'playing' ? computeDests() : new Map()
      switchClock(null, 'white')
    } catch (e) {
      fail(e)
    }
  }

  function finishGame(end: GameEndInfo) {
    endInfo = end
    phase = 'over'
    running = null
    dests = new Map()
    promotion = null
    confirmAction = null
    board?.cancelPremove()
  }

  function fail(e: unknown) {
    errorText = String(e)
    phase = 'error'
    running = null
  }

  async function locateEngine() {
    locateError = ''
    const path = await pickEngine()
    if (path === null) return
    locating = true
    try {
      // No phase change on success: the sidecar re-emits `ready`, and the
      // handler below is the single place that decides what a working engine
      // means — duplicating it here is how the two would drift apart.
      await api.setStockfishPath(path)
    } catch (e) {
      locateError = e instanceof Error ? e.message : String(e)
    } finally {
      locating = false
    }
  }

  // ── backend restart ─────────────────────────────────────────────────────
  // An unfinished game lives only in the sidecar's memory; it reaches the
  // database when it ends. So a restart loses it, and the replacement process
  // re-emits `ready`, which would drop the board back to the setup panel as
  // though nothing had happened. Note what was in flight at the moment the
  // backend went away — by the time the new one is up, `phase` is the only
  // record that there was a game at all.
  let gameLostAt = $state<number | null>(null)
  let wasPlayingAtRestart = false

  async function resyncAfterRestart() {
    // Ask rather than assume: get_state is the sidecar's own account of whether
    // a session survived, so if that ever changes this stops lying rather than
    // needing to be remembered.
    const state = await api.getState().catch(() => null)
    if (state?.active) return
    gameLostAt = sans.length
    running = null
    dests = new Map()
    promotion = null
    confirmAction = null
    board?.cancelPremove()
    phase = 'setup'
  }

  // ── moves ───────────────────────────────────────────────────────────────
  function onUserMove(orig: Key, dest: Key) {
    const candidates = chess.moves({ square: orig as Square, verbose: true })
    if (candidates.some((m) => m.to === dest && m.promotion)) {
      pendingPromotion = { orig, dest }
      const fileIdx = dest.charCodeAt(0) - 97
      promotion = {
        col: orientation === 'white' ? fileIdx : 7 - fileIdx,
        color: orientation,
      }
      return
    }
    void submitMove(orig, dest, undefined)
  }

  function onPromote(role: Role | null) {
    promotion = null
    const pending = pendingPromotion
    pendingPromotion = null
    if (!pending) return
    if (role === null) {
      board?.sync() // snap the pawn back
      return
    }
    void submitMove(pending.orig, pending.dest, ROLE_CHAR[role])
  }

  async function submitMove(orig: Key, dest: Key, promo: string | undefined) {
    const prevFen = fen
    let mv
    try {
      mv = chess.move({ from: orig, to: dest, promotion: promo as 'q' | 'n' | 'r' | 'b' | undefined })
    } catch {
      board?.sync()
      return
    }
    fen = chess.fen()
    check = chess.inCheck()
    lastMove = [orig, dest]
    sans = [...sans, mv.san]
    positions = [...positions, fen]
    moveSquares = [...moveSquares, [orig, dest]]
    viewPly = null
    dests = new Map()
    phase = 'thinking'
    switchClock(null, engineColor)

    try {
      const res = await api.userMove(orig + dest + (promo ?? ''))
      if (!res.ok) {
        phase = 'playing'
        sans = sans.slice(0, -1)
        positions = positions.slice(0, -1)
        moveSquares = moveSquares.slice(0, -1)
        syncFromFen(prevFen)
        switchClock(null, orientation)
        return
      }
      clocks[orientation] += incrementMs
      if (res.end) finishGame(res.end)
    } catch (e) {
      fail(e)
    }
  }

  async function onEngineMove(d: EngineMoveEvent) {
    if (!gameActive) return
    lastMove = [d.uci.slice(0, 2) as Key, d.uci.slice(2, 4) as Key]
    sans = [...sans, d.san]
    positions = [...positions, d.fen]
    moveSquares = [...moveSquares, [lastMove[0], lastMove[1]]]
    const wasLive = isLive
    if (d.end) {
      syncFromFen(d.fen)
      finishGame(d.end)
      return
    }
    phase = 'playing'
    syncFromFen(d.fen)
    switchClock(engineColor, orientation)
    await tick() // let chessground apply the new position first
    if (wasLive) board?.playPremove()
  }

  // ── resign / draw (inline confirm, no modal) ────────────────────────────
  function requestAction(action: 'resign' | 'draw') {
    if (confirmAction === action) {
      confirmAction = null
      clearTimeout(confirmTimer)
      void (action === 'resign' ? doResign() : doDraw())
      return
    }
    confirmAction = action
    clearTimeout(confirmTimer)
    confirmTimer = setTimeout(() => (confirmAction = null), 3000)
  }

  async function doResign() {
    try {
      finishGame((await api.resign()).end)
    } catch (e) {
      fail(e)
    }
  }

  async function doDraw() {
    try {
      finishGame((await api.draw()).end)
    } catch (e) {
      fail(e)
    }
  }

  // ── result text ─────────────────────────────────────────────────────────
  const resultTitle = $derived.by(() => {
    if (!endInfo) return ''
    if (endInfo.result === '1/2-1/2') return 'Draw'
    if (endInfo.result === '*') return 'Game abandoned'
    const playerWon =
      (endInfo.result === '1-0' && orientation === 'white') ||
      (endInfo.result === '0-1' && orientation === 'black')
    return playerWon ? 'You win' : 'Stockfish wins'
  })

  // ── arrow-key navigation ────────────────────────────────────────────────
  function onKey(e: KeyboardEvent) {
    if (!active) return
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    const t = e.target as HTMLElement | null
    if (
      t &&
      (t.tagName === 'INPUT' ||
        t.tagName === 'SELECT' ||
        t.tagName === 'TEXTAREA' ||
        t.isContentEditable)
    )
      return
    const total = sans.length
    if (total === 0) return
    e.preventDefault()
    const cur = viewPly === null ? total : viewPly
    const next = e.key === 'ArrowLeft' ? Math.max(0, cur - 1) : Math.min(total, cur + 1)
    viewPly = next >= total ? null : next
  }

  onMount(() => {
    window.addEventListener('keydown', onKey)
    const unsubscribe = sidecar.onStatus((s) => {
      // Captured on the way down, acted on on the way back up: at 'restarting'
      // `phase` still reflects the game that is about to be lost.
      if (s === 'restarting') wasPlayingAtRestart = phase === 'playing' || phase === 'thinking'
      else if (s === 'up' && wasPlayingAtRestart) {
        wasPlayingAtRestart = false
        void resyncAfterRestart()
      }
    })
    sidecar.on('ready', (d) => {
      const r = d as unknown as ReadyEvent
      if (r.ok) {
        locateError = ''
        phase = 'setup'
      } else {
        errorText =
          (r.error ?? 'Stockfish not found') +
          ' — point Zugzwang at the binary below, or install stockfish on PATH and relaunch.'
        phase = 'error'
      }
    })
    sidecar.on('engine_move', (d) => void onEngineMove(d as unknown as EngineMoveEvent))
    sidecar.on('opening', (d) => {
      opening = `${d.eco} · ${d.name}`
    })
    sidecar.on('engine_error', (d) => fail(d.message))
    ticker = setInterval(clockTick, 100)
    return unsubscribe
  })

  onDestroy(() => {
    clearInterval(ticker)
    window.removeEventListener('keydown', onKey)
  })
</script>

<div class="play" class:collapsed>
  <div class="board-col">
    {#if collapsed}
      <div class="float-clock" class:active={running === engineColor}>
        <span class="fc-name">Stockfish</span>
        <Clock ms={clocks[engineColor]} active={running === engineColor} />
      </div>
    {/if}
    <Board
      bind:this={board}
      fen={viewFen}
      lastMove={viewLastMove}
      turnColor={viewTurnColor}
      movableColor={viewMovable}
      dests={viewDests}
      check={viewCheck}
      {orientation}
      premovable={gameActive && isLive}
      {promotion}
      onmove={onUserMove}
      onpromote={onPromote}
    />
    {#if collapsed}
      <div class="float-clock" class:active={running === orientation}>
        <span class="fc-name">You</span>
        <Clock ms={clocks[orientation]} active={running === orientation} />
      </div>
    {/if}
  </div>

  {#if inGame}
    <button
      class="collapse-btn"
      onclick={toggleSidebar}
      title={sidebarHidden ? 'Show move list' : 'Hide move list'}
      aria-label={sidebarHidden ? 'Show move list' : 'Hide move list'}
    >
      {#if sidebarHidden}
        <svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6" /></svg>
      {:else}
        <svg viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6" /></svg>
      {/if}
    </button>
  {/if}

  <aside class="side" class:hidden={collapsed}>
    {#if phase === 'boot'}
      <div class="panel setup">
        <span class="boot-row"><span class="pulse-dot"></span> Waking the engine…</span>
      </div>
    {:else if phase === 'error'}
      <div class="panel setup">
        <h2 class="panel-title">Engine unavailable</h2>
        <p class="error-text">{errorText}</p>
        <button class="btn btn-accent" onclick={locateEngine} disabled={locating}>
          {locating ? 'Checking…' : 'Locate Stockfish…'}
        </button>
        {#if locateError}<p class="error-text">{locateError}</p>{/if}
      </div>
    {:else if phase === 'setup'}
      <div class="panel setup">
        {#if gameLostAt !== null}
          <p class="lost-notice">
            The engine backend stopped and restarted, so the
            {gameLostAt === 0 ? 'game in progress was lost' : `${gameLostAt}-move game was lost`}.
            Games are only saved once they finish.
          </p>
        {/if}
        <h2 class="panel-title">New game</h2>

        <div class="field-label">Play as</div>
        <div class="seg">
          <button class:on={playerColor === 'white'} onclick={() => (playerColor = 'white')}>
            White
          </button>
          <button class:on={playerColor === 'black'} onclick={() => (playerColor = 'black')}>
            Black
          </button>
        </div>

        <div class="field-label row">
          <span>Strength</span>
          <span class="field-value">Level {skill} of 20</span>
        </div>
        <input type="range" min="0" max="20" bind:value={skill} />

        <div class="field-label">Time control</div>
        <select bind:value={tcIndex}>
          {#each TIME_CONTROLS as tc, i (tc.label)}
            <option value={i}>{tc.label}</option>
          {/each}
        </select>

        <button class="btn btn-accent start" onclick={() => startGame()}>Start game</button>
      </div>
    {:else}
      <div class="panel game">
        <div class="player-row" class:active={running === engineColor}>
          <div class="ident">
            <span class="avatar {engineColor}" aria-hidden="true"></span>
            <div class="who">
              <span class="name">Stockfish</span>
              <span class="sub">Level {gameSkill} of 20</span>
            </div>
          </div>
          <Clock ms={clocks[engineColor]} active={running === engineColor} />
        </div>

        <div class="opening" class:empty={!opening}>{opening || ' '}</div>

        <MoveList
          {sans}
          {currentPly}
          onselect={(p) => (viewPly = p >= sans.length ? null : p)}
        />

        <div class="player-row bottom" class:active={running === orientation}>
          <div class="ident">
            <span class="avatar {orientation}" aria-hidden="true"></span>
            <div class="who">
              <span class="name">You</span>
              <span class="sub">Playing {orientation}</span>
            </div>
          </div>
          <Clock ms={clocks[orientation]} active={running === orientation} />
        </div>

        {#if phase === 'over' && endInfo}
          <div class="result">
            <span class="result-title">{resultTitle}</span>
            <span class="result-sub"
              >by {describeTermination(endInfo.termination)} · {endInfo.result}</span
            >
            <div class="result-actions">
              <button class="btn btn-accent" onclick={() => onreview(endInfo!.gameId)}>
                Review
              </button>
              <button class="btn btn-quiet" onclick={() => startGame()}>Rematch</button>
              <button class="btn btn-quiet" onclick={() => (phase = 'setup')}>New game</button>
            </div>
          </div>
        {:else}
          <div class="controls">
            <button
              class="btn"
              class:btn-quiet={confirmAction !== 'resign'}
              class:btn-danger-confirm={confirmAction === 'resign'}
              onclick={() => requestAction('resign')}
            >
              {confirmAction === 'resign' ? 'Confirm resign' : 'Resign'}
            </button>
            <button
              class="btn"
              class:btn-quiet={confirmAction !== 'draw'}
              class:btn-danger-confirm={confirmAction === 'draw'}
              onclick={() => requestAction('draw')}
            >
              {confirmAction === 'draw' ? 'Confirm draw' : 'Draw'}
            </button>
            <span class="status">
              {#if phase === 'thinking'}
                <span class="pulse-dot"></span> Thinking…
              {:else}
                Your move
              {/if}
            </span>
          </div>
        {/if}
      </div>
    {/if}
  </aside>
</div>

<style>
  .play {
    position: relative;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 28px;
    padding: 28px;
  }
  .board-col {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: min(calc(100vh - 112px), calc(100vw - 620px), 720px);
    min-width: 380px;
    transition: width 220ms ease;
  }
  .play.collapsed .board-col {
    width: min(calc(100vh - 212px), calc(100vw - 80px), 920px);
  }
  .side {
    width: 320px;
    align-self: stretch;
    display: flex;
    align-items: center;
  }
  .side.hidden {
    display: none;
  }

  /* ── collapse toggle ── */
  .collapse-btn {
    position: absolute;
    top: 20px;
    right: 20px;
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-sm);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    color: var(--text-muted);
    box-shadow: var(--shadow-tile);
    cursor: pointer;
    transition: color 120ms ease, border-color 120ms ease, background-color 120ms ease;
    z-index: 6;
  }
  .collapse-btn:hover {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .collapse-btn svg {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  /* ── floating clocks (sidebar hidden): above/below the board, right-aligned ── */
  .float-clock {
    align-self: flex-end;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 6px 12px;
    border-radius: var(--radius);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    box-shadow: var(--shadow-tile);
    transition: border-color 120ms ease;
  }
  .float-clock.active {
    border-color: var(--accent-line);
  }
  .fc-name {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
  }
  .float-clock.active .fc-name {
    color: var(--text);
  }

  .panel {
    width: 100%;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
  }

  /* ── setup card ── */
  .setup {
    padding: 22px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .panel-title {
    margin: 0 0 6px;
    font-weight: 600;
    font-size: 17px;
    letter-spacing: -0.01em;
  }
  .field-label {
    margin-top: 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .field-label.row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .field-value {
    text-transform: none;
    letter-spacing: 0.01em;
    font-size: 12px;
    color: var(--text);
  }
  .seg {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
    padding: 4px;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    background: var(--bg-surface);
  }
  .seg button {
    padding: 7px 0;
    font-size: 13px;
    font-weight: 600;
    border-radius: 4px;
    color: var(--text-muted);
    background: transparent;
    transition: background-color 120ms ease, color 120ms ease;
  }
  .seg button:hover:not(.on) {
    color: var(--text);
  }
  .seg button.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .start {
    margin-top: 14px;
    padding: 9px 0;
  }
  .boot-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
  }
  .error-text {
    color: var(--danger);
    font-size: 13px;
    line-height: 1.5;
    user-select: text;
  }
  .lost-notice {
    margin: 0 0 14px;
    padding: 9px 11px;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text-muted);
    background: var(--bg-raised);
    border-left: 2px solid var(--danger);
    border-radius: var(--radius-sm);
  }

  /* ── live game panel ── */
  .game {
    display: flex;
    flex-direction: column;
    height: min(calc(100vh - 112px), 720px);
  }
  .player-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 14px;
    border-left: 2px solid transparent;
    transition: background-color 120ms ease, border-color 120ms ease;
  }
  .player-row.active {
    background: var(--accent-soft);
    border-left-color: var(--accent);
  }
  .player-row.bottom {
    border-top: 1px solid var(--divider);
  }
  .ident {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .avatar {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25);
  }
  .avatar.white {
    background: #e8e2d4;
  }
  .avatar.black {
    background: #2b2620;
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
  }
  .who {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  .name {
    font-size: 13.5px;
    font-weight: 600;
  }
  .sub {
    font-size: 11.5px;
    color: var(--text-muted);
    text-transform: capitalize;
  }
  .opening {
    padding: 6px 14px;
    border-top: 1px solid var(--divider);
    border-bottom: 1px solid var(--divider);
    font-size: 12px;
    font-weight: 500;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  :global(.game .movelist) {
    flex: 1;
    min-height: 0;
    padding: 6px 0;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-top: 1px solid var(--divider);
  }
  .controls .status {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .result {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 14px;
    border-top: 1px solid var(--divider);
  }
  .result-title {
    font-size: 16px;
    font-weight: 600;
  }
  .result-sub {
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .result-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;
  }
</style>
