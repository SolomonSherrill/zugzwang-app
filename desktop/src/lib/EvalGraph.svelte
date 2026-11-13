<script lang="ts">
  import type { GraphMarker } from './report'

  interface Props {
    /** White's win probability per position (0 = start); null = not scored. The
     *  same scale every claim in the game report is made on. */
    series: (number | null)[]
    /** Position on the board: 0 = start, i = after ply i-1. */
    currentPly: number
    onseek: (position: number) => void
    markers?: GraphMarker[]
    /** First position from which the game never came back into doubt. */
    decided?: { position: number; side: 'white' | 'black' } | null
    /** Shown over an unscored opening stretch, e.g. "book". */
    gapLabel?: string | null
    gap?: number
    /** Position after the move that left the user's clock under a tenth of the start. */
    lowClock?: number | null
    /** Where the book stopped: the position before the first non-book move. */
    bookExit?: { position: number; label: string } | null
    /** The slow decline's stretch, shaded (slice 4). */
    slide?: { from: number; to: number } | null
  }
  let {
    series,
    currentPly,
    onseek,
    markers = [],
    decided = null,
    gapLabel = null,
    gap = 0,
    lowClock = null,
    bookExit = null,
    slide = null,
  }: Props = $props()

  const H = 132
  const PAD = 10
  const MID = H / 2
  // Faint guides at the report's "decided" band edges (core/game_report.DECIDED).
  const DECIDED = 0.8

  let w = $state(320)
  let hover = $state<number | null>(null)

  // Positions, not plies: series has one more entry than the game has moves.
  const n = $derived(Math.max(1, series.length - 1))
  const xAt = (k: number) => (k / n) * w
  const yAt = (wp: number) => PAD + (1 - Math.max(0, Math.min(1, wp))) * (H - 2 * PAD)
  const clampY = (y: number) => Math.max(0, Math.min(H, y))

  type Pt = { x: number; y: number; k: number }

  /** Runs of consecutive scored positions. The line breaks across an unscored one
   *  rather than holding the previous value, which would draw a confident curve
   *  over moves nothing measured. */
  const segments = $derived.by(() => {
    const runs: Pt[][] = []
    let cur: Pt[] = []
    series.forEach((v, k) => {
      if (v === null) {
        if (cur.length) runs.push(cur)
        cur = []
      } else cur.push({ x: xAt(k), y: yAt(v), k })
    })
    if (cur.length) runs.push(cur)
    return runs
  })

  function smooth(pts: Pt[]): string {
    if (pts.length < 2) return pts.length ? `M ${pts[0].x} ${pts[0].y}` : ''
    let d = `M ${pts[0].x.toFixed(2)} ${pts[0].y.toFixed(2)}`
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] ?? pts[i]
      const p1 = pts[i]
      const p2 = pts[i + 1]
      const p3 = pts[i + 2] ?? p2
      const c1x = p1.x + (p2.x - p0.x) / 6
      const c1y = clampY(p1.y + (p2.y - p0.y) / 6)
      const c2x = p2.x - (p3.x - p1.x) / 6
      const c2y = clampY(p2.y - (p3.y - p1.y) / 6)
      d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
    }
    return d
  }

  const runs = $derived(segments.filter((s) => s.length > 1))
  const linePaths = $derived(runs.map(smooth))
  const areaPaths = $derived(
    runs.map((s) => {
      const d = smooth(s)
      return `${d} L ${s[s.length - 1].x.toFixed(2)} ${MID} L ${s[0].x.toFixed(2)} ${MID} Z`
    }),
  )

  const cursorX = $derived(xAt(currentPly))
  const cursorV = $derived(series[currentPly] ?? null)
  const hoverX = $derived(hover !== null ? xAt(hover) : null)

  function markerY(position: number): number {
    const v = series[position]
    return v === null || v === undefined ? MID : yAt(v)
  }

  function positionFromEvent(e: PointerEvent | MouseEvent): number {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    return Math.max(0, Math.min(n, Math.round(frac * n)))
  }
  function onMarker(e: MouseEvent, position: number) {
    e.stopPropagation()
    onseek(position)
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="graph"
  bind:clientWidth={w}
  onclick={(e) => onseek(positionFromEvent(e))}
  onpointermove={(e) => (hover = positionFromEvent(e))}
  onpointerleave={() => (hover = null)}
>
  <svg viewBox="0 0 {w} {H}" width={w} height={H}>
    <defs>
      <clipPath id="eg-top"><rect x="0" y="0" width={w} height={MID} /></clipPath>
      <clipPath id="eg-bottom"><rect x="0" y={MID} width={w} height={MID} /></clipPath>
      <linearGradient id="eg-white" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--side-white)" stop-opacity="0.95" />
        <stop offset="100%" stop-color="var(--side-white)" stop-opacity="0.6" />
      </linearGradient>
      <linearGradient id="eg-black" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--side-black)" stop-opacity="0.6" />
        <stop offset="100%" stop-color="var(--side-black)" stop-opacity="0.95" />
      </linearGradient>
    </defs>

    {#if decided}
      <rect
        x={xAt(decided.position)}
        y="0"
        width={Math.max(0, w - xAt(decided.position))}
        height={H}
        class="decided {decided.side}"
      />
    {/if}

    {#if slide}
      <rect
        x={xAt(slide.from)}
        y="0"
        width={Math.max(2, xAt(slide.to) - xAt(slide.from))}
        height={H}
        class="slide"
      />
    {/if}

    {#each areaPaths as d, k (k)}
      <path {d} fill="url(#eg-white)" clip-path="url(#eg-top)" />
      <path {d} fill="url(#eg-black)" clip-path="url(#eg-bottom)" />
    {/each}
    <line x1="0" y1={yAt(DECIDED)} x2={w} y2={yAt(DECIDED)} class="band" />
    <line x1="0" y1={yAt(1 - DECIDED)} x2={w} y2={yAt(1 - DECIDED)} class="band" />
    <line x1="0" y1={MID} x2={w} y2={MID} class="midline" />
    {#each linePaths as d, k (k)}
      <path {d} class="curve" fill="none" />
    {/each}

    {#if gap > 1 && gapLabel}
      <!-- Left-aligned: most unscored openings are short, and a label centred over
           a few plies runs off the graph's edge. -->
      <text x="6" y={MID - 6} class="gap-label">{gapLabel}</text>
    {/if}

    {#if decided}
      <line x1={xAt(decided.position)} y1="0" x2={xAt(decided.position)} y2={H} class="pnr" />
    {/if}

    {#if bookExit}
      <line x1={xAt(bookExit.position)} y1="0" x2={xAt(bookExit.position)} y2="14" class="tick" />
      <text x={xAt(bookExit.position) + 4} y="11" class="tick-label">{bookExit.label}</text>
    {/if}

    {#if lowClock !== null}
      <line x1={xAt(lowClock)} y1={H - 14} x2={xAt(lowClock)} y2={H} class="tick" />
      <text x={xAt(lowClock) + 4} y={H - 4} class="tick-label">low clock</text>
    {/if}

    {#if hoverX !== null}
      <line x1={hoverX} y1="0" x2={hoverX} y2={H} class="hover" />
    {/if}

    <line x1={cursorX} y1="0" x2={cursorX} y2={H} class="cursor" />
    {#if cursorV !== null}
      <circle cx={cursorX} cy={yAt(cursorV)} r="3.4" class="cursor-dot" />
    {/if}

    {#each markers as m (m.n)}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <g class="marker {m.tone}" onclick={(e) => onMarker(e, m.position)}>
        <circle cx={xAt(m.position)} cy={markerY(m.position)} r="12" class="hit" />
        <circle cx={xAt(m.position)} cy={markerY(m.position)} r="8.5" class="dot" />
        <text x={xAt(m.position)} y={markerY(m.position) + 3.5} text-anchor="middle">{m.n}</text>
      </g>
    {/each}
  </svg>
  <span class="axis top">White</span>
  <span class="axis bottom">Black</span>
</div>

<style>
  .graph {
    position: relative;
    height: 132px;
    cursor: pointer;
    border-radius: var(--radius);
    border: 1px solid var(--divider);
    background: var(--bg-surface);
    overflow: hidden;
    flex-shrink: 0;
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
  }
  .axis {
    position: absolute;
    left: 6px;
    font-size: 10px;
    color: var(--text-muted);
    opacity: 0.7;
    pointer-events: none;
  }
  .axis.top {
    top: 3px;
  }
  .axis.bottom {
    bottom: 3px;
  }
  .midline {
    stroke: var(--text-muted);
    stroke-opacity: 0.45;
    stroke-width: 1;
    stroke-dasharray: 3 4;
  }
  .band {
    stroke: var(--text-muted);
    stroke-opacity: 0.18;
    stroke-width: 1;
  }
  .decided {
    opacity: 0.12;
  }
  .decided.white {
    fill: var(--side-white);
  }
  .decided.black {
    fill: var(--side-black);
  }
  .slide {
    fill: var(--danger);
    opacity: 0.1;
  }
  .pnr {
    stroke: var(--text-muted);
    stroke-opacity: 0.7;
    stroke-width: 1;
    stroke-dasharray: 2 2;
  }
  .curve {
    stroke: var(--text);
    stroke-opacity: 0.55;
    stroke-width: 1.4;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .gap-label {
    font-size: 11px;
    fill: var(--text-muted);
    opacity: 0.8;
  }
  .tick {
    stroke: var(--text-muted);
    stroke-width: 2;
  }
  .tick-label {
    font-size: 10px;
    fill: var(--text-muted);
  }
  .hover {
    stroke: var(--text-muted);
    stroke-opacity: 0.45;
    stroke-width: 1;
  }
  .cursor {
    stroke: var(--accent);
    stroke-width: 1.4;
    stroke-opacity: 0.9;
  }
  .cursor-dot {
    fill: var(--accent);
    stroke: var(--bg-surface);
    stroke-width: 1.5;
  }
  .marker .hit {
    fill: transparent;
  }
  .marker .dot {
    stroke: var(--bg-surface);
    stroke-width: 1.5;
  }
  .marker.you .dot {
    fill: var(--danger);
  }
  .marker.opponent .dot {
    fill: var(--accent);
  }
  .marker.neutral .dot {
    fill: var(--text-muted);
  }
  .marker text {
    font-size: 10px;
    font-weight: 700;
    fill: var(--bg-surface);
    pointer-events: none;
  }
  .marker:hover .dot {
    stroke: var(--text);
  }
</style>
