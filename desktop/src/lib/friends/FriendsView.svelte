<script lang="ts">
  /** The Friends screen (FRIENDS-1 C): whichever of its states applies, in order: not available in
   *  this build or on this computer, sign up (or recover), the recovery code once after sign-up, the
   *  friends list. */
  import { onMount } from 'svelte'
  import EmptyState from '../ui/EmptyState.svelte'
  import FriendsList from './FriendsList.svelte'
  import RecoveryView from './RecoveryView.svelte'
  import SignupView from './SignupView.svelte'
  import { friendsApi, type Linked } from './friendsApi'
  import { errorText, friendsState, refreshList, refreshStatus } from './friendsState.svelte'

  interface Props {
    onopen: (handle: string) => void
    now?: number
  }
  let { onopen, now }: Props = $props()
  let linked = $state<Linked[] | null>(null)
  let meError = $state<string | null>(null)

  async function loadMe() {
    try {
      linked = (await friendsApi.me()).linked
      meError = null
    } catch (e) {
      meError = errorText(e)
    }
  }
  onMount(async () => {
    const s = friendsState.status ?? (await refreshStatus())
    if (s?.signedIn) {
      await Promise.all([refreshList(), loadMe()])
    }
  })
  const st = $derived(friendsState.status)
  async function done() {
    friendsState.recoveryCode = null
    await Promise.all([refreshList(), loadMe()])
  }
</script>

<div class="screen">
  <header>
    <h1>Friends</h1>
    {#if st?.signedIn && st.handle}<span class="mine">Your handle <span class="h">{st.handle}</span></span>{/if}
  </header>
  {#if !st}
    <div class="pad"><EmptyState sentence={friendsState.error ? 'Friends could not start.' : 'Opening Friends…'} sub={friendsState.error} /></div>
  {:else if !st.enabled}
    <div class="pad"><EmptyState sentence="Friends is not in this build of Zugzwang yet." /></div>
  {:else if !st.configured}
    <div class="pad"><EmptyState sentence="Friends needs its server, which is not set up for this copy of Zugzwang yet." /></div>
  {:else if !st.keystore.available}
    <div class="pad"><EmptyState sentence="This computer has no keychain Zugzwang can keep a Friends key in." sub="Friends keeps your key in the macOS Keychain or the Windows Credential Manager, never in its own files." /></div>
  {:else if friendsState.recoveryCode}
    <RecoveryView code={friendsState.recoveryCode} oncontinue={done} />
  {:else if !st.signedIn}
    <SignupView />
  {:else if friendsState.list}
    <FriendsList list={friendsState.list} {linked} {onopen} onlinked={loadMe} {now} />
    {#if meError}<p class="err">{meError}</p>{/if}
  {:else}
    <div class="pad">
      <EmptyState
        sentence={friendsState.error ? 'Could not reach the Friends server.' : 'Opening your friends…'}
        sub={friendsState.error}
        tone={friendsState.error ? 'error' : 'quiet'}
        action={friendsState.error ? { label: 'Try again', run: () => void refreshList() } : null}
      />
    </div>
  {/if}
</div>

<style>
  .screen {
    display: flex;
    flex-direction: column;
    min-height: 100%;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  header {
    height: var(--header-height);
    box-sizing: border-box;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 0 16px 0 28px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    margin: 0;
    font: var(--body-strong);
  }
  .mine {
    color: var(--text-3);
    font: var(--secondary);
  }
  .h {
    color: var(--text);
  }
  .pad {
    padding: 20px 28px;
  }
  .err {
    margin: 0 28px;
    color: var(--loss);
    font: var(--secondary);
  }
</style>
