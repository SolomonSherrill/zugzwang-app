<script lang="ts">
  /** "Flag this" (BETA item 4): a small control beside a label, an explanation, a
   *  description or a report line. It asks for a one-line note and appends the flag —
   *  platform game id, ply, what was shown, the label, the app/classifier/rule versions
   *  (filled in by the sidecar) — to a file in the app's data folder, then offers to
   *  reveal that file. Nothing is sent over the network. Renders nothing outside beta. */
  import { revealItemInDir } from '@tauri-apps/plugin-opener'
  import { BETA } from './build'
  import { api } from './api'

  interface Props {
    kind: string
    shown: string
    gameId: number | null
    ply?: number | null
    label?: string | null
    context?: string | null
    /** the note form is open; bindable, so ⌘K's "Flag this move" can open it (BETA-4 B) */
    open?: boolean
  }
  let { kind, shown, gameId, ply = null, label = null, context = null, open = $bindable(false) }: Props = $props()

  let note = $state('')
  let saving = $state(false)
  let savedPath = $state<string | null>(null)
  let error = $state('')

  function stop(e: Event) {
    e.stopPropagation()
  }

  async function save() {
    saving = true
    error = ''
    try {
      const r = await api.flagItem({ kind, shown, note, gameId, ply, label, context })
      savedPath = r.path
      open = false
      note = ''
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      saving = false
    }
  }

  function focus(node: HTMLInputElement) {
    node.focus()
  }
</script>

{#if BETA}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <span class="flag" onclick={stop}>
    {#if open}
      <span class="form">
        <input
          use:focus
          type="text"
          maxlength="300"
          placeholder="What's wrong? (one line, optional)"
          bind:value={note}
          onkeydown={(e) => {
            e.stopPropagation()
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') open = false
          }}
        />
        <button class="go" disabled={saving} onclick={save}>{saving ? '…' : 'Save flag'}</button>
        <button class="cancel" onclick={() => (open = false)}>Cancel</button>
      </span>
    {:else if savedPath}
      <span class="saved">
        Flagged ·
        <button class="link" onclick={() => savedPath && revealItemInDir(savedPath)}
          >show file</button
        >
      </span>
    {:else}
      <button
        class="btn-flag"
        title="Flag this as wrong or confusing (saved to a file on this computer)"
        aria-label="Flag this"
        onclick={() => (open = true)}>⚑</button
      >
    {/if}
    {#if error}<span class="err">{error}</span>{/if}
  </span>
{/if}

<style>
  .flag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: 6px;
    vertical-align: middle;
    font-size: 11.5px;
  }
  .btn-flag {
    border: none;
    background: none;
    padding: 0 3px;
    color: var(--text-muted);
    opacity: 0.55;
    cursor: pointer;
    font-size: 12px;
    line-height: 1;
  }
  .btn-flag:hover {
    opacity: 1;
    color: var(--accent);
  }
  .form {
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }
  .form input {
    width: 220px;
    padding: 3px 7px;
    font-size: 12px;
    user-select: text;
  }
  .go,
  .cancel,
  .link {
    border: none;
    background: none;
    padding: 0;
    font-size: 11.5px;
    cursor: pointer;
    color: var(--accent);
  }
  .cancel {
    color: var(--text-muted);
  }
  .link {
    text-decoration: underline;
  }
  .saved {
    color: var(--text-muted);
  }
  .err {
    color: var(--danger);
  }
</style>
