<script lang="ts">
  /** A friend's profile (MinimalFriend.html; rulings S3, G1, G3, G4): ratings, your games together
   *  (Chess.com and Lichess games between your linked accounts), scouting, results by time control, how
   *  their games end, and their recent games with Analyse on request. All from the games' headers and
   *  moves; no engine runs here. Data over an hour old refreshes on open; Refresh does it now. */
  import { onDestroy, onMount } from 'svelte'
  import { sidecar } from '../api'
  import Button from '../ui/Button.svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import Avatar from './Avatar.svelte'
  import ChallengePopover from './ChallengePopover.svelte'
  import { floating } from '../ui/floating'
  import { sparkline } from '../home/homeModel'
  import { friendsApi, type OpeningRow, type Profile, type RecentGame } from './friendsApi'
  import {
    ago, dayLabel, deltaLabel, outcomeWord, presence, recordLabel, scoutingNote, shortOpening, siteLabel, speedLabel, splitLine, strip,
    tcLabel, wdlWidths,
  } from './friendsModel'
  import { errorText, friendsState, mine, refreshList } from './friendsState.svelte'

  interface Props {
    handle: string
    onback: () => void
    onanalyse: (gameId: number, label: string) => void
    now?: number
  }
  let { handle, onback, onanalyse, now = Date.now() }: Props = $props()
  let profile = $state<Profile | null>(null)
  let error = $state<string | null>(null)
  let tab = $state<'asWhite' | 'vsE4' | 'vsD4'>('asWhite')
  let recentLimit = $state(10)
  let menu = $state(false)
  /** Remove friend and Block ask first, like Delete account (BETA-5 ruling S5) */
  let asking = $state<'remove' | 'block' | null>(null)
  let acting = $state(false)
  let allTogether = $state(false)
  // FRIENDS-2 (MinimalFriend-challenge.html): Challenge, for a friend online (C2)
  let challenging = $state(false)

  async function load(refresh = true) {
    try {
      profile = await friendsApi.profile(handle, mine(), recentLimit, 0, refresh)
      error = null
    } catch (e) {
      error = errorText(e)
    }
  }
  const onData = (d: { handle: string; state: string; message?: string }) => {
    if (d.handle.toLowerCase() !== handle.toLowerCase()) return
    if (d.state === 'done') void load(false)
    else if (d.state === 'error' && profile) profile.data.fetching = false
    else if (d.state === 'fetching' && profile) profile.data.fetching = true
  }
  onMount(() => {
    sidecar.on('friend_data', onData)
    void load(true)
  })
  onDestroy(() => sidecar.off('friend_data', onData))

  async function refresh() {
    if (!profile) return
    profile.data.fetching = true
    try {
      await friendsApi.refresh(handle)
    } catch (e) {
      error = errorText(e)
    }
  }
  async function older() {
    if (!profile) return
    profile.data.fetching = true
    await friendsApi.refresh(handle, true).catch((e) => (error = errorText(e)))
  }
  async function more() {
    recentLimit += 50
    await load(false)
  }
  function toggleMenu() {
    menu = !menu
    asking = null
  }
  async function removeOrBlock(kind: 'remove' | 'block') {
    acting = true
    try {
      if (kind === 'remove') await friendsApi.remove(handle)
      else await friendsApi.block(handle)
      menu = false
      asking = null
      await refreshList()
      onback()
    } catch (e) {
      error = errorText(e)
    } finally {
      acting = false
    }
  }

  const f = $derived(profile?.friend)
  const p = $derived(f ? presence(f, now) : null)
  const rows = $derived<OpeningRow[]>(profile ? profile.scouting[tab] : [])
  const cc = $derived(f?.linked.find((l) => l.site === 'chesscom'))
  const li = $derived(f?.linked.find((l) => l.site === 'lichess'))
  const updated = $derived(profile?.data.fetchedAt ? `Updated ${ago(new Date(profile.data.fetchedAt).getTime(), now)}` : 'Not loaded yet')
  const together = $derived(profile ? (allTogether ? profile.together : profile.together.slice(0, 5)) : [])
  const source = $derived(friendsState.status?.ratingSource)
  function bar(r: { games: number; won: number; drawn: number; lost: number; score: number | null }) {
    return wdlWidths(r)
  }
  function friendSide(g: RecentGame): 'white' | 'black' | null {
    const u = g.player.toLowerCase()
    return g.white?.toLowerCase() === u ? 'white' : g.black?.toLowerCase() === u ? 'black' : null
  }
  function since(ms: number): string {
    return new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(new Date(ms).getFullYear() !== new Date(now).getFullYear() ? { year: 'numeric' } : {}) })
  }
