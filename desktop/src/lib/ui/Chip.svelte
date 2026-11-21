<script lang="ts">
  import type { Snippet } from 'svelte'
  /** A filter chip: radius-control, 1px border-control; selected = selected fill with an
   *  inset border-strong ring, text (never text-3 on selected). */
  interface Props {
    selected?: boolean
    disabled?: boolean
    onclick?: () => void
    children: Snippet
  }
  let { selected = false, disabled = false, onclick, children }: Props = $props()
</script>

<button type="button" class="chip" class:selected {disabled} aria-pressed={selected} {onclick}>
  {@render children()}
</button>

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    font: var(--secondary);
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    cursor: pointer;
  }
  .chip:hover:not(:disabled) {
    color: var(--text);
  }
  .chip.selected {
    background: var(--selected);
    color: var(--text);
    border-color: transparent;
    box-shadow: inset 0 0 0 1px var(--border-strong);
  }
  .chip:disabled {
    color: var(--disabled);
    cursor: default;
  }
  .chip:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
