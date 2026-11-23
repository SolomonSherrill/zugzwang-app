<script lang="ts">
  /** Friends, signed in (MinimalFriends.html): add by handle, requests, the friends list (online
   *  first), and your linked accounts until both are proven. Challenge buttons wait for FRIENDS-2. */
  import Button from '../ui/Button.svelte'
  import Avatar from './Avatar.svelte'
  import LinkedAccounts from './LinkedAccounts.svelte'
  import { friendsApi, type FriendsList, type Linked } from './friendsApi'
  import { ago, dayLabel, handleShape, onlineFirst, presence, ratingCell, recordLabel } from './friendsModel'
  import { errorText, friendsState, refreshList } from './friendsState.svelte'

  interface Props {
    list: FriendsList
    linked: Linked[] | null
    onopen: (handle: string) => void
    onlinked: () => void
    /** "now", for the harness's fixed clock */
    now?: number
  }
  let { list, linked, onopen, onlinked, now = Date.now() }: Props = $props()
  let add = $state('')
  let note = $state<{ text: string; bad: boolean } | null>(null)
  let busy = $state(false)
  const friends = $derived(onlineFirst(list.friends))
  const source = $derived(friendsState.status?.ratingSource?.source.split(',')[0] ?? 'ChessGoals')
  const requests = $derived([
    ...list.incoming.map((r) => ({ ...r, dir: 'in' as const })),
    ...list.outgoing.map((r) => ({ ...r, dir: 'out' as const })),
  ])
  const needLinks = $derived(linked !== null && !(['chesscom', 'lichess'] as const).every((s) => linked.some((l) => l.site === s && l.verified)))

  async function send() {
    const h = add.trim()
    const bad = handleShape(h)
    if (!h || bad) {
      note = { text: bad ?? 'Type a handle.', bad: true }
      return
    }
    busy = true
    note = null
    try {
      const r = await friendsApi.request(h)
      note = { text: r.status === 'friends' ? `You and ${r.handle} are friends.` : `Request sent to ${r.handle}.`, bad: false }
      add = ''
      await refreshList()
    } catch (e) {
      note = { text: errorText(e), bad: true }
    } finally {
      busy = false
    }
  }
  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      await refreshList()
    } catch (e) {
      note = { text: errorText(e), bad: true }
    }
  }
</script>

