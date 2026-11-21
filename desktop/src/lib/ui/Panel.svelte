<script lang="ts">
  import type { Snippet } from 'svelte'
  /** A panel: a 1px border box on bg, radius-panel, space-5 padding; no fill, no shadow.
   *  An optional title row (body-strong) with an aside on the right. */
  interface Props {
    title?: string
    aside?: Snippet
    pad?: boolean
    children: Snippet
  }
  let { title, aside, pad = true, children }: Props = $props()
</script>

<section class="panel" class:pad aria-label={title}>
  {#if title || aside}
    <header>
      {#if title}<h2>{title}</h2>{/if}
      {#if aside}<div class="aside">{@render aside()}</div>{/if}
    </header>
  {/if}
  {@render children()}
</section>

<style>
  .panel {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    min-width: 0;
  }
  .pad {
    padding: var(--space-5);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    margin-bottom: var(--space-4);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
    font-weight: 600;
  }
  .aside {
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
