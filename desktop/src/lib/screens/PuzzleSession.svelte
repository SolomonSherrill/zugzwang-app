<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { fade } from 'svelte/transition'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import MoveList from '../MoveList.svelte'
  import type { PromotionRequest } from '../Board.svelte'
  import { resolveUserMove } from '../puzzleMove'
  import { PUZZLE_WAIT_EXPLAIN_MS, puzzleWaitCaption } from '../puzzleWait'

  type Role = 'queen' | 'knight' | 'rook' | 'bishop'
  const ROLE_CHAR: Record<Role, string> = { queen: 'q', knight: 'n', rook: 'r', bishop: 'b' }
  import {
    api,
    PUZZLE_SURVIVAL_START_OFFSET,
    PUZZLE_SURVIVAL_FLOOR,
    PUZZLE_SURVIVAL_STEP,
    PUZZLE_SURVIVAL_RANGE,
    type PuzzleMode,
    type PuzzleRecord,
    type LeaderboardResult,
  } from '../api'

  interface Props {
    config: PuzzleMode
    onexit: () => void
  }
  let { config, onexit }: Props = $props()

  // Timing constants mirror config.py (PUZZLE_SETUP_DELAY_MS etc.)
  const SETUP_DELAY = 600
  const ANIM = 300
  const RUSH_NEXT_DELAY = 800
  const AUTO_CONTINUE_DELAY = 900
  const EMPTY_FEN = '8/8/8/8/8/8/8/8'
  // hold the loader back briefly so quick loads never flash a spinner
  const LOADER_DELAY = 120

  type SState =
    | 'loading'
    | 'setup' // setup move pending/animating
    | 'awaiting' // user to move
    | 'animating' // user/opponent move animating
    | 'complete' // solved or gave up — waiting on Next
    | 'solution' // stepping through the solution
    | 'ended' // rush time-up / survival run over

  const chess = new Chess()
  let board: Board

  let sstate = $state<SState>('loading')
  let puzzle = $state<PuzzleRecord | null>(null)
  let fen = $state('start')
  let promotion = $state<PromotionRequest | null>(null)
  let promoPending: { orig: Key; dest: Key } | null = null
  let lastMove = $state<[Key, Key] | null>(null)
  let dests = $state<Map<Key, Key[]>>(new Map())
  let check = $state(false)
  let orientation = $state<'white' | 'black'>('white')
  let hintArrow = $state<DrawShape[]>([])

  let solutionMoves: string[] = []
  let solutionIdx = 0
  // SAN of moves actually played in the current puzzle (setup move onward)
  let sans = $state<string[]>([])
  let failed = $state(false)
  let gaveUp = false
  let usedHint = false
  let ratingBefore: number | null = null
  let solveStart = 0

  let rating = $state(0)
  let score = $state(0)
  let streak = $state(0)
  let correct = $state(0)
  let wrong = $state(0)
  let difficultyOffset = 0
  let sessionId: number | null = null
  let prefetch: PuzzleRecord[] = []
  let refilling = false

  let rushRemaining = $state(0)
  let rushTimer: ReturnType<typeof setInterval> | undefined

  let feedback = $state<{ text: string; kind: 'correct' | 'wrong' | 'info'; change?: string } | null>(null)
  let showNext = $state(false)
  let autoContinue = $state(false)
  let showSolution = $state(false)
  let showNewRun = $state(false)
  let endBoard = $state<LeaderboardResult | null>(null)

  // solution view
  let solMoves = $state<string[]>([])
  let solIdx = $state(0)
  let timeouts: ReturnType<typeof setTimeout>[] = []

  const isRatedLike = $derived(config.mode === 'rated' || config.mode === 'theme')
  const turnColor = $derived<'white' | 'black'>(fen.split(' ')[1] === 'w' ? 'white' : 'black')
  const movableColor = $derived(sstate === 'awaiting' ? orientation : null)
  // empty board while the first puzzle loads — avoids flashing the start position
  const boardFen = $derived(sstate === 'loading' ? EMPTY_FEN : fen)

  // move list — puzzles begin mid-game, so derive the starting move number and
  // side to move from the puzzle FEN (the setup move is played by that side).
  const fenFields = $derived(puzzle?.fen.split(' ') ?? [])
  const movesBlackFirst = $derived(fenFields[1] === 'b')
  const movesStartNumber = $derived(Number(fenFields[5]) || 1)
  // while solving, only reveal moves already played (no spoilers); in the
  // solution view, show the full line and follow the stepper.
  const fullSolutionSans = $derived.by(() => {
    if (!puzzle) return []
    const b = new Chess(puzzle.fen)
    return puzzle.movesUci.map((uci) => b.move(uciToObj(uci)).san)
  })
  const listSans = $derived(sstate === 'solution' ? fullSolutionSans : sans)
  const listPly = $derived(sstate === 'solution' ? solIdx + 1 : sans.length)

  // delayed loader: only reveal the knight if the initial load takes a beat
  let showLoader = $state(false)
  let waitedMs = $state(0)
  const loaderCaption = $derived(puzzleWaitCaption(waitedMs))
  let loaderTimer: ReturnType<typeof setTimeout> | undefined
  let explainTimer: ReturnType<typeof setTimeout> | undefined
  $effect(() => {
    if (sstate === 'loading') {
      loaderTimer = setTimeout(() => (showLoader = true), LOADER_DELAY)
      explainTimer = setTimeout(
        () => (waitedMs = PUZZLE_WAIT_EXPLAIN_MS),
        PUZZLE_WAIT_EXPLAIN_MS,
      )
    } else {
      clearTimeout(loaderTimer)
      clearTimeout(explainTimer)
      showLoader = false
      waitedMs = 0
    }
    return () => {
      clearTimeout(loaderTimer)
      clearTimeout(explainTimer)
    }
  })

  function later(ms: number, fn: () => void) {
    timeouts.push(setTimeout(fn, ms))
  }

  function computeDests(): Map<Key, Key[]> {
    const map = new Map<Key, Key[]>()
    for (const m of chess.moves({ verbose: true })) {
      const arr = map.get(m.from as Key) ?? []
      arr.push(m.to as Key)
      map.set(m.from as Key, arr)
    }
    return map
  }

  function syncBoard() {
    fen = chess.fen()
    check = chess.inCheck()
    dests = computeDests()
  }

  // ── session lifecycle ────────────────────────────────────────────────────

  async function start() {
    const r = await api.getPuzzleRating()
    rating = r.rating
    if (config.mode === 'rush') {
      sessionId = (await api.startPuzzleSession('rush', config.rushSeconds)).sessionId
      rushRemaining = config.rushSeconds
      rushTimer = setInterval(onRushTick, 1000)
    } else if (config.mode === 'survival') {
      sessionId = (await api.startPuzzleSession('survival', null)).sessionId
    }
    await loadNext()
  }

  async function refillPrefetch() {
    if (refilling) return
    refilling = true
    try {
      const survivalStart = Math.max(PUZZLE_SURVIVAL_FLOOR, rating + PUZZLE_SURVIVAL_START_OFFSET)
      const target = config.mode === 'survival' ? survivalStart + difficultyOffset : rating
      const rng = config.mode === 'survival' ? PUZZLE_SURVIVAL_RANGE : config.ratingRange
      const res = await api.nextPuzzles(target, rng, config.themes)
      const known = new Set(prefetch.map((p) => p.id))
      prefetch.push(...res.puzzles.filter((p) => !known.has(p.id)))
    } finally {
      refilling = false
    }
  }

  async function loadNext() {
    if (prefetch.length === 0) await refillPrefetch()
    const next = prefetch.shift()
    if (!next) {
      feedback = { text: 'No puzzles found in this range — try widening the rating range.', kind: 'info' }
      return
    }
    startPuzzle(next)
    if (prefetch.length < 3) void refillPrefetch()
  }

  function startPuzzle(p: PuzzleRecord) {
    puzzle = p
    solutionMoves = p.movesUci.slice(1) // strip the setup move
    solutionIdx = 0
    failed = false
    gaveUp = false
    usedHint = false
    ratingBefore = rating
    solveStart = performance.now()
    feedback = null
    showNext = false
    showSolution = false
    hintArrow = []
    lastMove = null
    sans = []

    chess.load(p.fen)
    orientation = chess.turn() === 'w' ? 'black' : 'white' // user plays the other side
    sstate = 'setup'
    syncBoard()

    later(SETUP_DELAY, () => {
      applyMove(p.movesUci[0])
      later(ANIM + 60, () => {
        sstate = 'awaiting'
        syncBoard()
      })
    })
  }

  function applyMove(uci: string) {
    const mv = chess.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: (uci[4] as 'q' | 'r' | 'b' | 'n' | undefined) ?? undefined,
    })
    sans = [...sans, mv.san]
    lastMove = [uci.slice(0, 2) as Key, uci.slice(2, 4) as Key]
    syncBoard()
  }

  // ── user moves ───────────────────────────────────────────────────────────

  function onUserMove(orig: Key, dest: Key) {
    if (sstate !== 'awaiting' || !puzzle) return
    // Ask which piece before judging the move. Without this the board only ever
    // reports from/to, so an underpromotion puzzle could not be answered as
    // anything but the piece the solution already named (F8).
    if (chess.moves({ square: orig as Square, verbose: true }).some(
        (m) => m.to === dest && m.promotion)) {
      promoPending = { orig, dest }
      promotion = { col: dest.charCodeAt(0) - 97, color: chess.turn() === 'w' ? 'white' : 'black' }
      return
    }
    judgeMove(`${orig}${dest}`)
  }

  function onPromote(role: Role | null) {
    promotion = null
    const pending = promoPending
    promoPending = null
    if (!pending) return
    if (role === null) {
      board?.sync()
      return
    }
    judgeMove(`${pending.orig}${pending.dest}${ROLE_CHAR[role]}`)
  }

  function judgeMove(played: string) {
    if (!puzzle) return
    const verdict = resolveUserMove({
      expected: solutionMoves[solutionIdx],
      played,
      isFinal: solutionIdx === solutionMoves.length - 1,
      finalMates: puzzle.finalMates,
    })
    if (verdict.ok) onCorrect(verdict.uci)
    else onWrong()
  }

  function onCorrect(uci: string) {
    sstate = 'animating'
    hintArrow = []
    applyMove(uci)
    solutionIdx += 1
    later(280, () => {
      if (solutionIdx >= solutionMoves.length) void complete()
      else playOpponent()
    })
  }

  function onWrong() {
    if (!failed) void applyFail()
    if (config.mode === 'survival') {
      void endSurvival()
      return
    }
    // chessground already shows the wrong move; flash briefly, then snap back
    sstate = 'animating'
    later(350, () => {
      sstate = 'awaiting'
      syncBoard()
      board?.sync()
      if (!feedback || feedback.kind !== 'wrong') feedback = { text: 'Wrong — try again', kind: 'wrong' }
    })
  }

  async function applyFail() {
    failed = true
    if (isRatedLike && puzzle) {
      const res = await api.ratePuzzle(puzzle.rating, puzzle.ratingDeviation, 0.0)
      const change = res.rating - res.before
      rating = res.rating
      streak = 0
      wrong += 1
      feedback = {
        text: 'Incorrect',
        kind: 'wrong',
        change: `${res.before.toFixed(0)} → ${res.rating.toFixed(0)}  (${change >= 0 ? '+' : ''}${change.toFixed(0)})`,
      }
    } else {
      feedback = { text: 'Incorrect', kind: 'wrong' }
    }
  }

  function playOpponent() {
    const uci = solutionMoves[solutionIdx]
    later(120, () => {
      applyMove(uci)
      solutionIdx += 1
      later(ANIM + 60, () => {
        if (solutionIdx >= solutionMoves.length) void complete()
        else {
          sstate = 'awaiting'
          syncBoard()
        }
      })
    })
  }

  // ── completion / fail endings ────────────────────────────────────────────

  async function complete() {
    if (!puzzle) return
    sstate = 'complete'
    const solveTime = (performance.now() - solveStart) / 1000
    let ratingAfter: number | null = null

    if (isRatedLike && !failed) {
      const res = await api.ratePuzzle(puzzle.rating, puzzle.ratingDeviation, 1.0)
      const change = res.rating - res.before
      rating = res.rating
      ratingAfter = res.rating
      streak += 1
      correct += 1
      feedback = {
        text: 'Correct!',
        kind: 'correct',
        change: `${res.before.toFixed(0)} → ${res.rating.toFixed(0)}  (${change >= 0 ? '+' : ''}${change.toFixed(0)})`,
      }
    } else if (failed) {
      feedback = { text: 'Solved!', kind: 'correct' }
      ratingAfter = rating
    } else {
      feedback = { text: 'Correct!', kind: 'correct' }
    }

    score += 1
    if (config.mode === 'survival') {
      difficultyOffset += PUZZLE_SURVIVAL_STEP
      if (sessionId !== null) await api.updatePuzzleSession(sessionId, score, puzzle.rating)
    }

    await api.savePuzzleAttempt({
      puzzle_id: puzzle.id,
      session_id: sessionId,
      mode: config.mode,
      solved: true,
      failed,
      used_hint: false,
      gave_up: false,
      solve_time_s: solveTime,
      rating_before: ratingBefore,
      rating_after: ratingAfter,
    })

    if (config.mode === 'rush') {
      later(RUSH_NEXT_DELAY, () => void loadNext())
    } else {
      showNext = true
      if (autoContinue) later(AUTO_CONTINUE_DELAY, () => sstate === 'complete' && onNext())
    }
  }

  async function onHint() {
    if (sstate !== 'awaiting' || solutionIdx >= solutionMoves.length || !puzzle) return
    usedHint = true
    if (!failed) await applyFail()
    if (config.mode === 'survival') {
      void endSurvival()
      return
    }
    const expected = solutionMoves[solutionIdx]
    hintArrow = [
      { orig: expected.slice(0, 2) as Key, dest: expected.slice(2, 4) as Key, brush: 'green' },
    ]
    feedback = { text: 'Hint revealed', kind: 'info' }
    showNext = true
    showSolution = true
  }

  async function onGiveUp() {
    if (!puzzle || (sstate !== 'awaiting' && sstate !== 'complete')) return
    gaveUp = true
    if (!failed) await applyFail()
    sstate = 'complete'
    if (config.mode === 'survival') {
      void endSurvival()
      return
    }
    showNext = true
    showSolution = true
    await api.savePuzzleAttempt({
      puzzle_id: puzzle.id,
      session_id: sessionId,
      mode: config.mode,
      solved: false,
      failed: true,
      used_hint: usedHint,
      gave_up: true,
      solve_time_s: (performance.now() - solveStart) / 1000,
      rating_before: ratingBefore,
      rating_after: rating,
    })
  }

  async function endSurvival() {
    sstate = 'ended'
    const peak = puzzle?.rating ?? 0
    if (sessionId !== null) await api.updatePuzzleSession(sessionId, score, peak)
    if (puzzle) {
      await api.savePuzzleAttempt({
        puzzle_id: puzzle.id,
        session_id: sessionId,
        mode: config.mode,
        solved: false,
        failed: true,
        used_hint: usedHint,
        gave_up: gaveUp,
        solve_time_s: (performance.now() - solveStart) / 1000,
        rating_before: ratingBefore,
        rating_after: rating,
      })
    }
    feedback = {
      text: `Run over — streak ${score} puzzle${score === 1 ? '' : 's'}, peak difficulty ${peak}`,
      kind: 'info',
    }
    showNewRun = true
    showSolution = true
    endBoard = await api.puzzleLeaderboard('survival', null, 10)
  }

  function onRushTick() {
    rushRemaining -= 1
    if (rushRemaining <= 0) void endRush()
  }

  async function endRush() {
    clearInterval(rushTimer)
    rushTimer = undefined
    sstate = 'ended'
    if (sessionId !== null) await api.updatePuzzleSession(sessionId, score)
    feedback = { text: `Time's up — score ${score}`, kind: 'info' }
    showNewRun = true
    endBoard = await api.puzzleLeaderboard('rush', config.rushSeconds, 10)
  }

  function onNext() {
    if (config.mode === 'survival' && failed) return
    hintArrow = []
    void loadNext()
  }

  function newRun() {
    // fresh session of the same config
    endBoard = null
    showNewRun = false
    score = 0
    difficultyOffset = 0
    feedback = null
    void start()
  }

  // ── solution view ────────────────────────────────────────────────────────

  function viewSolution() {
    if (!puzzle) return
    solMoves = solutionMoves.slice()
    solIdx = 0
    sstate = 'solution'
    showSolutionStep(0)
  }

  function solutionStep(delta: number) {
    const next = Math.max(0, Math.min(solMoves.length, solIdx + delta))
    if (next === solIdx) return
    solIdx = next
    showSolutionStep(next)
  }

  function showSolutionStep(idx: number) {
    if (!puzzle) return
    const b = new Chess(puzzle.fen)
    b.move(uciToObj(puzzle.movesUci[0]))
    for (const uci of solMoves.slice(0, idx)) b.move(uciToObj(uci))
    chess.load(b.fen())
    fen = b.fen()
    check = b.inCheck()
    dests = new Map()
    lastMove =
      idx > 0
        ? [solMoves[idx - 1].slice(0, 2) as Key, solMoves[idx - 1].slice(2, 4) as Key]
        : [puzzle.movesUci[0].slice(0, 2) as Key, puzzle.movesUci[0].slice(2, 4) as Key]
    hintArrow =
      idx < solMoves.length
        ? [{ orig: solMoves[idx].slice(0, 2) as Key, dest: solMoves[idx].slice(2, 4) as Key, brush: 'green' }]
        : []
  }

  function uciToObj(uci: string) {
    return {
      from: uci.slice(0, 2) as Square,
      to: uci.slice(2, 4) as Square,
      promotion: (uci[4] as 'q' | 'r' | 'b' | 'n' | undefined) ?? undefined,
    }
  }

  function fmtRush(s: number): string {
    return `${Math.floor(Math.max(0, s) / 60)}:${String(Math.max(0, s) % 60).padStart(2, '0')}`
  }

  const modeLabel: Record<string, string> = {
    rated: 'Rated',
    theme: 'Themes',
    rush: 'Rush',
    survival: 'Survival',
  }

  onMount(() => void start())
  onDestroy(() => {
    clearInterval(rushTimer)
    for (const t of timeouts) clearTimeout(t)
    // mirror PuzzleController.cleanup: an abandoned rush still records its score
    if (config.mode === 'rush' && rushRemaining > 0 && sessionId !== null) {
      void api.updatePuzzleSession(sessionId, score)
    }
  })