<main class="page">
  <div class="add">
    <label class="search">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"
        ><circle cx="9" cy="8" r="4" /><path d="M2 21c1-4 4-6 7-6s6 2 7 6M19 8v6M16 11h6" /></svg
      >
      <input type="text" spellcheck="false" autocomplete="off" placeholder="Add a friend by their handle" aria-label="Friend's handle" bind:value={add}
        onkeydown={(e) => e.key === 'Enter' && send()} />
    </label>
    <Button disabled={busy} onclick={send}>Send request</Button>
    {#if note}<span class="note" class:bad={note.bad} role="status">{note.text}</span>{/if}
  </div>

  {#if requests.length}
    <section class="panel" aria-labelledby="req-h">
      <div class="phead bordered"><h2 id="req-h">Requests <span class="count">{requests.length}</span></h2></div>
      <ul>
        {#each requests as r, i (r.dir + r.id)}
          <li class="req" class:first={i === 0}>
            <Avatar handle={r.handle} size={24} />
            <span class="strong">{r.handle}</span>
            <span class="text2">{r.dir === 'in' ? 'wants to be friends' : 'Request sent'}</span>
            <span class="grow"></span>
            <span class="when">{ago(r.created, now)}</span>
            {#if r.dir === 'in'}
              <span class="pair">
                <Button onclick={() => act(() => friendsApi.answer(r.id, true))}>Accept</Button>
                <Button variant="quiet" onclick={() => act(() => friendsApi.answer(r.id, false))}>Decline</Button>
              </span>
            {:else}
              <Button variant="quiet" onclick={() => act(() => friendsApi.cancel(r.id))}>Cancel</Button>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <section class="panel" aria-labelledby="fr-h">
    <div class="phead"><h2 id="fr-h">Friends <span class="count">{friends.length}</span></h2><span class="muted">Online first</span></div>
    {#if friends.length}
      <div class="grid colhead" aria-hidden="true"><span>Friend</span><span>Ratings</span><span>Won, drawn, lost</span><span>Last game</span><span></span></div>
      <ul>
        {#each friends as f (f.handle)}
          {@const p = presence(f, now)}
          <li>
            <button type="button" class="grid row" onclick={() => onopen(f.handle)} aria-label="{f.handle}, {p.text}">
              <span class="who">
                <Avatar handle={f.handle} size={28} online={p.online} />
                <span class="names"><span class="el strong">{f.handle}</span><span class="el sub" class:on={p.online}>{p.text}</span></span>
              </span>
              <span class="el ratings">
                {#if !f.linked.length}<span class="muted">No linked accounts</span>
                {:else if !f.ratings.length}<span class="muted">{f.hasData ? 'No rated games' : 'Loading…'}</span>
                {:else}
                  {#each f.ratings as r (r.speed)}
                    {@const c = ratingCell(r, source)}
                    <span title={c.title}>{c.label} <span class="fig">{c.value}</span></span>
                  {/each}
                {/if}
              </span>
              {#if f.record.games}<span class="fig">{recordLabel(f.record)}</span>{:else}<span class="muted">No games yet</span>{/if}
              <span class="muted">{dayLabel(f.lastGame, new Date(now))}</span>
              <span class="end"></span>
            </button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="empty">No friends yet. Add one by their handle above; they accept in their app.</p>
    {/if}
  </section>

  {#if (needLinks || friendsState.chesscomLink.state === 'linked') && linked}<LinkedAccounts {linked} onchange={onlinked} />{/if}

  {#if list.blocked.length}
    <p class="blocked">
      Blocked: {#each list.blocked as b, i (b.handle)}{i ? ', ' : ''}{b.handle}
        <button type="button" class="link" onclick={() => act(() => friendsApi.unblock(b.handle))}>Unblock</button>{/each}
    </p>
  {/if}
  <p class="foot">
    Ratings come from your friends' linked Chess.com and Lichess accounts. A Lichess-only rating shows as ≈, converted to the Chess.com scale with the
    ChessGoals rating comparison.
  </p>
</main>

<style>
  .page {
    padding: 20px 28px 28px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    max-width: 1180px;
    width: 100%;
    box-sizing: border-box;
  }
  .add {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 320px;
    padding: 5px 10px;
    box-sizing: border-box;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    background: var(--surface);
    color: var(--text-3);
  }
  .search:focus-within {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .search input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: 0;
    outline: none;
    color: var(--text);
    font: var(--secondary);
  }
  .note {
    font: var(--secondary);
    color: var(--text-2);
  }
  .note.bad {
    color: var(--loss);
  }
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    overflow: hidden;
  }
  .phead {
    box-sizing: content-box;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
  }
  .phead.bordered {
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
  }
  .count,
  .muted,
  .when {
    color: var(--text-3);
    font-weight: 400;
  }
  .muted,
  .when {
    font: var(--secondary);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .req {
    box-sizing: content-box;
    display: flex;
    align-items: center;
    gap: 12px;
    height: 48px;
    padding: 0 16px;
    border-top: 1px solid var(--divider);
  }
  .req.first {
    border-top: 0;
  }
  .pair {
    display: flex;
    gap: var(--space-2);
  }
  .strong {
    font-weight: 500;
  }
  .text2 {
    color: var(--text-2);
  }
  .grow {
    flex: 1;
  }
  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1.2fr) 120px 84px 104px;
    gap: 20px;
    align-items: center;
    padding: 0 16px;
  }
  .colhead {
    box-sizing: content-box;
    height: 30px;
    color: var(--text-3);
    font: var(--secondary);
    border-top: 1px solid var(--border);
  }
  .row {
    box-sizing: content-box;
    width: 100%;
    height: 52px;
    border: 0;
    border-top: 1px solid var(--divider);
    background: transparent;
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
  .who {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .names {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .el {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .sub {
    color: var(--text-3);
    font: var(--secondary);
  }
  .sub.on {
    color: var(--win);
  }
  .ratings {
    display: flex;
    gap: 14px;
    color: var(--text-2);
  }
  .fig {
    color: var(--text);
  }
  .empty,
  .foot,
  .blocked {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .empty {
    padding: 0 16px 16px;
  }
  .link {
    background: none;
    border: 0;
    padding: 0 4px;
    color: var(--text-2);
    text-decoration: underline;
    font: inherit;
    cursor: pointer;
  }
</style>
