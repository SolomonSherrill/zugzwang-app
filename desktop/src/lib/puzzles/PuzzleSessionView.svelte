<script lang="ts">
  /**
   * A puzzle session (UI-BUILD-2 E2; DESIGN.md "Puzzles: rated session", ruling 19), for Rated
   * (with or without themes), Rush and Survival in one visual language. The puzzle logic is
   * the old PuzzleSession's: the setup move, judging moves (puzzleMove.ts), Glicko-2 through
   * rate_puzzle, attempts and sessions saved as before. The puzzle's rating stays hidden until
   * it is done.
   *
   * UI-BUILD-3 J (fourth rulings, 11): the panel lists the moves, from the setup move; ← → (and
   * Home, End, a click on a move) step through them at any time. Looking back only changes what
   * the board shows: the board is locked, no RPC is sent, a Rush clock keeps running. The
   * solution is the same list with the rest of the line added.
   */
  import { onDestroy, onMount } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import { uciOf, type PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import ResultDot from './ResultDot.svelte'
  import PuzzleMoveList from './PuzzleMoveList.svelte'
  import { resolveUserMove } from '../puzzleMove'
  import { PUZZLE_WAIT_EXPLAIN_MS, puzzleWaitCaption } from '../puzzleWait'
  import { registerCommands } from '../shell/commands.svelte'
  import { alreadyHandled, ownsEnter } from '../ui/keyTargets'
  import {
    api,
    PUZZLE_SURVIVAL_START_OFFSET,
    PUZZLE_SURVIVAL_FLOOR,
    PUZZLE_SURVIVAL_STEP,
    PUZZLE_SURVIVAL_RANGE,
    type PuzzleMode,
    type PuzzleRecord,
  } from '../api'
  import {
    canMove, clockText, lookingBack, newLine, nextUci, opponentMoveText, puzzleMoveRows, puzzleThemes, selectView,
    sessionModeLabel, shownIndex, shownPly, signed, stepOf, stepView, tally, themeLabel, uciToMove, withPly, withSolution,
    withTry, type PlyKind, type PuzzleLine, type SessionResult, type Step, type View,
  } from './puzzlesModel'

  type Color = 'white' | 'black'

  interface Props {
    config: PuzzleMode
    onexit: () => void
    /** a fresh session of the same mode (Start another rush / run) */
    onagain: () => void
  }
  let { config, onexit, onagain }: Props = $props()

  // Timing constants mirror config.py (PUZZLE_SETUP_DELAY_MS etc.), as before.
  const SETUP_DELAY = 600
  const ANIM = 300
  const RUSH_NEXT_DELAY = 800
  const AUTO_CONTINUE_DELAY = 900
  const EMPTY_FEN = '8/8/8/8/8/8/8/8'
  // hold the loader back briefly so quick loads never flash it
  const LOADER_DELAY = 120

  type SState =
    | 'loading' // fetching puzzles (the first search after launch can take ~27 s)
    | 'setup' // the opponent's move is about to play
    | 'awaiting' // the user to move
    | 'animating'
    | 'complete' // solved (or given up) — waiting on Next
    | 'solution' // stepping through the solution
    | 'ended' // Rush time up / Survival run over
    | 'empty' // no puzzle left in range
    | 'error'

  const chess = new Chess()
  let board: Board | undefined = $state()

  let sstate = $state<SState>('loading')
  let puzzle = $state<PuzzleRecord | null>(null)
  let fen = $state('start')
  let dests = $state<Map<Key, Key[]>>(new Map())
  /** the moves so far (the board's live position is the last one) and where the list is looked at */
  let line = $state<PuzzleLine>(newLine(EMPTY_FEN))
  let view = $state<View>(null)
  let userColor = $state<Color>('white')
  let flipped = $state(false)
  let hintArrow = $state<DrawShape[]>([])
  let setupPlayed = $state(false)

  let solutionMoves: string[] = []
  let solutionIdx = 0
  let failed = $state(false)
  let gaveUp = $state(false)
  let usedHint = false
  let failing: Promise<void> | null = null
  let ratingBefore: number | null = null
  let solveStart = 0
  let resultRecorded = false
  let attemptSaved = false

  let rating = $state(0)
  let startRating = $state<number | null>(null)
  let score = $state(0)
  let difficultyOffset = 0
  let sessionId: number | null = null
  let prefetch: PuzzleRecord[] = []
  let refilling: Promise<void> | null = null
  let loadError = $state('')
  let note = $state<'wrong' | 'hint' | null>(null)
  let results = $state<SessionResult[]>([])
  let autoContinue = $state(false)
  let runOver = $state(false)
  let prevBest = $state<number | null>(null)
  let lastRating = $state<number | null>(null)

  let rushRemaining = $state(0)
  let rushTimer: ReturnType<typeof setInterval> | undefined

  let timeouts: ReturnType<typeof setTimeout>[] = []

  // The session is keyed by its config (PuzzlesView remounts it), so reading it once is right.
  // svelte-ignore state_referenced_locally
  const isRatedLike = config.mode === 'rated' || config.mode === 'theme'
  const orientation = $derived<Color>(flipped ? (userColor === 'white' ? 'black' : 'white') : userColor)
  const shown = $derived(shownPly(line, view))
  const back = $derived(lookingBack(line, view))
  /** looking back while the puzzle is still being played: the board is locked, the panel says so */
  const backFromPlay = $derived(back && (sstate === 'setup' || sstate === 'awaiting' || sstate === 'animating'))
  /** the board can be moved only on the user's turn, at the end of the list */
  const movable = $derived(canMove(sstate, line, view))
  const boardFen = $derived(!puzzle ? EMPTY_FEN : shown ? shown.fen : fen)
  const turnColor = $derived<Color>(boardFen.split(' ')[1] === 'w' ? 'white' : 'black')
  const lastMove = $derived<[Key, Key] | null>(shown ? [shown.uci.slice(0, 2) as Key, shown.uci.slice(2, 4) as Key] : null)
  const check = $derived.by(() => {
    if (!puzzle) return false
    try {
      return new Chess(boardFen).inCheck()
    } catch {
      return false
    }
  })
  /** the solution's arrow is the move after the one on the board; the hint shows only at play */
  const shapes = $derived.by<DrawShape[]>(() => {
    if (sstate === 'solution') {
      const u = nextUci(line, view)
      return u ? [{ orig: u.slice(0, 2) as Key, dest: u.slice(2, 4) as Key, brush: 'green' }] : []
    }
    return back ? [] : hintArrow
  })
  const moveRows = $derived(puzzleMoveRows(line))
  const solutionShown = $derived(line.plies.some((p) => p.kind === 'solution'))
  const done = $derived(!!puzzle && (sstate === 'complete' || sstate === 'solution' || sstate === 'ended'))
  const setupSan = $derived(line.plies[0]?.kind === 'setup' ? line.plies[0].san : null)
  const counts = $derived(tally(results))
  const sessionChange = $derived(
    isRatedLike && startRating !== null && (results.length > 0 || failed) ? signed(Math.round(rating - startRating)) : null,
  )
  const modeName = $derived(
    config.mode === 'theme'
      ? `Rated: ${config.themes.map(themeLabel).join(', ')}`
      : sessionModeLabel({ mode: config.mode, timeLimit: config.mode === 'rush' ? config.rushSeconds : null }),
  )
  const userSide = $derived(userColor === 'white' ? 'White' : 'Black')

  // the loader: shown after a beat, its caption explaining a long first search
  let showLoader = $state(false)
  let waitedMs = $state(0)
  const caption = $derived(puzzleWaitCaption(waitedMs))
  $effect(() => {
    if (sstate !== 'loading') {
      showLoader = false
      waitedMs = 0
      return
    }
    const a = setTimeout(() => (showLoader = true), LOADER_DELAY)
    const b = setTimeout(() => (waitedMs = PUZZLE_WAIT_EXPLAIN_MS), PUZZLE_WAIT_EXPLAIN_MS)
    return () => {
      clearTimeout(a)
      clearTimeout(b)
    }
  })

  // the board fills its column
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      // a multiple of 8: chessground draws whole-pixel squares, so the strips, bar and
      // navigator line up with the board drawn (UI-BUILD-4 C)
      boardPx = Math.max(240, Math.floor((Math.min(r.width - 56, r.height - 44 - 80)) / 8) * 8)
    })
    if (section) ro.observe(section)
    return () => ro.disconnect()
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
    dests = computeDests()
  }
  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

  // ── session lifecycle ────────────────────────────────────────────────────

  async function start() {
    try {
      const r = await api.getPuzzleRating()
      rating = r.rating
      startRating = r.rating
      if (config.mode === 'rush') {
        sessionId = (await api.startPuzzleSession('rush', config.rushSeconds)).sessionId
        rushRemaining = config.rushSeconds
        prevBest = (await api.puzzleLeaderboard('rush', config.rushSeconds, 1)).entries[0]?.score ?? null
      } else if (config.mode === 'survival') {
        sessionId = (await api.startPuzzleSession('survival', null)).sessionId
        prevBest = (await api.puzzleLeaderboard('survival', null, 1)).entries[0]?.score ?? null
      } else {
        // E2: a rated session is recorded too, so Recent sessions can list it.
        sessionId = (await api.startPuzzleSession(config.mode, null)).sessionId
      }
    } catch (e) {
      loadError = errText(e)
      sstate = 'error'
      return
    }
    await loadNext()
  }

  function refillPrefetch(): Promise<void> {
    if (refilling) return refilling
    const survivalStart = Math.max(PUZZLE_SURVIVAL_FLOOR, rating + PUZZLE_SURVIVAL_START_OFFSET)
    const target = config.mode === 'survival' ? survivalStart + difficultyOffset : rating
    const rng = config.mode === 'survival' ? PUZZLE_SURVIVAL_RANGE : config.ratingRange
    refilling = api
      .nextPuzzles(target, rng, config.themes)
      .then((res) => {
        const known = new Set(prefetch.map((p) => p.id))
        prefetch.push(...res.puzzles.filter((p) => !known.has(p.id)))
      })
      .finally(() => (refilling = null))
    return refilling
  }

  async function loadNext() {
    if (prefetch.length === 0) {
      sstate = 'loading'
      try {
        await refillPrefetch()
      } catch (e) {
        loadError = errText(e)
        sstate = 'error'
        return
      }
    }
    const next = prefetch.shift()
    if (!next) {
      sstate = 'empty'
      return
    }
    startPuzzle(next)
    if (prefetch.length < 3) refillPrefetch().catch(() => {})
  }

  function startPuzzle(p: PuzzleRecord) {
    puzzle = p
    solutionMoves = p.movesUci.slice(1) // the setup move is the opponent's
    solutionIdx = 0
    failed = false
    failing = null
    gaveUp = false
    usedHint = false
    resultRecorded = false
    attemptSaved = false
    ratingBefore = rating
    solveStart = performance.now()
    note = null
    hintArrow = []
    setupPlayed = false
    line = newLine(p.fen)
    view = null

    chess.load(p.fen)
    userColor = chess.turn() === 'w' ? 'black' : 'white' // the user plays the other side
    sstate = 'setup'
    syncBoard()
    // E2: the Rush clock starts with the first puzzle on the board, not before the search.
    if (config.mode === 'rush' && rushTimer === undefined && !runOver) rushTimer = setInterval(onRushTick, 1000)

    later(SETUP_DELAY, () => {
      applyMove(p.movesUci[0], 'setup')
      setupPlayed = true
      later(ANIM + 60, () => {
        sstate = 'awaiting'
        syncBoard()
      })
    })
  }

  function applyMove(uci: string, kind: PlyKind) {
    line = withPly(line, uci, kind)
    chess.move(uciToMove(uci))
    syncBoard()
  }

  // ── user moves ───────────────────────────────────────────────────────────

  function onUserMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    if (!movable || !puzzle) {
      board?.sync()
      return
    }
    // A promotion arrives with the piece chosen in the board's picker (F8; UI-BUILD-4 D), so a
    // puzzle that under-promotes is judged on the piece played.
    judgeMove(uciOf(orig, dest, promo))
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
    else onWrong(played)
  }

  function onCorrect(uci: string) {
    sstate = 'animating'
    hintArrow = []
    applyMove(uci, 'played')
    solutionIdx += 1
    later(280, () => {
      if (solutionIdx >= solutionMoves.length) void complete()
      else playOpponent()
    })
  }

  function onWrong(played: string) {
    // J: the try is listed, struck, beside the move it was tried for
    line = withTry(line, played)
    if (!failed) markFailed()
    if (config.mode === 'survival') {
      void endSurvival()
      return
    }
    note = 'wrong'
    // chessground shows the wrong move; hold it briefly, then snap back
    sstate = 'animating'
    later(350, () => {
      sstate = 'awaiting'
      syncBoard()
      board?.sync()
    })
  }

  /** The first miss of a puzzle: a rated puzzle is scored as a loss now, as before. */
  function markFailed(): Promise<void> {
    if (failing) return failing
    failed = true
    failing = (async () => {
      if (isRatedLike && puzzle) {
        const res = await api.ratePuzzle(puzzle.rating, puzzle.ratingDeviation, 0.0)
        rating = res.rating
      }
    })().catch(() => {})
    return failing
  }

  function playOpponent() {
    const uci = solutionMoves[solutionIdx]
    later(120, () => {
      applyMove(uci, 'played')
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

  function recordResult(clean: boolean) {
    if (!puzzle || resultRecorded) return
    resultRecorded = true
    results = [
      ...results,
      {
        id: puzzle.id,
        rating: puzzle.rating,
        themes: puzzle.themes,
        clean,
        change: isRatedLike && ratingBefore !== null ? Math.round(rating - ratingBefore) : null,
      },
    ]
  }

  async function saveAttempt(solved: boolean) {
    if (!puzzle || attemptSaved) return
    attemptSaved = true
    await api.savePuzzleAttempt({
      puzzle_id: puzzle.id,
      session_id: sessionId,
      mode: config.mode,
      solved,
      failed: !solved || failed,
      used_hint: usedHint,
      gave_up: gaveUp,
      solve_time_s: (performance.now() - solveStart) / 1000,
      rating_before: ratingBefore,
      rating_after: solved && !isRatedLike && !failed ? null : rating,
    })
  }

  // ── completion / endings ────────────────────────────────────────────────

  async function complete() {
    if (!puzzle) return
    sstate = 'complete'
    note = null
    if (failing) await failing
    if (isRatedLike && !failed) {
      const res = await api.ratePuzzle(puzzle.rating, puzzle.ratingDeviation, 1.0)
      rating = res.rating
    }
    score += 1
    if (config.mode === 'survival') {
      difficultyOffset += PUZZLE_SURVIVAL_STEP
      if (sessionId !== null) await api.updatePuzzleSession(sessionId, score, puzzle.rating)
    }
    recordResult(!failed)
    await saveAttempt(true)

    if (config.mode === 'rush') {
      later(RUSH_NEXT_DELAY, () => !runOver && void loadNext())
    } else if (autoContinue) {
      later(AUTO_CONTINUE_DELAY, () => sstate === 'complete' && onNext())
    }
  }

  async function onHint() {
    if (!movable || solutionIdx >= solutionMoves.length || !puzzle) return
    usedHint = true
    await markFailed()
    if (config.mode === 'survival') {
      void endSurvival()
      return
    }
    const expected = solutionMoves[solutionIdx]
    hintArrow = [{ orig: expected.slice(0, 2) as Key, dest: expected.slice(2, 4) as Key, brush: 'green' }]
    note = 'hint'
  }

  /** Give up the puzzle on the board: it counts as missed, and is saved as given up. */
  async function giveUp() {
    if (!puzzle || sstate !== 'awaiting') return
    gaveUp = true
    await markFailed()
    if (config.mode === 'survival') {
      await endSurvival()
      return
    }
    sstate = 'complete'
    recordResult(false)
    await saveAttempt(false)
  }

  async function onViewSolution() {
    if (sstate === 'awaiting') {
      await giveUp()
      if (runOver) return
    }
    if (sstate === 'complete' || sstate === 'ended') viewSolution()
  }

  async function endSurvival() {
    if (runOver) return
    runOver = true
    sstate = 'ended'
    lastRating = puzzle?.rating ?? null
    if (sessionId !== null) await api.updatePuzzleSession(sessionId, score, puzzle?.rating ?? 0)
    recordResult(false)
    await saveAttempt(false)
  }

  function onRushTick() {
    rushRemaining -= 1
    if (rushRemaining <= 0) void endRush()
  }

  async function endRush() {
    clearInterval(rushTimer)
    rushTimer = undefined
    runOver = true
    sstate = 'ended'
    hintArrow = []
    if (sessionId !== null) await api.updatePuzzleSession(sessionId, score)
  }

  function onNext() {
    if (runOver) return
    hintArrow = []
    void loadNext()
  }

  // ── solution view ────────────────────────────────────────────────────────

  /** The solution is the move list with the rest of the line added (J). The board goes to where
   *  the solving stopped, the arrow on the move not found; a puzzle played to its end starts
   *  again from the setup move. */
  function viewSolution() {
    if (!puzzle) return
    const stop = line.plies.length - 1
    if (solutionIdx < solutionMoves.length) line = withSolution(line, solutionMoves.slice(solutionIdx))
    hintArrow = []
    sstate = 'solution'
    view = selectView(line, stop < line.plies.length - 1 ? stop : 0)
  }

  // ── keys and commands ────────────────────────────────────────────────────

  const flip = () => (flipped = !flipped)
  /** Step through the moves (J): only the view changes; nothing is sent, nothing is scored. */
  function step(s: Step) {
    if (!puzzle || !line.plies.length) return
    view = stepView(line, view, s)
  }
  function select(index: number) {
    if (!puzzle) return
    view = selectView(line, index)
  }
  const backToPuzzle = () => (view = null)

  function onKey(e: KeyboardEvent) {
    // a key a focused control already handled does not act twice (keyTargets.ts)
    if (alreadyHandled(e)) return
    const t = e.target as HTMLElement | null
    if (t?.closest?.('[role="dialog"]')) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    const k = e.key
    const s = stepOf(k)
    if (s !== null) {
      if (!puzzle || !line.plies.length) return
      step(s)
    } else if (k === 'f' || k === 'F') flip()
    // H only at play: while looking back the Hint button is not on screen (a hint scores a miss)
    else if ((k === 'h' || k === 'H') && movable) void onHint()
    else if (k === 'Enter') {
      // a focused button keeps ↵ for its own action
      if (ownsEnter(t)) return
      if ((sstate === 'complete' || sstate === 'solution') && !runOver && config.mode !== 'rush') onNext()
      else if (runOver && sstate !== 'solution') onagain()
      else return
    } else return
    e.preventDefault()
  }

  let off: (() => void) | null = null
  onMount(() => {
    void start()
    off = registerCommands('puzzle-session', () => [
      { id: 'pz-flip', group: 'Actions', label: 'Flip the board', kbd: 'F', run: flip },
      ...(backFromPlay
        ? [{ id: 'pz-live', group: 'Actions', label: 'Back to the puzzle', kbd: 'End', run: backToPuzzle }]
        : []),
      ...(sstate === 'awaiting' && !back
        ? [
            { id: 'pz-hint', group: 'Actions', label: 'Hint', kbd: 'H', run: () => void onHint() },
            { id: 'pz-solution', group: 'Actions', label: 'View the solution', run: () => void onViewSolution() },
          ]
        : []),
      ...((sstate === 'complete' || sstate === 'solution') && !runOver
        ? [{ id: 'pz-next', group: 'Actions', label: 'Next puzzle', kbd: '↵', run: onNext }]
        : []),
      { id: 'pz-back', group: 'Actions', label: 'Back to puzzles', run: onexit },
    ])
  })
  onDestroy(() => {
    off?.()
    clearInterval(rushTimer)
    for (const t of timeouts) clearTimeout(t)
    // an abandoned rush still records its score, as before
    if (config.mode === 'rush' && !runOver && rushRemaining > 0 && sessionId !== null) {
      void api.updatePuzzleSession(sessionId, score)
    }
    if (isRatedLike) {
      // E2: a rated puzzle already scored as a loss, then left unfinished, is saved as given
      // up, so its rating change is not lost from the record; the session is closed.
      if (puzzle && failed && !attemptSaved) {
        gaveUp = true
        const save = () => saveAttempt(false).catch(() => {})
        void (failing ? failing.then(save) : save())
      }
      if (sessionId !== null) void api.updatePuzzleSession(sessionId, counts.solved).catch(() => {})
    }
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="session" data-state={sstate}>
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onexit}>Puzzles</button>
      <span class="sep" aria-hidden="true">/</span>
      <span class="title">{modeName}</span>
    </div>
    <Button kbd="F" onclick={flip}>Flip</Button>
  </header>

  <div class="body">
    <section class="board-col" aria-label="Board" bind:this={section}>
      <div class="col" style:width="{boardPx}px">
        <div class="line">
          <span class="muted">
            {#if puzzle}{done ? `Puzzle rating ${puzzle.rating}` : "Puzzle rating shown when you're done"}{/if}
          </span>
          {#if puzzle && setupPlayed && setupSan}<span class="small">{opponentMoveText(puzzle.fen, setupSan)}</span>{/if}
        </div>
        <div class="board" style:width="{boardPx}px" style:height="{boardPx}px">
          <Board
            bind:this={board}
            fen={boardFen}
            {lastMove}
            {turnColor}
            movableColor={movable ? userColor : null}
            dests={movable ? dests : new Map()}
            {check}
            {orientation}
            {shapes}
            animationMs={ANIM}
            onmove={onUserMove}
          />
        </div>
        <div class="line">
          {#if puzzle}
            <span class="you"><span class="swatch {userColor}" aria-hidden="true"></span>You play {userSide}</span>
            {#if backFromPlay}<span class="small">Looking back</span>{/if}
          {/if}
        </div>
      </div>
    </section>

    <aside aria-label="Puzzle">
      <div class="top">
        {#if config.mode === 'rush'}
          <div><div class="cap">Time left</div><div class="metric">{clockText(rushRemaining)}</div></div>
          <div class="r"><div class="cap">Solved</div><div class="fig">{score}</div></div>
        {:else if config.mode === 'survival'}
          <div><div class="cap">In a row</div><div class="metric">{score}</div></div>
          {#if prevBest !== null}<div class="r"><div class="cap">Best</div><div class="fig">{prevBest}</div></div>{/if}
        {:else}
          <div><div class="cap">Your rating</div><div class="metric">{startRating === null ? '' : Math.round(rating)}</div></div>
          {#if sessionChange}
            <div class="r">
              <div class="cap">This session</div>
              <div class="fig" class:win={sessionChange.tone === 'win'} class:loss={sessionChange.tone === 'loss'}>{sessionChange.text}</div>
            </div>
          {/if}
        {/if}
      </div>

      <div class="prompt">
        {#if sstate === 'error'}
          <EmptyState tone="error" sentence="Puzzles could not be read." sub={loadError} action={{ label: 'Try again', run: () => (startRating === null ? void start() : void loadNext()) }} />
        {:else if sstate === 'empty'}
          <EmptyState
            sentence="No more puzzles here."
            sub={config.themes.length
              ? 'Every puzzle with these themes near your rating has been tried recently. Choose fewer themes or a wider difficulty.'
              : 'Every puzzle near this rating has been tried recently. Choose a wider difficulty.'}
            action={{ label: 'Back to puzzles', run: onexit }}
          />
        {:else if sstate === 'loading'}
          {#if showLoader}<EmptyState sentence={caption.sentence} sub={caption.sub} />{/if}
        {:else if sstate === 'ended'}
          <h2 class="state">{config.mode === 'rush' ? "Time's up" : 'The run is over'}</h2>
          <p>
            {#if config.mode === 'rush'}
              You solved {score}.
            {:else}
              {score} in a row.{#if lastRating !== null}{' '}The last puzzle was rated {lastRating}.{/if}
            {/if}
          </p>
          {#if prevBest === null || score > prevBest}
            {#if score > 0}<p class="best">A new best{config.mode === 'rush' ? ` for ${Math.round(config.rushSeconds / 60)} min` : ''}.</p>{/if}
          {:else}
            <p class="muted">Your best{config.mode === 'rush' ? ` for ${Math.round(config.rushSeconds / 60)} min` : ''} is {prevBest}.</p>
          {/if}
          <div class="acts">
            {#if config.mode === 'survival' && puzzle}<Button onclick={viewSolution}>View solution</Button>{/if}
            <Button variant="primary" kbd="↵" onclick={onagain}>{config.mode === 'rush' ? 'Start another rush' : 'Start another run'}</Button>
            <Button variant="quiet" onclick={onexit}>Back to puzzles</Button>
          </div>
        {:else if sstate === 'solution'}
          <h2 class="state">Solution</h2>
          <p>Step through it with ← and →.{solutionShown ? ' Grey moves are the rest of the solution.' : ''}</p>
          <div class="acts">
            {#if runOver}
              <Button variant="primary" onclick={onagain}>{config.mode === 'rush' ? 'Start another rush' : 'Start another run'}</Button>
              <Button variant="quiet" onclick={onexit}>Back to puzzles</Button>
            {:else}
              <Button variant="primary" kbd="↵" onclick={onNext}>Next puzzle</Button>
            {/if}
          </div>
        {:else if sstate === 'complete' && puzzle}
          {@const last = results.at(-1)}
          <h2 class="state">
            <ResultDot result={failed ? 'missed' : 'solved'} />
            {gaveUp ? 'Missed' : failed ? 'Solved after a miss' : 'Solved'}
          </h2>
          <p>
            Puzzle rating {puzzle.rating}{#if last && last.change !== null}{@const c = signed(last.change)}<span class="muted">. Your rating</span>{' '}<span class:win={c?.tone === 'win'} class:loss={c?.tone === 'loss'}>{c?.text}</span>{/if}
          </p>
          {#if config.mode !== 'rush'}
            <div class="acts">
              {#if failed}<Button onclick={viewSolution}>View solution</Button>{/if}
              <Button variant="primary" kbd="↵" onclick={onNext}>Next puzzle</Button>
              <Button variant="quiet" pressed={autoContinue} title="Load the next puzzle after each solve" onclick={() => (autoContinue = !autoContinue)}>
                Auto-continue{autoContinue ? ': on' : ''}
              </Button>
            </div>
          {/if}
        {:else if puzzle && backFromPlay}
          <h2 class="state">Looking back</h2>
          <p>
            The board is locked until you go back to the puzzle.{config.mode === 'rush'
              ? ' The clock keeps running.'
              : isRatedLike
                ? ' Looking back does not change your rating.'
                : ''}
          </p>
          <div class="acts">
            <Button variant="primary" kbd="End" onclick={backToPuzzle}>Back to the puzzle</Button>
          </div>
        {:else if puzzle}
          <h2 class="state"><span class="swatch {userColor}" aria-hidden="true"></span>{userSide} to move</h2>
          <p class:muted={!note}>
            {#if note === 'wrong'}
              {isRatedLike ? "That's not the move. This puzzle now counts as missed; you can still finish it." : "That's not the move. Try again."}
            {:else if note === 'hint'}
              {isRatedLike ? 'The arrow shows the move. This puzzle counts as missed.' : 'The arrow shows the move.'}
            {:else}
              Find the best move.
            {/if}
          </p>
          <div class="pair">
            <Button kbd="H" disabled={sstate !== 'awaiting' || note === 'hint'} onclick={() => void onHint()}>Hint</Button>
            <Button disabled={sstate !== 'awaiting'} onclick={() => void onViewSolution()}>View solution</Button>
          </div>
        {/if}
      </div>

      {#if puzzle && line.plies.length}
        <PuzzleMoveList rows={moveRows} shown={shownIndex(line, view)} last={line.plies.length - 1} onselect={select} onstep={step} />
      {/if}

      {#if results.length || puzzle}
        <div class="tally">
          <div class="th">
            <span class="strong">Streak {counts.streak}</span>
            <span class="muted small">{counts.solved} of {counts.tried} solved</span>
          </div>
          <div class="dots">
            {#each results as r, i (i)}<ResultDot result={r.clean ? 'solved' : 'missed'} />{/each}
            {#if puzzle && !runOver && sstate !== 'complete' && sstate !== 'solution'}<ResultDot result="current" />{/if}
          </div>
        </div>
      {/if}

      {#if results.length}
        <div class="earlier">
          <div class="cap">Earlier this session</div>
          <ul>
            {#each [...results].reverse() as r, i (results.length - i)}
              {@const c = signed(r.change)}
              <li>
                <ResultDot result={r.clean ? 'solved' : 'missed'} />
                <span class="pr">{r.rating}</span>
                <span class="th-list">{puzzleThemes(r.themes).join(', ')}</span>
                <span class="chg" class:win={c?.tone === 'win'} class:loss={c?.tone === 'loss'}>{c?.text ?? ''}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </aside>
  </div>
</div>

<style>
  .session {
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
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  .crumb {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
  }
  .back {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-3);
    font: var(--body);
    cursor: pointer;
  }
  .back:hover {
    color: var(--text);
  }
  .back:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .sep {
    color: var(--disabled);
  }
  .title {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
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
  .line {
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .muted {
    color: var(--text-3);
  }
  .small {
    color: var(--text-3);
    font: var(--secondary);
  }
  .you {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 500;
  }
  .swatch {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    flex: none;
    display: inline-block;
  }
  .swatch.white {
    background: var(--text);
  }
  .swatch.black {
    background: var(--bg);
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }
  aside {
    flex: 0 1 420px;
    min-width: 320px;
    min-height: 0;
    box-sizing: border-box;
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
  }
  .top {
    flex: none;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    min-height: 54px;
  }
  .cap {
    color: var(--text-3);
    font: var(--secondary);
  }
  .metric {
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
    font-variant-numeric: tabular-nums;
    min-height: 30px;
  }
  .fig {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .r {
    text-align: right;
  }
  .win {
    color: var(--win);
  }
  .loss {
    color: var(--loss);
  }
  .prompt {
    flex: none;
    padding: 20px;
    border-bottom: 1px solid var(--border);
  }
  .state {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    font: var(--heading);
    font-weight: 500;
  }
  .prompt p {
    margin: 6px 0 0;
    color: var(--text-2);
  }
  .prompt p.muted {
    color: var(--text-2);
  }
  .prompt p.best {
    color: var(--win);
  }
  .pair {
    margin-top: 16px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .acts {
    margin-top: 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .tally {
    flex: none;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }
  .th {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .strong {
    font-weight: 500;
  }
  .dots {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .earlier {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 14px 20px;
    scrollbar-width: thin;
    scrollbar-color: var(--border-control) transparent;
  }
  .earlier .cap {
    margin-bottom: 4px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: grid;
    grid-template-columns: 22px 48px minmax(0, 1fr) 40px;
    gap: 10px;
    align-items: center;
    padding: 7px 0;
    border-top: 1px solid var(--divider);
    font-variant-numeric: tabular-nums;
  }
  .pr {
    color: var(--text-2);
  }
  .th-list {
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chg {
    text-align: right;
  }
</style>
