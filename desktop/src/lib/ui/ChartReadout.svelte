<script lang="ts">
  /**
   * A chart's readout (owner ruling 12 of 2026-11-20, fourth): wraps a chart and draws, for the
   * point under the pointer, a vertical guide, a dot on the line and a small label (raised
   * surface, 1px border, tabular figures). Keyboard focus shows the same readout: on a move chart
   * for the current move (the chart's own slider moves it), on a date chart for a point ←/→
   * (Home, End) move, the box itself taking focus. The pointer leaving hides the hover readout;
   * a `pinned` point keeps its label alone (Review's current-move tooltip). Positions come from
   * the chart's own units (its viewBox) scaled by the box's measured size; the label is placed
   * by readoutModel.placeLabel and never leaves the box's width.
   */
  import type { Snippet } from 'svelte'
  import MoveQualityIcon from './MoveQualityIcon.svelte'
  import { nearestIndex, placeLabel, readoutText, stepIndex, type Readout } from './readoutModel'
  import { alreadyHandled } from './keyTargets'

  interface Props {
    /** each point in the chart's units; y null draws no dot (an unscored position, no bar) */
    points: { x: number; y: number | null }[]
    /** the chart's size in those units (its viewBox) */
    vw: number
    vh: number
    label: (i: number) => Readout | null
    placement?: 'side' | 'above'
    /** side: the label's top, in chart units */
    labelTop?: number
    /** the guide's extent, in chart units */
    guideTop?: number
    guideBottom?: number
    /** move charts: the point keyboard focus shows (the current move) */
    current?: number | null
    /** a point whose label shows when nothing is hovered or focused */
    pinned?: number | null
    /** date charts: the box takes focus and ←/→ move the point; keys group points by date */
    keyboard?: { label: string; keys?: string[] } | null
    /** the point the readout shows (hover or focus), for charts that hide their own labels then */
    shown?: number | null
    children: Snippet
  }
  let {
    points, vw, vh, label, placement = 'side', labelTop = 4, guideTop = 0, guideBottom, current = null,
    pinned = null, keyboard = null, shown = $bindable(null), children,
  }: Props = $props()

  let box: HTMLDivElement | undefined = $state()
  let bw = $state(0)
  let bh = $state(0)
  let hover = $state<number | null>(null)
  let focused = $state(false)
  let kb = $state<number | null>(null)
  let lw = $state(0)
  let lh = $state(0)

  const sx = $derived(vw > 0 ? bw / vw : 1)
  const sy = $derived(vh > 0 ? bh / vh : 1)
  const valid = (i: number | null) => (i !== null && i >= 0 && i < points.length ? i : null)
  const active = $derived(valid(hover) ?? (focused ? valid(keyboard ? kb : current) : null))
  const at = $derived(active ?? valid(pinned))
  const r = $derived(at === null ? null : label(at))
  $effect(() => {
    shown = active
  })
  // A jump (arrow keys on a move chart, a click) moves the readout to the new current point
  // until the pointer moves again.
  let lastCurrent: number | null = null
  $effect(() => {
    if (current !== lastCurrent) {
      lastCurrent = current
      hover = null
    }
  })

  const px = $derived(at === null ? 0 : points[at].x * sx)
  const py = $derived(at === null || points[at].y === null ? null : points[at].y! * sy)
  const place = $derived(placeLabel({ x: px, labelW: lw, labelH: lh, boxW: bw, placement, top: labelTop * sy }))
  const gTop = $derived(guideTop * sy)
  const gBot = $derived((guideBottom ?? vh) * sy)

  function move(e: PointerEvent) {
    if (!box || !points.length) return
    const rect = box.getBoundingClientRect()
    const xs = points.map((p) => p.x * sx)
    hover = nearestIndex(xs, e.clientX - rect.left)
  }
  function focusIn(e: FocusEvent) {
    const t = e.target as Element | null
    let visible = true
    try {
      visible = !!t?.matches(':focus-visible')
    } catch {
      visible = true
    }
    focused = visible
    if (keyboard && kb === null) kb = points.length - 1
  }
  function focusOut(e: FocusEvent) {
    if (box && e.relatedTarget instanceof Node && box.contains(e.relatedTarget)) return
    focused = false
  }
  /** A navigation key pressed while the chart has focus is keyboard use: show the readout then,
   *  as the focus ring does (:focus-visible matches after a key press). WebKit does not count a
   *  lone modifier, nor re-match :focus-visible for an element focused after a click, so
   *  focusIn alone left a move chart without its readout there (UI-BUILD-4 E). Capture phase:
   *  the chart's own handler may stop the event. */
  function keyUse(e: KeyboardEvent) {
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) focused = true
  }
  function key(e: KeyboardEvent) {
    if (!keyboard || alreadyHandled(e) || !points.length) return
    const keys = keyboard.keys ?? points.map((_, i) => String(i))
    const i = kb ?? points.length - 1
    if (e.key === 'ArrowLeft') kb = stepIndex(keys, i, -1)
    else if (e.key === 'ArrowRight') kb = stepIndex(keys, i, 1)
    else if (e.key === 'Home') kb = 0
    else if (e.key === 'End') kb = points.length - 1
    else return
    e.preventDefault()
    focused = true
    hover = null
  }
