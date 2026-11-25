<script lang="ts">
  /**
   * A Practice session (COACH-2 C; COACH.md "COACH-2: the spec", rulings CP1, 1, 5, 6; mockups MinimalCoachPractice*):
   * today's queue from practice_session, one position at a time. "Find the move" (a missed chance, the position before
   * the move) or "Spot the threat" (a threat allowed, the position before the move that allowed it); a transfer probe
   * says "A new position, not from your games." The theme stays hidden until the answer. Any good move counts: the
   * move is judged as Try it judges (judge_move, core/retry.py), then practice_answer appends the attempt to the log
   * (append-only) and says Right or Not quite, the sentence, the theme, "One of your focus themes" where it is one, and
   * when it comes back. Hint shows the square to look at; Show the answer counts as not known. "Earlier this session"
   * lists the answered ones.
   */
  import { onDestroy, onMount } from 'svelte'
  import { Chess } from 'chess.js'
  import type { Key } from 'chessground/types'
  import type { DrawShape } from 'chessground/draw'
  import Board from '../Board.svelte'
  import { uciOf, type PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import ResultDot from '../puzzles/ResultDot.svelte'
  import { registerCommands } from '../shell/commands.svelte'
  import { alreadyHandled, ownsEnter } from '../ui/keyTargets'
  import { api, sidecar, type MoveJudgedEvent, type PracticeItem, type PracticeReveal } from '../api'
  import { FORM, minutesLeft, promptText, sideText, sourceParts } from './practiceModel'

  interface Props {
    /** a focus item's key ("threat:fork"): Practise on its card; null for the whole queue */
    group?: string | null
    /** the crumb's title */
    title?: string
    onexit: () => void
    onopengame?: (gameId: number, ply: number) => void
  }
  let { group = null, title = 'Practice', onexit, onopengame }: Props = $props()

  type Phase = 'loading' | 'answering' | 'judging' | 'answered' | 'done' | 'error'
  let phase = $state<Phase>('loading')
  let items = $state<PracticeItem[]>([])
  let idx = $state(0)
  let secondsEach = $state(30)
  let session: string | null = null
  let errorText = $state('')
  let reveal = $state<PracticeReveal | null>(null)
  let answered = $state<{ item: PracticeItem; reveal: PracticeReveal }[]>([])
  let hint = $state(false)
  let flipped = $state(false)
  let shownFen = $state('')
  let lastMove = $state<[Key, Key] | null>(null)
  let t0 = 0

  const item = $derived(items[idx] ?? null)
  const orientation = $derived<'white' | 'black'>(item ? (flipped ? (item.side === 'white' ? 'black' : 'white') : item.side) : 'white')
  const chessOf = (fen: string) => {
    try {
      return new Chess(fen)
    } catch {
      return null
    }
  }
  const boardChess = $derived(shownFen ? chessOf(shownFen) : null)
  const dests = $derived.by(() => {
    const map = new Map<Key, Key[]>()
    if (!boardChess || phase !== 'answering') return map
    for (const m of boardChess.moves({ verbose: true })) {
      const arr = map.get(m.from as Key) ?? []
      arr.push(m.to as Key)
      map.set(m.from as Key, arr)
    }
    return map
  })
  const turnColor = $derived<'white' | 'black'>(shownFen.split(' ')[1] === 'b' ? 'black' : 'white')
  const check = $derived(!!boardChess?.inCheck())
  const shapes = $derived.by<DrawShape[]>(() => {
    if (!item) return []
    if (reveal && reveal.verdict === 'notQuite') {
      const u = reveal.answerUci
      return [{ orig: u.slice(0, 2) as Key, dest: u.slice(2, 4) as Key, brush: 'green' }]
    }
    if (hint && item.hintSquare && phase === 'answering') return [{ orig: item.hintSquare as Key, brush: 'green' }]
    return []
  })
  const left = $derived(Math.max(0, items.length - idx - (phase === 'answered' ? 1 : 0)))
  const src = $derived(item ? sourceParts(item) : null)

  // the board fills its column (as Puzzles' does)
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      boardPx = Math.max(240, Math.floor(Math.min(r.width - 56, r.height - 44 - 80) / 8) * 8)
    })
    if (section) ro.observe(section)
    return () => ro.disconnect()
  })

  function show(i: number) {
    idx = i
    reveal = null
    hint = false
    lastMove = null
    const it = items[i]
    if (!it) {
      phase = 'done'
      return
    }
    shownFen = it.fen
    phase = 'answering'
    t0 = Date.now()
  }

  async function start() {
    phase = 'loading'
    try {
      const s = await api.practiceSession(group ?? undefined)
      items = s.items
      secondsEach = s.secondsEach
      session = s.session
      show(0)
    } catch (e) {
      errorText = e instanceof Error ? e.message : String(e)
      phase = 'error'
    }
  }

  // judge_move answers with a token; the verdict arrives as move_judged
  const waiting = new Map<number, (e: MoveJudgedEvent) => void>()
  const early = new Map<number, MoveJudgedEvent>()
  const onJudged = (d: Record<string, unknown>) => {
    const e = d as unknown as MoveJudgedEvent
    const w = waiting.get(e.token)
    if (w) {
      waiting.delete(e.token)
      w(e)
    } else early.set(e.token, e)
  }
  function verdict(token: number): Promise<MoveJudgedEvent> {
    const got = early.get(token)
    if (got) {
      early.delete(token)
      return Promise.resolve(got)
    }
    return new Promise((res) => waiting.set(token, res))
  }

  async function onUserMove(orig: Key, dest: Key, promotion?: PromotionPiece) {
    if (!item || phase !== 'answering') return
    const it = item
    const uci = uciOf(orig, dest, promotion)
    const took = Date.now() - t0
    const c = chessOf(it.fen)
    if (c) {
      try {
        c.move({ from: orig, to: dest, promotion })
        shownFen = c.fen()
        lastMove = [orig, dest]
      } catch {
        /* the board allowed only legal moves */
      }
    }
    phase = 'judging'
    try {
      const { token } = await api.judgeMove(it.fen, uci)
      const v = await verdict(token)
      if (v.error) throw new Error(v.error)
      reveal = await api.practiceAnswer({
        item_id: it.id, answer_uci: uci, correct: !!v.accepted, time_ms: took, hint, revealed: false,
        loss: typeof v.loss === 'number' ? v.loss : null, session,
      })
      answered = [...answered, { item: it, reveal }]
      phase = 'answered'
    } catch (e) {
      errorText = e instanceof Error ? e.message : String(e)
      shownFen = it.fen
      lastMove = null
      phase = 'error'
    }
  }

  async function showAnswer() {
    if (!item || phase !== 'answering') return
    const it = item
    phase = 'judging'
    try {
      reveal = await api.practiceAnswer({
        item_id: it.id, answer_uci: null, correct: false, time_ms: Date.now() - t0, hint, revealed: true, loss: null, session,
      })
      answered = [...answered, { item: it, reveal }]
      phase = 'answered'
    } catch (e) {
      errorText = e instanceof Error ? e.message : String(e)
      phase = 'error'
    }
  }

  function next() {
    if (phase === 'answered') show(idx + 1)
  }
  function retry() {
    if (items.length && item) show(idx)
    else void start()
  }

  function onKey(e: KeyboardEvent) {
    if (alreadyHandled(e) || e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'Enter' && phase === 'answered' && !ownsEnter(e.target as HTMLElement | null)) {
      e.preventDefault()
      next()
    } else if ((e.key === 'h' || e.key === 'H') && phase === 'answering') {
      e.preventDefault()
      hint = true
    } else if ((e.key === 'f' || e.key === 'F') && phase !== 'loading') {
      e.preventDefault()
      flipped = !flipped
    }
  }

  let unregister: (() => void) | null = null
  onMount(() => {
    sidecar.on('move_judged', onJudged)
    unregister = registerCommands('practice', () => [
      ...(phase === 'answering' ? [{ id: 'pr-hint', group: 'Actions', label: 'Hint', kbd: 'H', run: () => (hint = true) }] : []),
      ...(phase === 'answered' ? [{ id: 'pr-next', group: 'Actions', label: 'Next position', kbd: '↵', run: next }] : []),
      { id: 'pr-exit', group: 'Actions', label: 'Back to Coach', run: onexit },
    ])
    void start()
  })
  onDestroy(() => {
    sidecar.off('move_judged', onJudged)
    unregister?.()
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="session" data-state={phase} data-testid="practice">
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onexit}>Coach</button>
      <span class="sep" aria-hidden="true">/</span>
      <span class="title" {title}>{title}</span>
    </div>
    <Button kbd="F" onclick={() => (flipped = !flipped)}>Flip</Button>
  </header>

  <div class="body">
    <section class="board-col" aria-label="Board" bind:this={section}>
      <div class="col" style:width="{boardPx}px">
        <div class="line">
          {#if item && item.source === 'game' && item.opponent}<span class="small name" title={item.opponent}>{item.opponent}</span>{/if}
          {#if item && item.oppMove}<span class="small">{item.side === 'white' ? 'Black' : 'White'} played {item.oppMove}</span>{/if}
        </div>
        <div class="board" style:width="{boardPx}px" style:height="{boardPx}px">
          <Board
            fen={shownFen || '8/8/8/8/8/8/8/8 w - - 0 1'}
            {lastMove}
            {turnColor}
            movableColor={phase === 'answering' && item ? item.side : null}
            {dests}
            {check}
            {orientation}
            {shapes}
            onmove={onUserMove}
          />
        </div>
        <div class="line">
          {#if item}<span class="you"><span class="swatch {item.side}" aria-hidden="true"></span>You play {item.side === 'white' ? 'White' : 'Black'}</span>{/if}
        </div>
      </div>
    </section>

    <aside aria-label="Practice">
      <div class="top">
        <div class="th">
          <span class="strong">{items.length ? `${Math.min(idx + 1, items.length)} of ${items.length}` : ''}</span>
          <span class="small">{phase === 'done' ? '' : minutesLeft(left, secondsEach)}</span>
        </div>
        <div class="dots" aria-label="This session">
          {#each items as it, i (it.id)}
            {@const a = answered.find((x) => x.item.id === it.id)}
            {#if a}<ResultDot result={a.reveal.verdict === 'right' ? 'solved' : 'missed'} />
            {:else if i === idx && phase !== 'done'}<ResultDot result="current" />
            {:else}<span class="todo" role="img" aria-label="To come"></span>{/if}
          {/each}
        </div>
      </div>

      <div class="prompt">
        {#if phase === 'error'}
          <EmptyState tone="error" sentence="This position could not be judged." sub={errorText} action={{ label: 'Try again', run: retry }} />
        {:else if phase === 'loading'}
          <EmptyState sentence="Reading your practice…" />
        {:else if phase === 'done'}
          {#if items.length === 0}
            <EmptyState sentence="Nothing to practise today." sub="New positions come from the moments you miss in your games." action={{ label: 'Back to Coach', run: onexit }} />
          {:else}
            {@const right = answered.filter((a) => a.reveal.verdict === 'right').length}
            <h2 class="state">Done for today</h2>
            <p>{right} of {answered.length} right. Each comes back when it is due.</p>
            <div class="acts"><Button variant="primary" onclick={onexit}>Back to Coach</Button></div>
          {/if}
        {:else if item}
          <div class="form">{FORM[item.kind]}</div>
          <h2 class="state"><span class="swatch {item.side}" aria-hidden="true"></span>{sideText(item)}</h2>
          <p>{promptText(item)}</p>
          {#if src}
            <p class="from">
              {src.before}{#if item.gameId != null && onopengame}<button type="button" class="link name" title={src.name ?? undefined} onclick={() => onopengame?.(item.gameId!, item.ply ?? 0)}>{src.name}</button>{:else}<span class="name" title={src.name ?? undefined}>{src.name}</span>{/if}{src.after}
            </p>
          {/if}
          {#if phase === 'answered' && reveal}
            <div class="verdict" data-verdict={reveal.verdict}>
              <h3 class="state v"><ResultDot result={reveal.verdict === 'right' ? 'solved' : 'missed'} />{reveal.verdict === 'right' ? 'Right' : 'Not quite'}</h3>
              <p>{reveal.sentence}</p>
              <p class="theme"><span class="tname">{reveal.theme}</span>{#if reveal.focus}<span class="tfocus">One of your focus themes</span>{/if}</p>
              <p class="small">{reveal.comesBack}</p>
              <div class="acts">
                <Button variant="primary" kbd="↵" onclick={next}>{idx + 1 < items.length ? 'Next' : 'Finish'}</Button>
                {#if item.gameId != null && onopengame}<Button variant="quiet" onclick={() => onopengame?.(item.gameId!, item.ply ?? 0)}>Open the game</Button>{/if}
              </div>
            </div>
          {:else}
            <p class="small later">The theme shows after you answer.</p>
            <div class="pair">
              <Button kbd="H" disabled={phase !== 'answering' || hint} onclick={() => (hint = true)}>Hint</Button>
              <Button disabled={phase !== 'answering'} onclick={() => void showAnswer()}>Show the answer</Button>
            </div>
            {#if phase === 'judging'}<p class="small">Checking your move…</p>{/if}
          {/if}
        {/if}
      </div>

      {#if answered.length}
        <div class="earlier">
          <div class="cap">Earlier this session</div>
          <ul>
            {#each [...answered].reverse() as a (a.item.id)}
              <li>
                <ResultDot result={a.reveal.verdict === 'right' ? 'solved' : 'missed'} />
                <span class="clip t2" title={FORM[a.item.kind]}>{FORM[a.item.kind]}</span>
                <span class="clip t3" title={a.reveal.theme}>{a.reveal.theme}</span>
                <span class="when">{a.reveal.dueText}</span>
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
    grid-template-columns: 22px minmax(0, 1fr) minmax(0, 1fr) 96px;
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

  .board {
    position: relative;
  }
  .top {
    display: block;
  }
  .todo {
    width: 16px;
    height: 16px;
    border-radius: var(--radius-round);
    flex: none;
    box-shadow: inset 0 0 0 1px var(--border-control);
  }
  .form {
    color: var(--text-3);
    font: var(--secondary);
    margin-bottom: 6px;
  }
  .from {
    color: var(--text-3) !important;
    font: var(--secondary);
    margin-top: 10px !important;
    min-width: 0;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-2);
    font: inherit;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .link:hover {
    color: var(--text);
  }
  .name {
    display: inline-block;
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
  }
  .line .name {
    max-width: 50%;
  }
  .later {
    margin: 10px 0 0 !important;
  }
  .verdict {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }
  .state.v {
    font: var(--body-strong);
  }
  .theme {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .tname {
    color: var(--text);
    font-weight: 500;
  }
  .tfocus {
    color: var(--text-3);
    font: var(--secondary);
  }
  .clip {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .t2 {
    color: var(--text-2);
  }
  .t3 {
    color: var(--text-3);
  }
  .when {
    text-align: right;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
