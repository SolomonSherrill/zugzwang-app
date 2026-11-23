<script lang="ts">
  /** Challenges to you, on any screen (ruling S2; MinimalFriends-challenge.html): one banner per challenge,
   *  newest on top, "Expires in m:ss" by the server's clock, Accept before Decline, neither red nor green.
   *  Accept opens the game on Play. BETA-6 (FRIENDS.md ruling S6, replacing FRIENDS-2's decided item 17): the
   *  banners float as cards at the top right of the content, below the screen's header: nothing moves when one
   *  appears, and on Play's game screens they lie over the side column (420 px wide), never the board or the
   *  clocks (the player strips), which the layout checks measure (overlays.browser.test.ts).
   *  FIX-B6 (ruling S8): the banner never covers a control on any screen. The banners float only where their cards
   *  cover no control (bannerRoom.ts); otherwise the screen makes room: the banners become a strip at the top of the
   *  content, in its flow, and the screen below it is that much shorter. Decided when the banners or the screen
   *  change (measured once, invisible, at the floating place), and re-checked while floating, since a screen's
   *  content can arrive or move later; once making room it stays so until the banners or the screen change. */
  import { onDestroy, onMount, tick } from 'svelte'
  import { controlsUnder } from './bannerRoom'
  import ChallengeBanner from './ChallengeBanner.svelte'
  import { friendsApi, type Challenge, type StartRating } from './friendsApi'
  import { answerChallenge, incomingChallenges, secondsLeft, youPlay } from './live.svelte'
  import { ratingsLine } from './liveModel'

  interface Props {
    /** the screen showing (the app's route): a new screen decides float or make room again */
    screen?: string
  }
  let { screen = '' }: Props = $props()

  let now = $state(Date.now())
  let box: HTMLDivElement | undefined = $state()
  /** measure: at the floating place, invisible, while deciding; float; room: a strip in the content's flow */
  let mode = $state<'measure' | 'float' | 'room'>('measure')
  const covers = () => !!box && controlsUnder([...box.querySelectorAll('.banner')].map((b) => b.getBoundingClientRect())).length > 0
  let decided = ''
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
  $effect(() => {
    const key = `${screen}|${list.length}`
    if (!list.length || key === decided) return
    decided = key
    mode = 'measure'
    void tick().then(() =>
      requestAnimationFrame(() => {
        if (decided === key) mode = covers() ? 'room' : 'float'
      }),
    )
  })
  onMount(
    () =>
      (ticker = setInterval(() => {
        now = Date.now()
        if (mode === 'float' && covers()) mode = 'room'
      }, 250)),
  )
  onDestroy(() => clearInterval(ticker))
</script>

{#if list.length}
  <div class="banners" class:room={mode === 'room'} class:measure={mode === 'measure'} data-mode={mode} aria-label="Challenges" bind:this={box}>
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
  .banners.measure {
    visibility: hidden;
    pointer-events: none;
  }
  /* S8: making room. A strip at the top of the content (the first child of main.content, a column), the cards in a
     row from the right as when floating, wrapping when they don't fit; the screen below shrinks by its height. */
  .banners.room {
    position: static;
    flex: none;
    width: auto;
    max-width: none;
    max-height: 45vh;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-end;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }
  .banners.room :global(.banner) {
    width: 388px;
    max-width: 100%;
  }
</style>
