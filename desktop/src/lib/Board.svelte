<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Chessground } from 'chessground'
  import type { Api } from 'chessground/api'
  import type { Config } from 'chessground/config'
  import type { DrawShape } from 'chessground/draw'
  import type { Key } from 'chessground/types'
  import MoveQualityIcon from './ui/MoveQualityIcon.svelte'
  import { boardTheme, boardThemeVars, lastMoveClasses, type BoardThemeId } from './board/boardThemes'
  import { appearance } from './board/appearance.svelte'
  import type { PieceSetId } from './board/pieceSets'
  import { pieceVars } from './board/pieceAssets'
  import { choose, openPicker, pickerKey, pickerSquares, staleAfter, type PickerState, type PromotionPiece } from './board/promotion'

  interface Props {
    fen: string
    lastMove: [Key, Key] | null
    turnColor: 'white' | 'black'
    movableColor: 'white' | 'black' | null
    dests: Map<Key, Key[]>
    check: boolean
    orientation: 'white' | 'black'
    premovable?: boolean
    /** engine arrows etc. (replay/analysis modes) */
    shapes?: DrawShape[]
    /** classification badge anchored to a square's top-right corner */
    badge?: { square: Key; cls: string } | null
    animationMs?: number
    /** a fixed theme (the Appearance preview); otherwise the user's choice */
    theme?: BoardThemeId
    /** a fixed piece set (a preview); otherwise the user's choice (ruling 20) */
    pieces?: PieceSetId
    /** corner coordinates; off for small boards */
    coordinates?: boolean
    /** a move made on the board. A pawn reaching the last rank first opens the promotion
     *  picker (UI-BUILD-4 D): the move arrives only once a piece is chosen, with it as
     *  `promotion`; Esc or a click outside cancels and nothing arrives (the pawn goes back). */
    onmove?: (orig: Key, dest: Key, promotion?: PromotionPiece) => void
  }
  let {
    fen,
    lastMove,
    turnColor,
    movableColor,
    dests,
    check,
    orientation,
    premovable = false,
    shapes = [],
    badge = null,
    animationMs = 220,
    theme,
    pieces,
    coordinates = true,
    onmove,
  }: Props = $props()

  const badgePos = $derived.by(() => {
    if (!badge) return null
    const fileIdx = badge.square.charCodeAt(0) - 97
    const rankIdx = badge.square.charCodeAt(1) - 49
    const col = orientation === 'white' ? fileIdx : 7 - fileIdx
    const rowTop = orientation === 'white' ? 7 - rankIdx : rankIdx
    return {
      // a 20px icon over the destination square's top-right corner, kept inside the board
      left: col === 7 ? 'calc(100% - 22px)' : `calc(${(col + 1) * 12.5}% - 13px)`,
      top: rowTop === 0 ? '2px' : `calc(${rowTop * 12.5}% - 7px)`,
    }
  })

  // ── the promotion picker (DESIGN.md fifth rulings, 3; board/promotion.ts) ──────────────
  let picker = $state<PickerState>(null)
  const choices = $derived(picker ? pickerSquares(picker.dest, orientation) : [])
  let pickerEl: HTMLElement | undefined = $state()

  function boardMove(orig: Key, dest: Key) {
    const open = openPicker(fen, orig, dest)
    if (!open) {
      onmove?.(orig, dest)
      return
    }
    picker = open
  }
  function finish(piece: PromotionPiece | 'cancel') {
    const p = picker
    if (!p) return
    picker = null
    const out = choose(p, piece)
    if (out.kind === 'move') onmove?.(out.orig, out.dest, out.piece)
    else sync() // the pawn goes back; nothing is sent
  }
  // While open, Q / R / B / N / Esc are the picker's alone: taken in the capture phase at the
  // window, before any screen's own key handler (svelte:window onkeydown) can act on them.
  $effect(() => {
    if (!picker) return
    const onKey = (e: KeyboardEvent) => {
      const k = pickerKey(e)
      if (k === null) return
      e.preventDefault()
      e.stopImmediatePropagation()
      finish(k)
    }
    // A press anywhere but on a choice cancels, like Esc. On the dimmed board it is swallowed
    // (no piece is picked up under it); elsewhere the click goes on to what it hit.
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element | null
      if (t?.closest?.('.promo-choice') && pickerEl?.contains(t)) return
      if (pickerEl?.contains(t)) e.preventDefault()
      finish('cancel')
    }
    window.addEventListener('keydown', onKey, true)
    window.addEventListener('pointerdown', onDown, true)
    pickerEl?.querySelector<HTMLElement>('.promo-choice')?.focus({ preventScroll: true })
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener('pointerdown', onDown, true)
    }
  })
  // The position under the picker changed, or the board stopped taking moves (a game ended on
  // the clock, the screen moved on): the picker closes as a cancel.
  $effect(() => {
    if (staleAfter(picker, fen, movableColor !== null)) {
      picker = null
      sync()
    }
  })

  let el: HTMLElement
  let api: Api | null = null
  // last fen pushed to chessground — lets the reactive effect skip the fen when
  // only interaction state changed, so a just-dropped piece is never reset to
  // its origin (which replayed a slide animation after drag-and-drop)
  let sentFen: string | null = null

  function config(): Config {
    return {
      fen,
      orientation,
      turnColor,
      lastMove: lastMove ?? undefined,
      check,
      // The last move is tinted per square colour (boardThemes.lastMoveClasses), so
      // chessground's own single-colour highlight is off.
      highlight: { lastMove: false, check: true, custom: lastMoveClasses(lastMove) },
      coordinates,
      animation: { enabled: true, duration: animationMs },
      movable: {
        free: false,
        color: movableColor ?? undefined,
        dests,
        showDests: true,
        events: { after: (orig, dest) => boardMove(orig, dest) },
      },
      draggable: { enabled: true, showGhost: true },
      premovable: { enabled: premovable },
      drawable: { autoShapes: shapes },
    }
  }

  /** Replay a stored premove if one is set and now legal (call after the
   *  opponent's move has been applied). */
  export function playPremove(): void {
    api?.playPremove()
  }

  export function cancelPremove(): void {
    api?.cancelPremove()
  }

  /** Force chessground back to the current props (e.g. snap a pawn back after
   *  a cancelled promotion, or recover from a rejected/wrong move). Unlike the
   *  reactive effect, this always reasserts the position. */
  export function sync(): void {
    sentFen = fen
    api?.set(config())
  }

  onMount(() => {
    api = Chessground(el, config())
    sentFen = fen
  })

  $effect(() => {
    const cfg = config()
    if (!api) return
    if (fen === sentFen) {
      // position unchanged → update interaction state only; never touch the
      // pieces, or a piece the user just dragged would snap back and re-slide
      delete cfg.fen
    } else {
      sentFen = fen
    }
    api.set(cfg)
  })

  onDestroy(() => api?.destroy())
