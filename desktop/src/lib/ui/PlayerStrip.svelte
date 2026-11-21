<script lang="ts">
  /**
   * The strip above or below a board (ruling 6): an initial avatar, "Name (rating)" with the
   * rating at the time of the game and nothing when it is missing, "You" beside the user,
   * and the clock at the right. Engine games pass the level in `rating`'s place as a label
   * ("Stockfish (Level 10)"). No rating change, ever.
   */
  interface Props {
    name: string
    /** a number, or a label such as "Level 10"; null/undefined shows nothing */
    rating?: number | string | null
    you?: boolean
    /** "1:40"; omitted when the game has no clocks */
    clock?: string | null
    /** the clock of the side to move is drawn filled (primary) */
    active?: boolean
    /** Stockfish: a knight in a rounded square instead of an initial (Play) */
    engine?: boolean
    /** 'lg': Play's live clock (the clock type style, idle in text-3, announced as a timer) */
    size?: 'md' | 'lg'
    /** a muted word in place of "You" ("Your move" on Play) */
    note?: string | null
  }
  let { name, rating = null, you = false, clock = null, active = false, engine = false, size = 'md', note = null }: Props =
    $props()
  const initial = $derived((name.trim()[0] ?? '?').toUpperCase())
  // "You (You)" would repeat itself: a user with no account name is just "You"
  const youWord = $derived(you && name !== 'You')
  const timerLabel = $derived(`${engine ? "Stockfish's" : 'Your'} clock, ${clock}${active ? ', running' : ''}`)
</script>

<div class="strip" class:lg={size === 'lg'}>
  <div class="who">
    {#if engine}
      <span class="avatar engine" aria-hidden="true"
        ><svg viewBox="0 0 45 45" width="14" height="14"
          ><path
            d="M22 10c10.5 1 16.5 8 16 29H15c0-9 10-6.5 8-21M24 18c.38 2.91-5.55 7.37-8 9-3 2-2.82 4.34-5 4-1.04-.94 1.41-3.04 0-3-1 0 .19 1.23-1 2-1 0-4 1-4-4 0-2 6-12 6-12s1.89-1.9 2-3.5c-.73-1-.5-2-.5-3 1-1 3 2.5 3 2.5h2s.78-1.99 2.5-3c1 0 1 3 1 3"
            fill="currentColor"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linejoin="round"
          /></svg
        ></span
      >
    {:else}
      <span class="avatar" class:you={you || name === 'You'} aria-hidden="true">{initial}</span>
    {/if}
    <span class="name"
      >{name}{#if rating != null && rating !== ''}{' '}<span class="rating">({rating})</span>{/if}</span
    >
    {#if note}<span class="you-word">{note}</span>{:else if youWord}<span class="you-word">You</span>{/if}
  </div>
  {#if clock && size === 'lg'}
    <span class="clock" class:active role="timer" aria-label={timerLabel}>{clock}</span>
  {:else if clock}
    <span class="clock" class:active aria-label="Clock {clock}">{clock}</span>
  {/if}
</div>

<style>
  .strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 36px;
    min-width: 0;
  }
  .who {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    white-space: nowrap;
  }
  .avatar {
    width: 20px;
    height: 20px;
    flex: none;
    border-radius: var(--radius-round);
    background: var(--selected);
    color: var(--text-2);
    font-size: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .avatar.you {
    background: var(--text);
    color: var(--primary-ink);
    font-weight: 600;
  }
  .name {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .rating,
  .you-word {
    color: var(--text-3);
    font-weight: 400;
  }
  .clock {
    font-size: 14px;
    font-weight: 500;
    padding: 3px 8px;
    border-radius: 5px;
    background: var(--surface);
    border: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }
  .clock.active {
    background: var(--text);
    color: var(--primary-ink);
    border-color: var(--text);
  }
  .lg {
    height: 44px;
  }
  .avatar.engine {
    border-radius: 5px;
  }
  .lg .clock {
    font: var(--clock);
    font-variant-numeric: tabular-nums;
    padding: 3px 10px;
    color: var(--text-3);
  }
  .lg .clock.active {
    color: var(--primary-ink);
    font-weight: 600;
  }
</style>
