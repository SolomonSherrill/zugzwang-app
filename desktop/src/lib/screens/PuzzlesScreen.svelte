<script lang="ts">
  import PuzzleLobby from './PuzzleLobby.svelte'
  import PuzzleSession from './PuzzleSession.svelte'
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
    <PuzzleSession config={session} onexit={() => (session = null)} />
  {/key}
{:else}
  <PuzzleLobby onstart={start} />
{/if}
