<script lang="ts">
  import type { Snippet } from 'svelte'
  import Kbd from './Kbd.svelte'

  /**
   * primary: the one filled action per screen. ghost: 1px border-control, text-2 (the
   * default). quiet: no border, text-3, for low-weight actions. pressed: a ghost held on
   * (raised fill, border-strong). danger: a destructive action (Delete account, Remove friend,
   * Block; FRIENDS.md ruling S4): --loss text on the --danger-border outline; never Accept / Decline.
   * Every variant keeps the 2px focus ring.
   */
  interface Props {
    variant?: 'primary' | 'ghost' | 'quiet' | 'danger'
    pressed?: boolean
    disabled?: boolean
    kbd?: string
    size?: 'sm' | 'md'
    title?: string
    ariaLabel?: string
    ariaExpanded?: boolean
    ariaHaspopup?: 'dialog' | 'menu' | 'true'
    type?: 'button' | 'submit'
    onclick?: (e: MouseEvent) => void
    children: Snippet
  }
  let {
    variant = 'ghost',
    pressed = false,
    disabled = false,
    kbd,
    size = 'md',
    title,
    ariaLabel,
    ariaExpanded,
    ariaHaspopup,
    type = 'button',
    onclick,
    children,
  }: Props = $props()
</script>

<button
  {type}
  class="btn {variant} {size}"
  class:pressed
  {disabled}
  {title}
  aria-label={ariaLabel}
  aria-pressed={variant === 'ghost' && pressed ? true : undefined}
  aria-expanded={ariaExpanded}
  aria-haspopup={ariaHaspopup}
  {onclick}
>
  {@render children()}
  {#if kbd}<Kbd keys={kbd} plain={variant === 'primary'} />{/if}
</button>

<style>
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    font: var(--body);
    border-radius: var(--radius-control);
    white-space: nowrap;
    cursor: pointer;
    transition:
      background-color 80ms ease,
      color 80ms ease,
      border-color 80ms ease;
  }
  .md {
    padding: 5px 10px;
  }
  .primary.md {
    padding: 6px 12px;
  }
  .sm {
    padding: 2px 8px;
    font: var(--secondary);
  }
  .primary {
    background: var(--primary);
    color: var(--primary-ink);
    border: 1px solid var(--primary);
    font-weight: 500;
    gap: 8px;
  }
  .primary:hover:not(:disabled) {
    background: #ffffff;
  }
  .ghost {
    background: transparent;
    color: var(--text-2);
    border: 1px solid var(--border-control);
  }
  .ghost:hover:not(:disabled) {
    color: var(--text);
    background: var(--surface);
  }
  .ghost.pressed {
    background: var(--raised);
    color: var(--text);
    border-color: var(--border-strong);
  }
  .quiet {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-3);
  }
  .quiet:hover:not(:disabled) {
    color: var(--text);
  }
  .danger {
    background: transparent;
    color: var(--loss);
    border: 1px solid var(--danger-border);
  }
  .danger:hover:not(:disabled) {
    background: var(--surface);
    border-color: var(--loss);
  }
  .btn:disabled {
    cursor: default;
    color: var(--disabled);
    border-color: var(--border);
    background: transparent;
  }
  .primary:disabled {
    background: var(--raised);
    color: var(--disabled);
    border-color: var(--raised);
  }
  .btn:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
