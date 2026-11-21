<script lang="ts">
  /**
   * Play, rebuilt (UI-BUILD-2; DESIGN.md "Play: new game", "Play: game in progress", ruling 15).
   * New game: the board between the two player strips (clocks at the right), the panel "New game
   * against Stockfish" with Play as, Strength (level 0–20) and the ten time controls grouped by
   * speed, Start game (↵). In game: breadcrumb "Play / Stockfish, level N" with the time control,
   * Flip (F), the opening with ECO and "casual", a plain move list, Offer a draw, Resign; Review
   * opens when the game ends.
   *
   * An honest game by default: no eval bar, no engine lines, no move icons and no hints during a
   * game. Turning help on is COACH-1's, not built here. The game logic is the old PlayScreen's
   * (sidecar RPCs new_game / user_move / resign / draw / flag, the engine_move and opening
   * events, frontend-owned clocks), unchanged but for the time control now written to the PGN and,
   * UI-BUILD-3 F, each move's clock: the user's sent with the move, the engine's measured by the
   * sidecar and shown as it reports it.
   */
  import { onDestroy, onMount, tick } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import Board from '../Board.svelte'
  import type { PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import Kbd from '../ui/Kbd.svelte'
  import PlayerStrip from '../ui/PlayerStrip.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import { api, sidecar, type Color, type GameEndInfo, type EngineMoveEvent, type ReadyEvent } from '../api'
  import { accounts } from '../settings.svelte'
  import { commandMenu, registerCommands, type Command } from '../shell/commands.svelte'
  import { playState } from './playState.svelte'
  import {
    LEVEL_MAX, PLAY_TIME_CONTROLS, TC_GROUPS, clockAfterMove, clockText, crumbTitle, engineClockAfter, engineStrip, moveRows, openingSub,
    readPrefs, resultSentence, tcLabel, tcPgn, writePrefs, youStrip,
  } from './playModel'

  type Phase = 'boot' | 'noengine' | 'setup' | 'playing' | 'thinking' | 'over' | 'error'
  const PREFS_KEY = 'zugzwang-play-prefs'
  const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  const NO_DESTS = new Map<Key, Key[]>()
  const SIDES: Color[] = ['white', 'black']

  interface Props {
    /** the game is saved: open its review (at its last move) */
    onreview: (gameId: number, lastPly: number) => void
    onsettings: () => void
    /** true while the Play route is visible: gates the keys and Review opening by itself */
    active?: boolean
  }
  let { onreview, onsettings, active = false }: Props = $props()

  const chess = new Chess()
  let board: Board | undefined = $state()

  // ── setup (persisted under the old screen's key) ───────────────────────────
  const saved = readPrefs(globalThis.localStorage?.getItem(PREFS_KEY) ?? null)
  let color = $state<Color>(saved.color)
  let level = $state(saved.level)
  let tcIndex = $state(saved.tc)
  function savePrefs() {
    globalThis.localStorage?.setItem(PREFS_KEY, writePrefs({ color, level, tc: tcIndex }))
  }

  // ── game state ─────────────────────────────────────────────────────────────
  let phase = $state<Phase>('boot')
  let fen = $state(START_FEN)
  let startFen = $state(START_FEN)
  let lastMove = $state<[Key, Key] | null>(null)
  let dests = $state<Map<Key, Key[]>>(new Map())
  let check = $state(false)
  let sans = $state<string[]>([])
  let positions = $state<string[]>([START_FEN]) // fen after each ply; [0] = start
  let moveSquares = $state<[Key, Key][]>([])
  let viewPly = $state<number | null>(null) // null = following live play
  let opening = $state<{ eco: string; name: string } | null>(null)
  let fromFen = $state(false)
  let endInfo = $state<GameEndInfo | null>(null)
  let errorText = $state('')
  let errorKind = $state<'start' | 'engine'>('engine')
  let confirmAction = $state<'resign' | 'draw' | null>(null)
  let confirmTimer: ReturnType<typeof setTimeout> | undefined
  let flipped = $state(false)
  let lostAt = $state<number | null>(null)

  // fixed per game: what the strips, breadcrumb and board orientation read once it starts
  let gameColor = $state<Color>(saved.color)
  let gameLevel = $state(saved.level)
  let gameTc = $state(saved.tc)

  const inGame = $derived(phase === 'playing' || phase === 'thinking')
  const started = $derived(inGame || phase === 'over')
  // the board, strips and breadcrumb keep the game's own state once one has started, and
  // through an engine failure in it
  const hasGame = $derived(started || (phase === 'error' && errorKind === 'engine'))
  $effect(() => {
    playState.inGame = inGame
  })

  const you = $derived<Color>(hasGame ? gameColor : color)
  const engineSide = $derived<Color>(you === 'white' ? 'black' : 'white')
  const orientation = $derived<Color>(flipped ? engineSide : you)
  const top = $derived<Color>(orientation === 'white' ? 'black' : 'white')
  const bottom = $derived<Color>(orientation)

  // ── clocks (frontend-owned, as before) ──────────────────────────────────────
  let clocks = $state({ white: 0, black: 0 })
  let running = $state<Color | null>(null)
  let incrementMs = 0
  let lastTick = 0
  let ticker: ReturnType<typeof setInterval> | undefined
  let flagInFlight = false

  const setupTc = $derived(PLAY_TIME_CONTROLS[tcIndex])
  function clockFor(side: Color): string {
    return hasGame ? clockText(clocks[side]) : clockText(setupTc.initialS * 1000)
  }

  function clockTick() {
    if (!running || flagInFlight) return
    const now = performance.now()
    clocks[running] = Math.max(0, clocks[running] - (now - lastTick))
    lastTick = now
    if (clocks[running] <= 0) void onFlag(running)
  }
  /** Charge the running clock the time since the last tick, so a move stops it to the ms rather
   *  than to the 100 ms tick (the clock it leaves is saved with the move, UI-BUILD-3 F). */
  function settleClock() {
    if (!running) return
    const now = performance.now()
    clocks[running] = Math.max(0, clocks[running] - (now - lastTick))
    lastTick = now
  }
  function switchClock(justMoved: Color | null, next: Color | null) {
    settleClock()
    if (justMoved) clocks[justMoved] += incrementMs
    running = next
    lastTick = performance.now()
  }
  async function onFlag(loser: Color) {
    flagInFlight = true
    running = null
    try {
      finishGame((await api.flag(loser)).end)
    } catch (e) {
      fail(e)
    } finally {
      flagInFlight = false
    }
  }

  // ── reviewing an earlier move vs following live ─────────────────────────────
  const isLive = $derived(viewPly === null || viewPly >= sans.length)
  const viewFen = $derived(isLive ? fen : (positions[viewPly!] ?? fen))
  const viewLastMove = $derived<[Key, Key] | null>(isLive ? lastMove : viewPly! > 0 ? (moveSquares[viewPly! - 1] ?? null) : null)
  const viewTurn = $derived<Color>(viewFen.split(' ')[1] === 'w' ? 'white' : 'black')
  const viewCheck = $derived(isLive ? check : new Chess(viewFen).inCheck())
  // the player's colour while thinking too: chessground premoves need it (turnColor is the engine's)
  const movable = $derived<Color | null>(inGame && isLive ? gameColor : null)
  const currentPly = $derived(viewPly === null ? sans.length : viewPly) // positions index shown
  const rows = $derived(moveRows(sans, startFen))

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
    dests = phase === 'playing' ? computeDests() : new Map()
  }

  // ── lifecycle ──────────────────────────────────────────────────────────────
  /** Start a game from a position (FEN analysis and the trainer's "Play it out vs Stockfish"). */
  export function startFromFen(f: string) {
    void startGame(f)
  }

  async function startGame(fenOverride?: string) {
    if (phase === 'boot' || phase === 'noengine' || inGame) return
    savePrefs()
    const tc = PLAY_TIME_CONTROLS[tcIndex]
    try {
      const res = await api.newGame(color, level, fenOverride, tcPgn(tc))
      lostAt = null
      gameColor = color
      gameLevel = level
      gameTc = tcIndex
      flipped = false
      opening = null
      fromFen = !!fenOverride
      endInfo = null
      sans = []
      lastMove = null
      confirmAction = null
      incrementMs = tc.incrementS * 1000
      clocks = { white: tc.initialS * 1000, black: tc.initialS * 1000 }
      running = null
      phase = res.engineToMove ? 'thinking' : 'playing'
      startFen = res.fen
      syncFromFen(res.fen)
      positions = [res.fen]
      moveSquares = []
      viewPly = null
      switchClock(null, res.fen.split(' ')[1] === 'b' ? 'black' : 'white')
    } catch (e) {
      errorKind = 'start'
      fail(e)
    }
  }

  function finishGame(end: GameEndInfo) {
    endInfo = end
    phase = 'over'
    running = null
    dests = new Map()
    confirmAction = null
    board?.cancelPremove()
    // Review opens when the game ends (ruling 15), if Play is on screen; a game that ends
    // while you look elsewhere waits here with its result.
    if (active) openReview()
  }
  function openReview() {
    if (!endInfo) return
    const id = endInfo.gameId
    const last = Math.max(0, sans.length - 1)
    newGame()
    onreview(id, last)
  }
  /** Back to the new-game panel: the board returns to the start. */
  function newGame() {
    phase = 'setup'
    endInfo = null
    errorText = ''
    sans = []
    positions = [START_FEN]
    moveSquares = []
    viewPly = null
    lastMove = null
    opening = null
    startFen = START_FEN
    flipped = false
    chess.load(START_FEN)
    fen = START_FEN
    check = false
    dests = new Map()
  }
  function fail(e: unknown) {
    errorText = e instanceof Error ? e.message : String(e)
    phase = 'error'
    running = null
  }

  // A restart of the backend loses an unfinished game (it lives in the sidecar until it ends).
  let wasPlayingAtRestart = false
  async function resyncAfterRestart() {
    const state = await api.getState().catch(() => null)
    if (state?.active) return
    lostAt = sans.length
    running = null
    board?.cancelPremove()
    newGame()
  }

  // ── moves ──────────────────────────────────────────────────────────────────
  // A promotion arrives with its piece: the board's picker asks first (UI-BUILD-4 D). The
  // clocks keep running while it is open.
  function onUserMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    void submitMove(orig, dest, promo)
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
    switchClock(null, engineSide)
    // the clock this move leaves (increment included), saved as its [%clk] (UI-BUILD-3 F)
    const clockMs = clockAfterMove(clocks[gameColor], incrementMs)
    try {
      const res = await api.userMove(orig + dest + (promo ?? ''), clockMs)
      if (!res.ok) {
        phase = 'playing'
        sans = sans.slice(0, -1)
        positions = positions.slice(0, -1)
        moveSquares = moveSquares.slice(0, -1)
        syncFromFen(prevFen)
        switchClock(null, gameColor)
        return
      }
      clocks[gameColor] += incrementMs
      if (res.end) finishGame(res.end)
    } catch (e) {
      fail(e)
    }
  }
  async function onEngineMove(d: EngineMoveEvent) {
    if (!inGame) return
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
    switchClock(engineSide, gameColor)
    // the sidecar measured the engine's move and saved this clock with it (UI-BUILD-3 F)
    clocks[engineSide] = engineClockAfter(d.clockMs, clocks[engineSide])
    await tick()
    if (wasLive) board?.playPremove()
  }

  // ── resign / offer a draw: a second click within 3 s confirms ───────────────
  function requestAction(action: 'resign' | 'draw') {
    if (!inGame) return
    if (confirmAction === action) {
      confirmAction = null
      clearTimeout(confirmTimer)
      void (action === 'resign' ? doEnd(api.resign) : doEnd(api.draw))
      return
    }
    confirmAction = action
    clearTimeout(confirmTimer)
    confirmTimer = setTimeout(() => (confirmAction = null), 3000)
  }
  async function doEnd(call: () => Promise<{ end: GameEndInfo }>) {
    try {
      finishGame((await call()).end)
    } catch (e) {
      fail(e)
    }
  }

  // ── keys and ⌘K ───────────────────────────────────────────────────────────
  function flip() {
    flipped = !flipped
  }
  function selectPly(p: number) {
    // p: positions index (moves played); the last one is live
    viewPly = p >= sans.length ? null : p
  }
  function onKey(e: KeyboardEvent) {
    if (!active || commandMenu.open || e.defaultPrevented) return   // B6: once per key press
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'TEXTAREA' || t.isContentEditable || (t.tagName === 'INPUT' && (t as HTMLInputElement).type !== 'range'))) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'f' || e.key === 'F') {
      flip()
    } else if (e.key === 'Enter') {
      // ↵ is the panel's primary action; a focused button other than a choice keeps its own
      if (t && (t.tagName === 'A' || (t.tagName === 'BUTTON' && t.getAttribute('role') !== 'radio'))) return
      if (phase === 'setup') void startGame()
      else if (phase === 'over') openReview()
      else return
    } else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && started && t?.getAttribute('role') !== 'radio') {
      if (t?.tagName === 'INPUT') return
      const total = sans.length
      if (!total) return
      const cur = viewPly === null ? total : viewPly
      selectPly(e.key === 'ArrowLeft' ? Math.max(0, cur - 1) : Math.min(total, cur + 1))
    } else return
    e.preventDefault()
  }
  function provide(): Command[] {
    if (!active) return []
    const out: Command[] = []
    if (phase === 'setup') out.push({ id: 'play-start', group: 'Actions', label: 'Start game', kbd: '↵', run: () => void startGame() })
    if (inGame) {
      out.push({ id: 'play-draw', group: 'Actions', label: 'Offer a draw', run: () => requestAction('draw') })
      out.push({ id: 'play-resign', group: 'Actions', label: 'Resign', run: () => requestAction('resign') })
    }
    if (phase === 'over') out.push({ id: 'play-review', group: 'Actions', label: 'Open review', kbd: '↵', run: openReview })
    out.push({ id: 'play-flip', group: 'Actions', label: 'Flip the board', kbd: 'F', run: flip })
    return out
  }

  // ── radiogroups: arrow keys move the choice ───────────────────────────────
  function radioKeys(e: KeyboardEvent, values: number[], current: number, set: (v: number) => void) {
    const i = values.indexOf(current)
    let next: number | null = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = values[(i + 1) % values.length]
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = values[(i + values.length - 1) % values.length]
    if (next === null) return
    e.preventDefault()
    e.stopPropagation()
    set(next)
    ;(e.currentTarget as HTMLElement).closest('[role=radiogroup]')?.querySelector<HTMLElement>('[data-v="' + next + '"]')?.focus()
  }
  const TC_ORDER = TC_GROUPS.flatMap((g) => g.indexes)

  // ── the board fills its column ────────────────────────────────────────────
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  let moveScroll: HTMLElement | undefined = $state()
  $effect(() => {
    // keep the newest move in view while following the game
    void sans.length
    if (viewPly === null && moveScroll) moveScroll.scrollTop = moveScroll.scrollHeight
  })

  let unregister: (() => void) | null = null
  let unsubscribe: (() => void) | null = null
  const onReady = (d: Record<string, unknown>) => {
    const r = d as unknown as ReadyEvent
    if (r.ok) {
      if (phase === 'boot' || phase === 'noengine') phase = 'setup'
    } else if (!started) phase = 'noengine'
  }
  const onEngineMoveEvt = (d: Record<string, unknown>) => void onEngineMove(d as unknown as EngineMoveEvent)
  const onOpening = (d: Record<string, unknown>) => {
    if (started) opening = { eco: String(d.eco), name: String(d.name) }
  }
  const onEngineError = (d: Record<string, unknown>) => {
    if (!inGame) return
    errorKind = 'engine'
    fail(String(d.message ?? 'unknown error'))
  }

  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      // the smaller of the column's width and the height left (fifth rulings, 2): no 744 px cap
      // a multiple of 8: chessground draws whole-pixel squares, so the strips, bar and
      // navigator line up with the board drawn (UI-BUILD-4 C)
      boardPx = Math.max(240, Math.floor((Math.min(r.width - 56, r.height - 44 - 88)) / 8) * 8)
    })
    if (section) ro.observe(section)
    let asked = false
    unsubscribe = sidecar.onStatus((s) => {
      if (s === 'restarting') wasPlayingAtRestart = inGame
      else if (s === 'up') {
        if (wasPlayingAtRestart) {
          wasPlayingAtRestart = false
          void resyncAfterRestart()
        }
        // The ready event can come before this screen subscribes (the harness starts the
        // sidecar first); ask once as well, and let a later ready win.
        if (!asked) {
          asked = true
          api
            .engineStatus()
            .then((st) => {
              if (phase === 'boot') phase = st.ok ? 'setup' : 'noengine'
            })
            .catch(() => {})
        }
      }
    })
    sidecar.on('ready', onReady)
    sidecar.on('engine_move', onEngineMoveEvt)
    sidecar.on('opening', onOpening)
    sidecar.on('engine_error', onEngineError)
    unregister = registerCommands('play', provide)
    ticker = setInterval(clockTick, 100)
    return () => ro.disconnect()
  })
  onDestroy(() => {
    clearInterval(ticker)
    clearTimeout(confirmTimer)
    sidecar.off('ready', onReady)
    sidecar.off('engine_move', onEngineMoveEvt)
    sidecar.off('opening', onOpening)
    sidecar.off('engine_error', onEngineError)
    unsubscribe?.()
    unregister?.()
    playState.inGame = false
  })

  const strips = $derived.by(() => {
    const engine = engineStrip(hasGame ? gameLevel : level)
    const me = youStrip(accounts)
    const strip = (side: Color) =>
      side === engineSide
        ? { name: engine.name, rating: engine.rating, you: false, engine: true, note: null }
        : { name: me.name, rating: null, you: me.you, engine: false, note: phase === 'playing' ? 'Your move' : null }
    return { top: strip(top), bottom: strip(bottom) }
  })
  const openingTitle = $derived(opening?.name ?? (fromFen ? 'From a set position' : 'Starting position'))
