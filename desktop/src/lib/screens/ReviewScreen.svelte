<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Chess, type Square } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import type { PromotionRequest } from '../Board.svelte'
  import EvalBar from '../EvalBar.svelte'
  import EvalGraph from '../EvalGraph.svelte'
  import ReportPanel from '../ReportPanel.svelte'
  import FlagThis from '../FlagThis.svelte'
  import {
    bookTick,
    graphMarkers,
    judgeOffline,
    leadingGap,
    liveSeries,
    type AnalysedReport,
    type TryVerdict,
  } from '../report'
  import EngineLines from '../EngineLines.svelte'
  import { analysisDepth } from '../settings.svelte'
  import {
    api,
    sidecar,
    describeTermination,
    type ClaimText,
    type DescriptionText,
    type GameDetail,
    type MoveAnalysisInfo,
    type AnalysisPlyEvent,
    type AnalysisDoneEvent,
    type FenAnalyzedEvent,
    type MoveJudgedEvent,
    type ReportMoment,
  } from '../api'
  import {
    addMove,
    childrenOf,
    emptyTree,
    getNode,
    pathOnto,
    type NodeId,
    type VarNode,
    type VarTree,
  } from '../variations'
  import {
    CLASS_COLORS,
    CLASS_GLYPHS,
    CLASS_LABELS,
    whiteWp,
    evalLabel,
  } from '../classification'

  interface Props {
    gameId?: number | null
    fen?: string | null
    onback: () => void
    onplayfen: (fen: string) => void
  }
  let { gameId = null, fen = null, onback, onplayfen }: Props = $props()

  type Role = 'queen' | 'knight' | 'rook' | 'bishop'
  const ROLE_CHAR: Record<Role, string> = { queen: 'q', knight: 'n', rook: 'r', bishop: 'b' }
  const EMPTY_DESTS = new Map<Key, Key[]>()

  // ── state ────────────────────────────────────────────────────────────────
  let detail = $state<GameDetail | null>(null)
  let idx = $state(0) // 0 = start position, i = after ply i-1
  let analyses = $state<Record<number, MoveAnalysisInfo>>({})
  let accuracies = $state<{ white: number | null; black: number | null } | null>(null)
  let analyzing = $state<{ done: number; total: number } | null>(null)
  let analysisError = $state('')
  let loadError = $state('')
  // The game report (core/game_report.py). Computed by the sidecar on request from
  // the stored run, ~4 ms; refetched whenever a run completes, never stored.
  let report = $state<AnalysedReport | null>(null)
  // What the report can say before any analysis: the opening line, which needs the
  // book and not the engine.
  let prelim = $state<string[]>([])

  // ── Try it (slice 5) ──────────────────────────────────────────────────────
  // The board goes to the position before one of the user's moments, with nothing on
  // it that gives the answer away; the first move played from there is judged — live
  // when an engine exists, against the stored unique answer when not.
  let engineOk = $state(false)
  let trying = $state<ReportMoment | null>(null)
  let tryVerdict = $state<TryVerdict | null>(null)
  let tryToken = -1
  let tab = $state<'report' | 'moves'>('report')

  // ── exploration off whatever position is on the board ────────────────────
  const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  // live multipv engine analysis of the currently viewed position (both modes)
  let liveEval = $state<FenAnalyzedEvent | null>(null)
  let board = $state<Board>()
  // Every move the user has played from a position they were looking at, as a tree.
  // `activePath` is the one line currently on screen and `vIdx` the point along it;
  // playing from an earlier point branches, and the moves that were on screen stay in
  // the tree. Nothing here deletes a move — the only ways to lose one are the explicit
  // "Clear lines" button and leaving the screen.
  let tree = $state<VarTree>(emptyTree())
  let activePath = $state<NodeId[]>([])
  let vIdx = $state(0)
  let fenPromotion = $state<PromotionRequest | null>(null)
  let fenPending: { orig: Key; dest: Key } | null = null

  const fenMode = $derived(fen !== null)
  const plies = $derived(detail?.plies ?? [])
  const line = $derived.by<VarNode[]>(() => {
    const out: VarNode[] = []
    for (const id of activePath) {
      const n = getNode(tree, id)
      if (n) out.push(n)
    }
    return out
  })
  // Which mainline ply a branch leaves from. There is no mainline in FEN mode, so
  // everything roots at 0; in game review it is wherever the board was standing.
  const anchor = $derived(fenMode ? 0 : idx)
  const inVar = $derived(vIdx > 0)

  // ── current position ─────────────────────────────────────────────────────
  // `posFen` is always a real FEN — it feeds the engine, the probe, and chess.js.
  // `curFen` may instead be chessground's 'start' sentinel.
  const baseFen = $derived(
    fenMode ? fen! : idx === 0 ? (detail?.startFen ?? START_FEN) : plies[idx - 1].fen,
  )
  const posFen = $derived(inVar ? line[vIdx - 1].fen : baseFen)
  const curFen = $derived(
    inVar
      ? line[vIdx - 1].fen
      : fenMode
        ? fen!
        : idx === 0
          ? (detail?.startFen ?? 'start')
          : plies[idx - 1].fen,
  )
  const curChess = $derived.by(() => {
    try {
      return new Chess(posFen)
    } catch {
      return null
    }
  })
  const dests = $derived.by(() => {
    if (!curChess) return EMPTY_DESTS
    const map = new Map<Key, Key[]>()
    for (const m of curChess.moves({ verbose: true })) {
      const arr = map.get(m.from as Key) ?? []
      arr.push(m.to as Key)
      map.set(m.from as Key, arr)
    }
    return map
  })
  const orientation = $derived<'white' | 'black'>(
    fenMode ? 'white' : detail?.playerColor === 'black' ? 'black' : 'white',
  )
  const curPly = $derived(!fenMode && idx > 0 ? plies[idx - 1] : null)
  // From the FEN rather than ply parity, because a variation's parity depends on
  // where it branched and a game can start from a position with black to move.
  const turnColor = $derived<'white' | 'black'>(posFen.split(' ')[1] === 'b' ? 'black' : 'white')
  const lastMove = $derived.by<[Key, Key] | null>(() => {
    const u = inVar ? line[vIdx - 1].uci : (curPly?.uci ?? null)
    if (!u) return null
    return [u.slice(0, 2) as Key, u.slice(2, 4) as Key]
  })
  const check = $derived(
    inVar || fenMode ? (curChess?.inCheck() ?? false) : (curPly?.check ?? false),
  )
  // Off the mainline nothing about this position was ever stored, so there is no
  // classification and no explanation — only what the engine says about it now.
  const curMa = $derived(!fenMode && !inVar && idx > 0 ? (analyses[idx - 1] ?? null) : null)
  const openingText = $derived.by(() => {
    if (fenMode || inVar) return ''
    const o = curPly?.opening ?? null
    return o ? `${o.eco} · ${o.name}` : ''
  })
  // Names the branch point, so "back" says where it goes instead of just "back".
  const branchLabel = $derived.by(() => {
    if (idx === 0) return 'the start'
    const ply = plies[idx - 1]
    if (!ply) return 'the game'
    return `${Math.floor((idx - 1) / 2) + 1}${(idx - 1) % 2 === 0 ? '.' : '…'} ${ply.san}`
  })

  const shapes = $derived.by<DrawShape[]>(() => {
    // Trying a moment: no arrow may give the answer away.
    if (trying && !inVar) return []
    if (fenMode || inVar) {
      if (!liveEval?.bestUci) return []
      return [
        {
          orig: liveEval.bestUci.slice(0, 2) as Key,
          dest: liveEval.bestUci.slice(2, 4) as Key,
          brush: 'green',
        },
      ]
    }
    if (!curMa?.bestUci || curMa.isBook || curMa.bestUci === curMa.playedUci) return []
    // The played move is shown by the warm square highlight (lastMove); only
    // the best move gets an arrow here.
    return [
      {
        orig: curMa.bestUci.slice(0, 2) as Key,
        dest: curMa.bestUci.slice(2, 4) as Key,
        brush: 'green',
      },
    ]
  })

  const badge = $derived(
    !trying && curMa && lastMove ? { square: lastMove[1], cls: curMa.classification } : null,
  )

  // ── eval bar / graph ─────────────────────────────────────────────────────
  const hasAnalysis = $derived(Object.keys(analyses).length > 0 || fenMode)

  // Whether a ply was actually evaluated. Book-ness used to stand in for this,
  // but since F4a book plies are analysed like any other — what makes a ply
  // unshowable is a missing score, which is also true of pre-v6 rows.
  function isScored(ma: MoveAnalysisInfo | null | undefined): ma is MoveAnalysisInfo {
    return !!ma && (ma.scoreAfterCp !== null || ma.scoreAfterMate !== null)
  }

  const barWp = $derived.by<number | null>(() => {
    if (fenMode || inVar) {
      if (!liveEval) return null
      const ply = turnColor === 'white' ? 0 : 1 // reuse mover→white POV conversion
      return whiteWp(ply, liveEval.cp, liveEval.mate)
    }
    // nearest *scored* ply at or before idx
    for (let p = idx - 1; p >= 0; p--) {
      const ma = analyses[p]
      if (isScored(ma)) return whiteWp(p, ma.scoreAfterCp, ma.scoreAfterMate)
    }
    // The start position is even by definition, so 0.5 there is a real eval.
    return idx === 0 ? 0.5 : null
  })

  const barLabel = $derived.by(() => {
    if (fenMode || inVar) {
      if (!liveEval) return ''
      return evalLabel(turnColor === 'white' ? 0 : 1, liveEval.cp, liveEval.mate)
    }
    if (!isScored(curMa)) return ''
    return evalLabel(curMa.ply, curMa.scoreAfterCp, curMa.scoreAfterMate)
  })

  // The report's series once it exists; while a run streams in, the same rule
  // applied to the plies seen so far. Either way an unscored position draws nothing.
  const graphSeries = $derived(report ? report.series : liveSeries(plies.length, analyses))
  const graphMarks = $derived(report ? graphMarkers(report) : [])
  const graphGap = $derived(leadingGap(graphSeries))
  // Runs from before F4a left book moves unscored (63 % of games); they fill in
  // when the game is re-analysed, not through any bulk backfill (owner ruling 5).
  const gapIsBook = $derived(graphGap > 1 && analyses[0]?.isBook === true)
  const showGraph = $derived(!fenMode && (hasAnalysis || analyzing !== null))

  // ── data loading ─────────────────────────────────────────────────────────
  async function load() {
    if (fenMode) return // analysis is driven reactively by the effect below
    try {
      const d = await api.getGame(gameId!)
      detail = d
      idx = d.plies.length
      const map: Record<number, MoveAnalysisInfo> = {}
      for (const ma of d.analysis?.moves ?? []) map[ma.ply] = ma
      analyses = map
      accuracies = d.analysis
        ? { white: d.analysis.whiteAccuracy, black: d.analysis.blackAccuracy }
        : null
      tab = d.analysis ? 'report' : 'moves'
      void fetchReport()
      // Opening an unanalyzed game kicks off analysis immediately — no extra
      // click. The progress card streams plies in as they complete.
      if (d.analysis === null && d.plies.length > 0) {
        void startAnalysis()
      }
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    }
  }

  async function fetchReport() {
    const id = gameId
    if (id == null) return
    try {
      const r = await api.gameReport(id)
      if (id !== gameId) return
      report = r.analysed ? r : null
      prelim = r.analysed ? [] : r.lines
    } catch {
      // The report is an addition to the screen, not a precondition for it: the
      // move list, graph and board all work without it.
      report = null
    }
  }

  // ── analysis ─────────────────────────────────────────────────────────────
  async function startAnalysis() {
    analysisError = ''
    accuracies = null
    analyses = {}
    report = null
    analyzing = { done: 0, total: plies.length }
    try {
      // The Settings depth, as sync and "analyse pending" already pass. Without it
      // the sidecar fell back to ANALYSIS_DEPTH 18, the "Deep" preset: 57.0 s for
      // game 285 against 7.4 s at the default 14 (FIXPLAN RA-DEPTH).
      await api.analyzeGame(gameId!, analysisDepth.value)
    } catch (e) {
      analysisError = e instanceof Error ? e.message : String(e)
      analyzing = null
    }
  }

  async function cancelAnalysis() {
    await api.cancelAnalysis()
  }

  const onPly = (d: Record<string, unknown>) => {
    const e = d as unknown as AnalysisPlyEvent
    if (e.gameId !== gameId) return
    analyzing = { done: e.ply + 1, total: e.total }
    if (e.analysis) analyses[e.ply] = e.analysis
  }
  const onDone = (d: Record<string, unknown>) => {
    const e = d as unknown as AnalysisDoneEvent
    if (e.gameId !== gameId) return
    analyzing = null
    accuracies = { white: e.whiteAccuracy, black: e.blackAccuracy }
    void fetchReport()
  }
  const onCancelled = (d: Record<string, unknown>) => {
    if ((d as { gameId: number }).gameId !== gameId) return
    analyzing = null
  }
  const onError = (d: Record<string, unknown>) => {
    analysisError = String(d.message)
    analyzing = null
  }
  const onFenAnalyzed = (d: Record<string, unknown>) => {
    const e = d as unknown as FenAnalyzedEvent
    if (e.fen === posFen) liveEval = e
  }

  // ── exploring: play a move from wherever the board is ─────────────────────
  function onBoardMove(orig: Key, dest: Key) {
    const c = curChess
    if (!c) return
    const cands = c.moves({ square: orig as Square, verbose: true })
    if (cands.some((m) => m.to === dest && m.promotion)) {
      fenPending = { orig, dest }
      fenPromotion = { col: dest.charCodeAt(0) - 97, color: turnColor }
      return
    }
    void playMove(orig, dest, undefined)
  }

  function onBoardPromote(role: Role | null) {
    fenPromotion = null
    const pending = fenPending
    fenPending = null
    if (!pending) return
    if (role === null) {
      board?.sync()
      return
    }
    void playMove(pending.orig, pending.dest, ROLE_CHAR[role])
  }

  async function playMove(orig: Key, dest: Key, promo: string | undefined) {
    const uci = `${orig}${dest}${promo ?? ''}`
    const from = posFen
    const at = vIdx
    const root = anchor
    const parent = at === 0 ? null : activePath[at - 1]
    let probed
    try {
      probed = await api.probeMove(from, uci)
    } catch {
      board?.sync()
      return
    }
    if (!probed.legal) {
      board?.sync()
      return
    }
    const added = addMove(tree, parent, root, { uci, san: probed.san, fen: probed.fen })
    tree = added.tree
    // The board may have moved while the probe was in flight. The node is kept
    // either way — only the cursor is held back, since moving it would drop the
    // user somewhere they did not click.
    if (vIdx !== at || anchor !== root) return
    showBranch(added.id)
    if (trying && at === 0 && root === trying.ply && tryVerdict === null) {
      void submitTry(from, uci, probed.san)
    }
  }

  function startTry(m: ReportMoment) {
    seek(m.ply) // the position before the move
    trying = m
    tryVerdict = null
  }

  function retryTry() {
    leaveVariation()
    tryVerdict = null
  }

  function stopTry() {
    const m = trying
    trying = null
    tryVerdict = null
    if (m) seek(m.ply + 1)
  }

  async function submitTry(fen: string, uci: string, san: string) {
    const m = trying
    if (!m) return
    if (!engineOk) {
      tryVerdict = judgeOffline(m, uci, san)
      return
    }
    tryVerdict = { kind: 'judging' }
    try {
      tryToken = (await api.judgeMove(fen, uci)).token
    } catch (e) {
      tryVerdict = { kind: 'error', message: e instanceof Error ? e.message : String(e) }
    }
  }

  const onJudged = (d: Record<string, unknown>) => {
    const e = d as unknown as MoveJudgedEvent
    if (!trying || e.token !== tryToken) return
    if (e.error) {
      tryVerdict = { kind: 'error', message: e.error }
      return
    }
    tryVerdict = e.accepted
      ? { kind: 'good', san: e.san!, bestSan: e.bestSan ?? null, exact: e.uci === e.bestUci }
      : { kind: 'not-it', san: e.san!, bestSan: e.bestSan!, loss: e.loss! }
  }

  /**
   * Play a prefix of an engine line onto the board as a variation.
   *
   * One probe per move, chained, because each position is the answer to the one
   * before it. A click re-probes the whole prefix, moves already in the tree
   * included; measured at 0.08 ms per move through the real stdio path, so a
   * six-move click is 0.479 ms median against the ~545 ms search that produced
   * the line (2026-09-30). Nothing here needs a batch RPC or a position cache.
   *
   * `addMove` returns the existing node for a move already there, so re-probing
   * cannot duplicate anything.
   */
  async function enterLine(ucis: string[]) {
    const at = vIdx
    const root = anchor
    let parent = at === 0 ? null : activePath[at - 1]
    let from = posFen
    const chain: NodeId[] = []
    for (const uci of ucis) {
      let probed
      try {
        probed = await api.probeMove(from, uci)
      } catch {
        break
      }
      if (!probed.legal) break
      const added = addMove(tree, parent, root, { uci, san: probed.san, fen: probed.fen })
      tree = added.tree
      chain.push(added.id)
      parent = added.id
      from = probed.fen
    }
    // Same as a dragged move: the nodes stay whichever way, but the cursor only
    // moves if the board is still where it was when the line was clicked.
    if (chain.length === 0 || vIdx !== at || anchor !== root) return
    for (const id of chain) showBranch(id)
  }

  /** Put `id` on screen and move the board onto it. */
  function showBranch(id: NodeId) {
    activePath = pathOnto(tree, activePath, vIdx, id)
    vIdx += 1
  }

  /** Put the game back on screen. The variation stays in the tree; it is still
   *  reachable from the branch point, and the mainline cell it left from is marked. */
  function leaveVariation() {
    activePath = []
    vIdx = 0
  }

  function clearLines() {
    tree = emptyTree()
    leaveVariation()
  }

  function varSeek(i: number) {
    vIdx = Math.max(0, Math.min(activePath.length, i))
  }

  // ── navigation ───────────────────────────────────────────────────────────
  // Moving along the mainline always leaves the variation, so the mainline move
  // list and nav row are themselves the way back — there is no state to get stuck in.
  function seek(i: number) {
    leaveVariation()
    idx = Math.max(0, Math.min(plies.length, i))
    // Going anywhere but the moment being tried ends the Try.
    if (trying && idx !== trying.ply) {
      trying = null
      tryVerdict = null
    }
  }

  function onKey(e: KeyboardEvent) {
    const len = activePath.length
    if (e.key === 'Escape') {
      // Only meaningful in game review: there is no mainline to return to in FEN mode.
      if (fenMode || len === 0) return
      leaveVariation()
    } else if (e.key === 'ArrowLeft') {
      if (vIdx > 0) varSeek(vIdx - 1)
      else if (fenMode) return
      else seek(idx - 1)
    } else if (e.key === 'ArrowRight') {
      if (vIdx < len) varSeek(vIdx + 1)
      // At the end of a variation, forward does nothing: the next mainline move is
      // not a continuation of the line on screen.
      else if (fenMode || len > 0) return
      else seek(idx + 1)
    } else if (e.key === 'Home') {
      if (vIdx > 0) varSeek(0)
      else if (fenMode) return
      else seek(0)
    } else if (e.key === 'End') {
      if (len > 0) varSeek(len)
      else if (fenMode) return
      else seek(plies.length)
    } else return
    e.preventDefault()
  }

  // Show engine lines for the viewed position. In game review the top lines are
  // persisted during analysis, so display them instantly; only fall back to a
  // live engine search when there's nothing stored (final position, plies
  // analysed before F4a, or FEN-analysis mode).
  $effect(() => {
    const f = posFen
    if (!f) return
    if (!fenMode && !inVar) {
      const ma = analyses[idx]
      if (ma && ma.lines.length) {
        liveEval = {
          fen: f,
          bestUci: ma.bestUci,
          cp: ma.scoreBeforeCp,
          mate: ma.scoreBeforeMate,
          lines: ma.lines,
        }
        return
      }
    }
    liveEval = null
    api.analyzeFen(f).catch((e) => {
      loadError = e instanceof Error ? e.message : String(e)
    })
  })

  $effect(() => {
    // A Try plays its move as a variation; the verdict is on the Report tab.
    if (inVar && !trying) tab = 'moves'
  })

  function showInMoves(position: number) {
    tab = 'moves'
    seek(position)
  }

  // ── move explanations ────────────────────────────────────────────────────
  //
  // Fetched per ply rather than with the game. Measured in the sidecar at 0.548 ms
  // median and 2.9 ms p95 per ply (RULE_VERSION 10, 5 000 plies, 2026-09-30), so
  // there is nothing to gain by storing them or by loading a whole game up front.
  //
  // `curMa` is null off the mainline, which is what keeps the sentences off a
  // position they were never computed for.
  //
  // Claims and descriptions arrive in separate arrays and render under separate
  // headings (layer 5): `claims` holds the rule sentences and, where the rules are
  // silent, a forcing engine line that passed gate P; `descriptions` holds board facts
  // about the played and best branches, which say what is different and not why.
  let explanation = $state<ClaimText[]>([])
  let descriptions = $state<DescriptionText[]>([])
  let comparedWith = $state<string | null>(null)
  $effect(() => {
    const ply = curMa?.ply ?? null
    explanation = []
    descriptions = []
    comparedWith = null
    if (gameId == null || ply == null) return
    let live = true
    api
      .explainMove(gameId, ply)
      .then((r) => {
        if (!live) return
        explanation = r.claims ? r.claims.map((c) => c.text) : (r.sentences as ClaimText[])
        descriptions = (r.descriptions ?? []).map((d) => d.text)
        comparedWith = r.bestSan ?? null
      })
      .catch(() => {
        // Silence is the designed outcome for most plies, so a failure here must
        // not surface as an error message beside the classification.
      })
    return () => {
      live = false
    }
  })

  // A different game is a different tree, and the screen is not keyed on `gameId`,
  // so nothing else would clear it. `seen` is deliberately not reactive — writing it
  // inside the effect must not re-run the effect.
  let seen = ''
  $effect(() => {
    const now = `${gameId}|${fen}`
    if (now === seen) return
    seen = now
    clearLines()
  })

  // auto-scroll both move lists to the current move
  let listEl: HTMLElement | undefined = $state()
  let varListEl: HTMLElement | undefined = $state()
  $effect(() => {
    void idx
    void vIdx
    listEl?.querySelector('.cell.current')?.scrollIntoView({ block: 'nearest' })
    varListEl?.querySelector('.cell.current')?.scrollIntoView({ block: 'nearest' })
  })

  const rows = $derived.by(() => {
    const out: { num: number; w: number; b: number }[] = []
    for (let i = 0; i < plies.length; i += 2) out.push({ num: i / 2 + 1, w: i, b: i + 1 })
    return out
  })

  // Mainline plies with a branch hanging off them, so a line the user left is
  // visible on the move list rather than only findable by walking back to it.
  const branchedAt = $derived.by<Set<number>>(() => {
    const out = new Set<number>()
    for (const n of tree.nodes.values()) if (n.parent === null) out.add(n.rootPly)
    return out
  })

  // Other moves explored from the position on the board. This is the whole point of
  // keeping a tree: a branch the user left is one click away instead of gone.
  const alts = $derived.by<VarNode[]>(() => {
    const parent = vIdx === 0 ? null : (activePath[vIdx - 1] ?? null)
    const onScreen = activePath[vIdx] ?? null
    return childrenOf(tree, parent, anchor).filter((n) => n.id !== onScreen)
  })

  // The variation laid out in the same three columns as the mainline, numbered from
  // where it branched — a line off black's 12th move starts at 12…, not at 1.
  const varRows = $derived.by(() => {
    const root = line.length > 0 ? line[0].rootPly : anchor
    const out: { num: number; w: number | null; b: number | null }[] = []
    let i = 0
    if (root % 2 === 1 && line.length > 0) {
      out.push({ num: Math.floor(root / 2) + 1, w: null, b: 0 })
      i = 1
    }
    for (; i < line.length; i += 2) {
      out.push({
        num: Math.floor((root + i) / 2) + 1,
        w: i,
        b: i + 1 < line.length ? i + 1 : null,
      })
    }
    return out
  })

  function fmtDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  onMount(() => {
    sidecar.on('analysis_ply', onPly)
    sidecar.on('analysis_done', onDone)
    sidecar.on('analysis_cancelled', onCancelled)
    sidecar.on('analysis_error', onError)
    sidecar.on('fen_analyzed', onFenAnalyzed)
    sidecar.on('move_judged', onJudged)
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
    sidecar.off('fen_analyzed', onFenAnalyzed)
    sidecar.off('move_judged', onJudged)
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="review" class:graphed={showGraph}>
  {#if loadError}
    <div class="load-error">{loadError}</div>
  {:else if !fenMode && !detail}
    <div class="load-error muted">Loading…</div>
  {:else}
    {#if hasAnalysis}
      <div class="bar-col"><EvalBar wp={barWp} label={barLabel} {orientation} /></div>
    {/if}

    <div class="board-col">
      <Board
        bind:this={board}
        fen={curFen}
        {lastMove}
        {turnColor}
        movableColor={turnColor}
        {dests}
        {check}
        {orientation}
        {shapes}
        {badge}
        promotion={fenPromotion}
        onmove={onBoardMove}
        onpromote={onBoardPromote}
        animationMs={150}
      />
      {#if fenMode || activePath.length > 0}
        <div class="nav-row">
          <button class="nav-btn" onclick={() => varSeek(0)} aria-label="Start of line">⏮</button>
          <button class="nav-btn" onclick={() => varSeek(vIdx - 1)} aria-label="Previous move"
            >◀</button
          >
          <span class="counter">{vIdx} / {activePath.length}</span>
          <button class="nav-btn" onclick={() => varSeek(vIdx + 1)} aria-label="Next move">▶</button>
          <button class="nav-btn" onclick={() => varSeek(activePath.length)} aria-label="Last move"
            >⏭</button
          >
          {#if !fenMode}
            <button class="nav-btn mainline" onclick={leaveVariation}>Back to game</button>
          {/if}
        </div>
      {:else}
        <div class="nav-row">
          <button class="nav-btn" onclick={() => seek(0)} aria-label="First move">⏮</button>
          <button class="nav-btn" onclick={() => seek(idx - 1)} aria-label="Previous move">◀</button>
          <span class="counter">{idx} / {plies.length}</span>
          <button class="nav-btn" onclick={() => seek(idx + 1)} aria-label="Next move">▶</button>
          <button class="nav-btn" onclick={() => seek(plies.length)} aria-label="Last move">⏭</button>
        </div>
      {/if}
      {#if showGraph}
        <EvalGraph
          series={graphSeries}
          currentPly={idx}
          onseek={seek}
          markers={graphMarks}
          decided={report?.decided ?? null}
          gap={graphGap}
          gapLabel={gapIsBook ? 'book · not scored' : graphGap > 1 ? 'not scored' : null}
          lowClock={report?.lowClock?.position ?? null}
          bookExit={bookTick(report?.opening)}
          slide={report?.slide ?? null}
        />
      {/if}
    </div>

    <aside class="panel">
      {#if fenMode}
        <div class="head">
          <button class="back" onclick={onback}>← Back</button>
          <h3>Position analysis</h3>
          <span class="turn-badge"
            ><span class="turn-dot {turnColor}"></span>{turnColor} to move</span
          >
        </div>
        <div class="fen-body">
          <EngineLines lines={liveEval?.lines ?? []} fen={posFen} onpick={enterLine} />

          {@render exploration()}

          <div class="fen-field">
            <span class="fen-cap">FEN</span>
            <code class="fen-str">{posFen}</code>
          </div>

          <button class="btn btn-accent fen-play" onclick={() => onplayfen(posFen)}>
            Play from here
          </button>
        </div>
      {:else if detail}
        <div class="head">
          <button class="back" onclick={onback}>← Games</button>
          <h3>{detail.white} vs {detail.black}</h3>
          <span class="sub">
            {detail.result === '1/2-1/2' ? '½–½' : detail.result}
            · {describeTermination(detail.termination)} · {fmtDate(detail.playedAt)}
          </span>
        </div>

        <div class="opening" class:hidden={!openingText}>{openingText || ' '}</div>

        <div class="tabs" role="tablist">
          <button
            role="tab"
            class="tab"
            class:active={tab === 'report'}
            aria-selected={tab === 'report'}
            onclick={() => (tab = 'report')}>Report</button
          >
          <button
            role="tab"
            class="tab"
            class:active={tab === 'moves'}
            aria-selected={tab === 'moves'}
            onclick={() => (tab = 'moves')}>Moves</button
          >
        </div>

        {#if tab === 'report'}
          {#if analyzing}
            {@render progress()}
            {@render prelimLines()}
            <p class="report-note">
              The report appears when the analysis finishes: a later move can outweigh an
              earlier one, so a partial list of moments would be wrong.
            </p>
          {:else if report}
            <ReportPanel
              {report}
              {gameId}
              current={idx}
              onseek={seek}
              onshowmoves={showInMoves}
              {engineOk}
              tryingPly={trying?.ply ?? null}
              verdict={tryVerdict}
              ontry={startTry}
              onretry={retryTry}
              onstop={stopTry}
            />
          {:else if !hasAnalysis}
            {@render prelimLines()}
            <div class="analyse-card">
              <button class="btn btn-accent" onclick={startAnalysis}>Analyse game</button>
              {#if analysisError}<span class="err">{analysisError}</span>{/if}
            </div>
            <p class="report-note">The rest of the report is built from the analysis of every move.</p>
          {:else}
            <p class="report-note">No report for this game.</p>
          {/if}
          {#if accuracies}
            <div class="acc-row">
              <span class="acc-label">Accuracy</span>
              <span class="acc-chip w">{accuracies.white?.toFixed(1) ?? '–'}</span>
              <span class="acc-chip b">{accuracies.black?.toFixed(1) ?? '–'}</span>
              <button class="reanalyse" onclick={startAnalysis}>Re-analyse</button>
            </div>
          {/if}
        {:else}
          {#if inVar}
            <!-- The engine lines below are live; everything that depends on the stored
                 analysis of a played move has nothing to say about a position that was
                 never played, so it says nothing rather than guessing. -->
            <div class="offline-card">
              <span class="offline-text">
                Your own line — engine evaluation only. No classification or move notes
                off the game.
              </span>
              <button class="undo" onclick={leaveVariation}>Back to {branchLabel}</button>
            </div>
          {:else if curMa}
            <div class="cls-card" style="--cls: {CLASS_COLORS[curMa.classification]}">
              <span class="cls-glyph" style="background: {CLASS_COLORS[curMa.classification]}"
                >{CLASS_GLYPHS[curMa.classification]}</span
              >
              <span class="cls-text">
                <strong>{curPly?.san}</strong> — {CLASS_LABELS[curMa.classification]}
                <FlagThis kind="label" gameId={gameId} ply={curMa.ply}
                          label={curMa.classification}
                          shown="{curPly?.san} — {CLASS_LABELS[curMa.classification]}" />
              </span>
              <span class="cls-eval">{barLabel}</span>
            </div>
            {#if explanation.length}
              <ul class="explain">
                {#each explanation as sentence (sentence)}
                  <li>{sentence}<FlagThis kind="claim" gameId={gameId} ply={curMa.ply}
                                          label={curMa.classification} shown={sentence} /></li>
                {/each}
              </ul>
            {/if}
            {#if descriptions.length}
              <div class="describe">
                <span class="describe-head"
                  >Compared with {comparedWith ?? 'the engine move'}</span
                >
                <ul class="explain">
                  {#each descriptions as line (line)}
                    <li>{line}<FlagThis kind="description" gameId={gameId} ply={curMa.ply}
                                        label={curMa.classification} shown={line}
                                        context="Compared with {comparedWith ?? 'the engine move'}" /></li>
                  {/each}
                </ul>
              </div>
            {/if}
          {:else if analyzing}
            {@render progress()}
          {:else if !hasAnalysis}
            <div class="analyse-card">
              <button class="btn btn-accent" onclick={startAnalysis}>Analyse game</button>
              {#if analysisError}<span class="err">{analysisError}</span>{/if}
            </div>
          {/if}

          <div class="engine-wrap">
            <EngineLines lines={liveEval?.lines ?? []} fen={posFen} onpick={enterLine} />
          </div>

          {@render exploration()}

          <div class="movelist" bind:this={listEl}>
            {#each rows as row (row.num)}
              <span class="num">{row.num}</span>
              {#each [row.w, row.b] as p (p)}
                {#if p < plies.length}
                  <button
                    class="cell"
                    class:current={!inVar && idx === p + 1}
                    class:branched={branchedAt.has(p + 1)}
                    onclick={() => seek(p + 1)}
                  >
                    {#if analyses[p]}
                      <span class="dot" style="background: {CLASS_COLORS[analyses[p].classification]}"
                        >{CLASS_GLYPHS[analyses[p].classification]}</span
                      >
                    {/if}
                    {plies[p].san}
                  </button>
                {:else}
                  <span></span>
                {/if}
              {/each}
            {/each}
          </div>
        {/if}
      {/if}
    </aside>
  {/if}
</div>

{#snippet prelimLines()}
  {#if prelim.length}
    <ul class="prelim">
      {#each prelim as line (line)}<li>{line}</li>{/each}
    </ul>
  {/if}
{/snippet}

{#snippet progress()}
  {#if analyzing}
    <div class="progress-card">
      <div class="progress-row">
        <span>Analysing… {analyzing.done} / {analyzing.total}</span>
        <button class="cancel" onclick={cancelAnalysis}>cancel</button>
      </div>
      <div class="progress-track">
        <div
          class="progress-fill"
          style="width: {analyzing.total ? (analyzing.done / analyzing.total) * 100 : 0}%"
        ></div>
      </div>
    </div>
  {/if}
{/snippet}

<!-- The line being explored, plus every other move tried from the position on the
     board. Identical in both modes, so the one block serves the analysis panel and
     the game-review panel. -->
{#snippet exploration()}
  {#if line.length > 0 || alts.length > 0}
    <div class="explore" class:boxed={!fenMode}>
      {#if line.length > 0}
        <div class="line-head">
          <span class="line-cap">{fenMode ? 'Moves' : `Line from ${branchLabel}`}</span>
          <button class="undo" onclick={clearLines}>Clear lines</button>
        </div>
        <div class="var-movelist" bind:this={varListEl}>
          {#each varRows as row (`${row.num}:${row.w ?? 'x'}`)}
            <span class="num">{row.num}</span>
            {#each [row.w, row.b] as p (p)}
              {#if p !== null}
                <button class="cell" class:current={vIdx === p + 1} onclick={() => varSeek(p + 1)}>
                  {line[p].san}
                </button>
              {:else}
                <span></span>
              {/if}
            {/each}
          {/each}
        </div>
      {/if}
      {#if alts.length > 0}
        <div class="alts">
          <span class="alts-cap">Other moves from here</span>
          {#each alts as alt (alt.id)}
            <button class="alt" onclick={() => showBranch(alt.id)}>{alt.san}</button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
{/snippet}

<style>
  .review {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 26px;
  }
  .load-error {
    color: var(--danger);
  }
  .load-error.muted {
    color: var(--text-muted);
  }

  .bar-col {
    align-self: center;
    height: min(calc(100vh - 150px), 680px);
  }
  .board-col {
    width: min(calc(100vh - 150px), calc(100vw - 640px), 680px);
    min-width: 360px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  /* The graph sits under the board (132 px + gap), so the board gives up that height
     and the columns align at the top, keeping the eval bar level with the board. */
  .review.graphed {
    align-items: flex-start;
  }
  .review.graphed .board-col {
    width: min(calc(100vh - 290px), calc(100vw - 640px), 680px);
  }
  .review.graphed .bar-col {
    align-self: flex-start;
    height: min(calc(100vh - 290px), calc(100vw - 640px), 680px);
  }

  .tabs {
    display: flex;
    gap: 2px;
    padding: 6px 10px 0;
    border-bottom: 1px solid var(--divider);
  }
  .tab {
    padding: 6px 12px 7px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-muted);
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .tab:hover {
    color: var(--text);
  }
  .tab.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .prelim {
    margin: 10px 14px 0;
    padding: 0 0 0 16px;
    font-size: 13px;
    line-height: 1.45;
  }
  .report-note {
    margin: 10px 14px;
    font-size: 12px;
    line-height: 1.45;
    color: var(--text-muted);
  }
  /* Played-move highlight (replaces the old yellow arrow): a warm amber wash on
     the from/to squares — stronger than the shared last-move tint so the move
     reads clearly on its own, with a faint inset edge for definition. */
  .board-col :global(cg-board square.last-move) {
    background-color: rgba(212, 168, 75, 0.42);
    box-shadow: inset 0 0 0 2px rgba(212, 168, 75, 0.32);
  }
  .nav-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .nav-btn {
    padding: 5px 16px;
    font-size: 13px;
    color: var(--text-muted);
    background: var(--bg-tile);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-tile);
    transition: color 100ms ease, border-color 100ms ease, background-color 100ms ease;
  }
  .nav-btn:hover {
    color: var(--accent);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .counter {
    min-width: 64px;
    text-align: center;
    font-size: 12px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  .panel {
    width: 340px;
    height: min(calc(100vh - 116px), 716px);
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
  }
  .back:hover {
    color: var(--accent);
  }
  h3 {
    margin: 0;
    font-size: 14.5px;
    font-weight: 600;
  }
  .sub {
    font-size: 12px;
    color: var(--text-muted);
  }

  .opening {
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-muted);
    border-bottom: 1px solid var(--divider);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .cls-card {
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 10px 14px 0;
    padding: 9px 12px;
    border-radius: var(--radius);
    border: 1px solid color-mix(in srgb, var(--cls) 40%, var(--divider));
    background: color-mix(in srgb, var(--cls) 10%, var(--bg-raised));
  }
  /* Most plies have nothing provable to say, so this block is absent more often
     than present and must not leave a gap when it is. */
  .explain {
    margin: 6px 14px 0;
    padding: 0 0 0 16px;
    list-style: disc;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text-muted);
  }
  .explain li + li {
    margin-top: 3px;
  }
  /* Descriptions sit under their own heading, apart from the claims above (layer 5). */
  .describe {
    margin-top: 8px;
  }
  .describe-head {
    display: block;
    margin: 0 14px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-muted);
  }
  .cls-glyph {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
  }
  .cls-text {
    font-size: 13px;
    flex: 1;
  }
  .cls-eval {
    font-size: 12px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
  }

  .progress-card {
    padding: 10px 14px;
    border-bottom: 1px solid var(--divider);
  }
  .progress-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 6px;
    font-variant-numeric: tabular-nums;
  }
  .cancel {
    color: var(--text-muted);
    font-size: 11.5px;
  }
  .cancel:hover {
    color: var(--danger);
  }
  .progress-track {
    height: 3px;
    border-radius: 2px;
    background: var(--bg-raised);
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent);
    transition: width 120ms linear;
  }

  .analyse-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--divider);
  }
  /* Sits exactly where the classification card would be, so the absence of a
     classification reads as deliberate rather than as a failure to load. */
  .offline-card {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 10px 14px 0;
    padding: 9px 12px;
    border-radius: var(--radius);
    border: 1px dashed var(--divider);
    background: var(--bg-raised);
  }
  .offline-text {
    flex: 1;
    font-size: 12px;
    line-height: 1.4;
    color: var(--text-muted);
  }
  .nav-btn.mainline {
    font-size: 11.5px;
    font-weight: 600;
  }
  .err {
    font-size: 12px;
    color: var(--danger);
  }

  .movelist {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: grid;
    grid-template-columns: 34px 1fr 1fr;
    align-content: start;
    padding: 6px 0;
    font-size: 13px;
    line-height: 26px;
  }
  .num {
    color: var(--text-muted);
    padding-left: 12px;
    font-variant-numeric: tabular-nums;
  }
  .cell {
    display: flex;
    align-items: center;
    gap: 6px;
    padding-left: 6px;
    font-size: 13px;
    text-align: left;
    border-radius: 3px;
    transition: background-color 60ms ease;
  }
  .cell:hover {
    background: var(--bg-raised);
  }
  .cell.current {
    background: var(--bg-raised);
    color: var(--accent);
    font-weight: 600;
  }
  /* A move with a line explored off it. Faint on purpose: it is a bookmark, not a
     classification, and must not compete with the glyph dots. */
  .cell.branched::after {
    content: '';
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: var(--accent);
    opacity: 0.55;
  }
  .dot {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    color: #fff;
    font-size: 7.5px;
    font-weight: 700;
  }

  .acc-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-top: 1px solid var(--divider);
  }
  .acc-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .acc-chip {
    font-size: 11.5px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    border-radius: var(--radius-sm);
    padding: 2px 7px;
    border: 1px solid var(--divider);
  }
  .acc-chip.w {
    background: var(--side-white);
    color: var(--side-white-ink);
  }
  .acc-chip.b {
    background: var(--side-black);
    color: var(--side-black-ink);
  }
  .reanalyse {
    margin-left: auto;
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .reanalyse:hover {
    color: var(--accent);
  }

  /* ── fen / position-analysis mode ── */
  .turn-badge {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
    color: var(--text-muted);
    text-transform: capitalize;
  }
  .turn-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25);
  }
  .turn-dot.white {
    background: var(--side-white);
  }
  .turn-dot.black {
    background: var(--side-black);
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
  }

  .fen-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 14px;
  }
  .engine-wrap {
    padding: 10px 14px;
    border-bottom: 1px solid var(--divider);
  }
  .fen-field {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .fen-cap {
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .fen-str {
    font-size: 11px;
    color: var(--text-muted);
    word-break: break-all;
    user-select: text;
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 7px 9px;
    line-height: 1.5;
  }
  .fen-play {
    margin-top: 2px;
    padding: 9px 0;
  }
  .line-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .line-cap {
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .undo {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-muted);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    transition: color 100ms ease, background-color 100ms ease;
  }
  .undo:hover {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .alts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .alts-cap {
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .alt {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    background: var(--bg-raised);
    color: var(--text);
    transition: color 100ms ease, background-color 100ms ease;
  }
  .alt:hover {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .explore {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  /* In FEN mode `.fen-body` already supplies the padding; in game review the block
     sits between two full-width sections and needs its own. */
  .explore.boxed {
    padding: 10px 14px;
    border-bottom: 1px solid var(--divider);
  }
  .var-movelist {
    display: grid;
    grid-template-columns: 30px 1fr 1fr;
    align-content: start;
    max-height: 168px;
    overflow-y: auto;
    border: 1px solid var(--divider);
    border-left: 2px solid var(--accent-line);
    border-radius: var(--radius-sm);
    background: var(--bg-surface);
    padding: 6px 0;
    font-size: 13px;
    line-height: 24px;
  }
  /* The two move lists share typography and sit close together, so moves that were
     never played are italic and the list carries an accent rail. Containment alone
     was the only cue, and it reads as a second game rather than a branch off this one. */
  .var-movelist .cell {
    font-style: italic;
  }
</style>
