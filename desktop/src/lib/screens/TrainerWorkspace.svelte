<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import {
    api,
    TRAINER_DIFFICULTY_PRESETS,
    TRAINER_DIFFICULTY_DEFAULT,
    type Color,
    type TrainerFamily,
    type TrainerFamilySummary,
    type TrainerLine,
  } from '../api'

  interface Props {
    family: TrainerFamilySummary
    onback: () => void
    onplayfen: (fen: string) => void
  }
  let { family, onback, onplayfen }: Props = $props()

  const OPP_ANIM = 400 // TRAINER_OPP_ANIM_MS
  const SETUP_DELAY = 500 // TRAINER_SETUP_DELAY_MS
  const ANIM = 250

  type TState = 'empty' | 'idle' | 'busy' | 'complete' | 'offBook'

  const chess = new Chess()
  let board: Board

  // family data
  let fam = $state<TrainerFamily | null>(null)
  let selectedIdx = $state(-1)

  // options
  let color = $state<Color>('white')
  let mode = $state<'varied' | 'random' | 'pinned'>('varied')
  let diffIdx = $state(TRAINER_DIFFICULTY_DEFAULT)
  let fromMove1 = $state(false)
  let offBook = $state(false)

  // board state
  let tstate = $state<TState>('empty')
  let fen = $state('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
  let lastMove = $state<[Key, Key] | null>(null)
  let dests = $state<Map<Key, Key[]>>(new Map())
  let check = $state(false)
  let arrows = $state<DrawShape[]>([])

  // session counters
  let openingLabel = $state('—')
  let movesPlayed = $state(0)
  let errors = $state(0)
  let feedback = $state<{ text: string; kind: 'info' | 'wrong' | 'correct' } | null>(null)
  let endStats = $state<{ moves: number; errors: number; accuracyPct: number } | null>(null)
  let terminalFen = ''

  let hintsUsed = 0
  let hintUsedThisPos = false
  let attemptRecorded = false
  let steerLine: string[] = []
  let steerIdx = 0
  let steerUserMoves = 0
  let steerErrors = 0
  let steerHints = 0
  let generation = 0 // bumped on restart; stale async steps abort
  let timeouts: ReturnType<typeof setTimeout>[] = []

  const turnColor = $derived<Color>(fen.split(' ')[1] === 'w' ? 'white' : 'black')
  const movableColor = $derived(tstate === 'idle' ? color : null)
  const threshold = $derived(TRAINER_DIFFICULTY_PRESETS[diffIdx][1])
  const inSteering = () => steerLine.length > 0 && steerIdx < steerLine.length
  const line = $derived(selectedIdx >= 0 ? (fam?.lines[selectedIdx] ?? null) : null)

  function later(ms: number, gen: number, fn: () => void) {
    timeouts.push(
      setTimeout(() => {
        if (gen === generation) fn()
      }, ms),
    )
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

  function applyUci(uci: string) {
    chess.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: (uci[4] as 'q' | 'r' | 'b' | 'n' | undefined) ?? undefined,
    })
    lastMove = [uci.slice(0, 2) as Key, uci.slice(2, 4) as Key]
    syncBoard()
  }

  async function updateOpening() {
    const res = await api.openingAt(chess.fen())
    if (res.opening) openingLabel = `${res.opening.eco}  ${res.opening.name}`
  }

  // ── session lifecycle ────────────────────────────────────────────────────

  function startSession() {
    if (!line) return
    generation += 1
    const gen = generation
    for (const t of timeouts) clearTimeout(t)
    timeouts = []

    movesPlayed = 0
    errors = 0
    hintsUsed = 0
    hintUsedThisPos = false
    attemptRecorded = false
    steerUserMoves = 0
    steerErrors = 0
    steerHints = 0
    feedback = null
    endStats = null
    terminalFen = ''
    arrows = []
    lastMove = null
    openingLabel = `${line.eco}  ${line.name}`

    if (fromMove1) {
      chess.reset()
      steerLine = line.uci.slice()
      steerIdx = 0
    } else {
      chess.load(line.fen)
      steerLine = []
      steerIdx = 0
    }
    tstate = 'busy'
    syncBoard()

    if (fromMove1) {
      if (inSteering() && turnColor !== color) {
        later(SETUP_DELAY, gen, () => advanceSteering(gen))
      } else {
        advanceSteering(gen)
      }
    } else if (turnColor !== color) {
      later(SETUP_DELAY, gen, () => void playOpponentMove(gen))
    } else {
      tstate = 'idle'
    }
  }

  function advanceSteering(gen: number) {
    if (gen !== generation) return
    if (!inSteering()) {
      feedback = { text: 'Opening reached — continue', kind: 'info' }
      void updateOpening()
      if (turnColor !== color) {
        later(SETUP_DELAY, gen, () => void playOpponentMove(gen))
      } else {
        tstate = 'idle'
        syncBoard()
      }
      return
    }
    if (turnColor !== color) {
      // opponent's steering move — auto-play
      applyUci(steerLine[steerIdx])
      steerIdx += 1
      tstate = 'busy'
      later(OPP_ANIM + 50, gen, () => advanceSteering(gen))
    } else {
      void updateOpening()
      tstate = 'idle'
      syncBoard()
    }
  }

  async function playOpponentMove(gen: number) {
    const reply = await api.bookReply(chess.fen(), mode)
    if (gen !== generation) return
    if (reply.uci === null) {
      void bookEnd(gen)
      return
    }
    applyUci(reply.uci)
    tstate = 'busy'
    later(OPP_ANIM + 50, gen, () => void afterOpponentMove(gen))
  }

  async function afterOpponentMove(gen: number) {
    const res = await api.bookMoves(chess.fen(), threshold)
    if (gen !== generation) return
    if (res.accepted.length === 0) {
      void bookEnd(gen)
      return
    }
    void updateOpening()
    tstate = 'idle'
    syncBoard()
  }

  // ── user moves ───────────────────────────────────────────────────────────

  async function onUserMove(orig: Key, dest: Key) {
    if (tstate !== 'idle' || !line) return
    const gen = generation
    const uci4 = `${orig}${dest}`

    if (inSteering()) {
      const target = steerLine[steerIdx]
      if (target === uci4 || (target.length === 5 && target.startsWith(uci4))) {
        await onAcceptedMove(target, gen, true)
      } else {
        errors += 1
        steerErrors += 1
        feedback = { text: 'Not in the target line — try again', kind: 'wrong' }
        arrows = [arrowFor(target)]
        board?.sync()
      }
      return
    }

    tstate = 'busy'
    const res = await api.bookMoves(chess.fen(), threshold)
    if (gen !== generation) return
    const accepted = res.accepted
    const match = accepted.find((u) => u === uci4 || (u.length === 5 && u.startsWith(uci4)))

    if (match) {
      await onAcceptedMove(match, gen, false)
      return
    }

    errors += 1
    if (accepted.length === 0) {
      feedback = { text: 'No book moves — end of theory', kind: 'info' }
      arrows = []
    } else {
      feedback = {
        text:
          accepted.length === 1
            ? 'Not in book — try again'
            : `Not in book — ${accepted.length} book moves available`,
        kind: 'wrong',
      }
      arrows = accepted.slice(0, 4).map(arrowFor)
    }

    if (offBook) {
      // continue with the off-book move (auto-queen promotions, as PyQt does)
      const candidates = chess.moves({ square: orig as Square, verbose: true })
      const promo = candidates.some((m) => m.to === dest && m.promotion) ? 'q' : ''
      applyUci(uci4 + promo)
      arrows = []
      feedback = { text: 'Off book — continuing', kind: 'info' }
      later(ANIM + 50, gen, () => void playOpponentMove(gen))
      return
    }
    tstate = 'idle'
    board?.sync()
  }

  async function onAcceptedMove(uci: string, gen: number, steering: boolean) {
    if (!attemptRecorded && line) {
      attemptRecorded = true
      void api.trainerAttempt(line.eco, line.name, color)
    }
    applyUci(uci)
    movesPlayed += 1
    if (steering) {
      steerIdx += 1
      steerUserMoves += 1
    }
    feedback = null
    hintUsedThisPos = false
    arrows = []
    tstate = 'busy'
    void updateOpening()
    if (steering) {
      later(ANIM + 50, gen, () => advanceSteering(gen))
    } else {
      later(ANIM + 50, gen, () => void playOpponentMove(gen))
    }
  }

  function arrowFor(uci: string): DrawShape {
    return { orig: uci.slice(0, 2) as Key, dest: uci.slice(2, 4) as Key, brush: 'green' }
  }

  // ── hint ─────────────────────────────────────────────────────────────────

  async function onHint() {
    if (tstate !== 'idle' || !line) return
    if (inSteering()) {
      arrows = [arrowFor(steerLine[steerIdx])]
      feedback = { text: 'Hint shown', kind: 'info' }
      if (!hintUsedThisPos) {
        hintsUsed += 1
        steerHints += 1
        hintUsedThisPos = true
      }
      return
    }
    const res = await api.bookMoves(chess.fen(), threshold)
    arrows = res.accepted.slice(0, 4).map(arrowFor)
    feedback = { text: 'Hint shown — counts against accuracy', kind: 'info' }
    if (!hintUsedThisPos) {
      hintsUsed += 1
      hintUsedThisPos = true
    }
  }

  // ── book end ─────────────────────────────────────────────────────────────

  async function bookEnd(gen: number) {
    terminalFen = chess.fen()
    const postErrors = errors - steerErrors
    if (offBook && postErrors > 0) {
      tstate = 'offBook'
      return
    }
    const postMoves = movesPlayed - steerUserMoves
    const postHints = hintsUsed - steerHints
    const penalty = postErrors + postHints
    const accuracy = postMoves > 0 ? Math.max(0, (postMoves - penalty) / postMoves) : 1.0
    endStats = { moves: movesPlayed, errors, accuracyPct: Math.round(accuracy * 100) }
    tstate = 'complete'
    if (!line) return
    const res = await api.trainerComplete({
      eco: line.eco,
      name: line.name,
      color,
      mode,
      terminal_fen: terminalFen,
      moves_played: movesPlayed,
      errors_made: errors,
      accuracy,
    })
    if (gen !== generation || !fam) return
    // refresh the line's mastery in place
    fam.lines[selectedIdx].progress = res.progress
    const refreshed = await api.trainerFamily(family.name)
    if (gen === generation) fam = refreshed
  }

  // ── line / option handling ───────────────────────────────────────────────

  function selectLine(i: number) {
    selectedIdx = i
    startSession()
  }

  function setOption<T>(setter: (v: T) => void, value: T) {
    setter(value)
    if (selectedIdx >= 0) startSession()
  }

  function shortName(name: string): string {
    for (const prefix of [`${family.name}: `, `${family.name} `]) {
      if (name.startsWith(prefix)) return name.slice(prefix.length)
    }
    return name
  }

  function masteryStr(l: TrainerLine): string {
    if (l.progress.mastered) return '★'
    if (l.progress.distinctLines > 0) return `${l.progress.distinctLines}✓`
    return ''
  }

  onMount(async () => {
    fam = await api.trainerFamily(family.name)
  })
  onDestroy(() => {
    generation += 1
    for (const t of timeouts) clearTimeout(t)
  })
