<script lang="ts">
  /**
   * A game against a friend (FRIENDS-2 D; MinimalPlayGame-friend.html and its -draw, -left, -over and
   * -chat-collapsed states; rulings P1-P4, H1-H4, R1-R3). The server decides everything: the clocks, the
   * moves' legality, the endings; this screen draws its last state (live.svelte.ts) and runs the clocks on
   * between states. The chat sits below the moves, collapsible, expanded by default, with a mute button
   * for this game; it lives in memory only. No engine help, no premoves, no takebacks.
   */
  import { onDestroy, onMount, tick } from 'svelte'
  import { Chess } from 'chess.js'
  import type { Key } from 'chessground/types'
  import Board from '../Board.svelte'
  import type { PromotionPiece } from '../board/promotion'
  import Button from '../ui/Button.svelte'
  import PlayerStrip from '../ui/PlayerStrip.svelte'
  import { commandMenu } from '../shell/commands.svelte'
  import { friendsApi, type Colour } from '../friends/friendsApi'
  import { answerChallenge, clockNow, closeGame, incomingChallenges, live, rematch, send, setChatOpen } from '../friends/live.svelte'
  import { claimIn, clockText, footerState, mmss, other, overLines, ratingText } from '../friends/liveModel'
  import { moveRows } from './playModel'

  interface Props {
    /** Review the game: the saved game's id in the library, at its last move */
    onreview: (gameId: number, lastPly: number) => void
    active?: boolean
  }
  let { onreview, active = false }: Props = $props()

  const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  const NO_DESTS = new Map<Key, Key[]>()
  const g = $derived(live.activeId ? live.games[live.activeId] : undefined)
  const s = $derived(g?.state ?? null)
  const you = $derived<Colour>(s?.you ?? 'white')
  const opp = $derived(s ? s[other(s.you)].handle : '')
  let flipped = $state(false)
  const orientation = $derived<Colour>(flipped ? other(you) : you)
  const top = $derived<Colour>(other(orientation))
  const bottom = $derived<Colour>(orientation)

  let now = $state(Date.now())
  let ticker: ReturnType<typeof setInterval> | undefined
  let board: Board | undefined = $state()
  let opening = $state<{ eco: string | null; name: string | null }>({ eco: null, name: null })

  // the board: the server's position; moves are legal only on your turn
  const chess = new Chess()
  const fen = $derived(s?.fen ?? START)
  const myTurn = $derived(!!s && s.status !== 'over' && s.turn === s.you)
  const dests = $derived.by(() => {
    if (!myTurn) return NO_DESTS
    chess.load(fen)
    const map = new Map<Key, Key[]>()
    for (const m of chess.moves({ verbose: true })) map.set(m.from as Key, [...(map.get(m.from as Key) ?? []), m.to as Key])
    return map
  })
  const check = $derived.by(() => {
    chess.load(fen)
    return chess.inCheck()
  })
  const lastMove = $derived<[Key, Key] | null>(s && s.moves.length ? [s.moves.at(-1)!.slice(0, 2) as Key, s.moves.at(-1)!.slice(2, 4) as Key] : null)
  const rows = $derived(moveRows(s?.sans ?? [], START))

  function onmove(orig: Key, dest: Key, promo?: PromotionPiece) {
    if (!s) return
    void send({ t: 'move', uci: orig + dest + (promo ?? ''), ply: s.moves.length })
  }
  // a refused move: the board goes back to the server's position
  $effect(() => {
    if (g?.error && ['illegal', 'not_your_turn', 'stale_ply', 'game_over'].includes(g.error.code)) board?.sync()
  })

  // ── the footer ───────────────────────────────────────────────────────────
  const footer = $derived(s ? footerState(s) : 'waiting')
  const claimSecs = $derived(s && g ? claimIn(s, g.skew, now) : null)
  let confirm = $state<'resign' | 'draw' | null>(null)
  let confirmTimer: ReturnType<typeof setTimeout> | undefined
  function ask(action: 'resign' | 'draw') {
    if (confirm === action) {
      confirm = null
      clearTimeout(confirmTimer)
      void send({ t: action === 'resign' ? 'resign' : 'draw_offer' })
      return
    }
    confirm = action
    clearTimeout(confirmTimer)
    confirmTimer = setTimeout(() => (confirm = null), 3000)
  }
  const over = $derived(s && s.status === 'over' ? overLines(s) : null)
  const rematchIn = $derived(live.activeId ? incomingChallenges().find((c) => c.rematch_of === live.activeId) ?? null : null)
  const rematchSent = $derived(opp ? live.sent[opp.toLowerCase()] : undefined)
  let rematchError = $state<string | null>(null)
  async function doRematch() {
    rematchError = await rematch()
  }
  function review() {
    if (!g?.savedGameId || !s) return
    const id = g.savedGameId
    const last = Math.max(0, s.moves.length - 1)
    closeGame()
    onreview(id, last)
  }
  function leave() {
    if (s?.status === 'over') closeGame()
  }

  // ── chat (H1-H4) ─────────────────────────────────────────────────────────
  let draft = $state('')
  let logBox: HTMLElement | undefined = $state()
  const lastLine = $derived(g?.chat.at(-1) ?? null)
  const chatNote = $derived(
    !s ? null : s.chat_blocked ? 'Chat is not available in this game.' : !s.chat_on ? 'Your chat in friend games is off (Settings → Friends).' : !s.opponent.chat_on ? `${opp} has chat turned off.` : null,
  )
  function sendChat() {
    const text = draft.trim()
    if (!text) return
    void send({ t: 'chat', text: text.slice(0, 200) })
    draft = ''
  }
  $effect(() => {
    void g?.chat.length
    if (logBox) tick().then(() => logBox && (logBox.scrollTop = logBox.scrollHeight))
  })

  // the opening, by the app's book, as the moves come
  $effect(() => {
    const id = live.activeId
    void s?.moves.length
    if (id) friendsApi.opening(id).then((o) => (opening = o)).catch(() => {})
  })

  function onKey(e: KeyboardEvent) {
    if (!active || commandMenu.open || e.defaultPrevented) return
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'f' || e.key === 'F') {
      flipped = !flipped
      e.preventDefault()
    }
  }

  // the board fills its column (as Play's: the smaller of the width and the height left, a multiple of 8)
  let section: HTMLElement | undefined = $state()
  let boardPx = $state(560)
  onMount(() => {
    ticker = setInterval(() => (now = Date.now()), 100)
    const ro = new ResizeObserver(() => {
      if (!section) return
      const r = section.getBoundingClientRect()
      boardPx = Math.max(240, Math.floor(Math.min(r.width - 56, r.height - 44 - 88) / 8) * 8)
    })
    if (section) ro.observe(section)
    return () => ro.disconnect()
  })
  onDestroy(() => {
    clearInterval(ticker)
    clearTimeout(confirmTimer)
  })

  function strip(side: Colour) {
    const r = g?.ratings?.[side] ?? null
    const gone = side !== you && s && !s.opponent.connected && s.status !== 'over' && s.opponent.gone_since != null
    return {
      name: s ? s[side].handle : '',
      rating: ratingText(r),
      you: side === you,
      note: side === you ? (myTurn && s?.status !== 'waiting' ? 'Your move' : myTurn ? 'Your move' : null) : gone ? 'Disconnected' : null,
      clock: g && s ? clockText(clockNow(g, side, now)) : '0:00',
      active: !!s && s.status === 'playing' && s.running === side,
    }
  }
  const tStrip = $derived(strip(top))
  const bStrip = $derived(strip(bottom))
