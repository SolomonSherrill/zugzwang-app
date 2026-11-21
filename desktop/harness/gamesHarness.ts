/**
 * The Games screen over the fake sidecar (UI-BUILD-3 E). `games_page` answers come from
 * `games_fixtures.json` (review/ui_fixtures/record_games_fixtures.py, recorded from the real
 * sidecar on a copy of a backup; private); a page the recorder did not ask for answers with the
 * harness's "no fixture" error, which the screen shows as its error state.
 *
 * Scenarios (?state=) for the drafted states:
 *   games-error         games_page fails
 *   games-none          no games stored
 *   games-no-match      games stored, none under the filters
 *   games-row-analysing the second row shown unanalysed; its Analyse replays analysis_ply events and never finishes
 *   games-kinds         the first page with the row kinds the stacked mockup draws (UI-BUILD-4 B), which the
 *                       recorded pages lack: the second row unanalysed, the third a game played here against
 *                       Stockfish level 10 (the user White, stored as "You"), the sixth an imported game with no
 *                       ratings
 * Import PGN always stores one game (the fixture's main game id) and its analysis runs through
 * analyze_pending's sync_progress events, stopping at 1 of 3.
 */
import { fixtureKey } from './fakeSidecar'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

export interface GamesFixtures {
  meta: Record<string, unknown>
  responses: Record<string, { games: unknown[]; total: number; all: number; months: unknown[]; offset: number }>
}

export function gamesHandlers(gf: GamesFixtures | null, scenario: string | undefined, mainGameId: number): Record<string, Handler> {
  if (!gf) return {}
  const first = gf.responses[fixtureKey('games_page', { sort: 'recent', offset: 0, limit: 50 })]
  const handlers: Record<string, Handler> = {
    games_page: (p) => {
      if (scenario === 'games-error') throw new Error('database is locked')
      if (scenario === 'games-none') return { games: [], total: 0, all: 0, offset: 0, months: [] }
      if (scenario === 'games-no-match') return { games: [], total: 0, all: first.all, offset: 0, months: [] }
      const res = gf.responses[fixtureKey('games_page', p)]
      if (!res) throw new Error(`harness: no fixture for games_page ${JSON.stringify(p)}`)
      if (scenario === 'games-row-analysing' && res.games.length > 1) {
        // the recorded pages hold no unanalysed game: show the second as one, so its Analyse can run
        const games = [...res.games] as Record<string, unknown>[]
        games[1] = { ...games[1], analyzed: false, whiteAccuracy: null, blackAccuracy: null }
        return { ...res, games }
      }
      if (scenario === 'games-kinds' && res.offset === 0 && res.games.length > 5) {
        const games = [...res.games] as Record<string, unknown>[]
        games[1] = { ...games[1], analyzed: false, whiteAccuracy: null, blackAccuracy: null }
        games[2] = {
          ...games[2], source: 'local', playerColor: 'white', white: 'You', black: 'Stockfish', whiteElo: null, blackElo: null,
          skillLevel: 10, ladderVersion: 1, externalId: null, timeControl: '600+0', rated: null,
        }
        games[5] = { ...games[5], source: 'imported', whiteElo: null, blackElo: null, externalId: null }
        return { ...res, games }
      }
      return res
    },
    import_pgn: () => ({ gameId: mainGameId, gameIds: [mainGameId], count: 1, issues: [] }),
    analyze_pending: (p, emit) => {
      const n = Array.isArray(p.game_ids) ? 3 : 2
      setTimeout(() => emit('sync_progress', { phase: 'analyzing', source: 'imported', done: 0, total: n }), 30)
      setTimeout(() => emit('sync_progress', { phase: 'analyzing', source: 'imported', done: 1, total: n }), 120)
      return { started: true, sources: ['imported'], count: n }
    },
  }
  if (scenario === 'games-row-analysing') {
    handlers.analyze_game = (p, emit) => {
      for (let i = 0; i < 37; i++)
        setTimeout(() => emit('analysis_ply', { gameId: p.game_id, ply: i, total: 90, analysis: {} }), 10 * (i + 1))
      return { runId: 1, depth: 14 }
    }
  }
  return handlers
}
