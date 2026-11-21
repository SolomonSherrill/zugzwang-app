<script lang="ts">
  /** UI-BUILD A7: the six board themes (ruling 20), each after 1.e4 e5 2.Nf3 with a badge.
   *  Green, Blue and Walnut's last-move tints: ruling 9 (2026-11-20, third). */
  import Board from '../src/lib/Board.svelte'
  import { BOARD_THEMES } from '../src/lib/board/boardThemes'
  const FEN = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2'
</script>

<main>
  {#each BOARD_THEMES as t (t.id)}
    <figure>
      <Board
        fen={FEN}
        lastMove={['g1', 'f3']}
        turnColor="black"
        movableColor={null}
        dests={new Map()}
        check={false}
        orientation="white"
        theme={t.id}
        badge={{ square: 'f3', cls: 'best' }}
      />
      <figcaption>{t.name}</figcaption>
    </figure>
  {/each}
</main>

<style>
  main {
    display: grid;
    grid-template-columns: repeat(3, 360px);
    gap: 24px 28px;
    padding: 28px;
  }
  figure {
    margin: 0;
  }
  figcaption {
    margin-top: 8px;
    color: var(--text-2);
    font: var(--secondary);
  }
</style>