</script>

<div class="session">
  <div class="board-col">
    <Board
      bind:this={board}
      fen={boardFen}
      {lastMove}
      {turnColor}
      {movableColor}
      dests={sstate === 'awaiting' ? dests : new Map()}
      {check}
      {orientation}
      shapes={hintArrow}
      animationMs={ANIM}
      {promotion}
      onpromote={onPromote}
      onmove={onUserMove}
    />
    {#if showLoader}
      <div class="loader" transition:fade={{ duration: 160 }}>
        <div class="loader-inner">
          <svg class="knight" viewBox="0 0 45 45" aria-hidden="true">
            <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M 22,10 C 32.5,11 38.5,18 38,39 L 15,39 C 15,30 25,32.5 23,18" />
              <path d="M 24,18 C 24.38,20.91 18.45,25.37 16,27 C 13,29 13.18,31.34 11,31 C 9.958,30.06 12.41,27.96 11,28 C 10,28 11.19,29.23 10,30 C 9,30 5.997,31 6,26 C 6,24 12,14 12,14 C 12,14 13.89,12.1 14,10.5 C 13.27,9.506 13.5,8.5 13.5,7.5 C 14.5,6.5 16.5,10 16.5,10 L 18.5,10 C 18.5,10 19.28,8.008 21,7 C 22,7 22,10 22,10" />
            </g>
            <circle cx="9.5" cy="25.5" r="0.95" fill="currentColor" />
          </svg>
          <span class="loader-cap">{loaderCaption}</span>
        </div>
      </div>
    {/if}
  </div>

  <aside class="panel">
    <div class="head">
      <button class="back" onclick={onexit}>← Puzzles</button>
      <div class="head-row">
        <h3>{modeLabel[config.mode]}</h3>
        {#if config.mode === 'rush'}
          <span class="rush-clock" class:low={rushRemaining <= 10 && sstate !== 'ended'}>
            {fmtRush(rushRemaining)}
          </span>
        {/if}
      </div>
      {#if config.mode === 'theme'}
        <span class="sub">{config.themes.join(' · ')}</span>
      {/if}
    </div>

    {#if config.mode === 'rush'}
      <div class="rush-track">
        <div
          class="rush-fill"
          class:low={rushRemaining <= 10 && sstate !== 'ended'}
          style="width: {config.rushSeconds ? (Math.max(0, rushRemaining) / config.rushSeconds) * 100 : 0}%"
        ></div>
      </div>
    {/if}

    <div class="stats">
      {#if isRatedLike}
        <div class="stat">
          <span class="stat-value accent">{rating.toFixed(0)}</span>
          <span class="stat-label">rating</span>
        </div>
        <div class="stat">
          <span class="stat-value">{streak}</span>
          <span class="stat-label">streak</span>
        </div>
        <div class="stat">
          <span class="stat-value">{correct}–{wrong}</span>
          <span class="stat-label">session</span>
        </div>
      {:else}
        <div class="stat">
          <span class="stat-value accent">{score}</span>
          <span class="stat-label">{config.mode === 'survival' ? 'streak' : 'score'}</span>
        </div>
      {/if}
      {#if puzzle && sstate !== 'loading'}
        <div class="stat">
          <span class="stat-value">{puzzle.rating}</span>
          <span class="stat-label">puzzle</span>
        </div>
      {/if}
    </div>

    <div class="turn-line">
      {#if sstate === 'awaiting'}
        <span class="turn-dot {orientation}"></span>
        {orientation === 'white' ? 'White' : 'Black'} to move — find the best move
      {:else if sstate === 'setup' || sstate === 'animating'}
        &nbsp;
      {:else if sstate === 'solution'}
        Solution — {solIdx} / {solMoves.length}
      {/if}
    </div>

    {#if feedback}
      <div class="feedback {feedback.kind}">
        <span class="fb-text">{feedback.text}</span>
        {#if feedback.change}<span class="fb-change">{feedback.change}</span>{/if}
      </div>
    {/if}

    {#if endBoard}
      <div class="end-board">
        {#each endBoard.entries as e, i (i)}
          <div class="lb-row" class:new={i === endBoard.newRank}>
            <span class="lb-rank">{i + 1}</span>
            <span class="lb-score">{e.score}</span>
            <span class="lb-date">{e.date}</span>
          </div>
        {/each}
      </div>
    {/if}

    {#if listSans.length && sstate !== 'ended'}
      <div class="moves">
        <MoveList
          sans={listSans}
          currentPly={listPly}
          startNumber={movesStartNumber}
          blackFirst={movesBlackFirst}
        />
      </div>
    {:else}
      <div class="spacer"></div>
    {/if}

    {#if sstate === 'solution'}
      <div class="controls">
        <button class="btn btn-quiet" onclick={() => solutionStep(-1)}>◀</button>
        <button class="btn btn-quiet" onclick={() => solutionStep(1)}>▶</button>
        {#if showNext && !(config.mode === 'survival' && failed)}
          <button class="btn btn-accent" onclick={onNext}>Next puzzle</button>
        {/if}
        {#if showNewRun}
          <button class="btn btn-accent" onclick={newRun}>New run</button>
        {/if}
      </div>
    {:else if sstate === 'ended'}
      <div class="controls">
        {#if showSolution}
          <button class="btn btn-quiet" onclick={viewSolution}>View solution</button>
        {/if}
        {#if showNewRun}
          <button class="btn btn-accent" onclick={newRun}>New run</button>
        {/if}
        <button class="btn btn-quiet" onclick={onexit}>Back to lobby</button>
      </div>
    {:else if showNext || showSolution}
      <div class="controls">
        {#if showSolution}
          <button class="btn btn-quiet" onclick={viewSolution}>View solution</button>
        {/if}
        {#if showNext}
          <button class="btn btn-accent" onclick={onNext}>Next puzzle</button>
          <button
            class="btn btn-quiet toggle"
            class:on={autoContinue}
            aria-pressed={autoContinue}
            title="Automatically load the next puzzle after each solve"
            onclick={() => (autoContinue = !autoContinue)}
          >
            Auto-continue
          </button>
        {/if}
      </div>
    {:else}
      <div class="controls">
        <button class="btn btn-quiet" disabled={sstate !== 'awaiting'} onclick={onHint}>Hint</button>
        <button class="btn btn-quiet" disabled={sstate !== 'awaiting'} onclick={onGiveUp}>
          Give up
        </button>
      </div>
    {/if}
  </aside>
</div>

<style>
  .session {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 28px;
    padding: 28px;
  }
  .board-col {
    position: relative;
    width: min(calc(100vh - 112px), calc(100vw - 620px), 720px);
    min-width: 380px;
  }

  .loader {
    position: absolute;
    inset: 0;
    z-index: 2;
    display: grid;
    place-items: center;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--bg-deep) 80%, transparent);
  }
  .loader-inner {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 18px;
  }
  .knight {
    width: 94px;
    height: 94px;
    color: var(--accent);
    filter: drop-shadow(0 8px 20px color-mix(in srgb, var(--accent) 30%, transparent));
    animation: knight-pulse 1.4s ease-in-out infinite;
  }
  .loader-cap {
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    /* the slow-path caption is a sentence, not a word */
    max-width: 30ch;
    text-align: center;
    text-wrap: balance;
  }
  @keyframes knight-pulse {
    0%,
    100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.4;
      transform: scale(0.9);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .knight {
      animation: none;
    }
  }
  .panel {
    width: 320px;
    height: min(calc(100vh - 112px), 720px);
    display: flex;
    flex-direction: column;
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-tile);
    overflow: hidden;
  }
  .head {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--divider);
  }
  .back {
    align-self: flex-start;
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 4px;
    transition: color 120ms ease;
  }
  .back:hover {
    color: var(--accent);
  }
  .head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  h3 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }
  .sub {
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .rush-clock {
    font-size: 20px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .rush-clock.low {
    color: var(--danger);
  }

  .rush-track {
    height: 3px;
    background: var(--bg-surface);
    overflow: hidden;
  }
  .rush-fill {
    height: 100%;
    background: var(--accent);
    transition: width 1000ms linear, background-color 200ms ease;
  }
  .rush-fill.low {
    background: var(--danger);
  }

  .stats {
    display: flex;
    gap: 20px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--divider);
  }
  .stat {
    display: flex;
    flex-direction: column;
  }
  .stat-value {
    font-size: 19px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .stat-value.accent {
    color: var(--accent);
  }
  .stat-label {
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  .turn-line {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 10px 14px;
    font-size: 12.5px;
    color: var(--text-muted);
    min-height: 38px;
  }
  .turn-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25);
  }
  .turn-dot.white {
    background: #e8e2d4;
  }
  .turn-dot.black {
    background: #2b2620;
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
  }

  .feedback {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0 14px;
    padding: 10px 12px;
    border-radius: var(--radius);
    border: 1px solid var(--divider);
    background: var(--bg-raised);
    animation: fb-in 180ms cubic-bezier(0.2, 0.7, 0.2, 1);
  }
  .feedback.correct {
    border-color: color-mix(in srgb, var(--win) 45%, var(--divider));
    background: color-mix(in srgb, var(--win) 12%, var(--bg-raised));
  }
  .feedback.correct .fb-text {
    color: var(--win);
  }
  .feedback.wrong {
    border-color: color-mix(in srgb, var(--danger) 45%, var(--divider));
    background: color-mix(in srgb, var(--danger) 12%, var(--bg-raised));
  }
  .feedback.wrong .fb-text {
    color: var(--danger);
  }
  .fb-text {
    font-size: 13.5px;
    font-weight: 600;
  }
  @keyframes fb-in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .feedback {
      animation: none;
    }
  }
  .fb-change {
    font-size: 12px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  .end-board {
    margin: 10px 14px 0;
    border-top: 1px solid var(--divider);
    padding-top: 8px;
    overflow-y: auto;
  }
  .lb-row {
    display: flex;
    gap: 12px;
    padding: 2px 4px;
    font-size: 12.5px;
    font-variant-numeric: tabular-nums;
    border-radius: 3px;
  }
  .lb-row.new {
    background: color-mix(in srgb, var(--accent) 18%, transparent);
  }
  .lb-rank {
    width: 18px;
    color: var(--text-muted);
  }
  .lb-score {
    width: 36px;
    font-weight: 600;
  }
  .lb-date {
    color: var(--text-muted);
  }

  .spacer {
    flex: 1;
  }
  .moves {
    flex: 1;
    min-height: 0;
    display: flex;
    overflow: hidden;
    border-top: 1px solid var(--divider);
    padding: 6px 0;
  }
  .moves :global(.movelist) {
    flex: 1;
  }
  .controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px 14px;
    border-top: 1px solid var(--divider);
  }

  .toggle.on {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
</style>
