<script lang="ts">
  /**
   * Coach (COACH-1 C; COACH.md rulings 1, 5, 6; mockups MinimalCoach, MinimalCoach-learning): Focus, at most
   * three items, what cost the user most in the last 12 months, each shown only when its place holds across the
   * games (COACH-2 ruling CF1; "Still learning your games" until one does), each with Practise (COACH-2 C: a session
   * of that item's positions); Practice (COACH-2 C: due today, by form, right first time this week, learned, Start
   * practice; the session is PracticeSession); and "Behind your focus", the moments the counts are made of, each opening the game's report at the move. No Practice or
   * Spar panel yet (COACH-2, COACH-3), and no placeholder for them. The overview is built by the sidecar off
   * its request thread (coach_overview, then coach_updated when a newer one is ready).
   */
  import { onMount } from 'svelte'
  import { api, sidecar, type CoachOverview, type CoachRow } from '../api'
  import EmptyState from '../ui/EmptyState.svelte'
  import Button from '../ui/Button.svelte'
  import { coachDate, countText, focusSub, recentText, rowsFor, windowText } from './coachModel'
  import PracticeSession from './PracticeSession.svelte'
  import { practice, refreshPractice } from './practiceState.svelte'
  import { dueLine, percent } from './practiceModel'

  let { onopen }: { onopen?: (gameId: number, ply: number) => void } = $props()

  let data = $state<CoachOverview | null>(null)
  let error = $state<string | null>(null)
  let showing = $state<string | null>(null)
  let more = $state(20)
  /** COACH-2 C: a Practice session on screen: the whole queue (group null) or a focus card's Practise */
  let practising = $state<{ group: string | null; title: string } | null>(null)
  const ps = $derived(practice.status)
  function practise(group: string | null, title: string) {
    practising = { group, title }
  }
  function endPractice() {
    practising = null
    refreshPractice()
  }

  async function load() {
    error = null
    try {
      data = await api.coachOverview()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }
  onMount(() => {
    void load()
    const onUpdated = () => void load()
    sidecar.on('coach_updated', onUpdated)
    return () => sidecar.off('coach_updated', onUpdated)
  })

  const ready = $derived(data && data.status === 'ready' ? data : null)
  const rows: CoachRow[] = $derived(ready ? rowsFor(ready, showing) : [])
  const shownTitle = $derived(ready?.focus.find((f) => f.key === showing)?.title ?? null)
  function show(key: string) {
    showing = showing === key ? null : key
    more = 20
  }
</script>

{#if practising}
  {#key practising}
    <PracticeSession group={practising.group} title={practising.title} onexit={endPractice} onopengame={onopen} />
  {/key}
{:else}
<div class="coach">
  <header>
    <h1>Coach</h1>
    {#if ready}<span class="count">{(ready.windowGames ?? ready.games).toLocaleString('en-GB')} analysed games in the {windowText(ready.windowDays)}</span>{/if}
  </header>

  <main>
    {#if error}
      <EmptyState tone="error" sentence="The coach could not read your games." sub={error} action={{ label: 'Try again', run: load }} />
    {:else if !ready}
      <EmptyState sentence="Reading your games…" />
    {:else}
      <section class="panel" aria-labelledby="coach-focus">
        <div class="ph">
          <h2 id="coach-focus">Focus</h2>
          <span title="What costs you most: the win chances lost on the moments you missed, {windowText(ready.windowDays)}"
            >What costs you most: the win chances lost on the moments you missed, {windowText(ready.windowDays)}</span>
        </div>
        {#if ready.focus.length === 0}
          <div class="learning" data-testid="coach-learning">
            <p class="s">Still learning your games</p>
            <p class="sub">
              The coach names a focus once what costs you most in your games of the {windowText(ready.windowDays)} holds
              steady across them.
            </p>
            <p class="n"><b>{(ready.windowGames ?? ready.games).toLocaleString('en-GB')}</b> games analysed in the {windowText(ready.windowDays)}</p>
            {#if ready.pending > 0}<p class="sub">Still reading {ready.pending.toLocaleString('en-GB')} of your games.</p>{/if}
          </div>
        {:else}
          <div class="cards">
            {#each ready.focus as f (f.key)}
              <article class="card" class:sel={showing === f.key} data-testid="coach-focus-item">
                <h3 title={f.title}>{f.title}</h3>
                <p class="big">{@html countText(f)}</p>
                <p class="sub">{focusSub(f)}</p>
                <p class="trend">{recentText(f)}</p>
                <div class="acts">
                  <Button onclick={() => practise(f.key, `Practice: ${f.title}`)}>Practise</Button>
                  <Button pressed={showing === f.key} onclick={() => show(f.key)}>Show positions</Button>
                </div>
              </article>
            {/each}
          </div>
          {#if ready.pending > 0}<p class="quiet">Still reading {ready.pending.toLocaleString('en-GB')} of your games.</p>{/if}
        {/if}
      </section>

      <section class="panel practice" aria-labelledby="coach-practice" data-testid="coach-practice">
        <div class="ph">
          <h2 id="coach-practice">Practice</h2>
          <span>Positions from your games</span>
        </div>
        {#if !ps}
          <p class="quiet pq">Reading your practice…</p>
        {:else}
          <div class="pbody">
            <div class="pdue"><b>{ps.due.toLocaleString('en-GB')}</b><span>{dueLine(ps)}</span></div>
            <dl>
              <div><dt>Find the move</dt><dd>{ps.find}</dd></div>
              <div><dt>Spot the threat</dt><dd>{ps.threat}</dd></div>
              <div><dt>Right first time, this week</dt><dd>{percent(ps.rightWeek)}</dd></div>
              <div><dt>Learned, now shown less often</dt><dd>{ps.learned.toLocaleString('en-GB')}</dd></div>
            </dl>
            <p class="pnote">
              Right answers come back after a few days, then weeks; misses come back sooner. At most {ps.newPerDay} new positions
              a day{ps.probes ? ', about one in five a puzzle that is not from your games' : ''}.
            </p>
          </div>
          <div class="pact">
            <Button variant="primary" disabled={ps.due === 0} onclick={() => practise(null, 'Practice')}>Start practice</Button>
            {#if ps.due === 0}<span class="quiet">{ps.items ? (ps.nextText ? `Nothing due today. Next: ${ps.nextText.toLowerCase()}.` : 'Nothing due today.') : 'Missed moments from your games come here.'}</span>{/if}
          </div>
        {/if}
      </section>

      {#if ready.focus.length}
        <section class="panel" aria-labelledby="coach-behind">
          <div class="ph">
            <h2 id="coach-behind">Behind your focus</h2>
            <span class="what" title={shownTitle ?? undefined}>{shownTitle ?? 'The moments the counts above are made of'}</span>
            {#if showing}<button type="button" class="link" onclick={() => (showing = null)}>Show all</button>{/if}
          </div>
          <div class="thead" aria-hidden="true">
            <span>Date</span><span>Game</span><span>Moment</span><span>Theme</span><span>You</span>
          </div>
          <ul class="rows" aria-label="Moments">
            {#each rows.slice(0, more) as r (r.key + ':' + r.gameId + ':' + r.ply)}
              <li>
                <button type="button" class="row" disabled={!onopen} onclick={() => onopen?.(r.gameId, r.ply)}>
                  <span class="d">{coachDate(r.date)}</span>
                  <span class="g" title={r.opponent ?? undefined}>{r.opponent ?? 'Unknown'}</span>
                  <span class="m">{r.move}</span>
                  <span class="t" title={(r.kind === 'threat' ? r.theme + ' against you' : 'Your own ' + r.theme.toLowerCase())}
                    >{r.kind === 'threat' ? r.theme + ' against you' : 'Your own ' + r.theme.toLowerCase()}</span>
                  <span class="o" class:missed={r.outcome === 'missed'}>{r.outcome === 'caught' ? 'Caught' : 'Missed'}</span>
                </button>
              </li>
            {/each}
          </ul>
          {#if rows.length > more}
            <button type="button" class="more" onclick={() => (more += 20)}>Show {Math.min(20, rows.length - more)} more</button>
          {/if}
        </section>
      {/if}
    {/if}
  </main>
</div>
{/if}

<style>
  .coach {
    display: flex;
    flex-direction: column;
    min-height: 100%;
    font: var(--body);
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
    flex: none;
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .count {
    color: var(--text-3);
    font: var(--secondary);
  }
  main {
    padding: 24px 28px 32px;
    max-width: 1140px;
    width: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    min-width: 0;
  }
  .ph {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    min-height: 44px;
    box-sizing: border-box;
    border-bottom: 1px solid var(--border);
  }
  .ph h2 {
    margin: 0;
    font: var(--body-strong);
    flex: none;
  }
  .ph > span {
    color: var(--text-3);
    font: var(--secondary);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ph .link {
    margin-left: auto;
    flex: none;
  }
  .link,
  .more {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-2);
    font: var(--secondary);
    cursor: pointer;
  }
  .link:hover,
  .more:hover {
    color: var(--text);
  }
  .more {
    display: block;
    padding: 10px 16px 14px;
  }
  .learning {
    padding: 20px 16px 22px;
  }
  .learning .s {
    margin: 0;
    font: var(--body-strong);
  }
  .learning .sub,
  .quiet {
    margin: 6px 0 0;
    color: var(--text-2);
    font: var(--secondary);
    max-width: 640px;
  }
  .quiet {
    margin: 0;
    padding: 0 16px 14px;
    color: var(--text-3);
  }
  .learning .n {
    margin: 14px 0 0;
    color: var(--text-2);
    font: var(--secondary);
  }
  .learning .n b {
    color: var(--text);
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
    margin-right: 6px;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .card {
    padding: 14px 16px 16px;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .card + .card {
    border-left: 1px solid var(--border);
  }
  .card.sel {
    background: var(--raised);
  }
  .card h3 {
    margin: 0;
    font: var(--body-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .big {
    margin: 10px 0 0;
    color: var(--text-2);
    font: var(--secondary);
  }
  .big :global(b) {
    color: var(--text);
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
    margin-right: 4px;
  }
  .card .sub,
  .trend {
    margin: 2px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .trend {
    color: var(--text-2);
    margin-top: 8px;
  }
  .acts {
    margin-top: 14px;
    display: flex;
    gap: 8px;
  }
  .thead,
  .row {
    display: grid;
    grid-template-columns: 84px minmax(0, 1.3fr) 110px minmax(0, 1.6fr) 72px;
    gap: 12px;
    align-items: center;
    padding: 0 16px;
  }
  .thead {
    height: 32px;
    color: var(--text-3);
    font: var(--secondary);
    border-bottom: 1px solid var(--border);
  }
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li + li {
    border-top: 1px solid var(--border);
  }
  .row {
    width: 100%;
    height: 40px;
    background: none;
    border: 0;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .row:hover {
    background: var(--raised);
  }
  .row:disabled {
    cursor: default;
  }
  .row span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .d,
  .t {
    color: var(--text-2);
  }
  .o {
    color: var(--text-2);
  }
  .o.missed {
    color: var(--text);
  }
  .pbody {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .pdue {
    display: flex;
    align-items: baseline;
    gap: 10px;
    color: var(--text-2);
  }
  .pdue b {
    color: var(--text);
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
  }
  dl {
    margin: 0;
    border-top: 1px solid var(--border);
    max-width: 520px;
  }
  dl div {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 7px 0;
    border-bottom: 1px solid var(--divider);
  }
  dl div:last-child {
    border-bottom: 0;
  }
  dt {
    color: var(--text-2);
  }
  dd {
    margin: 0;
    font-variant-numeric: tabular-nums;
  }
  .pnote {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
    max-width: 640px;
  }
  .pact {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 16px 16px;
    min-width: 0;
  }
  .pact .quiet {
    padding: 0;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pq {
    padding: 14px 16px;
  }
  @media (max-width: 1247.98px) {
    .cards {
      grid-template-columns: minmax(0, 1fr);
    }
    .card + .card {
      border-left: 0;
      border-top: 1px solid var(--border);
    }
  }
</style>
