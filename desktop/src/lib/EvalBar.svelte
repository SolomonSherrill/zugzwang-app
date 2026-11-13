<script lang="ts">
  import { labelOnWhite } from './evalBar'

  interface Props {
    /** white win probability 0..1, or null when the ply has no eval */
    wp: number | null
    label: string
    orientation: 'white' | 'black'
  }
  let { wp, label, orientation }: Props = $props()

  // A missing eval is not a drawn position. Resting the bar at half made an
  // unanalysed ply indistinguishable from a dead-equal one, so null gets its
  // own state instead of a fabricated 0.5.
  const hasEval = $derived(wp !== null)
  const whitePct = $derived((wp ?? 0) * 100)
  // label sits at the white end of the bar (bottom when white POV)
  const whiteAtBottom = $derived(orientation === 'white')

  // The bar's height decides where 1 % of it falls in pixels, so it has to be
  // measured rather than assumed — it ranges 450–680 px with the window.
  let barH = $state(0)
  const onWhite = $derived(labelOnWhite(whitePct, barH))
</script>

<div
  class="eval-bar"
  class:flipped={!whiteAtBottom}
  class:no-eval={!hasEval}
  bind:clientHeight={barH}
>
  {#if hasEval}
    <div class="black-half" style="height: {100 - whitePct}%"></div>
    <div class="white-half" style="height: {whitePct}%"></div>
    {#if label}
      <span class="label" class:on-white={onWhite}>{label}</span>
    {/if}
  {:else}
    <span class="label no-eval-mark" title="No evaluation for this move">–</span>
  {/if}
</div>

<style>
  .eval-bar {
    position: relative;
    width: 16px;
    height: 100%;
    display: flex;
    flex-direction: column;
    border-radius: 3px;
    overflow: hidden;
    background: var(--bg-raised);
  }
  .black-half {
    background: #403a32;
    transition: height 180ms ease;
  }
  .white-half {
    background: #e8e2d4;
    transition: height 180ms ease;
  }
  .eval-bar.flipped {
    flex-direction: column-reverse;
  }
  /* Hatched rather than a flat fill: reads as "nothing measured here" instead of
     as some third eval colour. */
  .eval-bar.no-eval {
    background: repeating-linear-gradient(
      135deg,
      var(--bg-raised) 0 4px,
      #4a443b 4px 8px
    );
  }
  .no-eval-mark {
    top: 50%;
    bottom: auto;
    transform: translateY(-50%);
    color: var(--text-dim, #8a8175);
    font-size: 11px;
  }
  .eval-bar.flipped .no-eval-mark {
    top: 50%;
  }
  .label {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 3px;
    text-align: center;
    font-size: 8.5px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.04em;
    color: #e8e2d4;
  }
  .eval-bar.flipped .label {
    bottom: auto;
    top: 3px;
  }
  .label.on-white {
    color: #353025;
  }
</style>
