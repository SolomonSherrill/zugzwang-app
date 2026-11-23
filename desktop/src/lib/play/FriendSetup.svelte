<script lang="ts">
  /** Play, new game, against a friend (MinimalPlaySetup-friend.html; ruling C1): your friends, online first
   *  (one who appears offline cannot be challenged, C2), Play as, the ten time controls, Send challenge (↵).
   *  The answer comes back here: waiting with Cancel, or why it did not start; an accepted challenge opens
   *  the game. */
  import { onDestroy, onMount, type Snippet } from 'svelte'
  import Kbd from '../ui/Kbd.svelte'
  import ChallengeForm from '../friends/ChallengeForm.svelte'
  import type { AskedColour, TimeControl } from '../friends/friendsApi'
  import { errorText, friendsState, refreshList } from '../friends/friendsState.svelte'
  import { cancelChallenge, forgetSent, live, secondsLeft, sendChallenge } from '../friends/live.svelte'
  import { mmss, speedWord } from '../friends/liveModel'
  import { onlineFirst, presence, ratingCell } from '../friends/friendsModel'

  interface Props {
    active?: boolean
    /** the Friends screen, for someone with no friends yet */
    onfriends?: () => void
    /** drawn first in the form: Play's "Against" choice */
    head?: Snippet
  }
  let { active = false, onfriends, head }: Props = $props()
  let colour = $state<AskedColour>('random')
  let tc = $state<TimeControl>('5+0')
  let pick = $state<string | null>(null)
  let error = $state<string | null>(null)
  let busy = $state(false)
  let now = $state(Date.now())
  let ticker: ReturnType<typeof setInterval> | undefined

  const friends = $derived(onlineFirst(friendsState.list?.friends ?? []))
  const online = $derived(friends.filter((f) => f.online))
  $effect(() => {
    if (!pick && online.length) pick = online[0].handle
  })
  const sent = $derived(pick ? live.sent[pick.toLowerCase()] : undefined)
  const speed = $derived(speedWord(tc))
  const source = $derived(friendsState.status?.ratingSource?.source ?? 'ChessGoals')

  async function go() {
    if (!pick || busy || sent?.outcome === 'waiting') return
    busy = true
    error = null
    try {
      await sendChallenge(pick, tc, colour)
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = false
    }
  }
  function onKey(e: KeyboardEvent) {
    if (!active || e.key !== 'Enter' || e.defaultPrevented) return
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'INPUT' || t.tagName === 'A' || (t.tagName === 'BUTTON' && t.getAttribute('role') !== 'radio'))) return
    e.preventDefault()
    void go()
  }
  onMount(() => {
    if (!friendsState.list) void refreshList()
    ticker = setInterval(() => (now = Date.now()), 250)
  })
  onDestroy(() => clearInterval(ticker))
</script>

<svelte:window onkeydown={onKey} />

<div class="form">
  {@render head?.()}
  <div>
    <div id="fr-l" class="lbl">Friend</div>
    {#if !friends.length}
      <p class="none">No friends yet. <button type="button" class="link" onclick={() => onfriends?.()}>Add one on Friends</button>; they accept in their app.</p>
    {:else}
      <div class="list" role="radiogroup" aria-labelledby="fr-l">
        {#each friends as f (f.handle)}
          {@const p = presence(f, now)}
          {@const r = f.ratings.find((x) => x.speed === speed) ?? f.ratings[0]}
          {#if f.online}
            <button type="button" role="radio" class="fr" aria-checked={pick === f.handle} onclick={() => (pick = f.handle)}>
              <span class="dot on" aria-hidden="true"></span>
              <span class="h" title={f.handle}>{f.handle}</span>
              {#if r}{@const c = ratingCell(r, source)}<span class="r" title={c.title}>{c.label} {c.value}</span>{/if}
            </button>
          {:else}
            <div class="fr off" aria-disabled="true">
              <span class="dot" aria-hidden="true"></span>
              <span class="h" title={f.handle}>{f.handle}</span>
              <span class="r">{p.text}</span>
            </div>
          {/if}
        {/each}
      </div>
    {/if}
  </div>
  <ChallengeForm bind:colour bind:tc idPrefix="play-friend" />
</div>
<div class="start">
  {#if sent && sent.outcome === 'waiting'}
    <button type="button" class="startbtn" onclick={() => pick && cancelChallenge(pick)}>Cancel challenge</button>
    <p class="saved" role="status">Waiting for {pick}: a {sent.challenge.tc} game. Expires in {mmss(secondsLeft(sent.challenge, now))}.</p>
  {:else}
    <button type="button" class="startbtn" disabled={!pick || busy} onclick={() => (sent ? (forgetSent(pick!), go()) : go())}
      >Send challenge <Kbd keys="↵" plain /></button
    >
    <p class="saved" role="status">
      {#if error}{error}
      {:else if sent && sent.outcome !== 'accepted'}{sent.outcome === 'declined' ? `${pick} declined.` : sent.outcome === 'expired' ? `${pick} did not answer in time.` : 'Challenge cancelled.'}
      {:else}Unrated. Saved to both your libraries, then analysed. Ratings shown: Chess.com {speed}.{/if}
    </p>
  {/if}
</div>

<style>
  .form {
    padding: var(--space-6);
    display: flex;
    flex-direction: column;
    gap: 22px;
    overflow-y: auto;
  }
  .lbl {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
    margin-bottom: 8px;
  }
  .list {
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    overflow: hidden;
  }
  .fr {
    width: 100%;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: transparent;
    border: 0;
    border-top: 1px solid var(--raised);
    color: var(--text);
    font: var(--body);
    text-align: left;
  }
  .fr:first-child {
    border-top: 0;
  }
  button.fr {
    cursor: pointer;
  }
  button.fr[aria-checked='true'] {
    background: var(--border);
  }
  .fr.off {
    color: var(--disabled);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 4px;
    background: var(--disabled);
    flex: none;
  }
  .dot.on {
    background: var(--online, #4ade80);
  }
  .h {
    flex: 1;
    min-width: 0;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fr.off .h {
    font-weight: 400;
  }
  .r {
    color: var(--text-2);
    white-space: nowrap;
  }
  .fr.off .r {
    color: var(--disabled);
  }
  .none {
    margin: 0;
    color: var(--text-3);
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text);
    text-decoration: underline;
    font: inherit;
    cursor: pointer;
  }
  .start {
    margin-top: auto;
    padding: 16px var(--space-6) var(--space-6);
    border-top: 1px solid var(--border);
  }
  .startbtn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: var(--primary);
    border: 1px solid var(--primary);
    border-radius: var(--radius-control);
    padding: 9px 12px;
    color: var(--primary-ink);
    font: var(--body-strong);
    cursor: pointer;
  }
  .startbtn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .saved {
    margin: 10px 0 0;
    text-align: center;
    color: var(--text-3);
    font: var(--secondary);
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
