<script lang="ts">
  /** Friends before an account (MinimalFriends-signup.html; rulings A1, A3, L1): a handle checked as
   *  you type, the linked accounts, what the server keeps, and the two required boxes (the sharing
   *  switch hidden, BETA-6 ruling SG1). Or the recovery code of an existing account (A2). */
  import Button from '../ui/Button.svelte'
  import LegalDialog from './LegalDialog.svelte'
  import { friendsApi } from './friendsApi'
  import { HANDLE_RULE, handleShape } from './friendsModel'
  import { accounts } from '../settings.svelte'
  import { errorText, friendsState, refreshList, refreshStatus } from './friendsState.svelte'

  let handle = $state('')
  let check = $state<{ handle: string; text: string; ok: boolean } | null>(null)
  let checking = $state(false)
  let age = $state(false)
  let terms = $state(false)
  let busy = $state(false)
  let error = $state<string | null>(null)
  let legal = $state<'privacy' | 'terms' | null>(null)
  let recovering = $state(false)
  let code = $state('')

  const shape = $derived(handleShape(handle.trim()))
  let timer: ReturnType<typeof setTimeout> | undefined
  $effect(() => {
    const h = handle.trim()
    clearTimeout(timer)
    check = null
    if (!h || handleShape(h)) return
    checking = true
    timer = setTimeout(async () => {
      try {
        const r = await friendsApi.checkHandle(h)
        if (h !== handle.trim()) return
        check = {
          handle: h,
          ok: r.available,
          text: r.available ? 'Available' : r.reason === 'reserved' ? 'Reserved' : r.reason === 'invalid' ? 'Not allowed' : 'Taken',
        }
      } catch (e) {
        check = { handle: h, ok: false, text: errorText(e) }
      } finally {
        checking = false
      }
    }, 350)
  })
  const ready = $derived(!!check?.ok && check.handle === handle.trim() && age && terms && !busy)

  async function create() {
    if (!ready) return
    busy = true
    error = null
    try {
      const r = await friendsApi.signup({ handle: handle.trim(), ageConfirmed: age, termsAccepted: terms })
      friendsState.recoveryCode = r.recoveryCode
      await refreshStatus()
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = false
    }
  }
  async function recover() {
    busy = true
    error = null
    try {
      await friendsApi.recover(code)
      await refreshStatus()
      await refreshList()
    } catch (e) {
      error = errorText(e)
    } finally {
      busy = false
    }
  }
</script>

<div class="wrap">
  <div class="col">
    {#if !recovering}
      <div>
        <h2>Play your friends</h2>
        <p class="lead">Pick a handle your friends can find you by. You can see each other's games, compare notes and play each other here.</p>
      </div>
      <div>
        <label for="hdl" class="cap">Handle</label>
        <div class="field">
          <input id="hdl" type="text" spellcheck="false" autocomplete="off" maxlength="20" bind:value={handle} placeholder="your_handle" />
          {#if shape}<span class="st bad">{shape}</span>
          {:else if checking}<span class="st">Checking…</span>
          {:else if check}<span class="st" class:good={check.ok} class:bad={!check.ok}>{check.text}</span>{/if}
        </div>
        <div class="hint">{HANDLE_RULE}</div>
      </div>
      <div class="box">
        <div class="boxhead">Linked accounts, for your ratings and your games</div>
        <div class="lrow">
          <span class="site">Chess.com</span>
          {#if accounts.chesscom}<span class="grow">{accounts.chesscom} <span class="muted">(from Settings)</span></span>
          {:else}<span class="grow muted">Not linked</span>{/if}
        </div>
        <div class="lrow div">
          <span class="site">Lichess</span>
          {#if accounts.lichess}<span class="grow">{accounts.lichess} <span class="muted">(from Settings)</span></span>
          {:else}<span class="grow muted">Not linked</span>{/if}
        </div>
        <div class="boxfoot">You prove they are yours on the Friends screen once the account exists: Lichess by its sign-in, Chess.com by a short code in your profile.</div>
      </div>
      <div class="keeps">
        The Zugzwang server keeps your handle, a public key, the date you joined, your linked usernames, your friends and requests, and when you were
        last online. No email and no password: this computer holds your key. Chat messages are never saved. You can delete your account in Settings at
        any time.
      </div>
      <div class="boxes">
        <label class="cb"><input type="checkbox" bind:checked={age} />I’m 13 or older</label>
        <label class="cb"
          ><input type="checkbox" bind:checked={terms} /><span
            >I agree to the <button type="button" class="link" onclick={() => (legal = 'terms')}>Terms of use</button> and the
            <button type="button" class="link" onclick={() => (legal = 'privacy')}>Privacy policy</button></span
          ></label
        >
      </div>
      {#if error}<p class="err" role="alert">{error}</p>{/if}
      <Button variant="primary" disabled={!ready} onclick={create}>{busy ? 'Creating…' : 'Create account'}</Button>
      <button type="button" class="link small" onclick={() => ((recovering = true), (error = null))}>Have an account already? Use your recovery code</button>
    {:else}
      <div>
        <h2>Use your recovery code</h2>
        <p class="lead">Type the code you saved when you made your account. Your key is made again from it, on this computer.</p>
      </div>
      <div class="field">
        <input type="text" spellcheck="false" autocomplete="off" aria-label="Recovery code" bind:value={code} placeholder="XXXX-XXXX-XXXX-…" />
      </div>
      {#if error}<p class="err" role="alert">{error}</p>{/if}
      <Button variant="primary" disabled={busy || code.trim().length < 36} onclick={recover}>{busy ? 'Checking…' : 'Restore account'}</Button>
      <button type="button" class="link small" onclick={() => ((recovering = false), (error = null))}>Make a new account instead</button>
    {/if}
  </div>
</div>
{#if legal}<LegalDialog doc={legal} onclose={() => (legal = null)} />{/if}

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
  .cap {
    display: block;
    color: var(--text-3);
    font: var(--secondary);
    margin-bottom: 6px;
  }
  .field {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  .field input {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: 0;
    outline: none;
    color: var(--text);
    font: var(--body);
  }
  .field:focus-within {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .st {
    font: var(--secondary);
    color: var(--text-3);
    white-space: nowrap;
  }
  .st.good {
    color: var(--win);
  }
  .st.bad {
    color: var(--loss);
  }
  .hint {
    color: var(--text-3);
    font: var(--secondary);
    margin-top: 6px;
  }
  .box {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
  }
  .boxhead {
    padding: 10px 14px;
    color: var(--text-3);
    font: var(--secondary);
    border-bottom: 1px solid var(--border);
  }
  .boxfoot {
    padding: 8px 14px 10px;
    color: var(--text-3);
    font: var(--secondary);
    border-top: 1px solid var(--divider);
  }
  .lrow {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
  }
  .lrow.div {
    border-top: 1px solid var(--divider);
  }
  .site {
    width: 72px;
    color: var(--text-2);
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .muted {
    color: var(--text-3);
  }
  .keeps {
    padding: 12px 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    color: var(--text-2);
    font: var(--secondary);
    line-height: 1.55;
  }
  .boxes {
    display: flex;
    flex-direction: column;
    gap: 8px;
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
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--text);
    text-decoration: underline;
    font: inherit;
    cursor: pointer;
  }
  .link.small {
    align-self: flex-start;
    color: var(--text-2);
    font: var(--secondary);
  }
  .err {
    margin: 0;
    color: var(--loss);
  }
</style>
