<script lang="ts">
  /**
   * Insights' Patterns (ruling 14; R6, PATTERNS.md §6a): each pattern a short title and two bars
   * from the sentence's own figures; the approved R6 sentence, verbatim, is the description
   * behind its link, above the plies it links to (newest first, each opening Review there).
   * Only sentences that pass are sent by the sidecar; nothing else is drawn.
   */
  import type { InsightsPatterns } from '../api'
  import { PAGE, coverageText, emptyText, itemText } from '../patterns'
  import { PATTERN_TITLES, fmtInt, ratio } from './insightsModel'

  let { patterns, onopen }: { patterns: InsightsPatterns; onopen?: (gameId: number, ply: number) => void } = $props()
  let open = $state<Record<string, number>>({})
  const stats = (key: string) => patterns.tested.find((t) => t.key === key) ?? null
</script>

{#if patterns.sentences.length === 0}
  <p class="none">{emptyText(patterns)}</p>
{/if}
{#each patterns.sentences as s (s.key)}
  {@const t = PATTERN_TITLES[s.key]}
  {@const st = stats(s.key)}
  <div class="pat">
    <div class="pt">{t?.title ?? s.link.label}</div>
    {#if t && st}
      {@const a = ratio(st.yx, st.nx)}
      {@const b = ratio(st.yo, st.no)}
      <div class="bars">
        <span class="bl">{t.you}</span>
        <span class="track" aria-hidden="true"><span class="fill you" style:width="{a ?? 0}%"></span></span>
        <span class="bv">{a === null ? '–' : Math.round(a) + '%'}</span>
        <span class="bl">{t.them}</span>
        <span class="track" aria-hidden="true"><span class="fill them" style:width="{b ?? 0}%"></span></span>
        <span class="bv">{b === null ? '–' : Math.round(b) + '%'}</span>
      </div>
    {/if}
    <button type="button" class="link" aria-expanded={!!open[s.key]} onclick={() => (open = { ...open, [s.key]: open[s.key] ? 0 : PAGE })}>
      {s.link.label} <span class="n">{fmtInt(s.link.count)}</span>
    </button>
    {#if open[s.key]}
      <div class="behind">
        <p class="say">{s.text}</p>
        <ul>
          {#each s.link.items.slice(0, open[s.key]) as it (`${it.gameId}:${it.ply}`)}
            <li><button type="button" disabled={!onopen} onclick={() => onopen?.(it.gameId, it.ply)}>{itemText(it)}</button></li>
          {/each}
        </ul>
        {#if s.link.items.length > open[s.key]}
          <button type="button" class="more" onclick={() => (open = { ...open, [s.key]: open[s.key] + PAGE })}
            >Show {Math.min(PAGE, s.link.items.length - open[s.key])} more</button
          >
        {/if}
      </div>
    {/if}
  </div>
{/each}
<p class="cov">{coverageText(patterns)}</p>

<style>
  .pat {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
  }
  .pt {
    font: var(--body-strong);
    margin-bottom: 10px;
  }
  .bars {
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr) 48px;
    gap: 6px 12px;
    align-items: center;
  }
  .bl {
    color: var(--text-2);
    font: var(--secondary);
  }
  .bv {
    text-align: right;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .track {
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    border-radius: 3px;
  }
  .fill.you {
    background: var(--chart-you);
  }
  .fill.them {
    background: var(--chart-opponent);
  }
  .link,
  .more,
  li button {
    background: none;
    border: 0;
    padding: 0;
    font: var(--secondary);
    color: var(--text-2);
    cursor: pointer;
    text-align: left;
  }
  .link {
    margin-top: 12px;
  }
  .link .n {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .link:hover,
  .more:hover,
  li button:hover:not(:disabled) {
    color: var(--text);
  }
  .link:focus-visible,
  .more:focus-visible,
  li button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .behind {
    margin-top: 10px;
  }
  .say {
    margin: 0 0 8px;
    color: var(--text);
  }
  ul {
    list-style: none;
    margin: 0 0 6px;
    padding: 0;
    max-height: 240px;
    overflow-y: auto;
  }
  li button {
    padding: 3px 0;
    color: var(--text-2);
  }
  .none,
  .cov {
    margin: 0;
    padding: 12px 16px;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
