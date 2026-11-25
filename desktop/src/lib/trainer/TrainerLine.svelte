<script lang="ts">
  /**
   * The opening trainer, rebuilt (UI-BUILD-2 E3; DESIGN.md "Openings: choose a line",
   * "Openings: training a line", rulings 18, 21; ruling 9 of 2026-11-20, third). Two states.
   * Choose: the family's lines with their progress word, the selected line, the options in plain
   * words (Colour; Replies Popular / Any book move / Main line; Accept This line only / Popular
   * moves / Any book move; Start Move 1 / Line start), Start training (↵). Train: the options
   * folded to one line with Change; feedback, the moves, this run's score, Hint (H), Play it out
   * vs Stockfish. This line only ends at the line's last move; the book modes end where the book
   * ends (Off-book is dropped). The run logic is the old workspace's (book_moves, book_reply,
   * trainer_attempt, trainer_complete), unchanged but for those rulings.
   */
  import { onDestroy, onMount } from 'svelte'
  import { Chess } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import { uciOf, type PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import { api, type Color, type TrainerFamily, type TrainerFamilySummary, type TrainerLine } from '../api'
  import { registerCommands } from '../shell/commands.svelte'
  import { alreadyHandled, ownsEnter } from '../ui/keyTargets'
  import {
    ACCEPT_DEFAULT, ACCEPT_OPTIONS, ACCEPT_THRESHOLD, REPLIES_OPTIONS, fullMoves, lineTail, movesText, plyLabel,
    progressWord, shortName, summaryLine, type Accept, type Replies,
  } from './trainerModel'

  interface Props {
    family: TrainerFamilySummary
    onback: () => void
    onplayfen: (fen: string) => void
  }
  let { family, onback, onplayfen }: Props = $props()

  const OPP_ANIM = 400
  const SETUP_DELAY = 500
  const ANIM = 250
  const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

  // ── family and options ───────────────────────────────────────────────────
  let fam = $state<TrainerFamily | null>(null)
  let loadError = $state<string | null>(null)
  let selectedIdx = $state(0)
  let showAllLines = $state(false)
  let color = $state<Color>('white')
  let replies = $state<Replies>('varied')
  let accept = $state<Accept>(ACCEPT_DEFAULT)
  let fromMove1 = $state(true)
  let orientation = $state<Color>('white')
  $effect(() => {
    orientation = color
  })
  $effect(() => {
    if (accept === 'line') fromMove1 = true // the line ends where Line start begins
  })
  const line = $derived<TrainerLine | null>(fam ? (fam.lines[selectedIdx] ?? null) : null)
  const LINES_SHOWN = 5

  // ── run state ───────────────────────────────────────────────────────────
  type Phase = 'choose' | 'train' | 'done'
  let phase = $state<Phase>('choose')
  const chess = new Chess()
  let board: Board | undefined = $state()
  let busy = $state(true)
  let fen = $state(START_FEN)
  let lastMove = $state<[Key, Key] | null>(null)
  let dests = $state<Map<Key, Key[]>>(new Map())
  let check = $state(false)
  let arrows = $state<DrawShape[]>([])
  let history = $state<string[]>([])
  let feedback = $state<{ text: string; strong?: string; kind: 'ok' | 'wrong' | 'info' } | null>(null)
  let right = $state(0)
  let yourMoves = $state(0)
  let hintsShown = $state(0)
  let result = $state<{ title: string; detail: string; recorded: boolean } | null>(null)
  let terminalFen = ''

  // the old workspace's counters, kept for the recorded accuracy (unchanged definition)
  let movesPlayed = 0
  let errors = 0
  let hintsUsed = 0
  let hintUsedThisPos = false
  let wrongThisPos = false
  let attemptRecorded = false
  let steerLine: string[] = []
  let steerIdx = 0
  let steerUserMoves = 0
  let steerErrors = 0
  let steerHints = 0
  let generation = 0
  let timeouts: ReturnType<typeof setTimeout>[] = []

  const turnColor = $derived<Color>(fen.split(' ')[1] === 'w' ? 'white' : 'black')
  const inSteering = () => steerLine.length > 0 && steerIdx < steerLine.length
  const threshold = () => (accept === 'line' ? ACCEPT_THRESHOLD.popular : ACCEPT_THRESHOLD[accept])

  function later(ms: number, gen: number, fn: () => void) {
    timeouts.push(setTimeout(() => gen === generation && fn(), ms))
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
    history = chess.history()
  }
  function applyUci(uci: string): string {
    const white = chess.turn() === 'w'
    const n = chess.moveNumber()
    const m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || undefined })
    lastMove = [uci.slice(0, 2) as Key, uci.slice(2, 4) as Key]
    syncBoard()
    return plyLabel(n, white, m.san)
  }
  /** "This run"'s moves, numbered from the run's own first position (FIX-B7: a run from the line start begins at the
   *  line's FEN, and replaying its moves from the standard start threw while drawing, an error the screen's boundary
   *  now shows) */
  function runMoves(): string {
    const h = chess.history({ verbose: true })
    return movesText(h.map((m) => m.lan), h[0]?.before)
  }
  const arrowFor = (uci: string): DrawShape => ({ orig: uci.slice(0, 2) as Key, dest: uci.slice(2, 4) as Key, brush: 'green' })

  // ── choose ──────────────────────────────────────────────────────────────
  function preview() {
    if (phase !== 'choose' || !line) return
    chess.load(line.fen)
    lastMove = null
    arrows = []
    syncBoard()
  }
  $effect(() => {
    void [line, phase]
    preview()
  })

  // ── a run ───────────────────────────────────────────────────────────────
  function start() {
    if (!line) return
    generation += 1
    const gen = generation
    for (const t of timeouts) clearTimeout(t)
    timeouts = []
    phase = 'train'
    movesPlayed = errors = hintsUsed = steerUserMoves = steerErrors = steerHints = 0
    right = yourMoves = hintsShown = 0
    hintUsedThisPos = wrongThisPos = false
    attemptRecorded = false
    feedback = null
    result = null
    arrows = []
    lastMove = null
    terminalFen = ''
    if (fromMove1) {
      chess.reset()
      steerLine = line.uci.slice()
    } else {
      chess.load(line.fen)
      steerLine = []
    }
    steerIdx = 0
    busy = true
    syncBoard()
    if (fromMove1) {
      if (inSteering() && turnColor !== color) later(SETUP_DELAY, gen, () => advanceSteering(gen))
      else advanceSteering(gen)
    } else if (turnColor !== color) {
      later(SETUP_DELAY, gen, () => void playOpponentMove(gen))
    } else {
      busy = false
    }
  }

  function advanceSteering(gen: number) {
    if (gen !== generation) return
    if (!inSteering()) {
      if (accept === 'line') {
        lineEnd()
        return
      }
      feedback = { text: 'The line is played. The book takes over from here.', kind: 'info' }
      if (turnColor !== color) later(SETUP_DELAY, gen, () => void playOpponentMove(gen))
      else busy = false
      return
    }
    if (turnColor !== color) {
      applyUci(steerLine[steerIdx])
      steerIdx += 1
      busy = true
      later(OPP_ANIM + 50, gen, () => advanceSteering(gen))
    } else {
      busy = false
    }
  }

  async function playOpponentMove(gen: number) {
    const reply = await api.bookReply(chess.fen(), replies)
    if (gen !== generation) return
    if (reply.uci === null) {
      void bookEnd(gen)
      return
    }
    applyUci(reply.uci)
    busy = true
    later(OPP_ANIM + 50, gen, () => void afterOpponentMove(gen))
  }

  async function afterOpponentMove(gen: number) {
    const res = await api.bookMoves(chess.fen(), threshold())
    if (gen !== generation) return
    if (res.accepted.length === 0) {
      void bookEnd(gen)
      return
    }
    busy = false
  }

  async function onUserMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    if (busy || phase !== 'train' || !line) return
    const gen = generation
    // the move as played: a promotion carries the piece chosen in the board's picker (UI-BUILD-4
    // D), and is judged with it: a book's e7e8n is not met by e7e8q
    const uci = uciOf(orig, dest, promo)
    if (inSteering()) {
      const target = steerLine[steerIdx]
      if (target === uci) {
        await accepted(target, gen, true)
      } else {
        errors += 1
        steerErrors += 1
        wrongThisPos = true
        feedback = { text: 'is not the line. Try again.', strong: sanOf(uci), kind: 'wrong' }
        board?.sync()
      }
      return
    }
    busy = true
    const res = await api.bookMoves(chess.fen(), threshold())
    if (gen !== generation) return
    const match = res.accepted.find((u) => u === uci)
    if (match) {
      await accepted(match, gen, false)
      return
    }
    errors += 1
    wrongThisPos = true
    feedback = res.accepted.length
      ? { text: `is not a book move ${accept === 'popular' ? 'popular enough ' : ''}here. Try again.`, strong: sanOf(uci), kind: 'wrong' }
      : { text: 'No book moves from here.', kind: 'info' }
    busy = false
    board?.sync()
  }

  function sanOf(uci: string): string {
    try {
      const c = new Chess(chess.fen())
      const m = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || undefined })
      return m.san
    } catch {
      return uci
    }
  }

  async function accepted(uci: string, gen: number, steering: boolean) {
    if (!attemptRecorded && line) {
      attemptRecorded = true
      api.trainerAttempt(line.eco, line.name, color).catch(() => {})
    }
    const label = applyUci(uci)
    movesPlayed += 1
    yourMoves += 1
    if (!wrongThisPos && !hintUsedThisPos) right += 1
    wrongThisPos = hintUsedThisPos = false
    if (steering) {
      steerIdx += 1
      steerUserMoves += 1
    }
    feedback = { text: steering ? 'is in the line.' : 'is in the book.', strong: label, kind: 'ok' }
    arrows = []
    busy = true
    if (steering) later(ANIM + 50, gen, () => advanceSteering(gen))
    else later(ANIM + 50, gen, () => void playOpponentMove(gen))
  }

  async function hint() {
    if (busy || phase !== 'train' || !line) return
    let shown: string[]
    if (inSteering()) shown = [steerLine[steerIdx]]
    else shown = (await api.bookMoves(chess.fen(), threshold())).accepted.slice(0, 4)
    arrows = shown.map(arrowFor)
    if (!hintUsedThisPos) {
      hintsUsed += 1
      hintsShown += 1
      if (inSteering()) steerHints += 1
      hintUsedThisPos = true
    }
  }

  function lineEnd() {
    // This line only (ruling 9): the run ends at the line's last move. The attempt is recorded
    // (first accepted move); no completion, which the record keeps for runs to the end of the book.
    terminalFen = chess.fen()
    phase = 'done'
    busy = true
    void refreshFamily()
    result = { title: 'Line finished', detail: `${right} of ${yourMoves} right${hintsShown ? `, ${hintsShown} ${hintsShown === 1 ? 'hint' : 'hints'}` : ''}.`, recorded: false }
  }

  async function bookEnd(gen: number) {
    terminalFen = chess.fen()
    const postErrors = errors - steerErrors
    const postMoves = movesPlayed - steerUserMoves
    const postHints = hintsUsed - steerHints
    const accuracy = postMoves > 0 ? Math.max(0, (postMoves - postErrors - postHints) / postMoves) : 1.0
    phase = 'done'
    busy = true
    result = { title: 'End of the book', detail: `${right} of ${yourMoves} right${hintsShown ? `, ${hintsShown} ${hintsShown === 1 ? 'hint' : 'hints'}` : ''}.`, recorded: true }
    if (!line) return
    const res = await api.trainerComplete({
      eco: line.eco, name: line.name, color, mode: replies, terminal_fen: terminalFen,
      moves_played: movesPlayed, errors_made: errors, accuracy,
    })
    if (gen !== generation || !fam) return
    fam.lines[selectedIdx].progress = res.progress
  }

  function change() {
    generation += 1
    for (const t of timeouts) clearTimeout(t)
    phase = 'choose'
    feedback = null
    result = null
    preview()
  }
  async function refreshFamily() {
    try {
      fam = await api.trainerFamily(family.name)
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    }
  }
  function nextLine() {
    if (!fam) return
    selectedIdx = (selectedIdx + 1) % fam.lines.length
    void refreshFamily().then(start)
  }

  // ── keys, commands ──────────────────────────────────────────────────────
  function onKey(e: KeyboardEvent) {
    // UI-BUILD-3 B6: a key a focused control handled, or Enter on a button or choice, is not
    // the screen's (Enter on "Change" or a line row started training instead of acting)
    if (alreadyHandled(e)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'f' || e.key === 'F') orientation = orientation === 'white' ? 'black' : 'white'
    else if ((e.key === 'h' || e.key === 'H') && phase === 'train') void hint()
    else if (e.key === 'Enter' && phase === 'choose' && line && !ownsEnter(e.target as HTMLElement | null)) start()
    else return
    e.preventDefault()
  }
  let unregister: (() => void) | null = null
  onMount(() => {
    void refreshFamily()
    unregister = registerCommands('trainer', () => [
      { id: 'tr-flip', group: 'Actions', label: 'Flip the board', kbd: 'F', run: () => (orientation = orientation === 'white' ? 'black' : 'white') },
      ...(phase === 'choose' && line ? [{ id: 'tr-start', group: 'Actions', label: 'Start training', kbd: '↵', run: start }] : []),
      ...(phase === 'train' ? [{ id: 'tr-hint', group: 'Actions', label: 'Hint', kbd: 'H', run: () => void hint() }] : []),
    ])
  })
  onDestroy(() => {
    generation += 1
    for (const t of timeouts) clearTimeout(t)
    unregister?.()
  })

  // ── derived ─────────────────────────────────────────────────────────────
  const recordFor = (l: TrainerLine) => l.progress.byColor?.[color] ?? null
  const lineName = $derived(line ? shortName(family.name, line.name) : '')
  const moveNo = $derived(chess && fen ? Number(fen.split(' ')[5]) : 1)
  const totalMoves = $derived(line ? fullMoves(line.uci.length) : 0)
  const repliesLabel = $derived(REPLIES_OPTIONS.find((o) => o.value === replies)!.label)
  const yourTurn = $derived(phase === 'train' && !busy && turnColor === color)
  const progressNow = $derived(line ? progressWord(recordFor(line)) : null)

  // the board fills its column
  let col: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!col) return
      const r = col.getBoundingClientRect()
      // a multiple of 8: chessground draws whole-pixel squares, so the strips, bar and
      // navigator line up with the board drawn (UI-BUILD-4 C)
      boardPx = Math.max(240, Math.floor((Math.min(r.width - 56, r.height - 40 - 64 - 40)) / 8) * 8)
    })
    if (col) ro.observe(col)
    return () => ro.disconnect()
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="trainer">
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onback}>Openings</button>
      <span class="sep" aria-hidden="true">/</span>
      <span class="title">{family.name}{#if phase !== 'choose' && line}, {lineName}{/if}</span>
    </div>
    <Button kbd="F" onclick={() => (orientation = orientation === 'white' ? 'black' : 'white')}>Flip</Button>
  </header>

  <div class="body">
    <section class="left" bind:this={col} aria-label="Board">
      <div class="colw" style:width="{boardPx}px">
        <div class="above">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.8" aria-hidden="true"><path d="M2 5h6a4 4 0 0 1 4 4v11a3 3 0 0 0-3-3H2zM22 5h-6a4 4 0 0 0-4 4v11a3 3 0 0 1 3-3h7z" /></svg>
          <span class="strong">Book</span><span class="dim">{accept === 'line' ? 'The line\'s own replies' : `${repliesLabel} replies`}</span>
        </div>
        <div class="board" style:width="{boardPx}px" style:height="{boardPx}px">
          <Board
            bind:this={board}
            {fen}
            {lastMove}
            {turnColor}
            movableColor={yourTurn ? color : null}
            dests={yourTurn ? dests : new Map()}
            {check}
            {orientation}
            shapes={arrows}
            animationMs={ANIM}
            onmove={(o, d, p) => void onUserMove(o, d, p)}
          />
        </div>
        <div class="below">
          <span class="you"><span class="av" aria-hidden="true">Y</span><span class="strong">You</span><span class="dim">{color === 'white' ? 'White' : 'Black'}</span></span>
          {#if phase === 'choose'}
            <span class="dim">Preview: the line's position</span>
          {:else if accept === 'line'}
            <span class="prog"><span class="dim">Move {Math.min(moveNo, totalMoves)} of {totalMoves}</span><span class="track" aria-hidden="true"><span style:width="{(100 * Math.min(history.length, line?.uci.length ?? 0)) / Math.max(1, line?.uci.length ?? 1)}%"></span></span></span>
          {:else}
            <span class="dim">Move {moveNo}</span>
          {/if}
        </div>
      </div>
    </section>

    <aside aria-label="Trainer">
      {#if loadError}
        <div class="pad"><EmptyState tone="error" sentence="This family's lines could not be read." sub={loadError} action={{ label: 'Back to openings', run: onback }} /></div>
      {:else if !fam}
        <div class="pad"><EmptyState sentence="Reading the family's lines from the book…" /></div>
      {:else if phase === 'choose'}
        <div class="scroll">
          <div class="sec">
            <div class="sh"><span class="strong">Lines</span><span class="dim">{fam.lines.length}</span></div>
            <ul class="lines">
              {#each showAllLines ? fam.lines : fam.lines.slice(0, Math.max(LINES_SHOWN, selectedIdx + 1)) as l, i (l.eco + l.name)}
                {@const w = progressWord(recordFor(l))}
                <li>
                  <button type="button" class:on={i === selectedIdx} aria-pressed={i === selectedIdx} onclick={() => (selectedIdx = i)}>
                    <span class="ln">{shortName(family.name, l.name)}</span>
                    <span class="lt">{lineTail(l.uci)}</span>
                    <span class="lw" class:mastered={w.word === 'Mastered'}>{w.word}</span>
                  </button>
                </li>
              {/each}
            </ul>
            {#if fam.lines.length > LINES_SHOWN}
              <button type="button" class="more" onclick={() => (showAllLines = !showAllLines)}
                >{showAllLines ? 'Fewer lines' : `${fam.lines.length - Math.max(LINES_SHOWN, selectedIdx + 1)} more lines`}</button
              >
            {/if}
          </div>
          {#if line}
            <div class="sec sel">
              <div class="strong">{lineName}</div>
              <div class="dim">{movesText(line.uci)}, {totalMoves} {totalMoves === 1 ? 'move' : 'moves'}</div>
              {#if progressNow}<div class="dim small">As {color === 'white' ? 'White' : 'Black'}: {progressNow.word}{progressNow.detail ? `, ${progressNow.detail}` : ''}</div>{/if}
            </div>
          {/if}
          <div class="sec opts">
            <span class="ol">Colour</span>
            <div class="seg">
              {#each [['white', 'White'], ['black', 'Black']] as [v, l] (v)}
                <button type="button" aria-pressed={color === v} onclick={() => (color = v as Color)}>{l}</button>
              {/each}
            </div>
            <span class="ol">Replies</span>
            <div class="seg">
              {#each REPLIES_OPTIONS as o (o.value)}
                <button type="button" aria-pressed={replies === o.value} disabled={accept === 'line'} title={accept === 'line' ? 'This line only plays the line\'s own replies' : undefined} onclick={() => (replies = o.value)}>{o.label}</button>
              {/each}
            </div>
            <span class="ol">Accept</span>
            <div class="seg">
              {#each ACCEPT_OPTIONS as o (o.value)}
                <button type="button" aria-pressed={accept === o.value} onclick={() => (accept = o.value)}>{o.label}</button>
              {/each}
            </div>
            <span class="ol">Start</span>
            <div class="seg">
              <button type="button" aria-pressed={fromMove1} onclick={() => (fromMove1 = true)}>Move 1</button>
              <button type="button" aria-pressed={!fromMove1} disabled={accept === 'line'} title={accept === 'line' ? 'This line only ends where Line start begins' : undefined} onclick={() => (fromMove1 = false)}>Line start</button>
            </div>
          </div>
        </div>
        <div class="foot"><Button variant="primary" kbd="↵" disabled={!line} onclick={start}>Start training</Button></div>
      {:else}
        <div class="scroll">
          <div class="sec sumrow">
            <div>
              <div class="strong">{lineName}</div>
              <div class="dim small">{summaryLine(color, replies, accept, fromMove1)}</div>
            </div>
            <Button size="sm" onclick={change}>Change</Button>
          </div>
          <div class="sec">
            {#if phase === 'done' && result}
              <div class="res">
                <div class="heading">{result.title}</div>
                <p class="dim">{result.detail}{#if !result.recorded}{' '}A line-only run is not counted toward Finished or Mastered.{/if}</p>
              </div>
            {:else}
              {#if feedback}
                <p class="fb {feedback.kind}">
                  {#if feedback.kind === 'ok'}<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(--q-good)" /><path d="m7 12.5 3.2 3.2L17 9" fill="none" stroke="var(--q-ink)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>{/if}
                  {#if feedback.strong}<span class="strong">{feedback.strong}</span> {/if}{feedback.text}
                </p>
              {/if}
              <div class="heading">{yourTurn ? 'Your move' : busy ? 'The book is replying…' : ''}</div>
            {/if}
            <p class="moves">{history.length ? runMoves() : 'No moves yet.'}</p>
          </div>
          <dl class="sec score">
            <div><dt>This run</dt><dd>{right} of {yourMoves} right</dd></div>
            <div><dt>Hints</dt><dd>{hintsShown}</dd></div>
            <div><dt>Progress</dt><dd>{progressNow?.word ?? '–'}</dd></div>
          </dl>
        </div>
        <div class="foot two">
          {#if phase === 'done'}
            <Button onclick={start}>Again</Button>
            <Button onclick={nextLine}>Next line</Button>
            <Button variant="primary" onclick={() => onplayfen(terminalFen)}>Play it out vs Stockfish</Button>
          {:else}
            <Button kbd="H" disabled={!yourTurn} onclick={() => void hint()}>Hint</Button>
            <Button onclick={() => onplayfen(chess.fen())}>Play it out vs Stockfish</Button>
          {/if}
        </div>
      {/if}
    </aside>
  </div>
</div>

<style>
  .trainer {
    display: flex;
    flex-direction: column;
    height: 100%;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  header {
    height: var(--header-height);
    flex: none;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  .crumb {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
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
  .sep {
    color: var(--disabled);
  }
  .title {
    font: var(--body-strong);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .body {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .left {
    flex: 1;
    min-width: 0;
    display: flex;
    justify-content: center;
    padding: 28px;
  }
  .colw {
    display: flex;
    flex-direction: column;
  }
  .above,
  .below {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 40px;
  }
  .below {
    justify-content: space-between;
  }
  .board {
    flex: none;
  }
  .you {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .av {
    width: 20px;
    height: 20px;
    border-radius: 10px;
    background: var(--text);
    color: var(--bg);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font: 600 11px var(--sans);
  }
  .prog {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .track {
    width: 120px;
    height: 3px;
    border-radius: 2px;
    background: var(--border);
    overflow: hidden;
  }
  .track span {
    display: block;
    height: 100%;
    background: var(--text);
  }
  aside {
    flex: 0 0 420px;
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .scroll {
    flex: 1;
    overflow-y: auto;
  }
  .pad {
    padding: 20px;
  }
  .sec {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }
  .sh {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .strong {
    font-weight: 500;
  }
  .dim {
    color: var(--text-2);
  }
  .small {
    font: var(--secondary);
    margin-top: 2px;
  }
  .lines {
    list-style: none;
    margin: 0 -8px;
    padding: 0;
  }
  .lines button {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto 72px;
    gap: 12px;
    align-items: center;
    padding: 6px 8px;
    border: 1px solid transparent;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .lines button:hover {
    background: var(--surface);
  }
  .lines button.on {
    background: var(--surface);
    border-color: var(--border-strong);
  }
  .ln {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lt,
  .lw {
    color: var(--text-2);
    font: var(--secondary);
    white-space: nowrap;
  }
  .lw {
    text-align: right;
    color: var(--text-3);
  }
  .lw.mastered {
    color: var(--text);
  }
  .more {
    margin-top: 6px;
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-2);
    font: var(--secondary);
    cursor: pointer;
  }
  .more:hover {
    color: var(--text);
  }
  .opts {
    display: grid;
    grid-template-columns: 76px minmax(0, 1fr);
    gap: 10px 12px;
    align-items: center;
    border-bottom: 0;
  }
  .ol {
    color: var(--text-2);
    font: var(--secondary);
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
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 4px 6px;
    font: var(--secondary);
    color: var(--text-2);
    cursor: pointer;
    white-space: nowrap;
  }
  .seg button[aria-pressed='true'] {
    background: var(--border);
    color: var(--text);
  }
  .seg button:disabled {
    color: var(--disabled);
    cursor: default;
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .foot {
    flex: none;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
    display: flex;
  }
  .foot :global(button) {
    flex: 1;
  }
  .foot.two {
    gap: 8px;
  }
  .sumrow {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .heading {
    font: var(--heading);
    margin: 6px 0 8px;
  }
  .fb {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 4px;
    color: var(--text-2);
  }
  .fb.wrong {
    color: var(--loss);
  }
  .fb.wrong .strong {
    color: var(--text);
  }
  .moves {
    margin: 0;
    color: var(--text-2);
    font: var(--secondary);
    line-height: 1.6;
  }
  .score {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    margin: 0;
  }
  .score dt {
    color: var(--text-3);
    font: var(--secondary);
  }
  .score dd {
    margin: 2px 0 0;
    font-weight: 500;
  }
  .res p {
    margin: 0 0 8px;
  }
</style>
