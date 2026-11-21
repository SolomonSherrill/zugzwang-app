<script lang="ts">
  /**
   * UI-BUILD A8: one board at the Review mockup's size (744 px), driven by harness/perf.ts's
   * Playwright script. `window.__perf.toggle()` plays 1.Nf3 or takes it back (chessground's
   * 220 ms animation); `start()` / `stop()` record requestAnimationFrame intervals.
   */
  import Board from '../src/lib/Board.svelte'
  import type { Key } from 'chessground/types'

  const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  const NF3 = 'rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1'
  let fen = $state(START)
  let lastMove = $state<[Key, Key] | null>(null)
  const dests = new Map<Key, Key[]>([
    ['e2', ['e3', 'e4']],
    ['g1', ['f3', 'h3']],
  ])

  let deltas: number[] = []
  let recording = false
  let prev = 0
  function frame(t: number) {
    if (!recording) return
    if (prev) deltas.push(t - prev)
    prev = t
    requestAnimationFrame(frame)
  }
  ;(window as unknown as { __perf: unknown }).__perf = {
    toggle() {
      if (fen === START) {
        fen = NF3
        lastMove = ['g1', 'f3']
      } else {
        fen = START
        lastMove = ['f3', 'g1']
      }
    },
    start() {
      deltas = []
      prev = 0
      recording = true
      requestAnimationFrame(frame)
    },
    stop(): number[] {
      recording = false
      return deltas
    },
  }
</script>

<div class="wrap">
  <Board
    {fen}
    {lastMove}
    turnColor={fen === START ? 'white' : 'black'}
    movableColor={fen === START ? 'white' : null}
    {dests}
    check={false}
    orientation="white"
    animationMs={220}
  />
</div>

<style>
  .wrap {
    width: 744px;
    margin: 20px;
  }
</style>
