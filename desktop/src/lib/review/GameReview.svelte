<script lang="ts">
  /**
   * Review, rebuilt (UI-BUILD B1–B6; DESIGN.md "Review: report", "Review: moves", rulings
   * 2–7, 9, 11). The frame: header with breadcrumb, Flip, Analyse again (depth menu) and
   * overflow; the board filling its column between the player strips, with the eval bar and
   * the move navigator; a resizable split; the panel with the Report and Moves tabs.
   */
  import { onDestroy, onMount } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import { uciOf, type PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import PlayerStrip from '../ui/PlayerStrip.svelte'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import ReportTab from './ReportTab.svelte'
  import MovesTab from './MovesTab.svelte'
  import DepthMenu from './DepthMenu.svelte'
  import {
    api,
    sidecar,
    type AnalysisPlyEvent,
    type GameDetail,
    type GameReport,
    type MoveJudgedEvent,
    type ReportMoment,
    type ReviewExtras,
  } from '../api'
  import { clockText, judgeOffline, timeControlText, canTry, type AnalysedReport, type TryVerdict } from '../report'
  import { registerCommands, commandMenu, parseMoveQuery, type Command } from '../shell/commands.svelte'
  import { QUALITY, isQualityClass } from '../ui/moveQuality'
  import { alreadyHandled } from '../ui/keyTargets'
  import { BETA } from '../build'
  import {
    clocksAt, gameMeta, materialSeries, moveLabel, players, sideOfPly, toMoveAt, type Side,
  } from './reviewModel'
  import { emptyTree, type NodeId, type VarTree } from '../variations'
  import {
    applyMoves, linesByRoot, nodeAt, nodePly, onMain, onVariation, placeFen, placeOn, placeUci, step,
    type MainMove, type Place, type Step,
  } from './explore'
  import { liveRows, liveWp, positionEnd, storedRows, type LinesStatus } from './engineLines'
  import { LiveLines } from './liveLines.svelte'

  interface Props {
    gameId: number
    ply?: number | null
    /** opened from Home's "Retry a moment": start Try it or Show the best move at `ply`;
     *  from Play when a game ends: 'analyse' starts the depth-14 analysis if there is none */
    action?: 'try' | 'best' | 'analyse' | null
    onback: () => void
    onsettings: () => void
  }
  let { gameId, ply = null, action = null, onback, onsettings }: Props = $props()
  let actionDone = false

  // ── data ────────────────────────────────────────────────────────────────
  let game = $state<GameDetail | null>(null)
  let report = $state<GameReport | null>(null)
  let extras = $state<ReviewExtras | null>(null)
  let loadError = $state<string | null>(null)
  let engineOk = $state(false)
  /** RUNS-DEPTH: the run shown; null = the deepest complete run (the sidecar's default) */
  let runId = $state<number | null>(null)

  async function load(keepPosition = false) {
    loadError = null
    try {
      const want = runId
      const [g, r, x] = await Promise.all([
        api.getGame(gameId, want),
        api.gameReport(gameId, want),
        api.reviewExtras(gameId, want).catch(() => null),
      ])
      game = g
      report = r
      extras = x
      if (!keepPosition) cur = ply !== null && ply !== undefined ? Math.min(g.plies.length, ply + 1) : 0
      if (g.playerColor === 'black') orientation = 'black'
      if (action === 'analyse' && !actionDone && !r.analysed) {
        actionDone = true
        api
          .engineStatus()
          .then((s) => {
            if (s.ok) void analyse(14)
          })
          .catch(() => {})
      }
      if ((action === 'try' || action === 'best') && !actionDone && r.analysed && ply !== null) {
        actionDone = true
        const m = r.moments.shown.find((x) => x.ply === ply)
        if (m) {
          openPly = m.ply
          if (action === 'try') startTry(m)
          else showBest(m)
        }
      }
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    }
  }

  const analysed = $derived(report && report.analysed ? (report as AnalysedReport) : null)
  const n = $derived(game?.plies.length ?? 0)
  const startsWhite = $derived(!game || !game.startFen.includes(' b '))
  const ppl = $derived(game ? players(game) : null)
  const names = $derived<Record<Side, string>>({
    white: ppl?.white.name ?? 'White',
    black: ppl?.black.name ?? 'Black',
  })
  const you = $derived<Side | null>(game?.playerColor ?? null)
  const material = $derived(game ? materialSeries(game) : [])
  const byPly = $derived(new Map((game?.analysis?.moves ?? []).map((m) => [m.ply, m])))

  // ── position ─────────────────────────────────────────────────────────────
  let cur = $state(0)
  let orientation = $state<'white' | 'black'>('white')
  let tab = $state<'report' | 'moves'>('report')
  let openPly = $state<number | null>(null)
  /** "Flag this" on the Moves tab's explanation is open (⌘K "Flag this move", BETA-4 B) */
  let flagOpen = $state(false)

  function jump(position: number) {
    if (trying) stopTry(false)
    vpath = []
    vat = 0
    cur = Math.max(0, Math.min(n, position))
  }

  // ── exploring (UI-BUILD-3 C): moves played on the board become variations ──────
  // The tree keeps every move explored while this game is open (nothing removes one but
  // "Clear variations"); `vpath`/`vat` say which variation move is on the board.
  let tree = $state<VarTree>(emptyTree())
  let vpath = $state<NodeId[]>([])
  let vat = $state(0)
  const place = $derived<Place>({ cur, path: vpath, at: vat })
  const onVar = $derived(onVariation(place))
  const varNode = $derived(nodeAt(tree, place))
  const mainMoves = $derived<MainMove[]>((game?.plies ?? []).map((p) => ({ uci: p.uci, san: p.san, fen: p.fen })))
  const varLines = $derived(linesByRoot(tree))
  /** bumped on every move of the board, so a probe that returns late does not move it */
  let navSeq = 0
  function setPlace(p: Place) {
    navSeq++
    cur = p.cur
    vpath = p.path
    vat = p.at
  }
  function go(how: Step) {
    if (trying) stopTry(false)
    setPlace(step(place, how, n))
  }
  function leaveVariation() {
    if (onVar) setPlace(onMain(cur))
  }
  function clearVariations() {
    tree = emptyTree()
    leaveVariation()
  }
  function showNode(id: NodeId) {
    if (trying) stopTry(false)
    const p = placeOn(tree, id)
    if (p) setPlace(p)
  }
  /** Play UCI moves from the board's position: each checked and named by the sidecar
   *  (probe_move, board truth), then placed: the game's own next move steps along the game,
   *  anything else is a variation. A line clicked in the engine lines plays up to its move. */
  async function playUcis(ucis: string[]) {
    if (!game) return
    const seq = navSeq
    let from = placeFen(tree, mainMoves, game.startFen, place)
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
    const s = applyMoves({ tree, main: mainMoves, place }, moves, false)
    tree = s.tree
    // The board moved while the sidecar answered: keep the moves, not the cursor.
    if (navSeq !== seq) return
    setPlace(s.place)
    if (onVariation(s.place) && tab !== 'moves') tab = 'moves'
  }

  const fenAt = (p: number) => (p === 0 ? game!.startFen : game!.plies[p - 1].fen)
  const positionFen = $derived(game ? fenAt(cur) : '8/8/8/8/8/8/8/8 w - - 0 1')

  // ── Try it (report.ts's judging and wording, unchanged) ───────────────────
  let trying = $state<ReportMoment | null>(null)
  let verdict = $state<TryVerdict | null>(null)
  let tryFen = $state<string | null>(null)
  let tryLast = $state<[Key, Key] | null>(null)
  let tryToken = -1

  function startTry(m: ReportMoment) {
    setPlace(onMain(m.ply))
    trying = m
    verdict = null
    tryFen = null
    tryLast = null
    openPly = m.ply
    tab = 'report'
    shapes = null
  }
  function retryTry() {
    verdict = null
    tryFen = null
    tryLast = null
  }
  function stopTry(advance = true) {
    const m = trying
    trying = null
    verdict = null
    tryFen = null
    tryLast = null
    if (m && advance) cur = m.ply + 1
  }
  const tryDests = $derived.by(() => {
    const dests = new Map<Key, Key[]>()
    if (!trying || tryFen || !game) return dests
    const c = new Chess(positionFen)
    for (const mv of c.moves({ verbose: true })) {
      const list = dests.get(mv.from as Key) ?? []
      list.push(mv.to as Key)
      dests.set(mv.from as Key, list)
    }
    return dests
  })
  async function onBoardMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    const m = trying
    if (!m) return onExploreMove(orig, dest, promo)
    if (tryFen) return
    const c = new Chess(positionFen)
    let mv
    try {
      // a promotion carries the piece chosen in the board's picker (UI-BUILD-4 D)
      mv = c.move({ from: orig as Square, to: dest as Square, promotion: promo })
    } catch {
      boardEl?.sync()
      return
    }
    const uci = mv.from + mv.to + (mv.promotion ?? '')
    tryFen = c.fen()
    tryLast = [orig, dest]
    if (!engineOk) {
      verdict = judgeOffline(m, uci, mv.san)
      return
    }
    verdict = { kind: 'judging' }
    try {
      tryToken = (await api.judgeMove(positionFen, uci)).token
    } catch (e) {
      verdict = { kind: 'error', message: e instanceof Error ? e.message : String(e) }
    }
  }
  const onJudged = (d: Record<string, unknown>) => {
    const e = d as unknown as MoveJudgedEvent
    if (!trying || e.token !== tryToken) return
    if (e.error) {
      verdict = { kind: 'error', message: e.error }
      return
    }
    verdict = e.accepted
      ? { kind: 'good', san: e.san!, bestSan: e.bestSan ?? null, exact: e.uci === e.bestUci }
      : { kind: 'not-it', san: e.san!, bestSan: e.bestSan!, loss: e.loss! }
  }

  // ── Show the best move: an arrow on the position before the moment ────────
  let shapes = $state<{ position: number; list: DrawShape[] } | null>(null)
  function showBest(m: ReportMoment) {
    if (trying) stopTry(false)
    if (!m.bestUci) return
    setPlace(onMain(m.ply))
    shapes = {
      position: m.ply,
      list: [{ orig: m.bestUci.slice(0, 2) as Key, dest: m.bestUci.slice(2, 4) as Key, brush: 'green' }],
    }
  }

  // ── the board ────────────────────────────────────────────────────────────
  const boardFen = $derived(tryFen ?? varNode?.fen ?? positionFen)
  const lastMove = $derived.by((): [Key, Key] | null => {
    if (tryLast) return tryLast
    if (!game) return null
    const u = placeUci(tree, mainMoves, place)
    return u ? [u.slice(0, 2) as Key, u.slice(2, 4) as Key] : null
  })
  const badge = $derived.by(() => {
    if (trying || onVar || !lastMove || cur === 0) return null
    const a = byPly.get(cur - 1)
    return a && isQualityClass(a.classification) ? { square: lastMove[1], cls: a.classification } : null
  })
  const check = $derived(
    tryFen || onVar ? new Chess(boardFen).inCheck() : !!(game && cur > 0 && game.plies[cur - 1].check),
  )
  /** Exploring: any legal move on the board, except while a moment is being tried. */
  const exploreDests = $derived.by(() => {
    const dests = new Map<Key, Key[]>()
    if (trying || !game) return dests
    let c: Chess
    try {
      c = new Chess(boardFen)
    } catch {
      return dests
    }
    for (const mv of c.moves({ verbose: true })) {
      const list = dests.get(mv.from as Key) ?? []
      list.push(mv.to as Key)
      dests.set(mv.from as Key, list)
    }
    return dests
  })
  let boardEl: Board | undefined = $state()
  function onExploreMove(orig: Key, dest: Key, promo?: PromotionPiece) {
    void playUcis([uciOf(orig, dest, promo)])
  }
  const turnColor = $derived<'white' | 'black'>(boardFen.split(' ')[1] === 'b' ? 'black' : 'white')

  // the board fills its column
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  const hasBar = $derived(!!analysed)
  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      // the bar does not count: it takes its 20 px from the column's 28 px side padding, so the
      // board keeps its size when the analysis arrives. (It counted, but this callback ran before
      // the game loaded in Chromium and after it in WebKit, so the two drew 720 and 704 px boards
      // at 1440 x 940; UI-BUILD-4 E. Chromium's 720 is the mockup's.)
      const w = r.width - 56
      const h = r.height - 44 - 72 - 53
      // a multiple of 8: chessground draws whole-pixel squares, so the strips, bar and
      // navigator line up with the board drawn (UI-BUILD-4 C)
      boardPx = Math.max(240, Math.floor((Math.min(w, h)) / 8) * 8)
    })
    if (section) ro.observe(section)
    return () => ro.disconnect()
  })

  // ── live engine lines (a variation, or a position no stored line covers) ─────────
  const live = new LiveLines()
  const storedHere = $derived(!onVar && (byPly.get(cur)?.lines.length ?? 0) > 0)
  const endHere = $derived(positionEnd(boardFen))
  /** the position wants a live search: not stored, not over, an engine to ask, no Try */
  const wantLive = $derived(!!game && engineOk && !trying && !storedHere && !endHere)
  $effect(() => {
    if (wantLive && (onVar || tab === 'moves')) live.request(boardFen)
  })
  const liveNow = $derived(wantLive ? live.state(boardFen) : null)
  /** The eval bar on a variation: the live score, held at the last one known while the
   *  next position is searched (so the bar does not jump to the middle and back). */
  let heldWp: number | null = null
  const varWp = $derived.by(() => {
    if (!onVar) return null
    if (endHere === 'Checkmate.') return turnColor === 'white' ? 0 : 1
    const v = liveNow?.kind === 'done' ? liveWp(liveNow.ev) : null
    if (v !== null) heldWp = v
    return v ?? heldWp
  })
  const wp = $derived(onVar ? varWp : analysed ? (analysed.series[cur] ?? null) : null)

  const engine = $derived.by((): { rows: ReturnType<typeof liveRows>; status: LinesStatus; depth: number | null; live: boolean; ply: number } => {
    const ply = onVar && varNode ? nodePly(tree, varNode.id) + 1 : cur
    const base = { rows: [], depth: null, live: false, ply }
    if (trying && (verdict === null || verdict.kind === 'judging'))
      return { ...base, status: { kind: 'note', text: 'Hidden while you try the move.' } }
    if (storedHere && game)
      return { ...base, rows: storedRows(game, byPly, cur), status: { kind: 'lines' }, depth: analysed?.basis.depth ?? null }
    if (endHere) return { ...base, status: { kind: 'note', text: endHere } }
    if (!engineOk)
      return game?.analysis && !onVar
        ? { ...base, status: { kind: 'note', text: 'No stored lines for this position.' } }
        : { ...base, status: { kind: 'no-engine', onsettings } }
    const s = liveNow
    if (s?.kind === 'done')
      return { ...base, rows: liveRows(s.ev), status: { kind: 'lines' }, depth: s.ev.depth ?? null, live: true }
    if (s?.kind === 'error' || s?.kind === 'illegal')
      return { ...base, status: { kind: 'error', text: s.message, retry: () => live.retry(boardFen) } }
    return { ...base, status: { kind: 'pending' } }
  })
  const clocks = $derived(
    extras && extras.clock.clocks.length
      ? clocksAt(extras.clock.clocks, extras.clock.base, cur, startsWhite)
      : null,
  )
  const toMove = $derived(toMoveAt(cur, startsWhite))
  const top = $derived<Side>(orientation === 'white' ? 'black' : 'white')
  const bottom = $derived<Side>(orientation)

  // ── the split ───────────────────────────────────────────────────────────
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

  // ── analysis (Analyse again, and the empty state's Analyse) ───────────────
  let depthMenu = $state(false)
  let overflow = $state(false)
  let run = $state<{ state: 'running' | 'error'; done: number; total: number; depth: number; message?: string } | null>(null)
  let pendingRun: number | null = null
  async function analyse(depth: number) {
    depthMenu = false
    try {
      const r = await api.analyzeGame(gameId, depth)
      pendingRun = r.runId
      run = { state: 'running', done: 0, total: n, depth: r.depth }
    } catch (e) {
      run = { state: 'error', done: 0, total: n, depth, message: e instanceof Error ? e.message : String(e) }
    }
  }
  function showRun(id: number) {
    if (game?.analysis?.runId === id) return
    if (trying) stopTry(false)
    runId = id
    void load(true)
  }
  async function cancelAnalysis() {
    await api.cancelAnalysis().catch(() => {})
    run = null
  }
  const onPly = (d: Record<string, unknown>) => {
    const e = d as unknown as AnalysisPlyEvent
    if (e.gameId !== gameId) return
    run = { state: 'running', done: e.ply + 1, total: e.total, depth: run?.depth ?? 14 }
  }
  const onDone = (d: Record<string, unknown>) => {
    if ((d as { gameId?: number }).gameId !== gameId) return
    run = null
    // show the run just finished (an Analyse again at 14 beside a kept 18 shows the 14)
    if (pendingRun !== null) runId = pendingRun
    pendingRun = null
    void load(true)
  }
  const onCancelled = (d: Record<string, unknown>) => {
    if ((d as { gameId?: number }).gameId === gameId) run = null
  }
  const onError = (d: Record<string, unknown>) => {
    if (typeof d.fen === 'string') return // a live position's failure: the engine lines show it
    if ((d as { gameId?: number }).gameId !== undefined && (d as { gameId?: number }).gameId !== gameId) return
    run = { state: 'error', done: run?.done ?? 0, total: n, depth: run?.depth ?? 14, message: String((d as { message?: string }).message ?? 'unknown error') }
  }

  // ── commands, keys ──────────────────────────────────────────────────────
  function copyFen() {
    void navigator.clipboard?.writeText(boardFen).catch(() => {})
  }
  function flip() {
    orientation = orientation === 'white' ? 'black' : 'white'
  }
  function nextBlunder() {
    if (!game?.analysis) return
    const next = game.analysis.moves.find((m) => m.ply >= cur && m.classification === 'blunder')
    if (next) jump(next.ply + 1)
  }
  /** The moment T tries: the one open in the report, else the user's first one at or
   *  after the board's position, else their first. */
  const tryTarget = $derived.by((): ReportMoment | null => {
    if (!analysed) return null
    const mine = analysed.moments.shown.filter((m) => canTry(m, engineOk))
    return (
      mine.find((m) => m.ply === openPly) ??
      mine.find((m) => m.ply >= cur - 1) ??
      mine[0] ??
      null
    )
  })
  function describeMove(p: number): { detail: string; cls: string | null } {
    const a = byPly.get(p)
    const side = sideOfPly(p, startsWhite)
    const who = side === you ? 'you' : names[side]
    if (!a || !isQualityClass(a.classification)) return { detail: who, cls: null }
    const name = QUALITY[a.classification].name.toLowerCase()
    const art = ['inaccuracy', 'excellent'].includes(a.classification) ? 'an' : 'a'
    const word = ['brilliant', 'great', 'book'].includes(a.classification) ? `${art} ${name} move` : ['best', 'excellent', 'good'].includes(a.classification) ? name : `${art} ${name}`
    return { detail: `${who}, ${word}`, cls: a.classification }
  }
  function provide(query: string): Command[] {
    if (!game) return []
    const out: Command[] = []
    const mq = parseMoveQuery(query)
    const plies: number[] = []
    if (mq) {
      for (const side of ['white', 'black'] as Side[]) {
        if (mq.side && mq.side !== side) continue
        const p = (mq.move - 1) * 2 + (side === 'white' ? 0 : 1) - (startsWhite ? 0 : 1)
        if (p >= 0 && p < n) plies.push(p)
      }
    } else if (!query.trim() && analysed) {
      plies.push(...analysed.moments.shown.map((m) => m.ply))
    }
    for (const p of plies) {
      const d = describeMove(p)
      out.push({
        id: `go-${p}`,
        group: 'Go to move',
        label: moveLabel(p, game.plies[p].san, startsWhite),
        detail: d.detail,
        icon: (d.cls ?? undefined) as never,
        run: () => {
          jump(p + 1)
        },
      })
    }
    if (tryTarget) {
      const t = tryTarget
      const lbl = moveLabel(t.ply, '', startsWhite).trim()
      out.push({ id: 'try', group: 'Actions', label: `Try ${lbl} yourself`, kbd: 'T', run: () => startTry(t) })
    }
    if (game.analysis?.moves.some((m) => m.classification === 'blunder'))
      out.push({ id: 'blunder', group: 'Actions', label: 'Next blunder', kbd: 'B', run: nextBlunder })
    if (onVar) out.push({ id: 'leave', group: 'Actions', label: 'Back to the game', kbd: 'Esc', run: leaveVariation })
    if (tree.nodes.size) out.push({ id: 'clear-vars', group: 'Actions', label: 'Clear variations', run: clearVariations })
    // FLAG-RESTORE (DESIGN.md "Owner rulings, 2026-11-21", 2): beta builds, a main-line move selected
    if (BETA && game.analysis && cur > 0 && !onVar) {
      const p = cur - 1
      out.push({
        id: 'flag',
        group: 'Actions',
        label: 'Flag this move',
        detail: moveLabel(p, game.plies[p].san, startsWhite),
        run: () => {
          tab = 'moves'
          flagOpen = true
        },
      })
    }
    out.push({ id: 'flip', group: 'Actions', label: 'Flip the board', kbd: 'F', run: flip })
    out.push({ id: 'fen', group: 'Actions', label: 'Copy the position as FEN', kbd: '⌘⇧C', run: copyFen })
    out.push({ id: 'again', group: 'Actions', label: 'Analyse again', run: () => (depthMenu = true) })
    for (const r of game?.runs ?? []) {   // RUNS-DEPTH: switch to a kept run
      if (r.id !== game?.analysis?.runId && r.engine === 'Stockfish')
        out.push({ id: `run-${r.id}`, group: 'Actions', label: `Show the depth-${r.depth} analysis`, run: () => showRun(r.id) })
    }
    return out
  }

  function onKey(e: KeyboardEvent) {
    if (commandMenu.open || depthMenu) return
    // A focused chart, split handle or radiogroup already acted on the key (B6).
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
      case 't':
      case 'T':
        if (tryTarget) startTry(tryTarget)
        break
      case 'b':
      case 'B':
        nextBlunder()
        break
      case 'Escape':
        if (trying) stopTry(false)
        else if (overflow) overflow = false
        else if (onVar) leaveVariation()
        else return
        break
      default:
        return
    }
    e.preventDefault()
  }

  let unregister: (() => void) | null = null
  let detachLive: (() => void) | null = null
  onMount(() => {
    sidecar.on('analysis_ply', onPly)
    sidecar.on('analysis_done', onDone)
    sidecar.on('analysis_cancelled', onCancelled)
    sidecar.on('analysis_error', onError)
    sidecar.on('move_judged', onJudged)
    unregister = registerCommands('review', provide)
    detachLive = live.attach()
    api
      .engineStatus()
      .then((s) => (engineOk = s.ok))
      .catch(() => (engineOk = false))
    void load()
  })
  onDestroy(() => {
    sidecar.off('analysis_ply', onPly)
    sidecar.off('analysis_done', onDone)
    sidecar.off('analysis_cancelled', onCancelled)
    sidecar.off('analysis_error', onError)
    sidecar.off('move_judged', onJudged)
    unregister?.()
    detachLive?.()
  })

  const meta = $derived.by(() => {
    if (!game) return []
    const out: string[] = []
    if (game.openingName) out.push(game.openingEco ? `${game.openingName} (${game.openingEco})` : game.openingName)
    const tc = analysed?.basis.timeControl ?? extras?.clock.timeControl ?? null
    const m = gameMeta(tc, game.speed, game.playedAt, timeControlText)
    if (m) out.push(m)
    if (analysed) out.push(`Depth ${analysed.basis.depth}`)
    return out
  })
  const curMove = $derived(
    varNode
      ? { label: moveLabel(nodePly(tree, varNode.id), varNode.san, startsWhite), cls: null }
      : game && cur > 0
        ? { label: moveLabel(cur - 1, game.plies[cur - 1].san, startsWhite), cls: byPly.get(cur - 1)?.classification ?? null }
        : null,
  )
  /** "Back to the game" names where it returns: the move the variation leaves from. */
  const branchLabel = $derived(game && cur > 0 ? moveLabel(cur - 1, game.plies[cur - 1].san, startsWhite) : 'the start')
