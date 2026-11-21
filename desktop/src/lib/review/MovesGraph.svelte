<script lang="ts">
  /** The Moves tab's graph (ruling 5): the eval line, 64 px, dots for brilliant, great,
   *  miss, mistake and blunder only, the current move as a line; click to jump. */
  import { QUALITY, type QualityClass } from '../ui/moveQuality'
  import ChartReadout from '../ui/ChartReadout.svelte'
  import type { Readout } from '../ui/readoutModel'

  interface Props {
    series: (number | null)[]
    dots: { ply: number; position: number; cls: QualityClass; title: string }[]
    current: number
    label: string
    /** the readout's label for a position (ruling 12 of 2026-11-20, fourth) */
    readout?: (position: number) => Readout | null
    onjump: (position: number) => void
  }
  let { series, dots, current, label, readout = () => null, onjump }: Props = $props()
  const n = $derived(Math.max(2, series.length))
  const x = (i: number) => (i / (n - 1)) * 380
  const y = (wp: number) => 4 + (1 - wp) * 56
  const pts = $derived(
    series
      .map((wp, i) => (wp === null ? null : `${x(i).toFixed(1)},${y(wp).toFixed(1)}`))
      .filter((p): p is string => p !== null),
  )
  const area = $derived(
    pts.length ? `${pts[0].split(',')[0]},32 ${pts.join(' ')} ${pts[pts.length - 1].split(',')[0]},32` : '',
  )
  const readoutPoints = $derived(
    Array.from({ length: n }, (_, i) => {
      const wp = series[i]
      return { x: x(i), y: wp === null || wp === undefined ? null : y(wp) }
    }),
  )
  let box: HTMLDivElement | undefined = $state()
  function click(e: MouseEvent) {
    if (!box) return
    const r = box.getBoundingClientRect()
    onjump(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))))
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') onjump(Math.max(0, current - 1))
    else if (e.key === 'ArrowRight') onjump(Math.min(n - 1, current + 1))
    else return
    e.preventDefault()
  }
</script>

<ChartReadout points={readoutPoints} vw={380} vh={64} label={readout} {current}>
<div
  class="graph"
  bind:this={box}
  tabindex="0"
  role="slider"
  aria-label={label}
  aria-valuemin={0}
  aria-valuemax={n - 1}
  aria-valuenow={current}
  onclick={click}
  onkeydown={key}
>
  <svg viewBox="0 0 380 64" preserveAspectRatio="none" width="100%" height="64" aria-hidden="true">
    <line x1="0" y1="32" x2="380" y2="32" stroke="var(--border-control)" stroke-dasharray="2 4" vector-effect="non-scaling-stroke" />
    {#if area}<polygon points={area} fill="var(--text)" opacity="0.06" />{/if}
    <polyline points={pts.join(' ')} fill="none" stroke="var(--chart-line)" stroke-width="1.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
    <line x1={x(current)} y1="0" x2={x(current)} y2="64" stroke="var(--text)" stroke-opacity="0.5" vector-effect="non-scaling-stroke" />
  </svg>
  {#each dots as d (d.ply)}
    {@const wp = series[d.position]}
    {#if wp !== null && wp !== undefined}
      <span
        class="dot"
        class:cur={d.position === current}
        title={d.title}
        style="left: {(d.position / (n - 1)) * 100}%; top: {(y(wp) / 64) * 100}%; background: var({QUALITY[d.cls].fill})"
      ></span>
    {/if}
  {/each}
</div>
</ChartReadout>

<style>
  .graph {
    position: relative;
    height: 64px;
    cursor: pointer;
  }
  .graph:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  svg {
    display: block;
  }
  .dot {
    position: absolute;
    width: 8px;
    height: 8px;
    margin: -4px 0 0 -4px;
    border-radius: 50%;
    box-shadow: 0 0 0 2px var(--bg);
    pointer-events: none;
  }
  .dot.cur {
    width: 10px;
    height: 10px;
    margin: -5px 0 0 -5px;
    box-shadow:
      0 0 0 2px var(--bg),
      0 0 0 3.5px var(--text);
  }
</style>
