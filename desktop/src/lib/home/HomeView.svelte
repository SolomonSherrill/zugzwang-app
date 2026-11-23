<script lang="ts">
  /**
   * Home, rebuilt (UI-BUILD C; DESIGN.md "Home", rulings 8, 10, 12): the continue strip, three
   * figures, the latest game with a moment to retry, ratings per time control with their
   * 30-day change, recent games. Every figure is read from home_summary, sync_status and the
   * latest game's report; a part with no data is not drawn.
   */
  import { onDestroy, onMount } from 'svelte'
  import type { Key } from 'chessground/types'
  import Board from '../Board.svelte'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import ChartReadout from '../ui/ChartReadout.svelte'
  import { dayKey, dayText } from '../ui/readoutModel'
  import { api, type GameDetail, type GameReport, type HomeRating, type HomeSummary, type ReportMoment, type SyncStatus } from '../api'
  import { registerCommands } from '../shell/commands.svelte'
  import { moveLabel, swingWords } from '../review/reviewModel'
  import { alreadyHandled } from '../ui/keyTargets'
  import {
    SPEED_NAME, changeText, dayWord, openingFamily, resultSentence, retryMoment, shortTimeControl, sparkCoords, sparkline,
  } from './homeModel'

  interface Props {
    showTrain: boolean
    onnav: (route: 'play' | 'games' | 'trainer' | 'settings') => void
    onanalyze: () => void
    onopen: (gameId: number) => void
    onopenat: (gameId: number, ply: number, action: 'try' | 'best') => void
  }
  let { showTrain, onnav, onanalyze, onopen, onopenat }: Props = $props()

  let summary = $state<HomeSummary | null>(null)
  let error = $state<string | null>(null)
  let sync = $state<SyncStatus | null>(null)
  let latestGame = $state<GameDetail | null>(null)
  let latestReport = $state<GameReport | null>(null)

  async function load() {
    error = null
    try {
      summary = await api.homeSummary()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      return
    }
    api.syncStatus().then((s) => (sync = s)).catch(() => (sync = null))
    const latest = summary.recent[0]
    if (latest) {
      const [g, r] = await Promise.all([
        api.getGame(latest.id).catch(() => null),
        api.gameReport(latest.id).catch(() => null),
      ])
      latestGame = g
      latestReport = r
    }
  }

  const latest = $derived(summary?.recent[0] ?? null)
  const moment = $derived<ReportMoment | null>(
    latestReport && latestReport.analysed ? retryMoment(latestReport.moments.shown) : null,
  )
  const miniFen = $derived.by(() => {
    if (!latestGame) return null
    const p = moment ? moment.ply : latestGame.plies.length
    return p === 0 ? latestGame.startFen : latestGame.plies[p - 1].fen
  })
  const miniLast = $derived.by((): [Key, Key] | null => {
    if (!latestGame) return null
    const p = moment ? moment.ply : latestGame.plies.length
    if (p === 0) return null
    const u = latestGame.plies[p - 1].uci
    return [u.slice(0, 2) as Key, u.slice(2, 4) as Key]
  })
  const pending = $derived(sync ? (sync.chesscom?.pending ?? 0) + (sync.lichess?.pending ?? 0) : 0)
  let resuming = $state(false)
  async function resume() {
    resuming = true
    try {
      await api.analyzePending()
    } catch {
      resuming = false
    }
  }

  const ratings = $derived<HomeRating[]>([...(summary?.ratings ?? []), ...(summary?.puzzles ? [summary.puzzles] : [])])
  const fmt = (n: number) => n.toLocaleString('en-US')
  const OUTCOME = { win: 'Won', loss: 'Lost', draw: 'Drawn' }

  function onKey(e: KeyboardEvent) {
    if (alreadyHandled(e)) return   // B6: a key a focused control handled is not the screen's
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === 'n' || e.key === 'N') onnav('play')
    else if ((e.key === 't' || e.key === 'T') && moment && latest) onopenat(latest.id, moment.ply, 'try')
    else return
    e.preventDefault()
  }
  let off: (() => void) | null = null
  onMount(() => {
    void load()
    off = registerCommands('home', () => [
      { id: 'home-new', group: 'Actions', label: 'New game', kbd: 'N', run: () => onnav('play') },
      ...(moment && latest
        ? [{ id: 'home-try', group: 'Actions', label: `Try ${moveLabel(moment.ply, moment.san ?? '')} again`, kbd: 'T', run: () => onopenat(latest.id, moment!.ply, 'try') }]
        : []),
    ])
  })
  onDestroy(() => off?.())
