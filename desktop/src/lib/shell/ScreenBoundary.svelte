<script lang="ts">
  /**
   * FIX-B7 (ruling HF2): a screen that fails while drawing shows an error instead of staying on its loading
   * state. Review: "This game could not be opened." with the error under it and "Back to games" (its existing
   * state). Any other screen: "This screen could not be opened." with the error under it and "Try again", which
   * redraws the screen. The error and its stack go to the sidecar log (screenError.ts).
   */
  import type { Snippet } from 'svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import { errorText, reportScreenError } from './screenError'

  interface Props {
    /** the route, for the log line */
    screen: string
    /** Review's wording and its way back */
    review?: { onback: () => void } | null
    children: Snippet
  }
  let { screen, review = null, children }: Props = $props()
</script>

<svelte:boundary onerror={(e) => reportScreenError(screen, e)}>
  {@render children()}
  {#snippet failed(error, reset)}
    <div class="failed" data-testid="screen-failed">
      {#if review}
        <EmptyState tone="error" sentence="This game could not be opened." sub={errorText(error)} action={{ label: 'Back to games', run: review.onback }} />
      {:else}
        <EmptyState tone="error" sentence="This screen could not be opened." sub={errorText(error)} action={{ label: 'Try again', run: reset, primary: true }} />
      {/if}
    </div>
  {/snippet}
</svelte:boundary>

<style>
  .failed {
    padding: var(--space-5);
    max-width: 640px;
  }
  .failed :global(.sub) {
    white-space: pre-line;
    overflow-wrap: anywhere;
  }
</style>