</script>

<svelte:window onkeydown={onKey} />

<div class="play">
  <header>
    {#if hasGame}
      <div class="crumb">
        <span class="back">Play</span>
        <span class="sep" aria-hidden="true">/</span>
        <span class="title">{crumbTitle(gameLevel)}</span>
        <span class="ctc">{tcLabel(PLAY_TIME_CONTROLS[gameTc])}</span>
      </div>
    {:else}
      <h1>Play</h1>
    {/if}
    <Button kbd="F" onclick={flip}>Flip</Button>
  </header>

  <div class="body">
    <section class="board-col" aria-label="Board" bind:this={section}>
      <div class="col" style:width="{boardPx}px">
        <PlayerStrip
          size="lg"
          name={strips.top.name}
          rating={strips.top.rating}
          you={strips.top.you}
          engine={strips.top.engine}
          note={strips.top.note}
          clock={clockFor(top)}
          active={running === top}
        />
        <div class="board" style:width="{boardPx}px" style:height="{boardPx}px">
          <Board
            bind:this={board}
            fen={viewFen}
            lastMove={viewLastMove}
            turnColor={viewTurn}
            movableColor={movable}
            dests={movable ? dests : NO_DESTS}
            check={viewCheck}
            {orientation}
            premovable={inGame && isLive}
            onmove={onUserMove}
          />
        </div>
        <PlayerStrip
          size="lg"
          name={strips.bottom.name}
          rating={strips.bottom.rating}
          you={strips.bottom.you}
          engine={strips.bottom.engine}
          note={strips.bottom.note}
          clock={clockFor(bottom)}
          active={running === bottom}
        />
      </div>
    </section>

    {#if started || phase === 'error'}
      <aside aria-label="Game">
        {#if phase === 'error'}
          <div class="pad">
            {#if errorKind === 'start'}
              <EmptyState tone="error" sentence="The game could not start." sub={errorText} action={{ label: 'Back to a new game', run: newGame }} />
            {:else}
              <EmptyState
                tone="error"
                sentence="The engine stopped, so this game ended unsaved."
                sub={errorText}
                action={{ label: 'New game', run: newGame, primary: true }}
              />
            {/if}
          </div>
        {:else}
          <div class="opening">
            <div class="oname">{openingTitle}</div>
            <div class="osub">{openingSub(opening?.eco ?? null)}</div>
          </div>
          <div class="moves" role="grid" aria-label="Moves" bind:this={moveScroll}>
            {#each rows as r (r.number)}
              <div class="mrow" role="row">
                <span class="num" role="rowheader">{r.number}.</span>
                {#each [r.white, r.black] as c, k (k)}
                  {#if c}
                    {@const sel = currentPly === c.ply + 1}
                    <button type="button" role="gridcell" class="cell" class:sel aria-selected={sel} onclick={() => selectPly(c.ply + 1)}>{c.san}</button>
                  {:else}
                    <span class="cell empty" role="gridcell">{k === 0 ? '…' : ''}</span>
                  {/if}
                {/each}
              </div>
            {/each}
          </div>
          <div class="foot">
            {#if phase === 'over' && endInfo}
              <p class="result" role="status">{resultSentence(endInfo, gameColor)}</p>
              <Button variant="primary" kbd="↵" onclick={openReview}>Open review</Button>
              <Button onclick={newGame}>New game</Button>
            {:else}
              <div class="two">
                <Button pressed={confirmAction === 'draw'} onclick={() => requestAction('draw')}
                  >{confirmAction === 'draw' ? 'Confirm the draw' : 'Offer a draw'}</Button
                >
                <Button pressed={confirmAction === 'resign'} onclick={() => requestAction('resign')}
                  >{confirmAction === 'resign' ? 'Confirm resign' : 'Resign'}</Button
                >
              </div>
              <p class="note">No engine help while you play. Review opens when the game ends.</p>
            {/if}
          </div>
        {/if}
      </aside>
    {:else}
      <aside aria-label="New game">
        <div class="ptitle"><h2>New game against Stockfish</h2></div>
        {#if phase === 'boot'}
          <div class="pad"><EmptyState sentence="Starting the engine…" /></div>
        {:else if phase === 'noengine'}
          <div class="pad">
            <EmptyState
              sentence="Play needs Stockfish, and none was found."
              sub="Choose a Stockfish binary in Settings, then start a game."
              action={{ label: 'Open Settings', run: onsettings }}
            />
          </div>
        {:else}
          <div class="form">
            {#if lostAt !== null}
              <EmptyState
                tone="error"
                sentence="The engine restarted, so the game in progress was lost."
                sub="Games are saved only when they finish."
                action={{ label: 'Dismiss', run: () => (lostAt = null) }}
              />
            {/if}
            <div>
              <div id="side-l" class="lbl">Play as</div>
              <div class="seg" role="radiogroup" aria-labelledby="side-l">
                {#each SIDES as c, i (c)}
                  <button
                    type="button"
                    role="radio"
                    aria-checked={color === c}
                    tabindex={color === c ? 0 : -1}
                    data-v={i}
                    onclick={() => (color = c)}
                    onkeydown={(e) => radioKeys(e, [0, 1], color === 'white' ? 0 : 1, (v) => (color = v === 0 ? 'white' : 'black'))}
                    ><span class="sw {c}" aria-hidden="true"></span>{c === 'white' ? 'White' : 'Black'}</button
                  >
                {/each}
              </div>
            </div>
            <div>
              <div class="lblrow">
                <label id="lvl-l" class="lbl" for="lvl">Strength</label>
                <span class="lv">Level {level} <span class="of">of {LEVEL_MAX}</span></span>
              </div>
              <input
                id="lvl"
                class="slider"
                type="range"
                min="0"
                max={LEVEL_MAX}
                step="1"
                bind:value={level}
                aria-valuetext="Level {level} of {LEVEL_MAX}"
                style:--pct="{(level / LEVEL_MAX) * 100}%"
              />
              <div class="ticks" aria-hidden="true"><span>0</span><span>5</span><span>10</span><span>15</span><span>20</span></div>
            </div>
            <div>
              <div id="tc-l" class="lbl">Time control</div>
              <div class="tcs" role="radiogroup" aria-labelledby="tc-l">
                {#each TC_GROUPS as g (g.speed)}
                  <span class="speed">{g.label}</span>
                  {#each g.indexes as i (i)}
                    <button
                      type="button"
                      role="radio"
                      class="tc"
                      aria-checked={tcIndex === i}
                      aria-label="{tcLabel(PLAY_TIME_CONTROLS[i])} {g.label}"
                      tabindex={tcIndex === i ? 0 : -1}
                      data-v={i}
                      onclick={() => (tcIndex = i)}
                      onkeydown={(e) => radioKeys(e, TC_ORDER, tcIndex, (v) => (tcIndex = v))}>{tcLabel(PLAY_TIME_CONTROLS[i])}</button
                    >
                  {/each}
                  {#each Array(4 - g.indexes.length) as _, k (k)}<span></span>{/each}
                {/each}
              </div>
            </div>
          </div>
          <div class="start">
            <button type="button" class="startbtn" onclick={() => startGame()}>Start game <Kbd keys="↵" plain /></button>
            <p class="saved">Saved to your games when it finishes.</p>
          </div>
        {/if}
      </aside>
    {/if}
  </div>
</div>

<style>
  .play {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  header {
    height: var(--header-height);
    flex: none;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 0 16px 0 20px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .crumb {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    white-space: nowrap;
  }
  .back,
  .ctc {
    color: var(--text-3);
  }
  .sep {
    color: var(--disabled);
  }
  .title {
    font-weight: 500;
  }
  .body {
    flex: 1;
    display: flex;
    min-height: 0;
  }
  .board-col {
    flex: 1 1 520px;
    min-width: 0;
    box-sizing: border-box;
    padding: 20px 28px 24px;
    display: flex;
    justify-content: center;
    overflow: hidden;
  }
  .col {
    display: flex;
    flex-direction: column;
  }
  aside {
    flex: 0 1 var(--panel-width);
    min-width: 320px;
    min-height: 0;
    box-sizing: border-box;
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
  }
  .pad {
    padding: var(--space-6);
  }
  .ptitle {
    height: var(--tab-height);
    flex: none;
    display: flex;
    align-items: center;
    padding: 0 var(--space-6);
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
  }
  .form {
    padding: var(--space-6);
    display: flex;
    flex-direction: column;
    gap: 22px;
    overflow-y: auto;
  }
  .lbl {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
    margin-bottom: 8px;
  }
  .lblrow {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 10px;
  }
  .lblrow .lbl {
    margin: 0;
  }
  .lv {
    font-weight: 500;
  }
  .of {
    color: var(--text-3);
    font-weight: 400;
  }
  .seg {
    display: flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .seg button {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 6px 10px;
    color: var(--text-2);
    font: var(--body);
    cursor: pointer;
  }
  .seg button[aria-checked='true'] {
    background: var(--border);
    color: var(--text);
  }
  .sw {
    width: 12px;
    height: 12px;
    border-radius: 3px;
  }
  .sw.white {
    background: var(--text);
    box-shadow: inset 0 0 0 1px var(--text-3);
  }
  .sw.black {
    background: var(--sidebar);
    box-shadow: inset 0 0 0 1px var(--disabled);
  }
  /* the level slider: a 4px track, filled to the thumb in text colour */
  .slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 18px;
    margin: 0;
    background: transparent;
    cursor: pointer;
  }
  .slider::-webkit-slider-runnable-track {
    height: 4px;
    border-radius: 2px;
    background: linear-gradient(to right, var(--text) var(--pct), var(--border) var(--pct));
  }
  .slider::-moz-range-track {
    height: 4px;
    border-radius: 2px;
    background: linear-gradient(to right, var(--text) var(--pct), var(--border) var(--pct));
  }
  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    margin-top: -6px;
    border-radius: 8px;
    background: var(--text);
    box-shadow: 0 0 0 3px var(--bg);
    border: 0;
  }
  .slider::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    background: var(--text);
    box-shadow: 0 0 0 3px var(--bg);
    border: 0;
  }
  .ticks {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    font-size: 11px;
    color: var(--text-3);
  }
  .tcs {
    display: grid;
    grid-template-columns: 72px repeat(4, minmax(0, 1fr));
    gap: 6px;
    align-items: center;
  }
  .speed {
    color: var(--text-2);
  }
  .tc {
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 6px 0;
    color: var(--text-2);
    text-align: center;
    font: var(--body);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .tc:hover {
    border-color: var(--border-strong);
    color: var(--text);
  }
  .tc[aria-checked='true'] {
    background: var(--primary);
    border-color: var(--primary);
    color: var(--primary-ink);
    font-weight: 500;
  }
  .start {
    margin-top: auto;
    padding: 16px var(--space-6) var(--space-6);
    border-top: 1px solid var(--border);
  }
  .startbtn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: var(--primary);
    border: 1px solid var(--primary);
    border-radius: var(--radius-control);
    padding: 9px 12px;
    color: var(--primary-ink);
    font: var(--body-strong);
    cursor: pointer;
  }
  .startbtn:hover {
    background: #ffffff;
  }
  .saved {
    margin: 10px 0 0;
    text-align: center;
    color: var(--text-3);
    font: var(--secondary);
  }
  .opening {
    flex: none;
    padding: 14px var(--space-6) 12px;
    border-bottom: 1px solid var(--border);
  }
  .oname {
    font-weight: 500;
  }
  .osub {
    color: var(--text-3);
    font: var(--secondary);
    margin-top: 2px;
  }
  .moves {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 8px 12px;
  }
  .mrow {
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
    gap: 4px;
    min-height: 30px;
  }
  .num {
    color: var(--text-3);
    padding-left: 8px;
    font-variant-numeric: tabular-nums;
  }
  .cell {
    padding: 4px 8px;
    border-radius: var(--radius-control);
    background: transparent;
    border: 0;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .cell:hover {
    background: var(--raised);
  }
  .cell.sel {
    background: var(--selected);
    box-shadow: inset 0 0 0 1px var(--border-strong);
    font-weight: 600;
  }
  .cell.empty {
    color: var(--text-3);
    cursor: default;
  }
  .cell.empty:hover {
    background: transparent;
  }
  .foot {
    flex: none;
    padding: 14px var(--space-6) 18px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .two :global(.btn) {
    padding: 7px 12px;
  }
  .note {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
    text-align: center;
  }
  .result {
    margin: 0;
    font-weight: 500;
  }
  button:focus-visible,
  .slider:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
