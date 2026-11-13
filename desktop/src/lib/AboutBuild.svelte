<script lang="ts">
  /** Settings → "About this build", shown only in beta builds (BETA items 2 and 4):
   *  the version, where the data and the sidecar log live, each with a button that
   *  reveals it in the file manager so a tester can send it. */
  import { onMount } from 'svelte'
  import { openUrl, revealItemInDir } from '@tauri-apps/plugin-opener'
  import { api, type AppInfo } from './api'
  import { updateState } from './updateState.svelte'

  let info = $state<AppInfo | null>(null)
  let revealError = $state('')

  async function reveal(path: string) {
    revealError = ''
    try {
      await revealItemInDir(path)
    } catch (e) {
      revealError = e instanceof Error ? e.message : String(e)
    }
  }

  // Licences (BETA scope 6): the texts ship in the app (public/licenses/), and the
  // Stockfish source link is the exact release tag.
  let licence = $state<{ name: string; text: string } | null>(null)
  async function showLicence(name: string, file: string) {
    if (licence?.name === name) {
      licence = null
      return
    }
    try {
      const res = await fetch(`/licenses/${file}`)
      licence = { name, text: await res.text() }
    } catch (e) {
      licence = { name, text: String(e) }
    }
  }

  onMount(async () => {
    try {
      info = await api.appInfo()
    } catch {
      /* sidecar not up yet; the card says so */
    }
  })
</script>

<section class="card">
  <div class="card-head">
    <h2 class="card-title">About this build <span class="badge">Beta</span></h2>
    <p class="card-sub">
      Version {info?.version ?? '…'}{info?.commit ? ` · ${info.commit.slice(0, 7)}` : ''} ·
      classifier v{info?.classifierVersion ?? '…'} · rules v{info?.ruleVersion ?? '…'}
    </p>
  </div>
  {#if info}
    <div class="row">
      <span class="label">Log file</span>
      <code class="path">{info.logPath}</code>
      <button class="btn btn-quiet" onclick={() => reveal(info!.logPath)}>Show in folder</button>
    </div>
    <div class="row">
      <span class="label">Flags</span>
      <code class="path">{info.flagsPath}</code>
      <button class="btn btn-quiet" onclick={() => reveal(info!.flagsDir)}>Show in folder</button>
    </div>
    <p class="hint">
      Use ⚑ beside any label, explanation or report line to flag it. Flags are saved to
      the file above, on this computer only — send it to the developer when you like.
    </p>
    <div class="row">
      <span class="label">Data folder</span>
      <code class="path">{info.dataDir}</code>
      <button class="btn btn-quiet" onclick={() => reveal(info!.dbPath ?? info!.dataDir)}>
        Show in folder
      </button>
    </div>
    {#if revealError}<span class="error">{revealError}</span>{/if}
    <div class="row">
      <span class="label">Updates</span>
      <span class="hint">{updateState.lastCheck || 'Checked when Zugzwang starts.'}</span>
      <button class="btn btn-quiet" disabled={!updateState.checkNow}
              onclick={() => updateState.checkNow?.()}>Check now</button>
    </div>

    <div class="licences">
      <h3 class="sub-title">Licences</h3>
      <p class="hint">
        Zugzwang is free software under the GNU General Public License, version 3 or (at your
        option) any later version. Its complete source for this version is public.
      </p>
      <div class="lic-actions">
        <button class="btn btn-quiet" onclick={() => showLicence('own', 'zugzwang-LICENSE.txt')}>
          Zugzwang licence (GPL-3.0-or-later)
        </button>
        <button class="btn btn-quiet" onclick={() => openUrl(info!.source)}>
          Zugzwang {info.version} source code
        </button>
      </div>
      <p class="hint">
        It bundles <strong>Stockfish 18</strong>, free software under the GNU General
        Public License v3, unmodified from the official release.
      </p>
      <div class="lic-actions">
        <button class="btn btn-quiet" onclick={() => showLicence('gpl', 'stockfish-COPYING.txt')}>
          Stockfish licence (GPLv3)
        </button>
        <button class="btn btn-quiet" onclick={() => openUrl(info!.stockfishSource)}>
          Stockfish 18 source code
        </button>
        <button class="btn btn-quiet" onclick={() => showLicence('third', 'THIRD-PARTY.txt')}>
          All third-party software
        </button>
      </div>
      {#if licence}<pre class="lic-text">{licence.text}</pre>{/if}
    </div>
  {:else}
    <p class="hint">Waiting for the engine backend…</p>
  {/if}
</section>

<style>
  .card {
    background: var(--bg-surface);
    border: 1px solid var(--divider);
    border-radius: var(--radius-lg);
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .card-head {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .card-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .badge {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent);
    border: 1px solid var(--accent);
    border-radius: 999px;
    padding: 1px 7px;
  }
  .card-sub,
  .hint {
    margin: 0;
    font-size: 13px;
    color: var(--text-muted);
  }
  .row {
    display: grid;
    grid-template-columns: 92px 1fr auto;
    align-items: center;
    gap: 10px;
  }
  .label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
  }
  .path {
    font-size: 11.5px;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    padding: 6px 9px;
    word-break: break-all;
    user-select: text;
    color: var(--text-muted);
  }
  .error {
    font-size: 12px;
    color: var(--danger);
  }
  .licences {
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-top: 1px solid var(--divider);
    padding-top: 14px;
  }
  .sub-title {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
  }
  .lic-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .lic-text {
    max-height: 260px;
    overflow: auto;
    margin: 0;
    padding: 10px 12px;
    font-size: 11px;
    line-height: 1.4;
    white-space: pre-wrap;
    border: 1px solid var(--divider);
    border-radius: var(--radius-sm);
    user-select: text;
    color: var(--text-muted);
  }
</style>
