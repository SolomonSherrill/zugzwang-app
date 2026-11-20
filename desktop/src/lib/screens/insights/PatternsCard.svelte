<script lang="ts">
  // R6 (PATTERNS.md §4, §6a; owner rulings R6-1..R6-6, 2026-11-13): the sentences of
  // "Patterns across your games" (the card's frame is InsightsScreen's). Only sentences that
  // pass are sent; each links to the plies behind it, newest first, each opening Review there.
  import type { InsightsPatterns } from '../../api'
  import { PAGE, itemText, linkText } from '../../patterns'

  let { patterns, onopen }: { patterns: InsightsPatterns; onopen?: (gameId: number, ply: number) => void } =
    $props()

  let open = $state<Record<string, number>>({})
  function toggle(key: string) {
    open = { ...open, [key]: open[key] ? 0 : PAGE }
  }
  function more(key: string) {
    open = { ...open, [key]: (open[key] ?? 0) + PAGE }
  }
</script>

{#each patterns.sentences as s (s.key)}
  <div class="pattern">
    <p class="pattern-text">{s.text}</p>
    <button class="pattern-link" aria-expanded={!!open[s.key]} onclick={() => toggle(s.key)}>
      {linkText(s.link.label, s.link.count)}
    </button>
    {#if open[s.key]}
      <ul class="pattern-items">
        {#each s.link.items.slice(0, open[s.key]) as it (`${it.gameId}:${it.ply}`)}
          <li>
            <button class="pattern-item" disabled={!onopen} onclick={() => onopen?.(it.gameId, it.ply)}>
              {itemText(it)}
            </button>
          </li>
        {/each}
      </ul>
      {#if s.link.items.length > open[s.key]}
        <button class="pattern-more" onclick={() => more(s.key)}>
          Show {Math.min(PAGE, s.link.items.length - open[s.key])} more
        </button>
      {/if}
    {/if}
  </div>
{/each}

<style>
  .pattern + .pattern {
    margin-top: 14px;
  }
  .pattern-text {
    margin: 0 0 6px;
    line-height: 1.45;
  }
  .pattern-link,
  .pattern-more,
  .pattern-item {
    background: none;
    border: none;
    padding: 2px 0;
    color: var(--accent, inherit);
    cursor: pointer;
    font: inherit;
    text-align: left;
  }
  .pattern-item {
    color: inherit;
  }
  .pattern-item:hover:not(:disabled),
  .pattern-link:hover,
  .pattern-more:hover {
    text-decoration: underline;
  }
  .pattern-items {
    list-style: none;
    margin: 6px 0 0;
    padding: 0 0 0 12px;
    max-height: 320px;
    overflow-y: auto;
    font-size: 0.92em;
  }
</style>
