<script lang="ts">
  /** ⌘K (ruling 9): a popover listing moves and actions the screens on view offer. */
  import MoveQualityIcon from '../ui/MoveQualityIcon.svelte'
  import { commandMenu, commandsFor, type Command } from './commands.svelte'

  let query = $state('')
  let active = $state(0)
  let input: HTMLInputElement | undefined = $state()

  const list = $derived.by(() => {
    void commandMenu.version
    return commandsFor(query)
  })
  const groups = $derived.by(() => {
    const g: { name: string; items: { c: Command; i: number }[] }[] = []
    list.forEach((c, i) => {
      let grp = g.find((x) => x.name === c.group)
      if (!grp) g.push((grp = { name: c.group, items: [] }))
      grp.items.push({ c, i })
    })
    return g
  })

  $effect(() => {
    if (commandMenu.open) {
      query = ''
      active = 0
      queueMicrotask(() => input?.focus())
    }
  })
  $effect(() => {
    void query
    active = 0
  })

  function close() {
    commandMenu.open = false
  }
  function run(c: Command) {
    close()
    c.run()
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      active = Math.min(list.length - 1, active + 1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      active = Math.max(0, active - 1)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (list[active]) run(list[active])
    }
  }
</script>

{#if commandMenu.open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={close}>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="menu" role="dialog" aria-label="Command menu" tabindex="-1" onclick={(e) => e.stopPropagation()}>
      <label class="q">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"
          ><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg
        >
        <input
          bind:this={input}
          bind:value={query}
          type="text"
          aria-label="Search moves and actions"
          aria-controls="cmd-list"
          aria-activedescendant={list[active] ? `cmd-${list[active].id}` : undefined}
          onkeydown={key}
          spellcheck="false"
          autocomplete="off"
        />
        <span class="hint">Moves and actions</span>
      </label>
      <div class="list" id="cmd-list" role="listbox">
        {#each groups as g (g.name)}
          <div class="group">{g.name}</div>
          {#each g.items as { c, i } (c.id)}
            <button
              type="button"
              role="option"
              id="cmd-{c.id}"
              aria-selected={i === active}
              class:active={i === active}
              onmouseenter={() => (active = i)}
              onclick={() => run(c)}
            >
              {#if c.icon}<MoveQualityIcon cls={c.icon} decorative />{/if}
              <span class="label"
                >{#if c.detail}<b>{c.label}</b> <span class="detail">{c.detail}</span>{:else}{c.label}{/if}</span
              >
              {#if c.kbd}<kbd>{c.kbd}</kbd>{:else if i === active}<kbd>↵</kbd>{/if}
            </button>
          {/each}
        {:else}
          <p class="empty">Nothing matches “{query}”.</p>
        {/each}
      </div>
      <div class="foot"><span>↑ ↓ to choose</span><span>↵ to open</span><span>esc to close</span></div>
    </div>
  </div>
{/if}

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding-top: 120px;
    z-index: 50;
  }
  .menu {
    width: 600px;
    max-width: calc(100% - 32px);
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: 10px;
    box-shadow: var(--shadow-popover);
    overflow: hidden;
  }
  .q {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    color: var(--text-3);
  }
  input {
    flex: 1;
    background: transparent;
    border: 0;
    color: var(--text);
    font: var(--body);
    font-size: 15px;
    outline: none;
    padding: 0;
  }
  .hint {
    font: var(--secondary);
    color: var(--text-3);
  }
  .list {
    padding: 6px;
    max-height: 420px;
    overflow-y: auto;
  }
  .group {
    padding: 8px 10px 4px;
    font: var(--secondary);
    color: var(--text-3);
  }
  button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  button.active {
    background: var(--border);
  }
  .label {
    flex: 1;
    min-width: 0;
  }
  b {
    font-weight: 500;
  }
  .detail {
    color: var(--text-2);
  }
  kbd {
    font: var(--kbd);
    font-family: inherit;
    color: var(--text-2);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    padding: 1px 6px;
  }
  .empty {
    margin: 0;
    padding: 12px 10px;
    color: var(--text-3);
  }
  .foot {
    display: flex;
    gap: 16px;
    padding: 8px 16px;
    border-top: 1px solid var(--border);
    font: var(--secondary);
    color: var(--text-3);
  }
</style>
