<script lang="ts">
  import TrainerFamilies from '../trainer/TrainerFamilies.svelte'
  import TrainerLine from '../trainer/TrainerLine.svelte'
  import { api, type TrainerFamilySummary } from '../api'

  interface Props {
    onplayfen: (fen: string) => void
    /** deep-link from Insights: jump straight into this opening's family */
    openingRequest?: { eco: string; name: string } | null
    /** fired once the request has been consumed, so the parent can clear it */
    onrequesthandled?: () => void
    /** the no-book state's action: the books are downloaded in Settings */
    onsettings?: () => void
  }
  let { onplayfen, openingRequest = null, onrequesthandled, onsettings = () => {} }: Props = $props()

  let family = $state<TrainerFamilySummary | null>(null)

  /** Best family for a played opening: the one whose ECO range contains the
   *  opening's code, tie-broken by name overlap then popularity; falls back to
   *  a plain name match. Returns null when nothing lines up (→ show lobby). */
  function matchFamily(
    families: TrainerFamilySummary[],
    req: { eco: string; name: string },
  ): TrainerFamilySummary | null {
    const eco = (req.eco || '').toUpperCase().trim()
    const name = req.name.toLowerCase()
    const inRange = families.filter((f) => eco && f.ecoLo <= eco && eco <= f.ecoHi)
    if (inRange.length) {
      return [...inRange].sort((a, b) => {
        const an = name.includes(a.name.toLowerCase()) ? 1 : 0
        const bn = name.includes(b.name.toLowerCase()) ? 1 : 0
        return bn - an || b.popularity - a.popularity
      })[0]
    }
    const byName = families.filter((f) => name.includes(f.name.toLowerCase()))
    if (byName.length) {
      return [...byName].sort((a, b) => b.popularity - a.popularity)[0]
    }
    return null
  }

  async function resolve(req: { eco: string; name: string }) {
    try {
      const { families } = await api.trainerLobby()
      const match = matchFamily(families, req)
      if (match) family = match
    } catch {
      // fall through to the lobby on any error
    }
  }

  // One-shot: consume the deep-link as soon as it arrives. Clearing it in the
  // parent means backing out of the workspace returns to the normal lobby
  // instead of bouncing straight back in.
  $effect(() => {
    if (openingRequest) {
      const req = openingRequest
      onrequesthandled?.()
      void resolve(req)
    }
  })
</script>

{#if family}
  {#key family.name}
    <TrainerLine {family} onback={() => (family = null)} {onplayfen} />
  {/key}
{:else}
  <TrainerFamilies onselect={(f) => (family = f)} {onsettings} />
{/if}
