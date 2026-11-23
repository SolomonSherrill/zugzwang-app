<script lang="ts">
  /**
   * Analyse a position (DESIGN.md fourth rulings, 8): Review's Moves layout with no game. The
   * board with neutral strips (White, Black, the side to move marked), the eval bar and the
   * navigator; the engine lines live; exploring as in Review (UI-BUILD-3 C): the moves played
   * from the starting FEN form the line, a different move from an earlier position branches.
   * No Report tab, no eval graph. Not designed: drafted in the established style (UI-BUILD-3 D).
   */
  import { onDestroy, onMount } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import Board from '../Board.svelte'
  import { uciOf, type PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import PlayerStrip from '../ui/PlayerStrip.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import EngineLinesPanel from './EngineLinesPanel.svelte'
  import MoveGrid from './MoveGrid.svelte'
  import { api } from '../api'
  import { alreadyHandled } from '../ui/keyTargets'
  import { registerCommands, commandMenu, type Command } from '../shell/commands.svelte'
  import { emptyTree, type NodeId, type VarTree } from '../variations'
  import {
    applyMoves, linesByRoot, nodeAt, nodePly, onMain, onVariation, placeFen, placeOn, placeUci, plyBaseOf, step,
    type MainMove, type Place, type Step,
  } from './explore'
  import { liveRows, liveWp, positionEnd, sideToMove, type LineRow, type LinesStatus } from './engineLines'
  import { LiveLines } from './liveLines.svelte'
  import { cellRows, lineTokens, type MoveCell } from './reviewModel'

  interface Props {
    /** the position to analyse */
    fen: string
    /** where Back goes, as the breadcrumb names it ("Games", "Home") */
    backLabel?: string
    onback: () => void
    /** "Play it vs Stockfish": a new game from the position on the board */
    onplayfen: (fen: string) => void
    onsettings: () => void
    /** a game's moves (UCI) from the FEN, laid out as the line: a friend's game analysed on
     *  request (FRIENDS.md G1), never stored */
    initialMoves?: string[] | null
    /** the screen's title, "Analyse a position" by default (a friend's game names itself) */
    title?: string
  }
  let { fen, backLabel = 'Games', onback, onplayfen, onsettings, initialMoves = null, title = 'Analyse a position' }: Props =
    $props()

  // ── the position ─────────────────────────────────────────────────────────────
  /** chess.js's reading of the FEN; the sidecar's stricter legality (VAL-FEN) answers
   *  through analyze_fen and shows the same state. */
  const startError = $derived.by(() => {
    try {
      new Chess(fen)
      return null
    } catch (e) {
      return e instanceof Error ? e.message : String(e)
    }
  })
  const startFen = $derived(fen.trim())
  const base = $derived(plyBaseOf(startFen))

  // ── exploring: the line from the FEN, and variations off it ─────────────────
  let main = $state<MainMove[]>([])
  let tree = $state<VarTree>(emptyTree())
  let cur = $state(0)
  let vpath = $state<NodeId[]>([])
  let vat = $state(0)
  const place = $derived<Place>({ cur, path: vpath, at: vat })
  const onVar = $derived(onVariation(place))
  const varNode = $derived(nodeAt(tree, place))
  let navSeq = 0
  function setPlace(p: Place) {
    navSeq++
    cur = p.cur
    vpath = p.path
    vat = p.at
  }
  const go = (how: Step) => setPlace(step(place, how, main.length))
  const leaveVariation = () => onVar && setPlace(onMain(cur))
  function clearVariations() {
    tree = emptyTree()
    leaveVariation()
  }
  function showNode(id: NodeId) {
    const p = placeOn(tree, id)
    if (p) setPlace(p)
  }

  const boardFen = $derived(startError ? startFen : placeFen(tree, main, startFen, place))
  const lastMove = $derived.by((): [Key, Key] | null => {
    const u = placeUci(tree, main, place)
    return u ? [u.slice(0, 2) as Key, u.slice(2, 4) as Key] : null
  })
  const chess = $derived.by(() => {
    try {
      return new Chess(boardFen)
    } catch {
      return null
    }
  })
  const turnColor = $derived<'white' | 'black'>(boardFen.split(' ')[1] === 'b' ? 'black' : 'white')
  const check = $derived(chess?.inCheck() ?? false)
  const dests = $derived.by(() => {
    const d = new Map<Key, Key[]>()
    for (const mv of chess?.moves({ verbose: true }) ?? []) d.set(mv.from as Key, [...(d.get(mv.from as Key) ?? []), mv.to as Key])
    return d
  })

  async function playUcis(ucis: string[]) {
    const seq = navSeq
    let from = boardFen
    const moves = []
    for (const uci of ucis) {
      let probed
      try {
        probed = await api.probeMove(from, uci)
      } catch {
        break
      }
      if (!probed.legal) break
      moves.push({ uci, san: probed.san, fen: probed.fen })
      from = probed.fen
    }
    if (!moves.length) {
      boardEl?.sync()
      return
    }
    const s = applyMoves({ tree, main, place }, moves, true)
    tree = s.tree
    main = s.main
    if (navSeq === seq) setPlace(s.place)
  }

  let boardEl: Board | undefined = $state()
  // a promotion arrives with the piece chosen in the board's picker (UI-BUILD-4 D)
  function onBoardMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    void playUcis([uciOf(orig, dest, promo)])
  }


  // ── live lines ───────────────────────────────────────────────────────────────
  let engineOk = $state<boolean | null>(null)
  const live = new LiveLines()
  const endHere = $derived(positionEnd(boardFen))
  $effect(() => {
    if (!startError && engineOk && !endHere) live.request(boardFen)
  })
  const liveNow = $derived(live.state(boardFen))
  /** the sidecar refused the starting position (VAL-FEN): the screen's illegal state */
  const refused = $derived.by(() => {
    const s = live.state(startFen)
    return s.kind === 'illegal' ? s.message : null
  })
  let heldWp: number | null = null
  const wp = $derived.by(() => {
    if (endHere === 'Checkmate.') return turnColor === 'white' ? 0 : 1
    const v = liveNow.kind === 'done' ? liveWp(liveNow.ev) : null
    if (v !== null) heldWp = v
    return v ?? heldWp
  })
  const plyHere = $derived(onVar && varNode ? nodePly(tree, varNode.id) + 1 : cur)
  const engine = $derived.by((): { rows: LineRow[]; status: LinesStatus; depth: number | null } => {
    if (endHere) return { rows: [], status: { kind: 'note', text: endHere }, depth: null }
    if (engineOk === false) return { rows: [], status: { kind: 'no-engine', onsettings }, depth: null }
    if (liveNow.kind === 'done') return { rows: liveRows(liveNow.ev), status: { kind: 'lines' }, depth: liveNow.ev.depth ?? null }
    if (liveNow.kind === 'error' || liveNow.kind === 'illegal')
      return { rows: [], status: { kind: 'error', text: liveNow.message, retry: () => live.retry(boardFen) }, depth: null }
    return { rows: [], status: { kind: 'pending' }, depth: null }
  })

  // ── the move list ──────────────────────────────────────────────────────────
  const rows = $derived(cellRows(main.map((m, ply): MoveCell => ({ ply, san: m.san, cls: null, eval: '' })), base))
  const varLines = $derived(linesByRoot(tree))
  let list: HTMLDivElement | undefined = $state()
  $effect(() => {
    const sel = varNode ? `[data-node="${varNode.id}"]` : cur > 0 ? `[data-ply="${cur - 1}"]` : null
    const el = sel && list?.querySelector<HTMLElement>(sel)
    if (!list || !el) return
    const box = list.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    if (r.top < box.top || r.bottom > box.bottom) el.scrollIntoView({ block: 'center' })
  })
  /** "23. Kg1" / "23… Qf4+", numbered from the FEN's own move number. */
  const label = (ply: number, san: string) => `${lineTokens(base + ply, [san], true)[0].num} ${san}`
  const curMove = $derived(varNode ? label(nodePly(tree, varNode.id), varNode.san) : cur > 0 ? label(cur - 1, main[cur - 1].san) : null)

  // ── board frame ─────────────────────────────────────────────────────────────
  // svelte-ignore state_referenced_locally
  let orientation = $state<'white' | 'black'>(fen.split(' ')[1] === 'b' ? 'black' : 'white')
  const top = $derived<'white' | 'black'>(orientation === 'white' ? 'black' : 'white')
  const bottom = $derived<'white' | 'black'>(orientation)
  const flip = () => (orientation = orientation === 'white' ? 'black' : 'white')
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      // a multiple of 8: chessground draws whole-pixel squares, so the strips, bar and
      // navigator line up with the board drawn (UI-BUILD-4 C)
      boardPx = Math.max(240, Math.floor((Math.min(r.width - 56 - 20, r.height - 44 - 72 - 53)) / 8) * 8)
    })
    if (section) ro.observe(section)
    return () => ro.disconnect()
  })
  const PANEL_KEY = 'zugzwang.reviewPanel'
  let panelW = $state(Number(globalThis.localStorage?.getItem(PANEL_KEY)) || 420)
  function startDrag(e: PointerEvent) {
    const startX = e.clientX
    const startW = panelW
    const target = e.currentTarget as HTMLElement
    target.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent) => (panelW = Math.max(320, Math.min(640, startW - (ev.clientX - startX))))
    const up = () => {
      target.removeEventListener('pointermove', move)
      target.removeEventListener('pointerup', up)
      globalThis.localStorage?.setItem(PANEL_KEY, String(panelW))
    }
    target.addEventListener('pointermove', move)
    target.addEventListener('pointerup', up)
  }
  function splitKey(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') panelW = Math.min(640, panelW + 16)
    else if (e.key === 'ArrowRight') panelW = Math.max(320, panelW - 16)
    else return
    e.preventDefault()
    globalThis.localStorage?.setItem(PANEL_KEY, String(panelW))
  }

  // ── actions, keys, commands ───────────────────────────────────────────────────
  let copied = $state(false)
  function copyFen() {
    void navigator.clipboard
      ?.writeText(boardFen)
      .then(() => {
        copied = true
        setTimeout(() => (copied = false), 1500)
      })
      .catch(() => {})
  }
  const playIt = () => onplayfen(boardFen)
  const illegal = $derived(startError ?? refused)

  function onKey(e: KeyboardEvent) {
    if (commandMenu.open || illegal) return
    if (alreadyHandled(e)) return
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'c') {
      e.preventDefault()
      copyFen()
      return
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return
    switch (e.key) {
      case 'ArrowLeft':
        go('back')
        break
      case 'ArrowRight':
        go('forward')
        break
      case 'Home':
        go('start')
        break
      case 'End':
        go('end')
        break
      case 'f':
      case 'F':
        flip()
        break
      case 'Escape':
        if (onVar) leaveVariation()
        else return
        break
      default:
        return
    }
    e.preventDefault()
  }
  function provide(): Command[] {
    if (illegal) return []
    const out: Command[] = []
    if (onVar) out.push({ id: 'leave', group: 'Actions', label: 'Back to the main line', kbd: 'Esc', run: leaveVariation })
    out.push({ id: 'play', group: 'Actions', label: 'Play it vs Stockfish', run: playIt })
    out.push({ id: 'flip', group: 'Actions', label: 'Flip the board', kbd: 'F', run: flip })
    out.push({ id: 'fen', group: 'Actions', label: 'Copy the position as FEN', kbd: '⌘⇧C', run: copyFen })
    if (tree.nodes.size) out.push({ id: 'clear-vars', group: 'Actions', label: 'Clear variations', run: clearVariations })
    return out
  }

  let cleanups: (() => void)[] = []
  onMount(() => {
    cleanups.push(live.attach(), registerCommands('analyse', provide))
    if (initialMoves?.length) void playUcis(initialMoves).then(() => setPlace(onMain(0)))
    api
      .engineStatus()
      .then((s) => (engineOk = s.ok))
      .catch(() => (engineOk = false))
  })
  onDestroy(() => cleanups.forEach((f) => f()))