</script>

<svelte:window onkeydown={onKey} />

<div class="home">
  <header>
    <h1>Home</h1>
    <div class="actions">
      <Button variant="quiet" onclick={onanalyze}>Analyse a game</Button>
      <Button variant="quiet" onclick={() => onnav('games')}>Import PGN</Button>
      {#if showTrain}<Button variant="quiet" onclick={() => onnav('trainer')}>Train</Button>{/if}
      <span class="div" aria-hidden="true"></span>
      <Button variant="primary" kbd="N" onclick={() => onnav('play')}>New game</Button>
    </div>
  </header>

  <main>
    {#if error}
      <EmptyState tone="error" sentence="Home could not load your games." sub={error} action={{ label: 'Try again', run: load }} />
    {:else if !summary}
      <EmptyState sentence="Loading your games…" />
    {:else if summary.games === 0}
      <EmptyState
        sentence="No games yet."
        sub="Connect a Chess.com or Lichess account to sync your games, or play one against Stockfish."
        action={{ label: 'Connect an account', run: () => onnav('settings'), primary: true }}
      />
    {:else}
      {#if pending > 0}
        <div class="continue">
          <span class="grow">
            <span class="cap">Continue where you left off</span>
            <span class="what"><span class="n">{fmt(pending)}</span> synced {pending === 1 ? 'game' : 'games'} waiting for analysis</span>
          </span>
          <Button disabled={resuming} onclick={resume}>{resuming ? 'Started' : 'Analyse now'}</Button>
        </div>
      {/if}

      <dl class="figures">
        <div>
          <dt>Games</dt>
          <dd class="metric">{fmt(summary.games)}</dd>
          <dd class="sub">{fmt(summary.analysed)} analysed</dd>
        </div>
        <div>
          <dt>Average accuracy</dt>
          <dd class="metric">{#if summary.avgAccuracy !== null}{Math.round(summary.avgAccuracy)}<span class="pct">%</span>{:else}–{/if}</dd>
          <dd class="sub">Analysed games</dd>
        </div>
        <div>
          <dt>Win rate</dt>
          <dd class="metric">{#if summary.winRate !== null}{summary.winRate.toFixed(1)}<span class="pct">%</span>{:else}–{/if}</dd>
          <dd class="sub">Not counting Stockfish</dd>
        </div>
      </dl>

      <div class="pair">
        {#if latest}
          <section class="card latest" aria-labelledby="latest-h">
            <div class="ch">
              <h2 id="latest-h">Latest game</h2>
              <button type="button" class="link" onclick={() => onopen(latest.id)}>Open review</button>
            </div>
            <div class="lbody">
              {#if miniFen}
                <div class="mini">
                  <Board
                    fen={miniFen}
                    lastMove={miniLast}
                    turnColor={miniFen.split(' ')[1] === 'b' ? 'black' : 'white'}
                    movableColor={null}
                    dests={new Map()}
                    check={false}
                    orientation={latest.playerColor === 'black' ? 'black' : 'white'}
                    coordinates={false}
                  />
                </div>
              {/if}
              <div class="ltext">
                <div>
                  <div class="meta">
                    {[dayWord(latest.playedAt), shortTimeControl(latest.timeControl), openingFamily(latest.openingName)].filter(Boolean).join(', ')}
                  </div>
                  {#if resultSentence(latest)}<div class="res" title={resultSentence(latest)}>{resultSentence(latest)}</div>{/if}
                </div>
                {#if latest.accuracy !== null}
                  <div class="accs">
                    <div><div class="cap">You</div><div class="acc">{latest.accuracy.toFixed(1)}</div></div>
                    {#if latest.opponentAccuracy !== null}
                      <div class="oppacc"><div class="cap name" title={latest.opponent}>{latest.opponent}</div><div class="acc opp">{latest.opponentAccuracy.toFixed(1)}</div></div>
                    {/if}
                  </div>
                {/if}
                {#if moment}
                  <div class="retry">
                    <div class="cap">Retry a moment</div>
                    <div class="mrow">
                      <span class="mv">{moveLabel(moment.ply, moment.san ?? '')}</span>
                      <MoveQualityIcon cls={moment.classification} />
                      <span class="sw">{swingWords(moment)}</span>
                    </div>
                    <div class="acts">
                      <Button variant="primary" kbd="T" onclick={() => onopenat(latest.id, moment!.ply, 'try')}>Try it</Button>
                      <Button onclick={() => onopenat(latest.id, moment!.ply, 'best')}>Show the best move</Button>
                    </div>
                  </div>
                {/if}
              </div>
            </div>
          </section>
        {/if}

        <section class="card ratings" aria-labelledby="ratings-h">
          <div class="ch"><h2 id="ratings-h">Ratings</h2><span class="hint">Last 30 days</span></div>
          {#if ratings.length}
            <ul>
              {#each ratings as r (r.platform + r.speed)}
                {@const ch = changeText(r.change)}
                {@const values = r.series.map((p) => p.rating)}
                {@const xy = sparkCoords(values)}
                <li>
                  <span class="rn"><span class="name">{SPEED_NAME[r.speed]}</span><span class="plat">{r.platform}</span></span>
                  {#if xy.length}
                    <ChartReadout
                      points={xy.map(([x, y]) => ({ x, y }))}
                      vw={96}
                      vh={24}
                      placement="above"
                      label={(i) => ({ title: dayText(r.series[i].t), value: String(r.series[i].rating) })}
                      keyboard={{ label: `${SPEED_NAME[r.speed]} rating, last 30 days`, keys: r.series.map((p) => dayKey(p.t)) }}
                    >
                      <svg width="96" height="24" viewBox="0 0 96 24" aria-hidden="true"
                        ><polyline points={sparkline(values)} fill="none" stroke="var(--chart-line)" stroke-width="1.5" stroke-linejoin="round" /></svg
                      >
                    </ChartReadout>
                  {:else}
                    <svg width="96" height="24" viewBox="0 0 96 24" aria-hidden="true"></svg>
                  {/if}
                  <span class="rv">{r.rating}</span>
                  <span class="rc" class:up={r.newPeak || (r.change ?? 0) > 0} class:down={!r.newPeak && (r.change ?? 0) < 0}
                    >{#if r.newPeak}↑ New peak{:else if ch}{ch}{/if}</span
                  >
                </li>
              {/each}
            </ul>
          {:else}
            <p class="none">No rated games in the last 30 days.</p>
          {/if}
        </section>
      </div>

      <section aria-labelledby="recent-h">
        <div class="rh"><h2 id="recent-h">Recent games</h2><button type="button" class="link" onclick={() => onnav('games')}>All games</button></div>
        <div class="table">
          <div class="thead" aria-hidden="true">
            <span>Result</span><span>Opponent</span><span>Opening</span><span>Time</span><span class="r">Accuracy</span><span class="r">Date</span><span></span>
          </div>
          <ul>
            {#each summary.recent as g (g.id)}
              <li>
                <button type="button" class="row" onclick={() => onopen(g.id)}>
                  <span class="out"><span class="dot {g.outcome ?? 'none'}" aria-hidden="true"></span>{g.outcome ? OUTCOME[g.outcome] : g.result}</span>
                  <span class="opp" title={g.opponent ?? 'Unknown'}>{g.opponent ?? 'Unknown'}</span>
                  <span class="muted ell">{g.openingName ? (g.openingEco ? `${g.openingName} (${g.openingEco})` : g.openingName) : ''}</span>
                  <span class="muted">{shortTimeControl(g.timeControl) ?? ''}</span>
                  <span class="r">{g.accuracy !== null ? g.accuracy.toFixed(1) : ''}</span>
                  <span class="r date">{dayWord(g.playedAt)}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
                </button>
              </li>
            {/each}
          </ul>
        </div>
      </section>
    {/if}
  </main>
</div>

<style>
  .home {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
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
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .div {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 8px;
  }
  main {
    padding: var(--space-7) var(--space-8) var(--space-8);
    display: flex;
    flex-direction: column;
    gap: var(--space-7);
    max-width: 1140px;
    width: 100%;
    box-sizing: border-box;
  }
  .continue {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .cap {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
  }
  .what {
    display: block;
    font-weight: 500;
  }
  .n {
    color: var(--text-2);
    font-weight: 400;
  }
  .figures {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .figures > div {
    padding: 16px 20px;
  }
  .figures > div + div {
    border-left: 1px solid var(--border);
  }
  dt {
    color: var(--text-3);
    font: var(--secondary);
  }
  dd {
    margin: 0;
  }
  .metric {
    margin-top: 6px;
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
  }
  .pct {
    font-size: 15px;
    color: var(--text-2);
  }
  .sub {
    margin-top: 2px;
    color: var(--text-2);
    font: var(--secondary);
  }
  .pair {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-7);
  }
  .card {
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .latest {
    flex: 3 1 460px;
  }
  .ratings {
    flex: 2 1 320px;
  }
  /* One column below 1248 px wide (DESIGN.md fifth rulings, 2; UI-BUILD-4 C): where the 1140 px
     column would narrow (1140 + the page padding, 56, + the icon rail, 52). The smallest window
     (1280) never reaches it; a browser can. */
  @media (max-width: 1247.98px) {
    .pair {
      flex-direction: column;
    }
    .latest,
    .ratings {
      flex: none;
    }
  }
  .ch {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-2);
    font: var(--secondary);
    cursor: pointer;
  }
  .link:hover {
    color: var(--text);
  }
  .hint {
    color: var(--text-3);
    font: var(--secondary);
  }
  .lbody {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    padding: 16px;
  }
  .mini {
    width: 208px;
    flex: none;
  }
  .ltext {
    flex: 1 1 200px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .meta {
    color: var(--text-3);
    font: var(--secondary);
  }
  /* BETA-6 (ruling S7): a long name ends in "…", the whole sentence in a tooltip */
  .res {
    margin-top: 2px;
    font-size: 15px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .oppacc {
    min-width: 0;
    max-width: 160px;
  }
  .cap.name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .accs {
    display: flex;
    gap: 24px;
  }
  /* BETA-6 layout check (WebKit): the figure's line as tall as its glyphs, so it no longer reaches 2 px into "You" */
  .acc {
    font-size: 18px;
    font-weight: 500;
    line-height: 1.3;
  }
  .acc.opp {
    color: var(--text-2);
  }
  .retry {
    margin-top: auto;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }
  .retry .cap {
    margin-bottom: 4px;
  }
  .mrow {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .mv {
    font-weight: 500;
  }
  .sw {
    color: var(--text-2);
  }
  .acts {
    display: flex;
    gap: 6px;
  }
  .ratings ul,
  .table ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .ratings li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 96px 48px 70px;
    align-items: center;
    gap: 12px;
    padding: 11px 16px;
  }
  .ratings li + li {
    border-top: 1px solid var(--divider);
  }
  .rn .name {
    display: block;
    font-weight: 500;
  }
  .plat {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
  }
  .rv {
    text-align: right;
    font-size: 15px;
    font-weight: 500;
  }
  .rc {
    text-align: right;
    font: var(--secondary);
    color: var(--text-3);
  }
  .rc.up {
    color: var(--win);
  }
  .rc.down {
    color: var(--loss);
  }
  .none {
    margin: 0;
    padding: 14px 16px;
    color: var(--text-3);
  }
  .rh {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .table {
    /* a block: Tailwind's `table` utility would make it display: table, shrink-to-fit (BETA-4 C) */
    display: block;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .thead,
  .row {
    display: grid;
    grid-template-columns: 88px minmax(0, 1.3fr) minmax(0, 2fr) 64px 72px 64px 16px;
    gap: 12px;
    align-items: center;
  }
  .thead {
    padding: 8px 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .row {
    width: 100%;
    padding: 10px 16px;
    background: none;
    border: 0;
    border-top: 1px solid var(--divider);
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .row:hover {
    background: var(--surface);
  }
  .row:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }
  .out {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 4px;
    background: var(--draw);
  }
  .dot.win {
    background: var(--win);
  }
  .dot.loss {
    background: var(--loss);
  }
  .opp {
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .muted {
    color: var(--text-2);
  }
  .ell {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .r {
    text-align: right;
  }
  .date {
    color: var(--text-3);
  }
</style>
