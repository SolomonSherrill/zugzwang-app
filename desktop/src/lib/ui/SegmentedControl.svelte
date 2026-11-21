<script lang="ts" generics="T extends string">
  /** One choice of a few, as the Eval / Material / Time switch: a 1px border box, the
   *  selected segment filled with border (#222327) and text. A radiogroup; arrow keys move. */
  interface Props {
    options: { value: T; label: string; disabled?: boolean }[]
    value: T
    label: string
    onchange?: (v: T) => void
  }
  let { options, value = $bindable(), label, onchange }: Props = $props()

  function pick(v: T) {
    value = v
    onchange?.(v)
  }
  function key(e: KeyboardEvent, i: number) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const enabled = options.filter((o) => !o.disabled)
    const at = enabled.findIndex((o) => o.value === options[i].value)
    const next = enabled[(at + (e.key === 'ArrowRight' ? 1 : enabled.length - 1)) % enabled.length]
    pick(next.value)
    ;(e.currentTarget as HTMLElement).parentElement
      ?.querySelector<HTMLElement>(`[data-value="${next.value}"]`)
      ?.focus()
  }
</script>

<div class="seg" role="radiogroup" aria-label={label}>
  {#each options as o, i (o.value)}
    <button
      type="button"
      role="radio"
      aria-checked={o.value === value}
      tabindex={o.value === value ? 0 : -1}
      data-value={o.value}
      disabled={o.disabled}
      onclick={() => pick(o.value)}
      onkeydown={(e) => key(e, i)}>{o.label}</button
    >
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  button {
    background: transparent;
    color: var(--text-3);
    border: 0;
    border-radius: 4px;
    padding: 2px 9px;
    font: var(--secondary);
    cursor: pointer;
  }
  button:hover:not(:disabled) {
    color: var(--text);
  }
  button[aria-checked='true'] {
    background: var(--border);
    color: var(--text);
  }
  button:disabled {
    color: var(--disabled);
    cursor: default;
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
