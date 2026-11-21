<script lang="ts">
  /**
   * Analyse a position (UI-BUILD-3 E; mockup design/mockups/MinimalGames-position.html): paste a
   * FEN, or a PGN to start from its last move; a small board shows it and a line says whether it
   * is legal. Reusable: Games shows it as a popover under its header button, App as a dialog for
   * Home's "Analyse a game". Nothing pasted is the starting position.
   */
  import { onMount } from 'svelte'
  import Board from '../Board.svelte'
  import { previewPlacement, readPosition } from './positionModel'

  interface Props {
    onanalyse: (fen: string) => void
    onplay: (fen: string) => void
    oncancel: () => void
  }
  let { onanalyse, onplay, oncancel }: Props = $props()

  let text = $state('')
  let field: HTMLTextAreaElement | undefined = $state()
  const read = $derived(readPosition(text))
  const placement = $derived(previewPlacement(read))
  const NO_DESTS = new Map()

  onMount(() => field?.focus())

  function analyse() {
    if (read.ok) onanalyse(read.fen)
  }
  function play() {
    if (read.ok && !read.over) onplay(read.fen)
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      oncancel()
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      analyse()
    }
  }
</script>

<div class="pop" role="dialog" aria-label="Analyse a position" tabindex="-1" onkeydown={key}>
  <div class="title">Analyse a position</div>
  <textarea
    bind:this={field}
    bind:value={text}
    rows="2"
    spellcheck="false"
    aria-label="FEN or PGN"
    placeholder="A FEN, or a PGN"
  ></textarea>
  <div class="body">
    <div class="mini" role="img" aria-label={read.ok ? `The position, ${read.turn === 'white' ? 'White' : 'Black'} to move` : 'The position as far as it can be read'}>
      <Board
        fen={placement}
        lastMove={null}
        turnColor={read.ok ? read.turn : 'white'}
        movableColor={null}
        dests={NO_DESTS}
        check={false}
        orientation="white"
        coordinates={false}
        animationMs={0}
      />
    </div>
    <div class="status" aria-live="polite">
      {#if read.ok}
        <span class="legal">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--win)" stroke-width="2.4" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19.5 7"></path></svg>
          A legal position
        </span>
        <span class="turn">{read.turn === 'white' ? 'White' : 'Black'} to move{read.over ? (read.check ? ', checkmated' : ', no legal move') : ''}</span>
        {#if read.from === 'start'}<span class="turn">The starting position</span>{/if}
        {#if read.from === 'pgn'}<span class="turn">After the PGN's last move</span>{/if}
      {:else}
        <span class="illegal">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--loss)" stroke-width="2.4" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
          Not a legal position
        </span>
        <span class="turn">{read.reason}</span>
      {/if}
      <span class="hint">Paste a FEN, or a PGN to start from its last move.</span>
    </div>
  </div>
  <div class="actions">
    <button type="button" class="ghost" disabled={!read.ok || read.over} onclick={play}>Play it vs Stockfish</button>
    <span class="grow"></span>
    <button type="button" class="quiet" onclick={oncancel}>Cancel</button>
    <button type="button" class="primary" disabled={!read.ok} onclick={analyse}>Analyse</button>
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
    padding: 6px 10px;
    color: var(--text);
    font: var(--secondary);
    user-select: text;
  }
  textarea::placeholder {
    color: var(--text-3);
  }
  textarea:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .body {
    display: flex;
    gap: 14px;
    align-items: flex-start;
  }
  .mini {
    width: 152px;
    height: 152px;
    flex: none;
    border-radius: var(--radius-board);
    overflow: hidden;
  }
  .status {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-top: 2px;
    min-width: 0;
  }
  .legal,
  .illegal {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .turn {
    color: var(--text-2);
  }
  .hint {
    color: var(--text-3);
    font: var(--secondary);
    margin-top: 6px;
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
  .ghost:hover:not(:disabled) {
    color: var(--text);
  }
  .quiet {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-2);
  }
  .quiet:hover {
    color: var(--text);
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
