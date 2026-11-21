<script lang="ts">
  /** A puzzle's result in this session: a 16px filled circle, a check in win for solved
   *  without a miss, a cross in loss otherwise (the mockup's marks; ink q-ink); or an
   *  outlined ring for the puzzle on the board. */
  interface Props {
    result: 'solved' | 'missed' | 'current'
  }
  let { result }: Props = $props()
</script>

{#if result === 'current'}
  <span class="dot current" role="img" aria-label="Current puzzle"></span>
{:else}
  <span class="dot {result}" role="img" aria-label={result === 'solved' ? 'Solved' : 'Missed'}>
    <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
      {#if result === 'solved'}
        <path d="M5 12.5l4.5 4.5L19.5 7" fill="none" stroke="var(--q-ink)" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" />
      {:else}
        <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" fill="none" stroke="var(--q-ink)" stroke-width="3.6" stroke-linecap="round" />
      {/if}
    </svg>
  </span>
{/if}

<style>
  .dot {
    width: 16px;
    height: 16px;
    border-radius: var(--radius-round);
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .solved {
    background: var(--win);
  }
  .missed {
    background: var(--loss);
  }
  .current {
    box-shadow: inset 0 0 0 1.5px var(--text);
  }
</style>
