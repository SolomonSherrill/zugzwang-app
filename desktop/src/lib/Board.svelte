<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Chessground } from 'chessground'
  import type { Api } from 'chessground/api'
  import type { Config } from 'chessground/config'
  import type { DrawShape } from 'chessground/draw'
  import type { Key } from 'chessground/types'
  import { CLASS_COLORS, CLASS_GLYPHS } from './classification'

  export type PromotionRequest = { col: number; color: 'white' | 'black' }
  type Role = 'queen' | 'knight' | 'rook' | 'bishop'

  interface Props {
    fen: string
    lastMove: [Key, Key] | null
    turnColor: 'white' | 'black'
    movableColor: 'white' | 'black' | null
    dests: Map<Key, Key[]>
    check: boolean
    orientation: 'white' | 'black'
    premovable?: boolean
    /** when non-null, the promotion picker column is shown */
    promotion?: PromotionRequest | null
    /** engine arrows etc. (replay/analysis modes) */
    shapes?: DrawShape[]
    /** classification badge anchored to a square's top-right corner */
    badge?: { square: Key; cls: string } | null
    animationMs?: number
    onmove?: (orig: Key, dest: Key) => void
    onpromote?: (role: Role | null) => void
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
    promotion = null,
    shapes = [],
    badge = null,
    animationMs = 220,
    onmove,
    onpromote,
  }: Props = $props()

  const badgePos = $derived.by(() => {
    if (!badge) return null
    const fileIdx = badge.square.charCodeAt(0) - 97
    const rankIdx = badge.square.charCodeAt(1) - 49
    const col = orientation === 'white' ? fileIdx : 7 - fileIdx
    const rowTop = orientation === 'white' ? 7 - rankIdx : rankIdx
    return {
      left: Math.min(Math.max((col + 1) * 12.5 - 5.2, 0), 94.5),
      top: Math.max(rowTop * 12.5 - 1.6, 0),
    }
  })

  const PROMOTION_ROLES: Role[] = ['queen', 'knight', 'rook', 'bishop']

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
      animation: { enabled: true, duration: animationMs },
      movable: {
        free: false,
        color: movableColor ?? undefined,
        dests,
        showDests: true,
        events: { after: (orig, dest) => onmove?.(orig, dest) },
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

<div class="board-wrap">
  <div class="board" bind:this={el}></div>
  {#if badge && badgePos}
    <span
      class="cls-badge"
      style="left: {badgePos.left}%; top: {badgePos.top}%; background: {CLASS_COLORS[
        badge.cls
      ] ?? 'var(--text-muted)'}"
    >
      {CLASS_GLYPHS[badge.cls] ?? '·'}
    </span>
  {/if}
  {#if promotion}
    <!-- in-board promotion picker, lichess-style; reuses chessground's piece
         sprites by carrying the cg-wrap class -->
    <div
      class="promo-scrim cg-wrap"
      role="dialog"
      tabindex="-1"
      onclick={() => onpromote?.(null)}
      onkeydown={(e) => e.key === 'Escape' && onpromote?.(null)}
    >
      {#each PROMOTION_ROLES as role, i (role)}
        <button
          class="promo-choice"
          style="left: {promotion.col * 12.5}%; top: {i * 12.5}%"
          onclick={(e) => {
            e.stopPropagation()
            onpromote?.(role)
          }}
          aria-label="Promote to {role}"
        >
          <piece class="{promotion.color} {role}"></piece>
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
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow:
      var(--shadow-board),
      0 0 0 1px var(--divider);
  }
  .board {
    width: 100%;
    height: 100%;
  }

  .cls-badge {
    position: absolute;
    width: 5.4%;
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    color: #fff;
    font-size: clamp(8px, 1.45vh, 12px);
    font-weight: 700;
    letter-spacing: -0.05em;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
    pointer-events: none;
    z-index: 5;
  }

  .promo-scrim {
    position: absolute;
    inset: 0;
    background: rgba(10, 8, 5, 0.55);
    z-index: 10;
  }
  .promo-choice {
    position: absolute;
    width: 12.5%;
    height: 12.5%;
    background: var(--bg-raised);
    border: 1px solid var(--divider);
    border-radius: 3px;
    cursor: pointer;
    transition: background-color 80ms ease;
  }
  .promo-choice:hover {
    background: var(--accent);
  }
  .promo-choice piece {
    position: static;
    display: block;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
</style>
