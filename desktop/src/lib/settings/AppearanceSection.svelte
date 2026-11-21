<script lang="ts">
  /** Settings → Appearance (ruling 20): the six board colours and the five piece sets, each
   *  saved at once and applied to every board (appearance.svelte.ts), and the sets' credit. */
  import { BOARD_THEMES, boardTheme, type BoardThemeId } from '../board/boardThemes'
  import { PIECE_SETS, creditLine, type PieceSetId } from '../board/pieceSets'
  import { pieceUrls } from '../board/pieceAssets'
  import { appearance, setBoardTheme, setPieceSet } from '../board/appearance.svelte'

  const theme = $derived(boardTheme(appearance.boardTheme))

  /** Arrow keys move the choice within a radiogroup, as the segmented control does. */
  function arrows<T extends string>(e: KeyboardEvent, ids: T[], current: T, set: (id: T) => void) {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = ids[(ids.indexOf(current) + step + ids.length) % ids.length]
    set(next)
    ;(e.currentTarget as HTMLElement).querySelector<HTMLElement>(`[data-id="${next}"]`)?.focus()
  }
  const themeIds = BOARD_THEMES.map((t) => t.id)
  const setIds = PIECE_SETS.map((s) => s.id)
</script>

<div class="line">
  <span class="cap">Board</span>
  <div
    class="choices"
    role="radiogroup"
    aria-label="Board colours"
    tabindex="-1"
    onkeydown={(e) => arrows<BoardThemeId>(e, themeIds, appearance.boardTheme, setBoardTheme)}
  >
    {#each BOARD_THEMES as t (t.id)}
      <button
        type="button"
        role="radio"
        data-id={t.id}
        aria-checked={appearance.boardTheme === t.id}
        tabindex={appearance.boardTheme === t.id ? 0 : -1}
        onclick={() => setBoardTheme(t.id)}
      >
        <span class="swatch sq" aria-hidden="true">
          <span style:background={t.light}></span><span style:background={t.dark}></span><span style:background={t.dark}></span><span
            style:background={t.light}
          ></span>
        </span>
        {t.name}
      </button>
    {/each}
  </div>
</div>

<div class="line pieces">
  <span class="cap">Pieces</span>
  <div
    class="choices"
    role="radiogroup"
    aria-label="Piece set"
    tabindex="-1"
    onkeydown={(e) => arrows<PieceSetId>(e, setIds, appearance.pieceSet, setPieceSet)}
  >
    {#each PIECE_SETS as s (s.id)}
      {@const urls = pieceUrls(s.id)}
      <button
        type="button"
        role="radio"
        data-id={s.id}
        aria-checked={appearance.pieceSet === s.id}
        tabindex={appearance.pieceSet === s.id ? 0 : -1}
        title="{s.name}, {s.licence}"
        onclick={() => setPieceSet(s.id)}
      >
        <span class="swatch wide" aria-hidden="true">
          <span style:background={theme.light}><img src={urls.wN} alt="" width="44" height="44" /></span>
          <span style:background={theme.dark}><img src={urls.bK} alt="" width="44" height="44" /></span>
        </span>
        {s.name}
      </button>
    {/each}
  </div>
</div>

<p class="credit">{creditLine()}</p>

<style>
  .line {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr);
    gap: var(--space-4);
    align-items: start;
  }
  .pieces {
    margin-top: 6px;
  }
  .cap {
    color: var(--text-3);
    font: var(--secondary);
    padding-top: 18px;
  }
  .choices {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
  }
  button {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    background: none;
    border: 0;
    padding: 0;
    font: var(--body);
    color: var(--text-2);
    cursor: pointer;
  }
  button[aria-checked='true'] {
    color: var(--text);
  }
  button:hover {
    color: var(--text);
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 4px;
    border-radius: var(--radius-board);
  }
  .swatch {
    height: 52px;
    border-radius: var(--radius-board);
    display: grid;
    grid-template-columns: 1fr 1fr;
    overflow: hidden;
  }
  .sq {
    width: 52px;
  }
  .wide {
    width: 104px;
  }
  .wide > span {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  button[aria-checked='true'] .swatch {
    box-shadow:
      0 0 0 2px var(--bg),
      0 0 0 3.5px var(--text);
  }
  .credit {
    margin: 0;
    color: var(--text-3);
    font: var(--secondary);
  }
</style>