</script>

<div class="screen">
  <header>
    <div class="crumb">
      <button type="button" class="back" onclick={onback}>Friends</button><span class="sep" aria-hidden="true">/</span>
      <h1>{handle}</h1>
    </div>
    <div class="actions">
      <span class="upd">{profile?.data.fetching ? 'Updating…' : updated}</span>
      <Button variant="quiet" disabled={!profile || profile.data.fetching} onclick={refresh}>Refresh</Button>
      {#if profile?.friend.online}
        <div class="chal">
          <Button variant="primary" ariaHaspopup="dialog" ariaExpanded={challenging} onclick={() => (challenging = !challenging)}>Challenge</Button>
          {#if challenging}
            <div class="veil" role="presentation" onclick={() => (challenging = false)}></div>
                  <div class="popat" use:floating={{ gap: 6 }}><ChallengePopover {handle} online={profile.friend.online} onclose={() => (challenging = false)} /></div>
          {/if}
        </div>
      {/if}
      <div class="more">
        <Button variant="quiet" ariaLabel="More: Remove friend, Block" ariaExpanded={menu} ariaHaspopup="menu" onclick={toggleMenu}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
        </Button>
        {#if menu}
          {#if asking}
            <div class="menu asking" role="alertdialog" aria-labelledby="ask-q">
              <p id="ask-q" class="q">{asking === 'remove' ? `Remove ${handle} as a friend?` : `Block ${handle}?`}</p>
              <div class="pair">
                <Button variant="danger" disabled={acting} onclick={() => removeOrBlock(asking!)}>{asking === 'remove' ? 'Remove' : 'Block'}</Button>
                <Button variant="quiet" onclick={() => ((asking = null), (menu = false))}>Keep</Button>
              </div>
            </div>
          {:else}
            <div class="menu" role="menu">
              <button type="button" role="menuitem" class="danger" onclick={() => (asking = 'remove')}>Remove friend</button>
              <button type="button" role="menuitem" class="danger" onclick={() => (asking = 'block')}>Block</button>
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </header>

  {#if error && !profile}
    <div class="pad"><EmptyState sentence="Could not open {handle}'s profile." sub={error} tone="error" action={{ label: 'Try again', run: () => load(true) }} /></div>
  {:else if !profile || !f || !p}
    <div class="pad"><EmptyState sentence="Opening {handle}'s profile…" /></div>
  {:else}
    <main class="page">
      <div class="who">
        <Avatar {handle} size={40} online={p.online} />
        <div>
          <div class="name">{handle}</div>
          <div class="facts">
            <span class:on={p.online}>{p.text}</span>
            {#if cc}<span>Chess.com <span class="t2">{cc.username}</span> <span class="ok" title="Verified">✓</span></span>{:else}<span>Chess.com not linked</span>{/if}
            {#if li}<span>Lichess <span class="t2">{li.username}</span> <span class="ok" title="Verified">✓</span></span>{:else}<span>Lichess not linked</span>{/if}
            <span>Friends since {since(f.since)}</span>
          </div>
        </div>
      </div>

      {#if !f.linked.length}
        <EmptyState sentence="{handle} has no linked Chess.com or Lichess account yet, so there are no games to show." />
      {:else}
        <div class="strip">
          {#each strip(profile.ratings) as r (r.site + r.speed)}
            {@const d = deltaLabel(r.delta30)}
            <div class="cell rating">
              <div class="cv">
                <div class="lab">{speedLabel(r.speed)} on {siteLabel(r.site)}</div>
                <div class="metric">{r.rating}</div>
                {#if r.estimate != null}
                  <div class="sm" title="About {r.estimate} on Chess.com, from the {source?.source ?? 'ChessGoals'} table ({source?.retrieved ?? ''})">≈{r.estimate} on Chess.com</div>
                {:else if d}<div class="sm {d.tone}">{d.text}</div>{/if}
              </div>
              {#if r.spark?.length >= 2}
                <!-- FRIENDS-1B D: the rating after each rated game of the last 30 days (scouting.spark_series) -->
                <svg class="spark" width="72" height="26" viewBox="0 0 72 26" aria-hidden="true"
                  ><polyline points={sparkline(r.spark, 72, 26)} fill="none" stroke="var(--chart-line)" stroke-width="1.4" stroke-linejoin="round" /></svg
                >
              {/if}
            </div>
          {/each}
          {#each Array(Math.max(0, 3 - strip(profile.ratings).length)) as _, i (i)}<div class="cell"><div class="lab">&nbsp;</div></div>{/each}
          <div class="cell">
            <div class="lab">Your record</div>
            <div class="metric">{profile.record.games ? recordLabel(profile.record) : '–'}</div>
            <div class="sm muted">{profile.record.games ? `Won, drawn, lost in ${profile.record.games} games` : 'No games together yet'}</div>
          </div>
        </div>

        <div class="two">
          <section class="panel" aria-labelledby="h2h-h">
            <div class="ph"><h2 id="h2h-h">Your games together</h2><span class="muted">Here, on Chess.com and on Lichess</span></div>
            {#if together.length}
              <div class="hrow colhead" aria-hidden="true"><span>You</span><span></span><span>Time</span><span>Opening</span><span>Where</span><span class="r">Date</span></div>
              {#each together as g (g.id)}
                <div class="hrow">
                  <span class="res"><span class="rdot {g.result}" aria-hidden="true"></span>{outcomeWord(g.result)}</span>
                  {#if g.color}
                    <span class="sq {g.color}" role="img" title="You played {g.color === 'white' ? 'White' : 'Black'}" aria-label="You played {g.color === 'white' ? 'White' : 'Black'}"></span>
                  {:else}<span></span>{/if}
                  <span class="t2">{tcLabel(g.time_control)}</span>
                  <span class="el t2" title={g.opening}>{shortOpening(g.opening)} <span class="muted">{g.eco ?? ''}</span></span>
                  <span class="el muted">{g.where}</span>
                  <span class="r muted">{dayLabel(g.ended_at, new Date(now))}</span>
                </div>
              {/each}
              {#if profile.together.length > 5 && !allTogether}
                <div class="pfoot"><button type="button" class="q" onclick={() => (allTogether = true)}>All {profile.together.length} games</button></div>
              {/if}
            {:else}
              <p class="none">No games between you yet{Object.keys(mine()).length ? '' : ': add your usernames in Settings → Accounts to find them'}.</p>
            {/if}
          </section>

          <section class="panel" aria-labelledby="sc-h">
            <div class="ph">
              <h2 id="sc-h">Scouting</h2>
              <div class="seg" role="tablist" aria-label="Scouting view">
                {#each [['asWhite', 'As White'], ['vsE4', 'Against 1.e4'], ['vsD4', 'Against 1.d4']] as [v, l] (v)}
                  <button type="button" role="tab" aria-selected={tab === v} class:on={tab === v} onclick={() => (tab = v as typeof tab)}>{l}</button>
                {/each}
              </div>
            </div>
            {#if rows.length}
              <div class="srow colhead" aria-hidden="true"><span>Opening</span><span class="r">Games</span><span>Won, drawn, lost</span><span class="r">Score</span></div>
              {#each rows as r (r.opening)}
                {@const w = bar(r)}
                <div class="srow">
                  <span class="el" title={r.opening}>{shortOpening(r.opening)} <span class="muted">{r.eco ?? ''}</span></span>
                  <span class="r t2">{r.games}</span>
                  <span class="bar" role="img" aria-label="{r.won} won, {r.drawn} drawn, {r.lost} lost"
                    ><span class="w" style:width="{w[0]}%"></span><span class="d" style:width="{w[1]}%"></span><span class="l" style:width="{w[2]}%"></span></span
                  >
                  <span class="r">{r.score?.toFixed(1)}%</span>
                </div>
              {/each}
            {:else}
              <p class="none">No games of this kind.</p>
            {/if}
            <div class="pfoot muted">{scoutingNote(handle, profile.scouting.sites, profile.scouting.oldest, new Date(now))}</div>
          </section>
        </div>

        <div class="two">
          <section class="panel" aria-labelledby="tc-h">
            <div class="ph"><h2 id="tc-h">Results by time control</h2><span class="muted">Score</span></div>
            {#each profile.bySpeed as s, i (s.speed)}
              {@const w = bar(s)}
              <div class="trow" class:first={i === 0}>
                <span>{speedLabel(s.speed)}</span><span class="muted">{s.games} games</span>
                <span class="bar" role="img" aria-label="{s.won} won, {s.drawn} drawn, {s.lost} lost"
                  ><span class="w" style:width="{w[0]}%"></span><span class="d" style:width="{w[1]}%"></span><span class="l" style:width="{w[2]}%"></span></span
                >
                <span class="r">{Math.round(s.score ?? 0)}%</span>
              </div>
            {/each}
          </section>
          <section class="panel" aria-labelledby="end-h">
            <div class="ph"><h2 id="end-h">How their games end</h2><span class="muted">Draws {profile.endings.draws.pct}%</span></div>
            <div class="ends">
              {#each [['Won', profile.endings.won], ['Lost', profile.endings.lost]] as [label, s] (label)}
                {@const sp = s as typeof profile.endings.won}
                <div>
                  <div class="eh"><span>{label}</span><span class="t2">{sp.pct}%</span></div>
                  <div class="bar" role="img" aria-label={splitLine(sp)}
                    ><span class="m" style:width="{sp.by.mate}%"></span><span class="rs" style:width="{sp.by.resigned}%"></span><span class="tm" style:width="{sp.by.time}%"></span><span class="ot" style:width="{sp.by.other}%"></span></div
                  >
                  <div class="legend">{#each splitLine(sp).split('  ') as part (part)}<span>{part}</span>{/each}</div>
                </div>
              {/each}
            </div>
          </section>
        </div>

        <section class="panel" aria-labelledby="rg-h">
          <div class="ph"><h2 id="rg-h">{handle}'s recent games</h2><span class="muted">Not analysed. Analyse any of them on this computer.</span></div>
          {#if profile.recent.length}
            <div class="rrow colhead" aria-hidden="true"><span class="el" title={handle}>{handle}</span><span>Players</span><span>Opening</span><span>Time</span><span class="r">Date</span><span></span></div>
            {#each profile.recent as g (g.id)}
              {@const side = friendSide(g)}
              <!-- the row opens Analyse, as its button does (the button is the keyboard's way) -->
              <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
              <div class="rrow" onclick={() => onanalyse(g.id, `${g.white} – ${g.black}`)}>
                <span class="res"><span class="rdot {g.result}" aria-hidden="true"></span>{outcomeWord(g.result)}</span>
                <span class="players">
                  {#each [['white', g.white, g.white_elo], ['black', g.black, g.black_elo]] as [c, n, e] (c)}
                    <span class="el pl"><span class="sq {c}" aria-hidden="true"></span><span class="el"><span class:them={side === c} class:opp={side !== c}>{n}</span> <span class="muted">{e ? `(${e})` : ''}</span></span></span>
                  {/each}
                </span>
                <span class="op"><span class="el t2" title={g.opening}>{shortOpening(g.opening)} <span class="muted">{g.eco ?? ''}</span></span>
                  <Button size="sm" onclick={(e) => (e.stopPropagation(), onanalyse(g.id, `${g.white} – ${g.black}`))}>Analyse</Button></span>
                <span class="t2">{tcLabel(g.time_control)}</span>
                <span class="r muted" title="On {g.where}">{dayLabel(g.ended_at, new Date(now))}</span>
                <svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
              </div>
            {/each}
          {:else}
            <p class="none">{profile.data.fetching ? 'Loading their games…' : 'No games in the last 12 months.'}</p>
          {/if}
          <div class="pfoot center">
            {#if profile.recentTotal > profile.recent.length}<button type="button" class="q" onclick={more}>Show 50 more</button>{/if}
            {#if !profile.data.complete}<button type="button" class="q" disabled={profile.data.fetching} onclick={older}>Load games older than 12 months</button>{/if}
          </div>
        </section>
      {/if}
      {#if error}<p class="err" role="alert">{error}</p>{/if}
    </main>
  {/if}
</div>

<style>
  /* the popover's backdrop: a click outside closes it, and what lies under it is out of reach meanwhile */
  .veil {
    position: fixed;
    inset: 0;
    z-index: 29;
    background: transparent;
    border: 0;
    padding: 0;
    cursor: default;
  }
  .chal {
    position: relative;
  }
  .popat {
    position: fixed;
    z-index: 30;
  }
  .screen {
    display: flex;
    flex-direction: column;
    min-height: 0;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    flex: none;
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
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .upd {
    color: var(--text-3);
    font: var(--secondary);
    margin-right: 4px;
  }
  .more {
    position: relative;
  }
  .menu {
    position: absolute;
    right: 0;
    top: calc(100% + 4px);
    z-index: 20;
    min-width: 160px;
    padding: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    display: flex;
    flex-direction: column;
  }
  .menu button {
    text-align: left;
    background: none;
    border: 0;
    border-radius: var(--radius-control);
    padding: 6px 10px;
    color: var(--text-2);
    font: var(--body);
    cursor: pointer;
  }
  .menu button:hover {
    background: var(--raised);
    color: var(--text);
  }
  /* ruling S5: the question, then the red confirming button and a quiet Keep */
  .menu.asking {
    width: 240px;
    padding: 12px;
    gap: 10px;
  }
  .q {
    margin: 0;
    color: var(--text);
    font: var(--body);
    overflow-wrap: anywhere;
  }
  .pair {
    display: flex;
    gap: var(--space-2);
  }
  /* ruling S4: Remove friend and Block are destructive, so red */
  .menu button.danger,
  .menu button.danger:hover {
    color: var(--loss);
  }
  .pad {
    padding: 20px 28px;
  }
  .page {
    padding: 20px 28px 28px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    max-width: 1180px;
    width: 100%;
    box-sizing: border-box;
  }
  .who {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .name {
    font: var(--heading);
  }
  .facts {
    display: flex;
    gap: 14px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .facts .on,
  .ok {
    color: var(--win);
  }
  .t2 {
    color: var(--text-2);
  }
  .muted {
    color: var(--text-3);
    font: var(--secondary);
  }
  .strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .cell {
    padding: 14px 16px;
    border-left: 1px solid var(--border);
  }
  .cell:first-child {
    border-left: 0;
  }
  .cell.rating {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 10px;
    min-width: 0;
  }
  .cv {
    min-width: 0;
  }
  .spark {
    flex: none;
  }
  .lab {
    color: var(--text-2);
    font: var(--secondary);
    margin-bottom: 4px;
  }
  .metric {
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
  }
  .sm {
    font: var(--secondary);
    margin-top: 4px;
    color: var(--text-3);
  }
  .sm.up {
    color: var(--win);
  }
  .sm.down {
    color: var(--loss);
  }
  .two {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
    min-width: 0;
  }
  .ph {
    box-sizing: content-box;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 16px;
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
    white-space: nowrap;
  }
  .colhead {
    height: 30px !important;
    color: var(--text-3);
    font: var(--secondary);
    border-top: 0 !important;
  }
  .hrow {
    box-sizing: content-box;
    display: grid;
    grid-template-columns: 72px 12px 44px minmax(0, 1fr) 84px 64px;
    gap: 14px;
    align-items: center;
    padding: 0 16px;
    height: 38px;
    border-top: 1px solid var(--divider);
  }
  .srow {
    box-sizing: content-box;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 44px 120px 52px;
    gap: 14px;
    align-items: center;
    padding: 0 16px;
    height: 40px;
    border-top: 1px solid var(--divider);
  }
  .trow {
    box-sizing: content-box;
    display: grid;
    grid-template-columns: 72px 84px minmax(0, 1fr) 52px;
    gap: 14px;
    align-items: center;
    padding: 0 16px;
    height: 40px;
    border-top: 1px solid var(--divider);
  }
  .trow.first {
    border-top: 0;
  }
  .rrow {
    display: grid;
    grid-template-columns: 72px minmax(0, 1.1fr) minmax(0, 1.4fr) 56px 64px 14px;
    gap: 20px;
    align-items: center;
    padding: 8px 16px;
    border-top: 1px solid var(--divider);
  }
  .rrow:hover {
    background: var(--surface);
  }
  .rrow:not(.colhead) {
    cursor: pointer;
  }
  .chev {
    color: var(--text-3);
  }
  .rrow .op :global(button) {
    visibility: hidden;
  }
  .rrow:hover .op :global(button),
  .rrow:focus-within .op :global(button) {
    visibility: visible;
  }
  .op {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .players {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .pl {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .them {
    color: var(--text-2);
  }
  .opp {
    color: var(--text);
    font-weight: 500;
  }
  .sq {
    flex: none;
    width: 9px;
    height: 9px;
    border-radius: 2px;
    box-sizing: border-box;
  }
  .sq.white {
    background: var(--text);
    border: 1px solid var(--text);
  }
  .sq.black {
    background: var(--bg);
    border: 1px solid var(--draw);
  }
  .r {
    text-align: right;
  }
  .res {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .rdot {
    width: 7px;
    height: 7px;
    border-radius: 4px;
    background: var(--draw);
  }
  .rdot.won {
    background: var(--win);
  }
  .rdot.lost {
    background: var(--loss);
  }
  .el {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    min-width: 0;
  }
  .bar {
    display: flex;
    height: 6px;
    border-radius: 3px;
    overflow: hidden;
    gap: 1px;
  }
  .bar .w {
    background: var(--win);
  }
  .bar .d {
    background: var(--draw);
  }
  .bar .l {
    background: var(--loss);
  }
  .bar .m {
    background: var(--text);
  }
  .bar .rs {
    background: var(--text-3);
  }
  .bar .tm {
    background: var(--disabled);
  }
  .bar .ot {
    background: var(--selected);
  }
  .ends {
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .eh {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .legend {
    display: flex;
    gap: 18px;
    margin-top: 6px;
    color: var(--text-3);
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
    flex: none;
    white-space: nowrap;
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 3px 10px;
    color: var(--text-3);
    font: var(--secondary);
    cursor: pointer;
  }
  .seg button.on {
    background: var(--selected);
    color: var(--text);
  }
  .pfoot {
    padding: 9px 16px;
    border-top: 1px solid var(--divider);
  }
  .pfoot.center {
    display: flex;
    justify-content: center;
    gap: 8px;
  }
  .pfoot:empty {
    display: none;
  }
  .q {
    background: transparent;
    border: 0;
    border-radius: var(--radius-control);
    padding: 3px 8px;
    color: var(--text-2);
    font: var(--secondary);
    cursor: pointer;
  }
  .q:hover {
    background: var(--raised);
    color: var(--text);
  }
  .none {
    margin: 0;
    padding: 12px 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .err {
    margin: 0;
    color: var(--loss);
  }
</style>
