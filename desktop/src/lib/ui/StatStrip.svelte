<script lang="ts">
  /** Figures in a row: a label (secondary, text-3), the metric (24px, 500) and an optional
   *  sub line. Separated by 1px border lines; tabular figures. */
  export interface Stat {
    label: string
    value: string
    sub?: string
    /** a word the sub line starts with in win/loss colour (always beside a word) */
    tone?: 'win' | 'loss' | null
  }
  interface Props {
    stats: Stat[]
  }
  let { stats }: Props = $props()
</script>

<dl class="strip" style:grid-template-columns="repeat({stats.length}, minmax(0, 1fr))">
  {#each stats as s (s.label)}
    <div class="stat">
      <dt>{s.label}</dt>
      <dd class="metric">{s.value}</dd>
      {#if s.sub}<dd class="sub" class:win={s.tone === 'win'} class:loss={s.tone === 'loss'}>{s.sub}</dd>{/if}
    </div>
  {/each}
</dl>

<style>
  .strip {
    display: grid;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
  }
  .stat {
    padding: var(--space-5);
    min-width: 0;
  }
  .stat + .stat {
    border-left: 1px solid var(--border);
  }
  dt {
    font: var(--secondary);
    color: var(--text-3);
  }
  dd {
    margin: 0;
  }
  .metric {
    margin-top: 6px;
    font: var(--metric);
    letter-spacing: var(--metric-letter-spacing);
    font-variant-numeric: tabular-nums;
  }
  .sub {
    margin-top: 4px;
    font: var(--secondary);
    color: var(--text-3);
  }
  .sub.win {
    color: var(--win);
  }
  .sub.loss {
    color: var(--loss);
  }
</style>
