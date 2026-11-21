/**
 * Promotion positions for the harness (UI-BUILD-4 D): the promotion picker on every screen that
 * takes a move from the board. Sample data built here with chess.js, not recorded; nothing in it
 * is measured. Player names are placeholders.
 *
 *   ?screen=review&game=promo[&ply=8]   a short game whose 5th move promotes (Try it, exploring)
 *   ?screen=review&fen=<FEN>            Analyse a position: any FEN, no scenario needed
 *   ?state=promotion                    the trainer's "Promotion drill" family (its book move
 *                                       under-promotes, b7a8n) and Puzzles' two under-promotion
 *                                       puzzles (the user White, then Black)
 */
import { Chess } from 'chess.js'
import { fixtureKey, type Fixtures } from './fakeSidecar'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

export const PROMO_GAME_ID = 990001
/** 1. e4 d5 2. exd5 c6 3. dxc6 Nf6 4. cxb7 Nbd7: White's b7 pawn promotes on a8, b8 or c8. */
export const PROMO_LINE = ['e2e4', 'd7d5', 'e4d5', 'c7c6', 'd5c6', 'g8f6', 'c6b7', 'b8d7']
/** The game goes on 5. bxc8=Q Qxc8 6. Nf3 e6 (the moment: 5. bxa8=Q was the move). */
const PROMO_GAME = [...PROMO_LINE, 'b7c8q', 'd8c8', 'g1f3', 'e7e6']
export const PROMO_FEN = (() => {
  const c = new Chess()
  for (const u of PROMO_LINE) c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] })
  return c.fen()
})()
/** Puzzles: after the setup move, the user forks king and queen by promoting to a knight. */
export const PROMO_PUZZLES = [
  // Black plays ...Qh7; White's f8=N+ forks Ke6 and Qh7 (the user is White)
  { id: 'promoW', fen: '8/5P2/4k3/8/8/8/7q/2K5 b - - 0 1', movesUci: ['h2h7', 'f7f8n'], rating: 1500, ratingDeviation: 80, themes: 'underPromotion fork short', finalMates: [] },
  // the same, mirrored: White plays Qh2; Black's f1=N+ forks Ke3 and Qh2 (the user is Black)
  { id: 'promoB', fen: '2k5/7Q/8/8/8/4K3/5p2/8 w - - 0 1', movesUci: ['h7h2', 'f2f1n'], rating: 1500, ratingDeviation: 80, themes: 'underPromotion fork short', finalMates: [] },
]
export const PROMO_FAMILY = 'Promotion drill'

const placement = (fen: string) => fen.split(' ')[0]

function promoGame(fx: Fixtures) {
  const main = fx.responses[fixtureKey('get_game', { game_id: fx.meta.mainGameId })] as Record<string, unknown> & {
    analysis: { moves: Record<string, unknown>[] }
    runs: Record<string, unknown>[]
  }
  const c = new Chess()
  const plies = []
  const moves = []
  for (const [i, u] of PROMO_GAME.entries()) {
    const before = c.fen()
    const best = i === 8 ? 'b7a8q' : u
    const bestSan = new Chess(before).move({ from: best.slice(0, 2), to: best.slice(2, 4), promotion: best[4] }).san
    const mv = c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] })
    plies.push({ san: mv.san, uci: u, fen: c.fen(), check: c.inCheck(), opening: i < 4 ? { eco: 'B01', name: 'Scandinavian Defense' } : null })
    const cp = i < 8 ? 30 : 450
    moves.push({
      ...main.analysis.moves[0],
      ply: i,
      playedUci: u,
      bestUci: best,
      pvUci: best,
      isBook: i < 4,
      classification: i < 4 ? 'book' : i === 8 ? 'mistake' : 'best',
      lines: [{ cp, mate: null, san: [bestSan], uci: [best] }],
      scoreBeforeCp: i === 8 ? 900 : cp,
      scoreAfterCp: cp,
      scoreBeforeMate: null,
      scoreAfterMate: null,
    })
  }
  const game = {
    ...main,
    id: PROMO_GAME_ID,
    externalId: 'promo-1',
    white: 'alice',
    black: 'bob',
    whiteElo: 1500,
    blackElo: 1480,
    playerColor: 'white',
    result: '1-0',
    termination: 'resignation',
    moveCount: plies.length,
    openingEco: 'B01',
    openingName: 'Scandinavian Defense',
    source: 'local',
    startFen: new Chess().fen(),
    plies,
    analysis: {
      runId: PROMO_GAME_ID,
      depth: 14,
      whiteAccuracy: 88.1,
      blackAccuracy: 71.4,
      summary: { white: { accuracy: 88.1, counts: { book: 2, best: 3, mistake: 1 } }, black: { accuracy: 71.4, counts: { book: 2, best: 4 } } },
      moves,
    },
    runs: [{ ...main.runs[0], id: PROMO_GAME_ID }],
  }
  const wp = (cp: number) => 1 / (1 + Math.exp(-0.00368208 * cp))
  const series = [0.5, ...moves.map((m) => wp(m.scoreAfterCp as number))]
  const moment = {
    ply: 8, side: 'white', yours: true, san: 'bxc8=Q', bestSan: 'bxa8=Q', label: '5.bxc8=Q', classification: 'mistake',
    swing: 0.22, before: wp(900), after: wp(450), bandBefore: 'winning', bandAfter: 'winning',
    sentences: [], descriptions: [], spent: null, clockLeft: null, bestUci: 'b7a8q', unique: true, reply: null, qualifier: null,
  }
  const mainReport = fx.responses[fixtureKey('game_report', { game_id: fx.meta.mainGameId })] as Record<string, unknown>
  const report = {
    ...mainReport,
    analysed: true,
    basis: { depth: 14, analysedPlies: plies.length, gamePlies: plies.length, complete: true, pov: 'white', timeControl: null },
    series,
    moments: { total: 1, shown: [moment], groups: [[8]] },
    decided: null, ending: null, fortune: [], lowClock: null, opening: null, slide: null, slideGated: null, slideReversed: null,
    found: null, headline: ['A sample game: the fifth move promotes.'], context: [], conversion: null, lines: [],
    result: '1-0', termination: 'resignation', you: 'white',
  }
  const extras = {
    analysed: true, depth: 14, plies: plies.length, phases: { middlegame: null, endgame: null },
    clock: { timeControl: null, base: null, increment: null, clocks: plies.map(() => null), spent: plies.map(() => null) },
    accuracyByPhase: null,
    errors: [{ ply: 8, side: 'white', classification: 'mistake', kind: null }],
    errorCounts: { white: { tactical: 0, errors: 1 }, black: { tactical: 0, errors: 0 } },
  }
  return { game, report, extras }
}

