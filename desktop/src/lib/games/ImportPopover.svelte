<script lang="ts">
  /**
   * Import PGN (UI-BUILD-3 E; mockup design/mockups/MinimalGames-import.html): paste one game or
   * many, or choose a file; the button counts the games pasted, live. The import is the old
   * screen's (import_pgn, colour from the saved usernames, a report of any game that did not come
   * through whole: importReport.ts); the parent then queues the imported games for depth 14.
   */
  import { onMount } from 'svelte'
  import { api, type ImportIssue, type ImportResult } from '../api'
  import { importSummary } from '../importReport'
  import { pickPgn } from '../pick'
  import { accounts } from '../settings.svelte'
  import { countPgnGames, importLabel } from './gamesModel'

  interface Props {
    /** the games are stored: refresh and analyse them; `stay` when the popover shows a report */
    onimported: (res: ImportResult, stay: boolean) => void
    oncancel: () => void
  }
  let { onimported, oncancel }: Props = $props()

  let text = $state('')
  let field: HTMLTextAreaElement | undefined = $state()
  let importing = $state(false)
  let error = $state<string | null>(null)
  let note = $state<string | null>(null)
  let issues = $state<ImportIssue[]>([])
  let from = $state<string | null>(null)
  const count = $derived(countPgnGames(text))

  onMount(() => field?.focus())

  const usernames = () => [accounts.lichess, accounts.chesscom].filter((u) => u.length > 0)

  async function run(call: () => Promise<ImportResult>) {
    importing = true
    error = null
    note = null
    issues = []
    try {
      const res = await call()
      text = ''
      if (res.issues.length > 0) {
        // Stay open: a truncated or skipped game is the one moment the user can still act.
        issues = res.issues
        note = importSummary(res.count, res.issues)
        onimported(res, true)
      } else onimported(res, false)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      importing = false
    }
  }
  const importText = () => {
    from = null
    if (count > 0) void run(() => api.importPgn(text, usernames()))
  }
  async function importFile() {
    const path = await pickPgn()
    if (path === null) return
    from = path.split(/[\\/]/).pop() ?? path
    await run(() => api.importPgnFile(path, usernames()))
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      oncancel()
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      importText()
    }
  }
</script>

<div class="pop" role="dialog" aria-label="Import PGN" tabindex="-1" onkeydown={key}>
  <div class="title">Import PGN</div>
  <textarea bind:this={field} bind:value={text} rows="7" spellcheck="false" aria-label="PGN" disabled={importing}></textarea>
  <div class="hint">Paste one game or many. They are added to your games and analysed at depth 14.</div>
  {#if error}<div class="error" role="alert">{error}</div>{/if}
  {#if note}
    <div class="note" role="status">{from ? `From ${from}: ` : ''}{note}</div>
    <ul class="issues">
      {#each issues as issue (issue.index)}
        <li><span class="where">Game {issue.index}, {issue.label}</span> <span class="why">{issue.imported ? 'stored incomplete' : 'skipped'}: {issue.reason}</span></li>
      {/each}
    </ul>
  {/if}
  <div class="actions">
    <button type="button" class="ghost" disabled={importing} onclick={importFile}>Choose a file</button>
    <span class="grow"></span>
    <button type="button" class="quiet" onclick={oncancel}>{note ? 'Close' : 'Cancel'}</button>
    <button type="button" class="primary" disabled={importing || count === 0} onclick={importText}>
      {importing ? 'Importing…' : importLabel(count)}
    </button>
  </div>
</div>

<style>
  .pop {
    width: 440px;
    box-sizing: border-box;
    background: var(--raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    font: var(--body);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .pop:focus {
    outline: none;
  }
  .title {
    font-weight: 500;
  }
  textarea {
    resize: none;
    background: var(--bg);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    padding: 8px 10px;
    color: var(--text-2);
    font: var(--secondary);
    line-height: 1.5;
    user-select: text;
  }
  textarea:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .hint,
  .note,
  .why {
    color: var(--text-3);
    font: var(--secondary);
  }
  .note {
    color: var(--text-2);
  }
  .error {
    font: var(--secondary);
    color: var(--text);
  }
  .error::before {
    content: '';
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 4px;
    background: var(--loss);
    margin-right: 8px;
    vertical-align: 1px;
  }
  .issues {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 140px;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font: var(--secondary);
  }
  .where {
    color: var(--text-2);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .grow {
    flex: 1;
  }
  button {
    font: var(--body);
    border-radius: var(--radius-control);
    padding: 5px 10px;
    cursor: pointer;
  }
  .ghost {
    background: transparent;
    border: 1px solid var(--border-control);
    color: var(--text-2);
  }
  .ghost:hover:not(:disabled),
  .quiet:hover {
    color: var(--text);
  }
  .quiet {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-2);
  }
  .primary {
    background: var(--primary);
    border: 1px solid var(--primary);
    color: var(--primary-ink);
    font-weight: 500;
  }
  button:disabled {
    cursor: default;
    color: var(--disabled);
    background: transparent;
    border-color: var(--border);
  }
</style>
