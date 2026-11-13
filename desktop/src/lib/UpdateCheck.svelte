<script lang="ts">
  /** The updater (BETA item 8). Beta builds check once on launch; when a newer version is
   *  published it says which, and installs only when the tester confirms, then restarts.
   *  A failed check (offline, or no update feed reachable) stays silent — it is logged to
   *  the console, not shown: the app works the same without it. Settings → About this
   *  build has a "Check for updates" button that calls `checkNow`, which does report. */
  import { onMount } from 'svelte'
  import { check, type Update } from '@tauri-apps/plugin-updater'
  import { relaunch } from '@tauri-apps/plugin-process'
  import { getVersion } from '@tauri-apps/api/app'
  import { BETA, UPDATE_AUTOCONFIRM } from './build'
  import { updateState } from './updateState.svelte'

  let update = $state<Update | null>(null)
  let current = $state('')
  let phase = $state<'offer' | 'downloading' | 'installing' | 'error' | 'hidden'>('hidden')
  let got = $state(0)
  let total = $state(0)
  let error = $state('')

  async function find(report: boolean) {
    try {
      current = await getVersion()
      const u = await check()
      updateState.lastCheck = u ? `Version ${u.version} is available.` : `Up to date (${current}).`
      if (u) {
        update = u
        phase = 'offer'
        if (UPDATE_AUTOCONFIRM) void install()     // local end-to-end proof builds only
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      console.warn('[updater] check failed:', msg)
      if (report) updateState.lastCheck = `Could not check for updates: ${msg}`
    }
  }

  async function install() {
    if (!update) return
    phase = 'downloading'
    got = 0
    total = 0
    try {
      await update.downloadAndInstall((ev) => {
        if (ev.event === 'Started') total = ev.data.contentLength ?? 0
        else if (ev.event === 'Progress') got += ev.data.chunkLength
        else if (ev.event === 'Finished') phase = 'installing'
      })
      await relaunch()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      phase = 'error'
    }
  }

  onMount(() => {
    if (!BETA) return
    updateState.checkNow = () => find(true)
    void find(false)
  })
</script>

{#if BETA && phase !== 'hidden'}
  <div class="update" role="status">
    {#if phase === 'offer' && update}
      <span>
        <strong>Zugzwang {update.version}</strong> is available — you have {current}.
      </span>
      <button class="btn btn-accent" onclick={install}>Update and restart</button>
      <button class="later" onclick={() => (phase = 'hidden')}>Later</button>
    {:else if phase === 'downloading'}
      <span class="pulse-dot"></span>
      <span>
        Downloading {update?.version}…
        {total ? `${Math.round((100 * got) / total)}%` : ''}
      </span>
    {:else if phase === 'installing'}
      <span class="pulse-dot"></span><span>Installing — Zugzwang will restart.</span>
    {:else if phase === 'error'}
      <span class="err">The update failed: {error}</span>
      <button class="later" onclick={() => (phase = 'hidden')}>Dismiss</button>
    {/if}
  </div>
{/if}

<style>
  .update {
    position: fixed;
    right: 16px;
    bottom: 16px;
    z-index: 1100;
    display: flex;
    align-items: center;
    gap: 10px;
    max-width: min(560px, calc(100vw - 32px));
    padding: 10px 14px;
    font-size: 13px;
    color: var(--text);
    background: var(--bg-surface);
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-pop);
  }
  .later {
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 12.5px;
  }
  .err {
    color: var(--danger);
  }
</style>