export function promotionHandlers(fx: Fixtures, scenario: string | undefined, gameParam: string | null): Record<string, Handler> {
  const out: Record<string, Handler> = {}
  const fixture = (method: string, p: Record<string, unknown>) => {
    const key = fixtureKey(method, p)
    if (!(key in fx.responses)) throw new Error(`harness: no fixture for ${key}`)
    return fx.responses[key]
  }
  if (gameParam === 'promo') {
    const { game, report, extras } = promoGame(fx)
    out.get_game = (p) => (p.game_id === PROMO_GAME_ID ? game : fixture('get_game', p))
    out.game_report = (p) => (p.game_id === PROMO_GAME_ID ? report : fixture('game_report', p))
    out.review_extras = (p) => (p.game_id === PROMO_GAME_ID ? extras : fixture('review_extras', p))
    out.explain_move = (p) =>
      p.game_id === PROMO_GAME_ID
        ? { analysed: true, bestSan: null, claims: [], descriptions: [], findings: [], ply: p.ply, ruleVersion: 22, sentences: [] }
        : fixture('explain_move', p)
  }
  if (scenario === 'promotion') {
    const lobby = fixture('trainer_lobby', {}) as { families: Record<string, unknown>[] }
    const base = (lobby.families[0] ?? {}) as Record<string, unknown>
    const summary = {
      ...base, name: PROMO_FAMILY, ecoLo: 'B01', ecoHi: 'B01', firstMove: 'e4', popularity: 1, lineCount: 1, available: true,
      sampleMoves: '1. e4 d5 2. exd5 c6 3. dxc6 Nf6 4. cxb7 Nbd7', sharedMoves: '1. e4 d5 2. exd5 c6 3. dxc6 Nf6 4. cxb7 Nbd7', drilled: 0, mastered: 0,
    }
    const record = { attempts: 0, completions: 0, distinctLines: 0, bestAccuracy: null, mastered: false }
    const progress = { distinctLines: 0, bestAccuracy: null, mastered: false, byColor: { white: record, black: record } }
    const family = {
      label: PROMO_FAMILY, mastered: 0, drilled: 0,
      lines: [{ eco: 'B01', name: `${PROMO_FAMILY}: the b-pawn`, fen: PROMO_FEN, pgn: summary.sampleMoves, uci: PROMO_LINE, coverage: { white: true, black: true }, progress }],
    }
    out.trainer_lobby = () => ({ ...lobby, families: [summary, ...lobby.families] })
    out.trainer_family = (p) => (p.name === PROMO_FAMILY ? family : fixture('trainer_family', p))
    // the book's move here is the under-promotion; elsewhere it has none
    out.book_moves = (p) => ({ accepted: placement(String(p.fen)) === placement(PROMO_FEN) ? ['b7a8n'] : [] })
    out.book_reply = () => ({ uci: null })
    out.trainer_complete = () => ({ progress })
    let served = 0
    out.next_puzzles = () => {
      const pz = PROMO_PUZZLES.slice(served)
      served = PROMO_PUZZLES.length
      return { puzzles: pz }
    }
    out.rate_puzzle = (p) => ({ before: 1500, rating: p.outcome ? 1508 : 1492, rd: 80 })
  }
  return out
}
