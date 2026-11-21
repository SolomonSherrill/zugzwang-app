<script lang="ts">
  /**
   * The Report's chart (DESIGN.md "Review: report"): Eval, Material or Time over the game,
   * the game's own phase bands, the key moments as dots, the current move as a line with
   * its tooltip; click to jump. 380 × 134 viewBox, scaled to the panel's width.
   */
  import type { PhaseBand } from './reviewModel'
  import type { QualityClass } from '../ui/moveQuality'
  import { QUALITY } from '../ui/moveQuality'
  import ChartReadout from '../ui/ChartReadout.svelte'
  import { readoutText, type Readout } from '../ui/readoutModel'

  export type ChartMode = 'eval' | 'material' | 'time'
  interface Props {
    mode: ChartMode
    /** White's win probability per position, 0..1; null where unscored */
    series: (number | null)[]
    material: number[]
    /** seconds spent per ply; empty with no clocks */
    spent: (number | null)[]
    /** which side's bars are the user's (chart-you); null when unattributed */
    you: 'white' | 'black' | null
    startsWhite: boolean
    bands: PhaseBand[]
    dots: { position: number; cls: QualityClass }[]
    current: number
    /** the readout's label for a position (ruling 12 of 2026-11-20, fourth): the move and the
     *  value in this mode; the current move's label stays as the chart's tooltip */
    readout: (position: number) => Readout | null
    onjump: (position: number) => void
  }
  let { mode, series, material, spent, you, startsWhite, bands, dots, current, readout, onjump }: Props = $props()

  const W = 380
  const TOP = 10
  const MID = 60
  const BOT = 110
  const n = $derived(Math.max(2, series.length))
  const x = (i: number) => +((i / (n - 1)) * W).toFixed(1)
  const yEval = (wp: number) => +(TOP + (1 - wp) * (BOT - TOP)).toFixed(1)

  const evalPts = $derived.by(() => {
    const pts: string[] = []
    series.forEach((wp, i) => {
      if (wp !== null) pts.push(`${x(i)},${yEval(wp)}`)
    })
    return pts
  })
  const areaPts = $derived.by(() => {
    if (!evalPts.length) return ''
    const first = evalPts[0].split(',')[0]
    const last = evalPts[evalPts.length - 1].split(',')[0]
    return `${first},${MID} ${evalPts.join(' ')} ${last},${MID}`
  })

  const matMax = $derived(Math.max(4, ...material.map((m) => Math.abs(m))))
  const yMat = (m: number) => +(MID - (m / matMax) * 45).toFixed(1)
  const matPath = $derived.by(() => {
    if (!material.length) return ''
    let d = `M0,${yMat(material[0])}`
    for (let i = 1; i < material.length; i++) d += ` H${x(i)} V${yMat(material[i])}`
    return d + ` H${W}`
  })

  const spentMax = $derived(Math.max(1, ...spent.map((s) => s ?? 0)))
  const bars = $derived.by(() =>
    spent.map((s, ply) => {
      const white = (ply + (startsWhite ? 0 : 1)) % 2 === 0
      const h = s === null ? 0 : Math.max(1, (s / spentMax) * 46)
      const side = white ? 'white' : 'black'
      return { x: x(ply + 1), y2: white ? MID - h : MID + h, mine: you === side }
    }),
  )

  const curY = $derived.by(() => {
    if (mode === 'eval') {
      const wp = series[current]
      return wp === null || wp === undefined ? null : yEval(wp)
    }
    if (mode === 'material') return yMat(material[current] ?? 0)
    return null
  })

  // The readout's points: the eval line, the material step, or the tip of each time bar.
  const readoutPoints = $derived.by(() =>
    Array.from({ length: n }, (_, i) => {
      let y: number | null = null
      if (mode === 'eval') {
        const wp = series[i]
        y = wp === null || wp === undefined ? null : yEval(wp)
      } else if (mode === 'material') y = i < material.length ? yMat(material[i]) : null
      else if (i > 0 && spent[i - 1] !== null && spent[i - 1] !== undefined) y = bars[i - 1].y2
      return { x: x(i), y }
    }),
  )

  let svg: SVGSVGElement | undefined = $state()
  function click(e: MouseEvent) {
    if (!svg) return
    const r = svg.getBoundingClientRect()
    const frac = (e.clientX - r.left) / r.width
    onjump(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))))
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') onjump(Math.max(0, current - 1))
    else if (e.key === 'ArrowRight') onjump(Math.min(n - 1, current + 1))
    else return
    e.preventDefault()
  }
  const LABEL = { eval: 'Evaluation', material: 'Material', time: 'Time spent per move' }
