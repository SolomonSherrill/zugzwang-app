<script lang="ts">
  /**
   * Puzzles, rebuilt (UI-BUILD-2 E2; DESIGN.md "Puzzles", "Puzzles: rated session", ruling 19):
   * the lobby, or a session of the chosen mode. Leaving a session returns to a fresh lobby, so
   * its figures include the session just played.
   */
  import PuzzleLobbyView from './PuzzleLobbyView.svelte'
  import PuzzleSessionView from './PuzzleSessionView.svelte'
  import type { PuzzleMode } from '../api'

  let session = $state<PuzzleMode | null>(null)
  let sessionKey = $state(0)

  function start(config: PuzzleMode) {
    session = config
    sessionKey += 1
  }
</script>

{#if session}
  {#key sessionKey}
    <PuzzleSessionView config={session} onexit={() => (session = null)} onagain={() => start({ ...session! })} />
  {/key}
{:else}
  <PuzzleLobbyView onstart={start} />
{/if}
