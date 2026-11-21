<script lang="ts">
  import { QUALITY, iconMetrics, isQualityClass, type IconSize } from './moveQuality'

  interface Props {
    cls: string
    size?: IconSize
    /** hide from assistive tech when a neighbouring word already names the class */
    decorative?: boolean
  }
  let { cls, size = 16, decorative = false }: Props = $props()
  const q = $derived(isQualityClass(cls) ? QUALITY[cls] : null)
  const m = $derived(iconMetrics(size))
</script>

{#if q}
  <span
    class="mq"
    role={decorative ? undefined : 'img'}
    aria-hidden={decorative ? 'true' : undefined}
    aria-label={decorative ? undefined : q.name}
    data-cls={q.cls}
    style:width="{size}px"
    style:height="{size}px"
    style:background="var({q.fill})"
    style:font-size="{m.font}px"
  >
    {#if q.mark}{q.mark}{:else if q.symbol}<svg
        width={m.symbol}
        height={m.symbol}
        viewBox="0 0 24 24"
        aria-hidden="true"
        ><path
          d={q.symbol.d}
          fill={q.symbol.mode === 'fill' ? 'var(--q-ink)' : 'none'}
          stroke={q.symbol.mode === 'stroke' ? 'var(--q-ink)' : 'none'}
          stroke-width={q.symbol.strokeWidth ?? 0}
          stroke-linecap="round"
          stroke-linejoin="round"
        /></svg
      >{/if}
  </span>
{/if}

<style>
  .mq {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-round);
    color: var(--q-ink);
    font-family: var(--sans);
    font-weight: 800;
    letter-spacing: -0.04em;
    line-height: 1;
    vertical-align: middle;
  }
  svg {
    display: block;
  }
</style>
