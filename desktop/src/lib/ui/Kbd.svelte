<script lang="ts">
  /** A keyboard hint: 11px in a 1px border-control box (design system, Keyboard). */
  interface Props {
    keys: string
    /** inside a primary button the box drops and the ink dims, as the mockups draw it */
    plain?: boolean
  }
  let { keys, plain = false }: Props = $props()
</script>

<kbd class:plain>{keys}</kbd>

<style>
  kbd {
    font: var(--kbd);
    font-family: inherit;
    color: var(--text-3);
    border: 1px solid var(--border-control);
    border-radius: 4px;
    padding: 0 5px;
  }
  kbd.plain {
    border: 0;
    padding: 0;
    color: inherit;
    opacity: 0.6;
  }
</style>