</script>

{#if keyboard}
  <div
    class="readout-box"
    bind:this={box}
    bind:clientWidth={bw}
    bind:clientHeight={bh}
    tabindex="0"
    role="slider"
    aria-label={keyboard.label}
    aria-valuemin={0}
    aria-valuemax={Math.max(0, points.length - 1)}
    aria-valuenow={kb ?? points.length - 1}
    aria-valuetext={readoutText(label(kb ?? points.length - 1))}
    onpointermove={move}
    onpointerleave={() => (hover = null)}
    onfocusin={focusIn}
    onfocusout={focusOut}
    onkeydowncapture={keyUse}
    onkeydown={key}
  >
    {@render children()}
    {@render overlay()}
  </div>
{:else}
  <div
    class="readout-box"
    bind:this={box}
    bind:clientWidth={bw}
    bind:clientHeight={bh}
    role="presentation"
    onpointermove={move}
    onpointerleave={() => (hover = null)}
    onfocusin={focusIn}
    onfocusout={focusOut}
    onkeydowncapture={keyUse}
  >
    {@render children()}
    {@render overlay()}
  </div>
{/if}

{#snippet overlay()}
  {#if active !== null}
    <span class="guide" aria-hidden="true" style:left="{px}px" style:top="{gTop}px" style:height="{Math.max(0, gBot - gTop)}px"></span>
    {#if py !== null}<span class="dot" aria-hidden="true" style:left="{px}px" style:top="{py}px"></span>{/if}
  {/if}
  {#if r}
    <span
      class="label"
      aria-hidden="true"
      bind:offsetWidth={lw}
      bind:offsetHeight={lh}
      style:left="{place.left}px"
      style:top="{place.top}px"
      style:visibility={lw ? 'visible' : 'hidden'}
    >
      <span class="t">{r.title}</span>
      {#if r.cls}<MoveQualityIcon cls={r.cls} size={16} decorative />{/if}
      {#if r.value}<span class="sep">·</span><span class="v">{r.value}</span>{/if}
      {#if r.note}<span class="sep">·</span><span class="n">{r.note}</span>{/if}
    </span>
  {/if}
{/snippet}

<style>
  .readout-box {
    position: relative;
  }
  /* the box is the chart's size, so its measured size scales the chart's units */
  .readout-box > :global(svg) {
    display: block;
  }
  .readout-box[role='slider']:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
    border-radius: 2px;
  }
  .guide {
    position: absolute;
    width: 1px;
    margin-left: -0.5px;
    background: var(--text);
    opacity: 0.35;
    pointer-events: none;
  }
  .dot {
    position: absolute;
    width: 7px;
    height: 7px;
    margin: -3.5px 0 0 -3.5px;
    border-radius: var(--radius-round);
    background: var(--text);
    box-shadow: 0 0 0 2px var(--bg);
    pointer-events: none;
  }
  .label {
    position: absolute;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: var(--space-1);
    padding: 3px var(--space-3);
    background: var(--raised);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    font: var(--secondary);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    pointer-events: none;
  }
  .t {
    color: var(--text);
    font-weight: 500;
  }
  .v {
    color: var(--text);
  }
  .sep,
  .n {
    color: var(--text-3);
  }
</style>