</script>

<ChartReadout
  points={readoutPoints}
  vw={W}
  vh={134}
  label={readout}
  labelTop={14}
  guideTop={TOP}
  guideBottom={BOT}
  {current}
  pinned={current > 0 ? current : null}
>
<svg
  bind:this={svg}
  class="chart"
  viewBox="0 0 380 134"
  width="100%"
  role="slider"
  aria-label="{LABEL[mode]} through the game. Click to jump to a move."
  aria-valuemin={0}
  aria-valuemax={n - 1}
  aria-valuenow={current}
  aria-valuetext={readoutText(readout(current)) || 'Start'}
  tabindex="0"
  onclick={click}
  onkeydown={key}
>
  <line x1="0" y1={TOP} x2={W} y2={TOP} stroke="var(--divider)" />
  <line x1="0" y1={MID} x2={W} y2={MID} stroke="var(--border-control)" stroke-dasharray="2 4" />
  <line x1="0" y1={BOT} x2={W} y2={BOT} stroke="var(--divider)" />
  {#each bands.slice(1) as b (b.phase)}
    <line x1={x(b.from)} y1={TOP} x2={x(b.from)} y2={BOT} stroke="var(--border)" />
  {/each}
  {#if mode === 'time'}
    <text x="3" y="21" class="axis">White</text>
    <text x="3" y="105" class="axis">Black</text>
  {:else}
    <text x="3" y="21" class="axis">White</text>
    <text x="3" y="105" class="axis">Black</text>
  {/if}
  {#if mode === 'eval'}
    {#if areaPts}<polygon points={areaPts} fill="var(--text)" opacity="0.06" />{/if}
    <polyline points={evalPts.join(' ')} fill="none" stroke="var(--chart-line)" stroke-width="1.5" stroke-linejoin="round" />
    {#each dots as d (d.position)}
      {#if series[d.position] !== null && series[d.position] !== undefined}
        <circle cx={x(d.position)} cy={yEval(series[d.position]!)} r="3.5" fill="var({QUALITY[d.cls].fill})" />
      {/if}
    {/each}
  {:else if mode === 'material'}
    <path d={matPath} fill="none" stroke="var(--chart-line)" stroke-width="1.5" />
  {:else}
    {#each bars as b, i (i)}
      <line x1={b.x} y1={MID} x2={b.x} y2={b.y2} stroke={b.mine ? 'var(--chart-you)' : 'var(--chart-opponent)'} stroke-width="2.2" />
    {/each}
  {/if}
  <line x1={x(current)} y1={TOP} x2={x(current)} y2={BOT} stroke="var(--text)" stroke-opacity="0.5" />
  {#if curY !== null}
    <circle cx={x(current)} cy={curY} r="4" fill="var(--bg)" stroke="var(--text)" stroke-width="2" />
  {/if}
  {#each bands as b (b.phase)}
    <text x={(x(b.from) + x(b.to)) / 2} y="127" class="phase" text-anchor="middle">{b.phase}</text>
  {/each}
</svg>
</ChartReadout>

<style>
  .chart {
    display: block;
    cursor: pointer;
  }
  .chart:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .axis {
    fill: #5a5b62;
    font-size: 9px;
    font-family: var(--sans);
  }
  .phase {
    fill: var(--text-3);
    font-size: 10px;
    font-family: var(--sans);
  }
</style>
