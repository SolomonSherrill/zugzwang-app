/**
 * Whether a game against Stockfish is running, shared so the sidebar can mark Play with a dot
 * on every screen (Play stays mounted while you look elsewhere, so the game and its clocks run
 * on). Written only by PlayView.
 */
export const playState = $state({ inGame: false })
