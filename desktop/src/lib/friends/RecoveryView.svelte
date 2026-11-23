<script lang="ts">
  /** The recovery code, once, right after sign-up (MinimalFriends-recovery.html; ruling A2). "Save as a
   *  file" goes through the save dialog and the sidecar writes the file (BETA-5 B: a download link does
   *  nothing in Tauri's macOS webview). Copy uses the clipboard API, else the selection's copy. */
  import Button from '../ui/Button.svelte'
  import { pickSavePath } from '../pick'
  import { friendsApi } from './friendsApi'
  import { errorText } from './friendsState.svelte'
  interface Props {
    code: string
    oncontinue: () => void
  }
  let { code, oncontinue }: Props = $props()
  let saved = $state(false)
  let copied = $state(false)
  let note = $state<{ text: string; error: boolean } | null>(null)
  let saving = $state(false)

  /** the selection's copy: works where navigator.clipboard is missing or refused */
  function copyBySelection(text: string): boolean {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    ta.remove()
    return ok
  }
  async function copy() {
    note = null
    let ok = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code)
        ok = true
      }
    } catch {
      ok = false
    }
    if (!ok) ok = copyBySelection(code)
    if (ok) {
      copied = true
      setTimeout(() => (copied = false), 1500)
    } else {
      note = { text: 'Could not copy it. Select the code and copy it yourself.', error: true }
    }
  }
  async function saveFile() {
    note = null
    let path: string | null
    try {
      path = await pickSavePath('Save your recovery code', 'zugzwang-recovery-code.txt', [{ name: 'Text', extensions: ['txt'] }])
    } catch (e) {
      note = { text: 'The save dialog did not open: ' + errorText(e), error: true }
      return
    }
    if (!path) return // cancelled: nothing happens
    saving = true
    try {
      const out = await friendsApi.saveRecovery(path)
      note = { text: `Saved to ${out.path}`, error: false }
    } catch (e) {
      note = { text: errorText(e), error: true }
    } finally {
      saving = false
    }
  }
</script>

<div class="wrap">
  <div class="col">
    <div>
      <h2>Save your recovery code</h2>
      <p class="lead">It's the only way back into your account on another computer, or if this one is lost. Zugzwang can't recover it for you.</p>
    </div>
    <div class="code" aria-label="Recovery code">{code}</div>
    <div class="row">
      <Button onclick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
      <Button disabled={saving} onclick={saveFile}>{saving ? 'Saving…' : 'Save as a file'}</Button>
    </div>
    {#if note}<p class="note" class:err={note.error} role={note.error ? 'alert' : 'status'}>{note.text}</p>{/if}
    <label class="cb"><input type="checkbox" bind:checked={saved} />I've saved it somewhere safe</label>
    <Button variant="primary" disabled={!saved} onclick={oncontinue}>Continue</Button>
    <p class="hint">You can see it again later in Settings → Friends.</p>
  </div>
</div>

<style>
  .wrap {
    flex: 1;
    display: flex;
    justify-content: center;
    padding: 56px 28px;
  }
  .col {
    width: 460px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  h2 {
    margin: 0 0 6px;
    font: var(--heading);
  }
  .lead {
    margin: 0;
    color: var(--text-2);
  }
  .code {
    padding: 16px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-panel);
    text-align: center;
    font-size: 15px;
    font-weight: 500;
    letter-spacing: 0.04em;
    line-height: 1.6;
    user-select: all;
    word-spacing: 0.2em;
  }
  .row {
    display: flex;
    gap: var(--space-2);
  }
  .note {
    margin: -8px 0 0;
    color: var(--text-2);
    font: var(--secondary);
    overflow-wrap: anywhere;
  }
  .note.err {
    color: var(--loss);
  }
  .cb {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }
  .cb input {
    margin: 0;
    width: 14px;
    height: 14px;
    accent-color: var(--text);
  }
  .hint {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
