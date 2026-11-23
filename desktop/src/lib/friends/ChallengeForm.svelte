<script lang="ts">
  /** Play as (White / Random / Black) and the ten live time controls (ruling C1), as both the Challenge
   *  popover (MinimalFriend-challenge.html) and Play's "A friend" (MinimalPlaySetup-friend.html) draw them. */
  import { TIME_CONTROLS, type AskedColour, type TimeControl } from './friendsApi'
  interface Props {
    colour: AskedColour
    tc: TimeControl
    idPrefix: string
  }
  let { colour = $bindable(), tc = $bindable(), idPrefix }: Props = $props()
  const COLOURS: { v: AskedColour; label: string }[] = [
    { v: 'white', label: 'White' },
    { v: 'random', label: 'Random' },
    { v: 'black', label: 'Black' },
  ]
  const ORDER = TIME_CONTROLS.flatMap((g) => g.tcs)
  function keys<T>(e: KeyboardEvent, values: T[], current: T, set: (v: T) => void) {
    const i = values.indexOf(current)
    let next: T | null = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = values[(i + 1) % values.length]
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = values[(i + values.length - 1) % values.length]
    if (next === null) return
    e.preventDefault()
    e.stopPropagation()
    set(next)
    ;(e.currentTarget as HTMLElement).closest('[role=radiogroup]')?.querySelector<HTMLElement>(`[data-v="${String(next)}"]`)?.focus()
  }
</script>

<div>
  <div id="{idPrefix}-as" class="lbl">Play as</div>
  <div class="seg" role="radiogroup" aria-labelledby="{idPrefix}-as">
    {#each COLOURS as c (c.v)}
      <button
        type="button"
        role="radio"
        aria-checked={colour === c.v}
        tabindex={colour === c.v ? 0 : -1}
        data-v={c.v}
        onclick={() => (colour = c.v)}
        onkeydown={(e) => keys(e, COLOURS.map((x) => x.v), colour, (v) => (colour = v))}>{c.label}</button
      >
    {/each}
  </div>
</div>
<div>
  <div id="{idPrefix}-tc" class="lbl">Time control</div>
  <div class="tcs" role="radiogroup" aria-labelledby="{idPrefix}-tc">
    {#each TIME_CONTROLS as g (g.group)}
      <span class="speed">{g.group}</span>
      {#each g.tcs as t (t)}
        <button
          type="button"
          role="radio"
          class="tc"
          aria-checked={tc === t}
          aria-label="{t} {g.group}"
          tabindex={tc === t ? 0 : -1}
          data-v={t}
          onclick={() => (tc = t)}
          onkeydown={(e) => keys(e, ORDER, tc, (v) => (tc = v))}>{t}</button
        >
      {/each}
      {#each Array(4 - g.tcs.length) as _, k (k)}<span></span>{/each}
    {/each}
  </div>
</div>

<style>
  .lbl {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
    margin-bottom: 8px;
  }
  .seg {
    display: flex;
    gap: 2px;
    padding: 2px;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .seg button {
    flex: 1;
    background: transparent;
    border: 0;
    border-radius: 4px;
    padding: 6px 10px;
    color: var(--text-2);
    font: var(--body);
    cursor: pointer;
  }
  .seg button[aria-checked='true'] {
    background: var(--border);
    color: var(--text);
  }
  .tcs {
    display: grid;
    grid-template-columns: 72px repeat(4, minmax(0, 1fr));
    gap: 6px;
    align-items: center;
  }
  .speed {
    color: var(--text-2);
  }
  .tc {
    background: transparent;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 6px 0;
    color: var(--text-2);
    text-align: center;
    font: var(--body);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .tc:hover {
    border-color: var(--border-strong);
    color: var(--text);
  }
  .tc[aria-checked='true'] {
    background: var(--primary);
    border-color: var(--primary);
    color: var(--primary-ink);
    font-weight: 500;
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
</style>
