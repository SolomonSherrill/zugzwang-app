<script lang="ts">
  /** Settings → Friends (MinimalSettings.html, its Friends section; rulings A2, C2, H3, L4): the handle,
   *  the recovery code (hidden until Show), sharing, Appear offline, Chat in friend games, the Privacy
   *  policy and the Terms of use, and Delete account. Delete is red, as its confirmation is (ruling S4,
   *  2026-11-21: destructive buttons are red; replaces FRIENDS-1's plain button). */
  import Button from '../ui/Button.svelte'
  import Switch from '../friends/Switch.svelte'
  import LegalDialog from '../friends/LegalDialog.svelte'
  import { friendsApi } from '../friends/friendsApi'
  import { errorText, friendsState, refreshStatus } from '../friends/friendsState.svelte'

  let code = $state<string | null>(null)
  let error = $state<string | null>(null)
  let legal = $state<'privacy' | 'terms' | null>(null)
  let confirming = $state(false)
  let deleting = $state(false)
  const st = $derived(friendsState.status)

  $effect(() => {
    if (!friendsState.status) void refreshStatus()
  })
  async function toggleCode() {
    if (code) return void (code = null)
    try {
      code = (await friendsApi.recoveryCode()).code
    } catch (e) {
      error = errorText(e)
    }
  }
  async function set(p: { chatEnabled?: boolean }) {
    try {
      friendsState.status = await friendsApi.setSettings(p)
    } catch (e) {
      error = errorText(e)
    }
  }
  async function offline(on: boolean) {
    error = null
    try {
      await friendsApi.appearOffline(on)
      await refreshStatus()
    } catch (e) {
      error = errorText(e)
    }
  }
  async function del() {
    deleting = true
    error = null
    try {
      await friendsApi.deleteAccount()
      confirming = false
      code = null
      friendsState.list = null
      await refreshStatus()
    } catch (e) {
      error = errorText(e)
    } finally {
      deleting = false
    }
  }
</script>

<div class="friends">
  {#if !st}
    <p class="quiet">Opening…</p>
  {:else if !st.signedIn}
    <p class="quiet">No Friends account on this computer. Make one, or bring yours back with its recovery code, on the Friends screen.</p>
    <div class="links">
      <button type="button" class="link" onclick={() => (legal = 'privacy')}>Privacy policy</button>
      <button type="button" class="link" onclick={() => (legal = 'terms')}>Terms of use</button>
    </div>
  {:else}
    <div class="kv"><span class="k">Handle</span><span>{st.handle}</span><span></span></div>
    <div class="kv">
      <span class="k">Recovery code</span>
      {#if code}<span class="code">{code}</span>{:else}<span class="dots" aria-label="Hidden">••••-••••-••••-••••-••••</span>{/if}
      <Button size="sm" onclick={toggleCode}>{code ? 'Hide' : 'Show'}</Button>
    </div>
    <!-- BETA-6 (FRIENDS.md ruling SG1): "Share the games you play in Zugzwang" is hidden until a screen shows
         shared games; its stored value is kept, unused -->
    <Switch checked={st.settings.appearOffline} label="Appear offline" sub="Friends see you as offline and can’t challenge you." onchange={offline} />
    <Switch
      checked={st.settings.chatEnabled}
      label="Chat in friend games"
      sub="Off: you don’t see or send messages, and friends see that your chat is off. Messages are never saved: they’re deleted when the game ends."
      onchange={(v) => set({ chatEnabled: v })}
    />
    <div class="links">
      <button type="button" class="link" onclick={() => (legal = 'privacy')}>Privacy policy</button>
      <button type="button" class="link" onclick={() => (legal = 'terms')}>Terms of use</button>
    </div>
    <div class="del">
      <span
        ><span class="block">Delete account</span><span class="sub">Removes your handle, friends and requests from the server. Your games stay on this computer.</span></span
      >
      {#if confirming}
        <span class="pair">
          <Button variant="danger" disabled={deleting} onclick={del}>{deleting ? 'Deleting…' : 'Delete it'}</Button>
          <Button variant="quiet" onclick={() => (confirming = false)}>Keep it</Button>
        </span>
      {:else}
        <Button variant="danger" onclick={() => (confirming = true)}>Delete account</Button>
      {/if}
    </div>
  {/if}
  {#if error}<p class="err" role="alert">{error}</p>{/if}
</div>
{#if legal}<LegalDialog doc={legal} onclose={() => (legal = null)} />{/if}

<style>
  .friends {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .kv {
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
  }
  .k {
    color: var(--text-2);
  }
  .dots {
    color: var(--text-3);
    letter-spacing: 0.1em;
  }
  .code {
    user-select: all;
    letter-spacing: 0.04em;
    overflow-wrap: anywhere;
  }
  .links {
    display: flex;
    align-items: center;
    gap: 16px;
    font: var(--secondary);
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-2);
    text-decoration: underline;
    font: inherit;
    cursor: pointer;
  }
  .del {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding-top: 12px;
    border-top: 1px solid var(--divider);
  }
  .block {
    display: block;
  }
  .sub,
  .quiet {
    color: var(--text-3);
    font: var(--secondary);
  }
  .quiet {
    margin: 0;
  }
  .pair {
    display: flex;
    gap: var(--space-2);
    flex: none;
  }
  .err {
    margin: 0;
    color: var(--loss);
    font: var(--secondary);
  }
</style>