</script>

<svelte:window onkeydown={onKey} />

<div class="review">
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onback}>{backLabel}</button>
      <span class="sep" aria-hidden="true">/</span>
      <span class="title">{title}</span>
    </div>
    {#if !illegal}
      <div class="actions">
        <span class="tomove"><span class="dot {turnColor}" aria-hidden="true"></span>{sideToMove(boardFen)} to move</span>
        <Button variant="quiet" onclick={copyFen}>{copied ? 'Copied' : 'Copy FEN'}</Button>
        <Button onclick={playIt} disabled={!!endHere}>Play it vs Stockfish</Button>
        <Button kbd="F" onclick={flip}>Flip</Button>
      </div>
    {/if}
  </header>

  {#if illegal}
    <div class="illegal">
      <EmptyState
        tone="error"
        sentence="This position cannot be analysed."
        sub={illegal}
        action={{ label: `Back to ${backLabel}`, run: onback }}
      />
      <code class="fen">{startFen}</code>
    </div>
  {:else}
    <div class="body">
      <section class="board-col" aria-label="Board" bind:this={section}>
        <div class="col" style:width="{boardPx + 20}px">
          <div class="strip barpad">
            <PlayerStrip name={top === 'white' ? 'White' : 'Black'} note={turnColor === top ? 'To move' : null} />
          </div>
          <div class="row">
            <div class="bar" class:flip={orientation === 'black'} role="img" aria-label={wp === null ? 'No evaluation yet' : `White's chances ${Math.round(wp * 100)} percent`}>
              <span class="dark" style:height="{wp === null ? 50 : (1 - wp) * 100}%"></span>
            </div>
            <div class="board" style:width="{boardPx}px">
              <Board
                bind:this={boardEl}
                fen={boardFen}
                {lastMove}
                {turnColor}
                movableColor={turnColor}
                {dests}
                {check}
                {orientation}
                onmove={onBoardMove}
              />
            </div>
          </div>
          <div class="strip barpad">
            <PlayerStrip name={bottom === 'white' ? 'White' : 'Black'} note={turnColor === bottom ? 'To move' : null} />
          </div>
          <div class="nav barpad">
            <div class="btns">
              <button type="button" aria-label={onVar ? 'Back to the main line' : 'Start'} onclick={() => go('start')}>|‹</button>
              <button type="button" aria-label="Previous move" onclick={() => go('back')}>‹</button>
              <button type="button" aria-label="Next move" onclick={() => go('forward')}>›</button>
              <button type="button" aria-label={onVar ? 'End of the variation' : 'End'} onclick={() => go('end')}>›|</button>
            </div>
            {#if onVar}
              <button type="button" class="leave" title="Esc" onclick={leaveVariation}>Back to the main line</button>
            {/if}
            <div class="where">
              {#if curMove}<span class="cm" class:var={onVar}>{curMove}</span>{/if}
              {#if onVar}<span>Variation, {vat} of {vpath.length}</span>{:else}<span>{cur} of {main.length}</span>{/if}
            </div>
          </div>
        </div>
      </section>

      <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
      <div
        class="split"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize board and panel"
        aria-valuenow={panelW}
        aria-valuemin={320}
        aria-valuemax={640}
        tabindex="0"
        onpointerdown={startDrag}
        onkeydown={splitKey}
      >
        <span class="line"></span><span class="grip"></span>
      </div>

      <aside style:flex-basis="{panelW}px" aria-label="Analysis">
        <div class="head"><h2>Moves</h2></div>
        <EngineLinesPanel
          rows={engine.rows}
          status={engine.status}
          ply={base + plyHere}
          startsWhite={true}
          depth={engine.depth}
          live={engine.depth !== null}
          onpick={(ucis) => void playUcis(ucis)}
        />
        <div class="scroll list" bind:this={list}>
          {#if main.length === 0 && tree.nodes.size === 0 && !endHere}
            <p class="hint">Play a move on the board, or click a move in an engine line.</p>
          {:else if main.length || tree.nodes.size}
            <MoveGrid {rows} selectedPly={varNode ? null : cur > 0 ? cur - 1 : null} lines={varLines} selectedNode={varNode?.id ?? null} {base} onjump={(p) => setPlace(onMain(p))} onnode={showNode} />
          {/if}
          <p class="from"><span>From</span> <code>{startFen}</code></p>
        </div>
      </aside>
    </div>
  {/if}
</div>

<style>
  .review {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  header {
    position: relative;
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

  .sep {
    color: var(--disabled);
  }

  .title {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 6px;
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

  .barpad {
    padding-left: 20px;
  }

  .row {
    display: flex;
    gap: 10px;
  }

  .bar {
    width: 10px;
    border-radius: 2px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: var(--text);
  }

  .bar.flip {
    flex-direction: column-reverse;
  }

  .bar .dark {
    background: #3a3b42;
    transition: height 160ms ease;
  }

  .nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 10px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }

  .nav.barpad {
    margin-left: 20px;
    padding-left: 0;
  }

  .btns {
    display: flex;
    gap: 4px;
  }

  .btns button {
    width: 32px;
    height: 30px;
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    color: var(--text-2);
    cursor: pointer;
    font: var(--body);
  }

  .btns button:hover {
    color: var(--text);
    background: var(--surface);
  }

  .btns button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }

  .leave {
    margin-left: auto;
    height: 30px;
    padding: 0 10px;
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    color: var(--text);
    font: var(--body);
    cursor: pointer;
  }

  .leave:hover {
    background: var(--surface);
  }

  .leave:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }

  .cm.var {
    color: var(--text-2);
  }

  .where {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-3);
  }

  .cm {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    font-weight: 500;
  }

  .split {
    flex: none;
    width: 9px;
    margin: 0 -4px;
    position: relative;
    z-index: 1;
    cursor: col-resize;
    touch-action: none;
  }

  .split .line {
    position: absolute;
    left: 4px;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--border);
  }

  .split .grip {
    position: absolute;
    left: 2px;
    top: 50%;
    width: 5px;
    height: 32px;
    margin-top: -16px;
    border-radius: 3px;
    background: var(--border-control);
    opacity: 0.7;
  }

  .split:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }

  aside {
    flex: 0 1 420px;
    min-width: 320px;
    min-height: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
  }

  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border-control) transparent;
  }

  .pad {
    padding: 16px 20px 18px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .split:hover .grip,
  .split:focus-visible .grip {
    opacity: 1;
    background: #3a3b42;
  }

  .tomove {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-right: 8px;
    color: var(--text-2);
    font: var(--secondary);
  }
  .tomove .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px var(--border-control);
  }
  .tomove .dot.white {
    background: var(--text);
  }
  .tomove .dot.black {
    background: #3a3b42;
  }
  .head {
    flex: none;
    display: flex;
    align-items: center;
    height: var(--tab-height);
    padding: 0 20px;
    border-bottom: 1px solid var(--border);
  }
  .head h2 {
    margin: 0;
    font: var(--body);
    font-weight: 500;
  }
  .list {
    padding: 8px 12px 16px;
  }
  .hint {
    margin: 6px 8px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .from {
    margin: 16px 8px 0;
    color: var(--text-3);
    font: var(--secondary);
    overflow-wrap: anywhere;
  }
  .from code {
    font-family: inherit;
    color: var(--text-2);
    user-select: text;
  }
  .illegal {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 40px;
  }
  .illegal :global(> *:first-child) {
    width: min(520px, 100%);
  }
  .illegal .fen {
    color: var(--text-3);
    font: var(--secondary);
    user-select: text;
    overflow-wrap: anywhere;
    max-width: 520px;
  }
</style>
