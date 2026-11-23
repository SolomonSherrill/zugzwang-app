<script lang="ts">
  /** Challenges to you, on any screen (ruling S2; MinimalFriends-challenge.html): one banner per challenge,
   *  newest on top, "Expires in m:ss" by the server's clock, Accept before Decline, neither red nor green.
   *  Accept opens the game on Play. BETA-6 (FRIENDS.md ruling S6, replacing FRIENDS-2's decided item 17): the
   *  banners float as cards at the top right of the content, below the screen's header: nothing moves when one
   *  appears, and on Play's game screens they lie over the side column (420 px wide), never the board or the
   *  clocks (the player strips), which the layout checks measure (overlays.browser.test.ts). */
  import { onDestroy, onMount } from 'svelte'
  import ChallengeBanner from './ChallengeBanner.svelte'
  import { friendsApi, type Challenge, type StartRating } from './friendsApi'
  import { answerChallenge, incomingChallenges, secondsLeft, youPlay } from './live.svelte'
  import { ratingsLine } from './liveModel'

  let now = $state(Date.now())
  let ticker: ReturnType<typeof setInterval> | undefined
  let ratings = $state<Record<string, { you: StartRating; them: StartRating } | null>>({})
  let errors = $state<Record<string, string>>({})
  const list = $derived(incomingChallenges().filter((c) => secondsLeft(c, now) > 0).reverse())
  $effect(() => {
    for (const c of list) {
      if (c.id in ratings) continue
      ratings[c.id] = null
      friendsApi
        .ratings(c.from_handle, c.tc)
        .then((r) => {
          ratings[c.id] = r
        })
        .catch(() => {})
    }
  })
  async function answer(c: Challenge, accept: boolean) {
    const e = await answerChallenge(c, accept)
    if (e) errors[c.id] = e
  }
  onMount(() => (ticker = setInterval(() => (now = Date.now()), 250)))
  onDestroy(() => clearInterval(ticker))
</script>

{#if list.length}
  <div class="banners" aria-label="Challenges">
    {#each list as c (c.id)}
      {@const r = ratings[c.id]}
      <ChallengeBanner
        from={c.from_handle}
        timeControl={c.tc}
        youPlay={youPlay(c)}
        rematch={c.rematch_of != null}
        note={(errors[c.id] ? errors[c.id] + ' ' : '') + 'Unrated. ' + ratingsLine(r?.you ?? null, r?.them ?? null, c.from_handle, c.tc)}
        expiresIn={secondsLeft(c, now)}
        onaccept={() => answer(c, true)}
        ondecline={() => answer(c, false)}
      />
    {/each}
  </div>
{/if}

<style>
  /* fixed, so it takes no room in any screen's flow; 16 px in from the window's right edge and 8 px below the
     48 px header, 388 px wide: inside the 420 px side column of Play's game screens */
  .banners {
    position: fixed;
    top: calc(var(--header-height) + 8px);
    right: 16px;
    width: 388px;
    max-width: calc(100vw - 32px);
    max-height: calc(100vh - var(--header-height) - 24px);
    overflow-y: auto;
    z-index: 45;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .banners :global(.banner) {
    max-width: none;
  }
</style>