</script>

<div
  class="board-wrap"
  data-pieces={pieces ?? appearance.pieceSet}
  style={boardThemeVars(boardTheme(theme ?? appearance.boardTheme)) + ' ' + pieceVars(pieces ?? appearance.pieceSet)}
>
  <div class="board" bind:this={el}></div>
  {#if badge && badgePos}
    <span class="cls-badge" style="left: {badgePos.left}; top: {badgePos.top}">
      <MoveQualityIcon cls={badge.cls} size={20} />
    </span>
  {/if}
  {#if picker}
    <!-- the promotion picker: the four pieces over the promotion square, running toward the
         centre, each on its own square's colour from the theme; the rest of the board dimmed.
         Carries cg-wrap so chessground's piece sheet is the fallback under the chosen set. -->
    <div class="promo-scrim cg-wrap" role="dialog" aria-modal="true" aria-label="Promote to" bind:this={pickerEl} data-promo-square={picker.dest}>
      {#each choices as c (c.role)}
        <button
          type="button"
          class="promo-choice"
          class:light={c.light}
          style="left: {c.col * 12.5}%; top: {c.row * 12.5}%"
          data-square={c.square}
          data-piece={c.piece}
          onclick={(e) => {
            e.stopPropagation()
            finish(c.piece)
          }}
          aria-label="Promote to {c.role} ({c.piece.toUpperCase()})"
          title="{c.role[0].toUpperCase() + c.role.slice(1)} ({c.piece.toUpperCase()})"
        >
          <piece class="{picker.side} {c.role}"></piece>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .board-wrap {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    border-radius: var(--radius-board);
    overflow: hidden;
  }
  .board {
    width: 100%;
    height: 100%;
  }

  /* The chosen piece set (ruling 20): each piece's image is a variable the wrapper sets from
     src/assets/pieces/<set>/ (pieceAssets.ts). More specific than chessground's cburnett sheet,
     which stays as the fallback for anything drawn outside a board-wrap. The promotion picker
     and the drag ghost are inside the wrapper, so they follow the set too. */
  .board-wrap[data-pieces] :global(piece.pawn.white) { background-image: var(--pc-white-pawn); }
  .board-wrap[data-pieces] :global(piece.knight.white) { background-image: var(--pc-white-knight); }
  .board-wrap[data-pieces] :global(piece.bishop.white) { background-image: var(--pc-white-bishop); }
  .board-wrap[data-pieces] :global(piece.rook.white) { background-image: var(--pc-white-rook); }
  .board-wrap[data-pieces] :global(piece.queen.white) { background-image: var(--pc-white-queen); }
  .board-wrap[data-pieces] :global(piece.king.white) { background-image: var(--pc-white-king); }
  .board-wrap[data-pieces] :global(piece.pawn.black) { background-image: var(--pc-black-pawn); }
  .board-wrap[data-pieces] :global(piece.knight.black) { background-image: var(--pc-black-knight); }
  .board-wrap[data-pieces] :global(piece.bishop.black) { background-image: var(--pc-black-bishop); }
  .board-wrap[data-pieces] :global(piece.rook.black) { background-image: var(--pc-black-rook); }
  .board-wrap[data-pieces] :global(piece.queen.black) { background-image: var(--pc-black-queen); }
  .board-wrap[data-pieces] :global(piece.king.black) { background-image: var(--pc-black-king); }

  .cls-badge {
    position: absolute;
    display: flex;
    pointer-events: none;
    z-index: 5;
    filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.35));
  }

  .promo-scrim {
    position: absolute;
    inset: 0;
    background: rgba(10, 8, 5, 0.55);
    z-index: 10;
  }
  /* each choice on its square's own colour (the theme's), lifted out of the dimming */
  .promo-choice {
    position: absolute;
    width: 12.5%;
    height: 12.5%;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: var(--sq-dark);
    cursor: pointer;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
  }
  .promo-choice.light {
    background: var(--sq-light);
  }
  /* the focused choice (the queen when the picker opens: Enter takes it) is ringed the same
     way every time, whatever the browser's focus-visible heuristics say; hover rings too */
  .promo-choice:hover,
  .promo-choice:focus,
  .promo-choice:focus-visible {
    outline: none;
    box-shadow: inset 0 0 0 3px var(--accent);
  }
  .promo-choice piece {
    position: static;
    display: block;
    width: 100%;
    height: 100%;
    background-size: cover;
    pointer-events: none;
    transition: transform 80ms ease;
  }
  .promo-choice:hover piece {
    transform: scale(1.06);
  }
</style>