</script>

<svelte:window onkeydown={onKey} />

{#if s && g}
  <div class="play">
    <header>
      <div class="crumb">
        <button type="button" class="back" onclick={leave} disabled={s.status !== 'over'} title={s.status === 'over' ? 'Back to a new game' : 'Finish the game first'}>Play</button>
        <span class="sep" aria-hidden="true">/</span>
        <span class="title">{opp}</span>
        <span class="ctc">{s.tc}</span>
        <span class="ctc">Unrated</span>
      </div>
      <Button kbd="F" onclick={() => (flipped = !flipped)}>Flip</Button>
    </header>

    <div class="body">
      <section class="board-col" aria-label="Board" bind:this={section}>
        <div class="col" style:width="{boardPx}px">
          <PlayerStrip size="lg" name={tStrip.name} rating={tStrip.rating} you={tStrip.you} note={tStrip.note} clock={tStrip.clock} active={tStrip.active} />
          <div class="board" style:width="{boardPx}px" style:height="{boardPx}px">
            <Board
              bind:this={board}
              {fen}
              {lastMove}
              turnColor={s.turn}
              movableColor={myTurn ? you : null}
              dests={myTurn ? dests : NO_DESTS}
              {check}
              {orientation}
              premovable={false}
              {onmove}
            />
          </div>
          <PlayerStrip size="lg" name={bStrip.name} rating={bStrip.rating} you={bStrip.you} note={bStrip.note} clock={bStrip.clock} active={bStrip.active} />
        </div>
      </section>

      <aside aria-label="Game">
        <div class="opening">
          <div class="oname">{opening.name ?? (s.moves.length ? 'Opening' : 'Starting position')}</div>
          <div class="osub">{opening.eco ? opening.eco + ', unrated' : 'Unrated'}</div>
        </div>
        <div class="moves" role="grid" aria-label="Moves">
          {#each rows as r (r.number)}
            <div class="mrow" role="row">
              <span class="num" role="rowheader">{r.number}.</span>
              {#each [r.white, r.black] as c, k (k)}
                {#if c}
                  {@const sel = c.ply === s.sans.length - 1}
                  <span role="gridcell" class="cell" class:sel aria-selected={sel}>{c.san}</span>
                {:else}
                  <span class="cell empty" role="gridcell">{k === 0 ? '…' : ''}</span>
                {/if}
              {/each}
            </div>
          {/each}
        </div>

        <section class="chat" aria-label="Chat">
          <div class="chead">
            <button type="button" class="ctoggle" aria-expanded={live.chatOpen} onclick={() => setChatOpen(!live.chatOpen)}>
              <svg class="chev" class:open={live.chatOpen} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
              Chat
              {#if !live.chatOpen && g.unread}<span class="badge" aria-label="{g.unread} unread">{g.unread}</span>{/if}
              {#if !live.chatOpen && lastLine}<span class="last" title="{lastLine.from === you ? 'You' : lastLine.handle}: {lastLine.text}">{lastLine.from === you ? 'You' : lastLine.handle}: {lastLine.text}</span>{/if}
            </button>
            <button
              type="button"
              class="mute"
              class:on={s.muted}
              aria-pressed={s.muted}
              aria-label={s.muted ? 'Unmute chat for this game' : 'Mute chat for this game'}
              title={s.muted ? 'Unmute chat for this game' : 'Mute chat for this game'}
              onclick={() => send({ t: 'mute', on: !s.muted })}
            >
              {#if s.muted}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="m17 9 4 6M21 9l-4 6" /></svg>
              {:else}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="M17 8a5 5 0 0 1 0 8" /></svg>
              {/if}
            </button>
          </div>
          {#if live.chatOpen}
            <div class="log" role="log" aria-live="polite" bind:this={logBox}>
              {#each g.chat as line, i (i)}
                <span><span class="from">{line.from === you ? 'You' : line.handle}</span> {line.text}</span>
              {/each}
              {#if s.muted}<span class="hint">Muted for this game: {opp}'s messages are not shown.</span>{/if}
            </div>
            {#if chatNote}
              <p class="hint">{chatNote}</p>
            {:else}
              <input
                type="text"
                placeholder="Message {opp}"
                aria-label="Message {opp}"
                maxlength="200"
                bind:value={draft}
                onkeydown={(e) => e.key === 'Enter' && sendChat()}
              />
            {/if}
            {#if g.error && ['too_long', 'chat_rate', 'chat_off', 'opponent_chat_off', 'chat_unavailable', 'empty'].includes(g.error.code)}
              <p class="hint" role="status">{g.error.message}</p>
            {/if}
          {/if}
        </section>

        <div class="foot">
          {#if footer === 'over' && over}
            <div class="over">
              <div class="otitle">{over.title}</div>
              <div class="oreason">{over.reason}</div>
            </div>
            {#if rematchIn}
              <div class="alert" role="alert">
                <span class="grow"><span class="strong">{opp}</span> wants a rematch</span>
                <Button variant="primary" size="sm" onclick={() => answerChallenge(rematchIn, true)}>Accept</Button>
                <Button variant="quiet" size="sm" onclick={() => answerChallenge(rematchIn, false)}>Decline</Button>
              </div>
            {/if}
            {#if s.result !== '*'}
              <div class="two">
                <Button variant="primary" disabled={!g.savedGameId} onclick={review}>Review the game</Button>
                <Button disabled={rematchSent?.outcome === 'waiting' && rematchSent.challenge.rematch_of === live.activeId} onclick={doRematch}
                  >{rematchSent?.outcome === 'waiting' && rematchSent.challenge.rematch_of === live.activeId ? 'Rematch offered' : 'Rematch'}</Button
                >
              </div>
              <p class="note">
                {#if rematchError}{rematchError}
                {:else if rematchSent && rematchSent.challenge.rematch_of === live.activeId && rematchSent.outcome !== 'waiting'}{opp} {rematchSent.outcome === 'declined' ? 'declined the rematch' : 'did not answer the rematch'}.
                {:else}{g.savedGameId ? 'Saved to both your libraries. Analysing at depth 14.' : 'Saving to your library…'}{/if}
              </p>
            {:else}
              <div class="two">
                <Button variant="primary" onclick={closeGame}>New game</Button>
                <Button onclick={doRematch}>Rematch</Button>
              </div>
            {/if}
          {:else}
            {#if footer === 'draw-offered'}
              <div class="alert" role="alert">
                <span class="grow"><span class="strong">{opp}</span> offers a draw</span>
                <Button variant="primary" size="sm" onclick={() => send({ t: 'draw_accept' })}>Accept</Button>
                <Button variant="quiet" size="sm" onclick={() => send({ t: 'draw_decline' })}>Decline</Button>
              </div>
            {:else if footer === 'opponent-left'}
              <div class="alert col" role="alert">
                <span><span class="strong">{opp}</span> left the game.</span>
                <span class="sub">
                  {#if claimSecs && claimSecs > 0}In {mmss(claimSecs)} you can claim the win or call it a draw. Or keep playing on: they may come back.
                  {:else}You can claim the win or call it a draw. Or keep playing on: they may come back.{/if}
                </span>
                <div class="two">
                  <Button disabled={!(claimSecs === 0)} onclick={() => send({ t: 'claim_win' })}>Claim the win</Button>
                  <Button disabled={!(claimSecs === 0)} onclick={() => send({ t: 'call_draw' })}>Call it a draw</Button>
                </div>
              </div>
            {:else if footer === 'waiting'}
              <p class="note" role="status">
                {s.turn === you ? 'You have' : `${opp} has`} {mmss(Math.max(0, ((s.first_deadline ?? 0) - (now - g.skew)) / 1000))} to make the first move, or the game is aborted.
              </p>
            {/if}
            <div class="two">
              <Button
                pressed={confirm === 'draw'}
                disabled={footer === 'waiting' || !s.can_offer_draw || s.draw_offer === you}
                onclick={() => ask('draw')}>{s.draw_offer === you ? 'Draw offered' : confirm === 'draw' ? 'Confirm the offer' : 'Offer a draw'}</Button
              >
              <Button pressed={confirm === 'resign'} onclick={() => ask('resign')}>{confirm === 'resign' ? 'Confirm resign' : 'Resign'}</Button>
            </div>
            <p class="note">
              {#if g.error && ['too_soon', 'already_offered', 'not_started', 'send', 'not_connected'].includes(g.error.code)}{g.error.message}
              {:else if !g.connected}Reconnecting to the game…
              {:else}Unrated. Saved to both your libraries when it ends.{/if}
            </p>
          {/if}
        </div>
      </aside>
    </div>
  </div>
{:else}
  <div class="play"><p class="loading">Opening the game…</p></div>
{/if}

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
  .crumb {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    white-space: nowrap;
  }
  .back {
    background: transparent;
    border: 0;
    padding: 0;
    color: var(--text-3);
    font: var(--body);
    cursor: pointer;
  }
  .back:disabled {
    cursor: default;
  }
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
    color: var(--text);
  }
  .cell.sel {
    background: var(--selected);
    box-shadow: inset 0 0 0 1px var(--border-strong);
    font-weight: 600;
  }
  .cell.empty {
    color: var(--text-3);
  }
  .chat {
    flex: none;
    border-top: 1px solid var(--border);
    padding: 10px 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .chead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .ctoggle {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
    background: transparent;
    border: 0;
    padding: 0;
    color: var(--text-3);
    font: var(--secondary);
    text-align: left;
    cursor: pointer;
  }
  .chev {
    flex: none;
    transition: transform 0.12s;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .badge {
    flex: none;
    min-width: 16px;
    height: 16px;
    box-sizing: border-box;
    padding: 0 4px;
    border-radius: 8px;
    background: var(--border);
    color: var(--text);
    font-size: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .last {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--text-2);
  }
  .mute {
    background: transparent;
    border: 0;
    padding: 2px;
    color: var(--text-3);
    display: flex;
    cursor: pointer;
    border-radius: 4px;
  }
  .mute.on {
    color: var(--text);
  }
  .log {
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-height: 84px;
    overflow-y: auto;
    overflow-wrap: anywhere;
  }
  .from {
    color: var(--text-3);
  }
  .chat input {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    padding: 6px 10px;
    color: var(--text);
    font: var(--secondary);
  }
  .hint {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
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
  .alert {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: var(--raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-control);
  }
  .alert.col {
    flex-direction: column;
    align-items: stretch;
  }
  .alert .sub {
    color: var(--text-3);
    font: var(--secondary);
  }
  .grow {
    flex: 1;
  }
  .strong {
    font-weight: 500;
  }
  .note {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
    text-align: center;
  }
  .over {
    text-align: center;
    padding: 4px 0 2px;
  }
  .otitle {
    font-size: 15px;
    font-weight: 600;
  }
  .oreason {
    color: var(--text-2);
    margin-top: 2px;
  }
  .loading {
    margin: auto;
    color: var(--text-3);
  }
  button:focus-visible,
  input:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
