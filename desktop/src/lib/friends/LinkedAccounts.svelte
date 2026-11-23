<script lang="ts">
  /** Proving your Chess.com and Lichess accounts (rulings K1, K2): Lichess by its sign-in (the browser
   *  opens), Chess.com by a short code in your public profile's Location until Chess.com's own sign-in
   *  is approved. Shown on the Friends screen while an account is not proven.
   *  Chess.com waits for Chess.com (BETA-5 ruling K3): its public profile can take up to 12 hours to
   *  update, so after a check finds no code the link waits ("Waiting for Chess.com"), the sidecar checks
   *  every 15 minutes while the app is open, and the code lasts 24 hours. The pending link and its code
   *  are the sidecar's (friendsState.chesscomLink), so they survive a restart. */
  import Button from '../ui/Button.svelte'
  import { friendsApi, type Linked } from './friendsApi'
  import { accounts } from '../settings.svelte'
  import { errorText, friendsState } from './friendsState.svelte'

  interface Props {
    linked: Linked[]
    onchange: () => void
  }
  let { linked, onchange }: Props = $props()
  const cc = $derived(linked.find((l) => l.site === 'chesscom'))
  const li = $derived(linked.find((l) => l.site === 'lichess'))
  const link = $derived(friendsState.chesscomLink)
  let busy = $state<'chesscom' | 'lichess' | null>(null)
  let error = $state<string | null>(null)
  let ccName = $state(accounts.chesscom ?? '')

  // linked by a check on its own (the heartbeat): read the proven name back from the server
  let announced = false
  $effect(() => {
    if (link.state === 'linked' && !cc?.verified && !announced) {
      announced = true
      onchange()
    }
    if (link.state !== 'linked') announced = false
  })

  async function startChesscom() {
    busy = 'chesscom'
    error = null
    try {
      friendsState.chesscomLink = await friendsApi.chesscomStart((link.state === 'expired' && link.username) || ccName.trim())
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = null
    }
  }
  async function checkChesscom() {
    if (link.state !== 'code' && link.state !== 'waiting') return
    busy = 'chesscom'
    error = null
    try {
      const out = await friendsApi.chesscomVerify(link.username ?? '')
      if (!out.checking) friendsState.chesscomLink = out
      if (out.state === 'linked') onchange()
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = null
    }
  }
  async function cancelChesscom() {
    error = null
    try {
      friendsState.chesscomLink = await friendsApi.chesscomCancel()
      onchange()
    } catch (e) {
      error = errorText(e)
    }
  }
  async function lichess() {
    busy = 'lichess'
    error = null
    try {
      await friendsApi.linkLichess()
      onchange()
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = null
    }
  }
  async function unlink(site: 'chesscom' | 'lichess') {
    error = null
    try {
      await friendsApi.unlink(site)
      onchange()
    } catch (e) {
      error = errorText(e)
    }
  }
  // Z4 (owner, 2026-11-22): Check now at most once every 30 s; the button says when it can be pressed again
  let nowMs = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (nowMs = Date.now()), 500)
    return () => clearInterval(t)
  })
  function checkNowWait(l: { checkNowAt?: number | null }, n: number): number {
    return l.checkNowAt ? Math.max(0, Math.ceil((l.checkNowAt - n) / 1000)) : 0
  }
</script>