</script>

<svelte:window onkeydown={onKey} />

<div class="review">
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onback}>Games</button>
      <span class="sep" aria-hidden="true">/</span>
      <span class="title">{game ? `${names.white} vs ${names.black}` : ''}</span>
    </div>
    <div class="actions">
      <Button kbd="F" onclick={flip}>Flip</Button>
      <Button ariaHaspopup="dialog" ariaExpanded={depthMenu} pressed={depthMenu} disabled={!engineOk || !game} onclick={() => (depthMenu = !depthMenu)}
        >{game?.analysis ? 'Analyse again' : 'Analyse'}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></Button
      >
      <Button ariaLabel="More actions" ariaHaspopup="menu" ariaExpanded={overflow} pressed={overflow} onclick={() => (overflow = !overflow)}>···</Button>
    </div>
    {#if depthMenu && game}
      <DepthMenu currentDepth={analysed?.basis.depth ?? null} plies={n} onanalyse={analyse} oncancel={() => (depthMenu = false)} />
    {/if}
    {#if overflow}
      <div class="over" role="menu">
        <button type="button" role="menuitem" onclick={() => { overflow = false; copyFen() }}>Copy the position as FEN</button>
        {#if tree.nodes.size}
          <button type="button" role="menuitem" onclick={() => { overflow = false; clearVariations() }}>Clear variations</button>
        {/if}
        <button type="button" role="menuitem" onclick={() => { overflow = false; commandMenu.open = true }}>Command menu <kbd>⌘K</kbd></button>
      </div>
    {/if}
  </header>

  <div class="body">
    <section class="board-col" aria-label="Board" bind:this={section}>
      {#if game}
        <div class="col" style:width="{boardPx + (hasBar ? 20 : 0)}px">
          <div class="strip" class:barpad={hasBar}>
            <PlayerStrip
              name={ppl![top].name}
              rating={ppl![top].rating}
              you={ppl![top].you}
              clock={clocks?.[top] != null ? clockText(clocks[top]!) : null}
              active={!!clocks && toMove === top}
            />
          </div>
          <div class="row">
            {#if hasBar}
              <div class="bar" class:flip={orientation === 'black'} role="img" aria-label={wp === null ? 'No evaluation' : `White's chances ${Math.round(wp * 100)} percent`}>
                <span class="dark" style:height="{wp === null ? 50 : (1 - wp) * 100}%"></span>
              </div>
            {/if}
            <div class="board" style:width="{boardPx}px">
              <Board
                bind:this={boardEl}
                fen={boardFen}
                {lastMove}
                {turnColor}
                movableColor={trying ? (tryFen ? null : turnColor) : turnColor}
                dests={trying ? tryDests : exploreDests}
                {check}
                {orientation}
                {badge}
                shapes={shapes && shapes.position === cur && !trying && !onVar ? shapes.list : []}
                onmove={onBoardMove}
              />
            </div>
          </div>
          <div class="strip" class:barpad={hasBar}>
            <PlayerStrip
              name={ppl![bottom].name}
              rating={ppl![bottom].rating}
              you={ppl![bottom].you}
              clock={clocks?.[bottom] != null ? clockText(clocks[bottom]!) : null}
              active={!!clocks && toMove === bottom}
            />
          </div>
          <div class="nav" class:barpad={hasBar}>
            <div class="btns">
              <button type="button" aria-label={onVar ? 'Back to the game' : 'Start'} onclick={() => go('start')}>|‹</button>
              <button type="button" aria-label="Previous move" onclick={() => go('back')}>‹</button>
              <button type="button" aria-label="Next move" onclick={() => go('forward')}>›</button>
              <button type="button" aria-label={onVar ? 'End of the variation' : 'End'} onclick={() => go('end')}>›|</button>
            </div>
            {#if onVar}
              <button type="button" class="leave" title="Esc" onclick={leaveVariation}>Back to the game</button>
            {/if}
            <div class="where">
              {#if curMove}
                <span class="cm" class:var={onVar}>{curMove.label}{#if curMove.cls}<MoveQualityIcon cls={curMove.cls} />{/if}</span>
              {/if}
              {#if onVar}<span>Variation, {vat} of {vpath.length}</span>{:else}<span>{cur} of {n}</span>{/if}
            </div>
          </div>
        </div>
      {/if}
    </section>

    <!-- A focusable separator is the ARIA splitter pattern: arrow keys resize. -->
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

    <aside style:flex-basis="{panelW}px" aria-label="Game report">
      <div class="tabs" role="tablist" aria-label="Panel">
        <button type="button" role="tab" aria-selected={tab === 'report'} onclick={() => (tab = 'report')}>Report</button>
        <button type="button" role="tab" aria-selected={tab === 'moves'} onclick={() => (tab = 'moves')}>Moves</button>
      </div>
      {#if game && (game.runs ?? []).length > 1}
        <div class="runs" role="group" aria-label="Analysis shown">
          <span class="rl">Depth</span>
          {#each game.runs as r (r.id)}
            {@const on = game.analysis?.runId === r.id}
            <button type="button" class:on aria-pressed={on} onclick={() => showRun(r.id)}>{r.engine === 'Stockfish' ? r.depth : 'Cloud'}</button>
          {/each}
          <span class="rn">Insights and Home use the depth-14 run.</span>
        </div>
      {/if}
      {#if loadError}
        <div class="pad">
          <EmptyState tone="error" sentence="This game could not be opened." sub={loadError} action={{ label: 'Back to games', run: onback }} />
        </div>
      {:else if !game || !report}
        <div class="pad"><EmptyState sentence="Opening the game…" /></div>
      {:else if tab === 'moves'}
        <MovesTab
          {game}
          series={analysed?.series ?? []}
          {names}
          {you}
          current={cur}
          {engine}
          playedCls={!onVar ? (byPly.get(cur)?.classification ?? null) : null}
          lines={varLines}
          selectedNode={varNode?.id ?? null}
          onjump={jump}
          onnode={showNode}
          onpick={(ucis) => void playUcis(ucis)}
          {runId}
          bind:flagOpen
        />
      {:else}
        <div class="scroll pad">
          {#if onVar}
            <EmptyState
              sentence="You are on a variation from {branchLabel}."
              sub="The report is about the game; the Moves tab shows the variation's engine lines."
              action={{ label: 'Back to the game', run: leaveVariation }}
            />
          {/if}
          {#if run?.state === 'running'}
            <EmptyState
              sentence="Analysing at depth {run.depth}: {run.done} of {run.total} moves."
              sub="You can keep reviewing; the report appears when it finishes."
              progress={run.total ? run.done / run.total : 0}
              action={{ label: 'Cancel', run: cancelAnalysis }}
            />
          {:else if run?.state === 'error'}
            <EmptyState tone="error" sentence="The analysis stopped." sub={run.message ?? null} action={{ label: 'Try again', run: () => analyse(run!.depth), primary: true }} />
          {/if}
          {#if analysed}
            <ReportTab
              {game}
              report={analysed}
              {extras}
              {names}
              {you}
              {meta}
              current={cur}
              {material}
              {engineOk}
              {trying}
              {verdict}
              {openPly}
              onjump={jump}
              ontoggle={(p) => (openPly = openPly === p ? null : p)}
              ontry={startTry}
              onstoptry={() => stopTry()}
              onretry={retryTry}
              onshowbest={showBest}
              oncounts={() => {
                tab = 'moves'
                queueMicrotask(() => document.getElementById('counts')?.scrollIntoView({ block: 'start' }))
              }}
            />
          {:else if !run}
            <div class="unan">
              <div class="head">
                <h1>{names.white} vs {names.black}</h1>
                <div class="meta">{#each meta as m (m)}<span>{m}</span>{/each}</div>
              </div>
              {#if engineOk}
                <EmptyState
                  sentence="This game has not been analysed yet."
                  sub="Every game is analysed at depth 14, so all your games compare."
                  action={{ label: 'Analyse at depth 14', run: () => analyse(14), primary: true }}
                />
              {:else}
                <EmptyState
                  sentence="Analysis needs Stockfish, and none was found."
                  sub="Choose a Stockfish binary in Settings, then analyse this game."
                  action={{ label: 'Open Settings', run: onsettings }}
                />
              {/if}
              {#each report.lines as l (l)}<p class="ctx">{l}</p>{/each}
            </div>
          {/if}
        </div>
      {/if}
    </aside>
  </div>
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
  .over {
    position: absolute;
    top: 44px;
    right: 16px;
    min-width: 220px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    padding: 6px;
    z-index: 20;
  }
  .over button {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 8px;
    background: none;
    border: 0;
    border-radius: var(--radius-control);
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .over button:hover {
    background: var(--raised);
  }
  .over kbd {
    font: var(--kbd);
    font-family: inherit;
    color: var(--text-3);
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
  .where {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-3);
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
  .split:hover .grip,
  .split:focus-visible .grip {
    opacity: 1;
    background: #3a3b42;
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
  .runs {
    flex: none;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 8px 20px;
    border-bottom: 1px solid var(--border);
    font: var(--secondary);
  }
  .runs .rl {
    color: var(--text-3);
    margin-right: 4px;
  }
  .runs button {
    min-width: 32px;
    height: 24px;
    padding: 0 8px;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text-2);
    font: var(--secondary);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .runs button:hover {
    background: var(--raised);
  }
  .runs button.on {
    background: var(--selected);
    color: var(--text);
    border-color: var(--selected);
  }
  .runs button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .runs .rn {
    margin-left: auto;
    color: var(--text-3);
  }
  .tabs {
    flex: none;
    display: flex;
    gap: 18px;
    padding: 0 20px;
    border-bottom: 1px solid var(--border);
    height: var(--tab-height);
    align-items: stretch;
  }
  .tabs button {
    background: none;
    border: 0;
    border-bottom: 1.5px solid transparent;
    padding: 0;
    color: var(--text-3);
    font: var(--body);
    cursor: pointer;
  }
  .tabs button[aria-selected='true'] {
    border-bottom-color: var(--text);
    color: var(--text);
    font-weight: 500;
  }
  .tabs button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
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
  .unan {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .unan h1 {
    margin: 0;
    font: var(--heading);
  }
  .unan .meta {
    margin-top: 3px;
    display: flex;
    flex-wrap: wrap;
    gap: 2px 14px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .ctx {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
