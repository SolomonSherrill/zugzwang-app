<script lang="ts">
  /**
   * Analyse again (ruling 7; ruling 8 of 2026-11-20, third): 14 standard, 18, 24, no custom.
   * A deeper run is kept beside the depth-14 one (RUNS-DEPTH), which Insights and Home keep
   * reading. Each option's time is the measured estimate for this game's plies (depth.ts).
   */
  import Button from '../ui/Button.svelte'
  import { DEEP_RUNS_AVAILABLE, estimateText } from './depth'

  interface Props {
    currentDepth: number | null
    plies: number
    onanalyse: (depth: number) => void
    oncancel: () => void
  }
  let { currentDepth, plies, onanalyse, oncancel }: Props = $props()
  const OPTIONS = [
    { depth: 14, name: 'Standard' },
    { depth: 18, name: 'Deep' },
    { depth: 24, name: 'Deepest' },
  ]
  const enabled = (d: number) => d === 14 || DEEP_RUNS_AVAILABLE
  let choice = $state(14)
  let box: HTMLDivElement | undefined = $state()
  $effect(() => {
    box?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
  })
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      oncancel()
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="menu" role="dialog" aria-label="Analyse again" tabindex="-1" bind:this={box} onkeydown={key}>
  <div class="title">Engine depth</div>
  <div role="radiogroup" aria-label="Engine depth">
    {#each OPTIONS as o (o.depth)}
      {@const on = choice === o.depth}
      {@const est = estimateText(o.depth, plies)}
      <button
        type="button"
        role="radio"
        aria-checked={on}
        disabled={!enabled(o.depth)}
        class:on
        onclick={() => (choice = o.depth)}
      >
        <span class="radio" aria-hidden="true"></span>
        <span class="d">{o.depth}</span>
        <span class="n">{o.name}</span>
        <span class="x">{currentDepth === o.depth ? 'Current' : est ?? ''}</span>
      </button>
    {/each}
  </div>
  <div class="rule"></div>
  <p class="note">
    {#if DEEP_RUNS_AVAILABLE}This game only. The depth-14 run is kept, so you can switch back.{:else}This game
      only. Depths 18 and 24 open once a deeper run can be kept beside the depth-14 one.{/if}
  </p>
  <div class="acts">
    <Button onclick={oncancel}>Cancel</Button>
    <Button variant="primary" disabled={!enabled(choice)} onclick={() => onanalyse(choice)}>Analyse at depth {choice}</Button>
  </div>
</div>

<style>
  .menu {
    position: absolute;
    top: 44px;
    right: 58px;
    width: 300px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    padding: 6px;
    z-index: 20;
  }
  .title {
    padding: 6px 8px 4px;
    font: var(--secondary);
    color: var(--text-3);
  }
  button[role='radio'] {
    width: 100%;
    display: grid;
    grid-template-columns: 14px 28px minmax(0, 1fr) auto;
    gap: 8px;
    align-items: center;
    padding: 7px 8px;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  button[role='radio']:hover:not(:disabled) {
    background: var(--raised);
  }
  button[role='radio'].on {
    background: var(--border);
  }
  button[role='radio']:disabled {
    cursor: default;
    color: var(--disabled);
  }
  button[role='radio']:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .radio {
    width: 12px;
    height: 12px;
    border-radius: 6px;
    border: 1.5px solid var(--disabled);
    box-sizing: border-box;
  }
  .on .radio {
    border: 4px solid var(--text);
  }
  .d {
    font-weight: 500;
  }
  .n {
    color: var(--text-2);
  }
  .on .n {
    color: var(--text);
  }
  :disabled .n,
  :disabled .x {
    color: var(--disabled);
  }
  .x {
    color: var(--text-3);
    font: var(--secondary);
  }
  .rule {
    margin: 6px 0;
    border-top: 1px solid var(--border);
  }
  .note {
    margin: 0;
    padding: 2px 8px 10px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .acts {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
    padding: 0 2px 2px;
  }
</style>