<section class="panel" aria-labelledby="lk-h">
  <div class="head"><h2 id="lk-h">Your linked accounts</h2><span class="muted">Friends see your ratings and games from these</span></div>
  <div class="row">
    <span class="site">Chess.com</span>
    {#if cc?.verified}
      <span class="grow"
        >{cc.username} <span class="ok" title="Proven yours">✓</span
        >{#if link.state === 'linked'}<span class="sub" role="status">Linked. You can remove the code from your Location.</span>{/if}</span
      >
      {#if link.state === 'linked'}<Button variant="quiet" onclick={cancelChesscom}>OK</Button>{/if}
      <Button variant="quiet" onclick={() => unlink('chesscom')}>Unlink</Button>
    {:else if link.state === 'code'}
      <span class="grow">Put <strong class="code">{link.code}</strong> in your Chess.com profile's Location, then check. You can remove it afterwards.</span>
      <Button disabled={busy === 'chesscom'} onclick={checkChesscom}>{busy === 'chesscom' ? 'Checking…' : 'Check'}</Button>
      <Button variant="quiet" onclick={cancelChesscom}>Cancel</Button>
    {:else if link.state === 'waiting'}
      {@const wait = checkNowWait(link, nowMs)}
      <span class="grow"
        ><span class="title">Waiting for Chess.com</span> <strong class="code">{link.code}</strong>
        <span class="sub">Chess.com's public profile can take up to 12 hours to update. Leave the code in your Location; Zugzwang checks every 15 minutes while it's open.</span>
        {#if link.error}<span class="sub warn">Last check: {link.error}</span>{/if}</span
      >
      <!-- FRIENDS.md ruling Z4: at most once every 30 s (the sidecar holds it too) -->
      <Button disabled={busy === 'chesscom' || wait > 0} title={wait > 0 ? 'Check now can be pressed once every 30 seconds' : undefined} onclick={checkChesscom}
        >{busy === 'chesscom' ? 'Checking…' : wait > 0 ? `Check again in 0:${String(wait).padStart(2, '0')}` : 'Check now'}</Button
      >
      <Button variant="quiet" onclick={cancelChesscom}>Cancel</Button>
    {:else if link.state === 'expired'}
      <span class="grow"
        ><span class="title">The code expired</span> <strong class="code">{link.code}</strong>
        <span class="sub" role="status">Chess.com's profile did not show it within 24 hours, so Zugzwang stopped checking. Start again for a new code.</span></span
      >
      <Button disabled={busy === 'chesscom'} onclick={startChesscom}>Start again</Button>
      <Button variant="quiet" onclick={cancelChesscom}>Cancel</Button>
    {:else}
      <input class="name" type="text" spellcheck="false" placeholder="Chess.com username" aria-label="Chess.com username" bind:value={ccName} />
      <Button disabled={!ccName.trim() || busy === 'chesscom'} onclick={startChesscom}>Verify</Button>
    {/if}
  </div>
  <div class="row div">
    <span class="site">Lichess</span>
    {#if li?.verified}
      <span class="grow">{li.username} <span class="ok" title="Proven yours">✓</span></span>
      <Button variant="quiet" onclick={() => unlink('lichess')}>Unlink</Button>
    {:else}
      <span class="grow muted">Not linked</span>
      <Button disabled={busy === 'lichess'} onclick={lichess}>{busy === 'lichess' ? 'Waiting for Lichess…' : 'Sign in with Lichess'}</Button>
    {/if}
  </div>
  {#if error}<p class="err" role="alert">{error}</p>{/if}
</section>

<style>
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
  }
  .head {
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
  }
  .muted {
    color: var(--text-3);
    font: var(--secondary);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 48px;
    padding: 6px 16px;
    box-sizing: border-box;
  }
  .row.div {
    border-top: 1px solid var(--divider);
  }
  .site {
    width: 80px;
    flex: none;
    color: var(--text-2);
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .ok {
    color: var(--win);
  }
  .title {
    font: var(--body-strong);
  }
  .sub {
    display: block;
    margin-top: 2px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .sub.warn {
    color: var(--text-2);
  }
  .code {
    font-weight: 500;
    letter-spacing: 0.04em;
    user-select: all;
  }
  .name {
    flex: 1;
    min-width: 0;
    max-width: 240px;
    padding: 4px 10px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    color: var(--text);
    font: var(--body);
  }
  .err {
    margin: 0;
    padding: 0 16px 12px;
    color: var(--loss);
  }
</style>
