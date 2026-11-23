<script lang="ts">
  /** Settings → About, at the foot (UI-BUILD-2 E1): what was "About this build" (BETA items 2,
   *  4, 6 and 8), in the redesign's language. Every build shows its version and licences; a beta
   *  build also shows where its log, flags and data live, each revealable, and the update check. */
  import { onMount } from 'svelte'
  import { openUrl, revealItemInDir } from '@tauri-apps/plugin-opener'
  import Button from '../ui/Button.svelte'
  import { api, type AppInfo } from '../api'
  import { BETA, SHOW_FRIENDS } from '../build'
  import { updateState } from '../updateState.svelte'

  let info = $state<AppInfo | null>(null)
  let error = $state<string | null>(null)
  let revealError = $state<string | null>(null)
  let licence = $state<{ name: string; text: string } | null>(null)

  async function load() {
    try {
      info = await api.appInfo()
      error = null
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }
  async function reveal(path: string) {
    revealError = null
    try {
      await revealItemInDir(path)
    } catch (e) {
      revealError = e instanceof Error ? e.message : String(e)
    }
  }
  // The licence texts ship in the app (public/licenses/).
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
  onMount(load)
</script>

{#if error && !info}
  <p class="quiet">The build's details could not be read: {error} <Button size="sm" variant="quiet" onclick={load}>Try again</Button></p>
{:else if !info}
  <p class="quiet">Reading the build's details…</p>
{:else}
  <div class="strong">
    Zugzwang {info.version}{info.commit ? ` · ${info.commit.slice(0, 7)}` : ''}{BETA ? ' · beta' : ''}
  </div>
  <div class="sub">Classifier version {info.classifierVersion}, rules version {info.ruleVersion}</div>

  {#if BETA}
    <dl class="files">
      <div><dt>Log file</dt><dd title={info.logPath}>{info.logPath}</dd><Button size="sm" onclick={() => reveal(info!.logPath)}>Show in folder</Button></div>
      <div><dt>Flags</dt><dd title={info.flagsPath}>{info.flagsPath}</dd><Button size="sm" onclick={() => reveal(info!.flagsDir)}>Show in folder</Button></div>
      <div><dt>Data folder</dt><dd title={info.dataDir}>{info.dataDir}</dd><Button size="sm" onclick={() => reveal(info!.dbPath ?? info!.dataDir)}>Show in folder</Button></div>
      <div>
        <dt>Updates</dt><dd>{updateState.lastCheck || 'Checked when Zugzwang starts.'}</dd>
        <Button size="sm" disabled={!updateState.checkNow} onclick={() => updateState.checkNow?.()}>Check now</Button>
      </div>
    </dl>
    <p class="quiet">
      Flag any label, explanation or report line with ⚑. Flags are saved to the file above, on this computer only; send it to
      the developer when you like.
    </p>
    {#if revealError}<p class="err">{revealError}</p>{/if}
  {/if}

  <p class="quiet">
    Zugzwang is free software under the GNU General Public License, version 3 or later. It bundles Stockfish 18 (GPLv3),
    unmodified from the official release.
  </p>
  {#if SHOW_FRIENDS}
    <p class="quiet">
      Friends' "≈" ratings convert Lichess ratings to Chess.com's scale with the ChessGoals rating comparison
      (chessgoals.com/rating-comparison), a copy taken on 21 November 2026. The app's ℤ mark is the msbm10 font of the
      American Mathematical Society (SIL Open Font License 1.1).
    </p>
  {/if}
  <div class="acts">
    <Button size="sm" onclick={() => showLicence('own', 'zugzwang-LICENSE.txt')}>Zugzwang licence</Button>
    <Button size="sm" onclick={() => showLicence('gpl', 'stockfish-COPYING.txt')}>Stockfish licence</Button>
    <Button size="sm" onclick={() => showLicence('third', 'THIRD-PARTY.txt')}>All third-party software</Button>
    <Button size="sm" variant="quiet" onclick={() => openUrl(info!.source)}>Source code</Button>
    <Button size="sm" variant="quiet" onclick={() => openUrl(info!.stockfishSource)}>Stockfish 18 source</Button>
  </div>
  {#if licence}<pre class="lic">{licence.text}</pre>{/if}
{/if}

<style>
  .strong {
    font-weight: 500;
  }
  .sub,
  .quiet {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .err {
    margin: 0;
    color: var(--loss);
    font: var(--secondary);
  }
  .files {
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .files > div {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) auto;
    gap: var(--space-4);
    align-items: center;
    padding: 8px 12px;
  }
  .files > div + div {
    border-top: 1px solid var(--divider);
  }
  dt {
    color: var(--text-3);
    font: var(--secondary);
  }
  dd {
    margin: 0;
    color: var(--text-2);
    font: var(--secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    user-select: text;
  }
  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .lic {
    max-height: 260px;
    overflow: auto;
    margin: 0;
    padding: 10px 12px;
    font: var(--secondary);
    white-space: pre-wrap;
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    color: var(--text-2);
    user-select: text;
  }
</style>