</script>

<div class="workspace">
  <div class="board-col">
    <Board
      bind:this={board}
      {fen}
      {lastMove}
      {turnColor}
      {movableColor}
      dests={tstate === 'idle' ? dests : new Map()}
      {check}
      orientation={color}
      shapes={arrows}
      animationMs={ANIM}
      onmove={(o, d) => void onUserMove(o, d)}
    />
  </div>

  <aside class="panel">
    <div class="head">
      <button class="back" onclick={onback}>← Openings</button>
      <div class="head-row">
        <h3>{family.name}</h3>
        {#if fam}
          <span class="mastery-count">
            {fam.mastered > 0 ? `${fam.mastered} / ${fam.lines.length} mastered` : fam.drilled > 0 ? `${fam.drilled} drilled` : ''}
          </span>
        {/if}
      </div>
    </div>

    <div class="lines">
      {#if !fam}
        <div class="loading"><span class="pulse-dot"></span> Curating lines…</div>
      {:else}
        {#each fam.lines as l, i (l.eco + l.name)}
          <button class="line" class:selected={selectedIdx === i} onclick={() => selectLine(i)}>
            <span class="line-eco">{l.eco}</span>
            <span class="line-name">{shortName(l.name)}</span>
            {#if !l.coverage[color]}<span class="no-cov" title="No book coverage for {color}">no {color === 'white' ? 'W' : 'B'}</span>{/if}
            <span class="line-mark" class:star={l.progress.mastered}>{masteryStr(l)}</span>
          </button>
        {/each}
      {/if}
    </div>

    <div class="options">
      <div class="opt-row">
        <span class="opt-label">Color</span>
        <div class="seg">
          <button class:on={color === 'white'} onclick={() => setOption((v: Color) => (color = v), 'white')}>White</button>
          <button class:on={color === 'black'} onclick={() => setOption((v: Color) => (color = v), 'black')}>Black</button>
        </div>
      </div>
      <div class="opt-row">
        <span class="opt-label">Mode</span>
        <div class="seg">
          {#each ['varied', 'random', 'pinned'] as m (m)}
            <button
              class:on={mode === m}
              title={m === 'varied'
                ? 'Weighted-random replies — popular lines appear more often'
                : m === 'random'
                  ? 'Uniform-random among all book replies'
                  : 'Always the mainline reply'}
              onclick={() => setOption((v: typeof mode) => (mode = v), m as typeof mode)}
            >
              {m[0].toUpperCase() + m.slice(1)}
            </button>
          {/each}
        </div>
      </div>
      <div class="opt-row">
        <span class="opt-label">Strictness</span>
        <div class="seg">
          {#each TRAINER_DIFFICULTY_PRESETS as [label, frac], i (label)}
            <button
              class:on={diffIdx === i}
              title="Accept moves with weight ≥ {Math.round(frac * 100)}% of the top move"
              onclick={() => setOption((v: number) => (diffIdx = v), i)}
            >
              {label}
            </button>
          {/each}
        </div>
      </div>
      <div class="opt-row">
        <span class="opt-label">Start</span>
        <div class="seg">
          <button class:on={!fromMove1} title="Start from the opening's defining position" onclick={() => setOption((v: boolean) => (fromMove1 = v), false)}>Line</button>
          <button class:on={fromMove1} title="Play into the opening from move 1" onclick={() => setOption((v: boolean) => (fromMove1 = v), true)}>Move 1</button>
        </div>
      </div>
      <button
        class="offbook"
        class:on={offBook}
        role="switch"
        aria-checked={offBook}
        title="Continue past the book instead of stopping at end of theory"
        onclick={() => setOption((v: boolean) => (offBook = v), !offBook)}
      >
        <span class="ob-box" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="m5 12 5 5L20 7" /></svg>
        </span>
        Allow off-book continuation
      </button>
    </div>

    <div class="session">
      {#if tstate === 'empty'}
        <div class="empty">Select a line to begin</div>
      {:else if tstate === 'complete' && endStats}
        <div class="end">
          <div class="end-banner correct">
            <span class="end-title">Opening theory complete</span>
            <span class="end-detail">
              {endStats.moves} book moves · {endStats.errors} errors · {endStats.accuracyPct}% accuracy
            </span>
          </div>
          <button class="btn btn-accent" onclick={() => onplayfen(terminalFen)}>
            Play position vs Stockfish →
          </button>
          <button class="btn btn-quiet" onclick={() => startSession()}>Train line again</button>
          <span class="end-hint">Alternatively, select another line to train</span>
        </div>
      {:else if tstate === 'offBook'}
        <div class="end">
          <div class="end-banner info">
            <span class="end-title">Left the book</span>
            <span class="end-detail">Play moved outside theory. Keep training to learn the position.</span>
          </div>
          <button class="btn btn-accent" onclick={() => onplayfen(terminalFen)}>
            Play vs Stockfish →
          </button>
        </div>
      {:else}
        <div class="live">
          <span class="opening">{openingLabel}</span>
          <span class="mode-line">{color} · {mode} · {TRAINER_DIFFICULTY_PRESETS[diffIdx][0].toLowerCase()}</span>
          <div class="stats-row">
            <span class="mini-stat"><b>{movesPlayed}</b> {movesPlayed === 1 ? 'move' : 'moves'}</span>
            <span class="mini-stat" class:err={errors > 0}><b>{errors}</b> {errors === 1 ? 'error' : 'errors'}</span>
            <button class="hint-btn" disabled={tstate !== 'idle'} onclick={() => void onHint()}>
              Hint
            </button>
          </div>
          {#if feedback}
            <div class="fb {feedback.kind}">{feedback.text}</div>
          {/if}
        </div>
      {/if}
    </div>
  </aside>
</div>

<style>
  .workspace {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 28px;
    padding: 28px;
  }
  .board-col {
    width: min(calc(100vh - 112px), calc(100vw - 640px), 720px);
    min-width: 380px;
  }
  .panel {
    width: 340px;
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
    gap: 10px;
  }
  h3 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }
  .mastery-count {
    font-size: 11.5px;
    color: var(--accent);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .lines {
    flex: 1;
    min-height: 120px;
    overflow-y: auto;
  }
  .loading {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 16px;
    font-size: 12.5px;
    color: var(--text-muted);
  }
  .line {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    font-size: 12.5px;
    text-align: left;
    border-bottom: 1px solid var(--divider);
    transition: background-color 100ms ease, color 100ms ease;
  }
  .line:hover {
    background: var(--bg-raised);
  }
  .line.selected {
    background: var(--accent-soft);
    color: var(--accent);
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .line-eco {
    width: 30px;
    flex-shrink: 0;
    color: var(--text-muted);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .line.selected .line-eco {
    color: var(--accent);
  }
  .line-name {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .line-mark {
    flex-shrink: 0;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
  }
  .line-mark.star {
    color: var(--accent);
  }
  .no-cov {
    flex-shrink: 0;
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-muted);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 1px 4px;
    opacity: 0.8;
  }

  .options {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    border-top: 1px solid var(--divider);
  }
  .opt-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .opt-label {
    width: 62px;
    flex-shrink: 0;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--bg-raised);
  }
  .seg button {
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-muted);
    transition: color 120ms ease, background-color 120ms ease;
  }
  .seg button:hover:not(.on) {
    color: var(--text);
  }
  .seg button.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .offbook {
    display: flex;
    align-items: center;
    gap: 8px;
    align-self: flex-start;
    margin-top: 2px;
    font-size: 12px;
    color: var(--text-muted);
    transition: color 120ms ease;
  }
  .offbook:hover {
    color: var(--text);
  }
  .offbook.on {
    color: var(--text);
  }
  .ob-box {
    display: grid;
    place-items: center;
    width: 16px;
    height: 16px;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    background: var(--bg-surface);
    transition: background-color 120ms ease, border-color 120ms ease;
  }
  .ob-box svg {
    width: 11px;
    height: 11px;
    fill: none;
    stroke: var(--accent-ink);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .offbook.on .ob-box {
    background: var(--accent);
    border-color: var(--accent);
  }
  .offbook.on .ob-box svg {
    opacity: 1;
  }

  .session {
    border-top: 1px solid var(--divider);
    padding: 12px 14px;
    min-height: 124px;
  }
  .empty {
    font-size: 12.5px;
    color: var(--text-muted);
    text-align: center;
    padding: 30px 0;
  }
  .live {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .opening {
    font-size: 13.5px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .mode-line {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .stats-row {
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 12.5px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  .mini-stat b {
    color: var(--text);
    font-weight: 700;
  }
  .mini-stat.err b {
    color: var(--danger);
  }
  .hint-btn {
    margin-left: auto;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 4px 13px;
    transition: color 120ms ease, border-color 120ms ease, background-color 120ms ease;
  }
  .hint-btn:hover:not(:disabled) {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .hint-btn:disabled {
    opacity: 0.4;
  }
  .fb {
    font-size: 12.5px;
    font-weight: 500;
    padding: 8px 11px;
    border-radius: var(--radius);
    border: 1px solid var(--divider);
    background: var(--bg-raised);
  }
  .fb.wrong {
    color: var(--danger);
    border-color: color-mix(in srgb, var(--danger) 45%, var(--divider));
    background: color-mix(in srgb, var(--danger) 12%, var(--bg-raised));
  }
  .fb.info {
    color: var(--text-muted);
  }
  .fb.correct {
    color: var(--win);
    border-color: color-mix(in srgb, var(--win) 45%, var(--divider));
    background: color-mix(in srgb, var(--win) 12%, var(--bg-raised));
  }

  .end {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .end-banner {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 10px 12px;
    border-radius: var(--radius);
    border: 1px solid var(--divider);
    background: var(--bg-raised);
  }
  .end-banner.correct {
    border-color: color-mix(in srgb, var(--win) 45%, var(--divider));
    background: color-mix(in srgb, var(--win) 12%, var(--bg-raised));
  }
  .end-title {
    font-size: 14px;
    font-weight: 600;
  }
  .end-banner.correct .end-title {
    color: var(--win);
  }
  .end-detail {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.4;
  }
  .end-hint {
    font-size: 11.5px;
    color: var(--text-muted);
    text-align: center;
  }
</style>
