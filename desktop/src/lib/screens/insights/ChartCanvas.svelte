<script lang="ts">
  import { onMount } from 'svelte'
  import {
    Chart,
    LineController,
    LineElement,
    PointElement,
    BarController,
    BarElement,
    DoughnutController,
    ArcElement,
    LinearScale,
    CategoryScale,
    Filler,
    Tooltip,
    type ChartConfiguration,
  } from 'chart.js'

  // Registered once for the whole insights screen.
  Chart.register(
    LineController,
    LineElement,
    PointElement,
    BarController,
    BarElement,
    DoughnutController,
    ArcElement,
    LinearScale,
    CategoryScale,
    Filler,
    Tooltip,
  )

  // `make` reads current theme/filter/data and returns a fresh config; `watch`
  // is any reactive value whose change should rebuild the chart.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let { make, watch }: { make: () => ChartConfiguration<any>; watch?: unknown } = $props()

  let canvas: HTMLCanvasElement | undefined = $state()
  let chart: Chart | null = null

  $effect(() => {
    // touch reactive deps so the effect re-runs on change
    void watch
    if (!canvas) return
    chart?.destroy()
    chart = new Chart(canvas, make())
  })

  onMount(() => () => chart?.destroy())
</script>

<canvas bind:this={canvas}></canvas>
