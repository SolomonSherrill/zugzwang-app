<script lang="ts">
  /** The Challenge popover (MinimalFriend-challenge.html; ruling C1): Play as, the ten live time controls,
   *  the ratings line, Cancel and Send challenge. Once sent it waits for the answer, with Cancel; a decline
   *  or an expiry is said here. An accepted challenge opens Play (live.svelte.ts). Unrated; no
   *  correspondence games. */
  import { onDestroy, onMount } from 'svelte'
  import Button from '../ui/Button.svelte'
  import ChallengeForm from './ChallengeForm.svelte'
  import { friendsApi, type AskedColour, type StartRating, type TimeControl } from './friendsApi'
  import { errorText } from './friendsState.svelte'
  import { cancelChallenge, forgetSent, live, secondsLeft, sendChallenge } from './live.svelte'
  import { mmss, ratingsLine } from './liveModel'

  interface Props {
    handle: string
    online: boolean
    onclose: () => void
  }
  let { handle, online, onclose }: Props = $props()
  let colour = $state<AskedColour>('random')
  let tc = $state<TimeControl>('5+0')
  let ratings = $state<{ you: StartRating; them: StartRating } | null>(null)
  let error = $state<string | null>(null)
  let busy = $state(false)
  let now = $state(Date.now())
  let ticker: ReturnType<typeof setInterval> | undefined
  const sent = $derived(live.sent[handle.toLowerCase()])

  $effect(() => {
    const t = tc
    friendsApi.ratings(handle, t).then((r) => (ratings = r)).catch(() => (ratings = null))
  })
  async function go() {
    busy = true
    error = null
    try {
      await sendChallenge(handle, tc, colour)
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = false
    }
  }
  async function cancel() {
    if (sent?.outcome === 'waiting') await cancelChallenge(handle)
    forgetSent(handle)
    onclose()
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      void cancel()
    }
  }
  onMount(() => (ticker = setInterval(() => (now = Date.now()), 250)))
  onDestroy(() => clearInterval(ticker))
</script>

<svelte:window onkeydown={onKey} />

<div class="pop" role="dialog" aria-label="Challenge {handle}">
  <div class="head"><span class="t">Challenge {handle}</span><span class="st" class:on={online}>{online ? 'Online' : 'Offline'}</span></div>
  {#if sent && sent.outcome === 'waiting'}
    <p class="wait" role="status">
      Waiting for {handle} to answer: a {sent.challenge.tc} game. Expires in {mmss(secondsLeft(sent.challenge, now))}.
    </p>
    <div class="acts"><Button variant="quiet" onclick={cancel}>Cancel challenge</Button></div>
  {:else if sent && sent.outcome !== 'accepted'}
    <p class="wait" role="status">
      {sent.outcome === 'declined' ? `${handle} declined.` : sent.outcome === 'expired' ? `${handle} did not answer in time.` : sent.outcome === 'busy' ? `${handle} started another game.` : 'Challenge cancelled.'}
    </p>
    <div class="acts">
      <Button variant="quiet" onclick={cancel}>Close</Button>
      <Button variant="primary" onclick={() => forgetSent(handle)}>Challenge again</Button>
    </div>
  {:else}
    <ChallengeForm bind:colour bind:tc idPrefix="pop-{handle}" />
    <div class="note">
      {ratingsLine(ratings?.you ?? null, ratings?.them ?? null, handle, tc)} Unrated. The game is saved to both your libraries and analysed afterwards.
    </div>
    {#if error}<p class="err" role="alert">{error}</p>{/if}
    <div class="acts">
      <Button variant="quiet" onclick={cancel}>Cancel</Button>
      <Button variant="primary" disabled={busy || !online} onclick={go}>Send challenge</Button>
    </div>
  {/if}
</div>

<style>
  .pop {
    width: 440px;
    max-width: calc(100vw - 32px);
    box-sizing: border-box;
    background: var(--raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    text-align: left;
    color: var(--text);
    font: var(--body);
    cursor: default;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .t {
    font-size: 15px;
    font-weight: 600;
  }
  .st {
    color: var(--text-3);
    font: var(--secondary);
  }
  .st.on {
    color: var(--online, #4ade80);
  }
  .note {
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    color: var(--text-2);
    font: var(--secondary);
    line-height: 1.55;
  }
  .wait {
    margin: 0;
    color: var(--text-2);
  }
  .err {
    margin: 0;
    color: var(--loss);
    font: var(--secondary);
  }
  .acts {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
  }
</style>
