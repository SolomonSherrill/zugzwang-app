<script lang="ts">
  /**
   * The selected move's explanation in Review's Moves tab (BETA-4 B; DESIGN.md "Owner rulings,
   * 2026-11-21", 2): the move, its label, and what the rule layer says about it (explain_move:
   * the claims, else the rule sentences, then the descriptions under "Compared with …", as the
   * old Review showed them), with "Flag this" at the right (beta builds only; FlagThis renders
   * nothing in other builds). Only for a main-line move of an analysed game.
   */
  import { api, type ExplainResult } from '../api'
  import FlagThis from '../FlagThis.svelte'
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import { QUALITY, isQualityClass } from '../ui/moveQuality'

  interface Props {
    gameId: number
    /** ply index of the move (0 = the first move) */
    ply: number
    /** "34. b5" */
    label: string
    cls: string | null
    /** the run shown (RUNS-DEPTH); null = the sidecar's default */
    runId: number | null
    /** the flag's note form is open (⌘K "Flag this move" opens it) */
    flagOpen?: boolean
  }
  let { gameId, ply, label, cls, runId, flagOpen = $bindable(false) }: Props = $props()

  let ex = $state<ExplainResult | null>(null)
  $effect(() => {
    const [g, p, r] = [gameId, ply, runId]
    ex = null
    let live = true
    api
      .explainMove(g, p, r)
      .then((x) => {
        if (live) ex = x
      })
      .catch(() => {
        if (live) ex = null
      })
    return () => {
      live = false
    }
  })
  const name = $derived(cls && isQualityClass(cls) ? QUALITY[cls].name : null)
  const mine = $derived(ex && ex.ply === ply ? ex : null)
  const says = $derived<string[]>(mine ? (mine.claims ? mine.claims.map((c) => c.text) : mine.sentences) : [])
  const descriptions = $derived<string[]>(mine ? (mine.descriptions ?? []).map((d) => d.text) : [])
  const compared = $derived(`Compared with ${mine?.bestSan ?? 'the engine move'}`)
  const shown = $derived(
    [`${label}${name ? ` — ${name}` : ''}`, ...says, ...(descriptions.length ? [`${compared}: ${descriptions.join(' ')}`] : [])].join(' / '),
  )
</script>

<section class="why" aria-label="The selected move">
  <div class="top">
    <span class="mv">
      {label}
      {#if name && cls}<MoveQualityIcon cls={cls as never} decorative /><span class="nm">{name}</span>{/if}
    </span>
    {#key ply}
      <span class="flagslot">
        <FlagThis
          kind="move explanation"
          {gameId}
          {ply}
          label={cls}
          {shown}
          context={descriptions.length ? compared : null}
          bind:open={flagOpen}
        />
      </span>
    {/key}
  </div>
  {#each says as s, i (i)}<p class="say">{s}</p>{/each}
  {#if descriptions.length}
    <p class="cmp">{compared}</p>
    {#each descriptions as d, i (i)}<p class="say">{d}</p>{/each}
  {/if}
</section>

<style>
  .why {
    flex: none;
    max-height: 132px;
    overflow-y: auto;
    padding: 8px 20px;
    border-bottom: 1px solid var(--border);
    scrollbar-width: thin;
    scrollbar-color: var(--border-control) transparent;
  }
  .top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
    min-height: 22px;
  }
  .mv {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 500;
    white-space: nowrap;
  }
  .nm {
    color: var(--text-2);
    font-weight: 400;
  }
  .flagslot {
    margin-left: auto;
    max-width: 100%;
    display: flex;
    align-items: center;
  }
  /* the note form wraps onto a line of its own rather than widen the panel */
  .flagslot :global(.form) {
    flex-wrap: wrap;
  }
  .say {
    margin: 4px 0 0;
    color: var(--chart-line);
  }
  .cmp {
    margin: 6px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
