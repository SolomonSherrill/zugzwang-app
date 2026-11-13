<script lang="ts">
  interface Props {
    ms: number
    active: boolean
  }
  let { ms, active }: Props = $props()

  const low = $derived(ms < 10_000)

  const display = $derived.by(() => {
    const clamped = Math.max(0, ms)
    const totalS = Math.floor(clamped / 1000)
    const m = Math.floor(totalS / 60)
    const s = totalS % 60
    if (low) {
      const tenths = Math.floor((clamped % 1000) / 100)
      return `${m}:${String(s).padStart(2, '0')}.${tenths}`
    }
    return `${m}:${String(s).padStart(2, '0')}`
  })
</script>

<div class="clock" class:active class:low>{display}</div>

<style>
  .clock {
    font-size: 22px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
    padding: 4px 13px;
    border-radius: var(--radius-sm);
    background: var(--bg-raised);
    border: 1px solid transparent;
    color: var(--text-muted);
    transition:
      background-color 120ms ease,
      border-color 120ms ease,
      color 120ms ease;
  }
  .clock.active {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--text);
  }
  .clock.low {
    color: var(--danger);
  }
  .clock.low.active {
    animation: low-pulse 1s ease-in-out infinite;
  }
  @keyframes low-pulse {
    0%,
    100% {
      background: color-mix(in srgb, var(--danger) 18%, var(--bg-raised));
    }
    50% {
      background: var(--bg-raised);
    }
  }
</style>
