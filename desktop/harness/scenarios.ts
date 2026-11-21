/**
 * Scenarios for the fake sidecar: how the answers change for an empty, loading or error
 * state. Each is a set of handlers that override the fixtures for some methods.
 */
import { fixtureKey, type Fixtures } from './fakeSidecar'
import { playHandlers } from './fakePlay'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

export function scenarioHandlers(fx: Fixtures, scenario: string | undefined): Record<string, Handler> {
  const main = fx.meta.mainGameId
  const game = fx.responses[fixtureKey('get_game', { game_id: main })] as {
    analysis: { moves: unknown[] } | null
    plies: unknown[]
  }
  const insightsAll = () => fx.responses[fixtureKey('insights', { view: 'v2', color: 'all' })] as Record<string, unknown>
  switch (scenario) {
    case 'analysing': {
      // The main game with its analysis taken away; Analyse replays the stored moves as
      // analysis_ply events, one every 40 ms, and never finishes (the running state).
      return {
        get_game: (p) => {
          const g = fx.responses[fixtureKey('get_game', p)] as Record<string, unknown>
          return p.game_id === main ? { ...g, analysis: null } : g
        },
        game_report: (p) =>
          p.game_id === main
            ? fx.responses[fixtureKey('game_report', { game_id: fx.meta.unanalysedGameId })]
            : fx.responses[fixtureKey('game_report', p)],
        analyze_game: (p, emit) => {
          const moves = game.analysis?.moves ?? []
          const total = game.plies.length
          moves.slice(0, Math.floor(total * 0.42)).forEach((m, i) =>
            setTimeout(() => emit('analysis_ply', { gameId: p.game_id, ply: i, total, analysis: m }), 40 * (i + 1)),
          )
          return { runId: 1, depth: p.depth ?? 14 }
        },
      }
    }
    case 'no-games':
      return {
        home_summary: () => ({ games: 0, analysed: 0, avgAccuracy: null, winRate: null, ratings: [], puzzles: null, recent: [] }),
        insights: (p) => ({ ...insightsAll(), overview: { total: 0, analyzed: 0, pending: 0, excluded: 0 }, ready: false, view: p.view }),
      }
    case 'insights-pending':
      // Games synced, none analysed yet.
      return {
        insights: () => ({ ...insightsAll(), overview: { total: 412, analyzed: 0, pending: 412, excluded: 0 }, ready: false }),
      }
    case 'insights-error':
      return {
        insights: () => {
          throw new Error('database is locked')
        },
      }
    case 'home-error':
      return {
        home_summary: () => {
          throw new Error('database is locked')
        },
      }
    // Settings (E1): sync, books. Events carry the scenario's own figures (a state, not data).
    case 'sync-running':
      return {
        start_sync: (_p, emit) => {
          setTimeout(() => emit('sync_progress', { phase: 'fetching', source: 'chesscom', done: 0, total: 0 }), 20)
          setTimeout(() => emit('sync_progress', { phase: 'analyzing', source: 'chesscom', done: 37, total: 100 }), 120)
          return { started: true, sources: ['chesscom'] }
        },
      }
    case 'sync-finished':
      return {
        start_sync: (_p, emit) => {
          setTimeout(() => emit('sync_progress', { phase: 'fetching', source: 'chesscom', done: 0, total: 0 }), 20)
          setTimeout(() => emit('sync_done', { source: 'chesscom', new: 2, analyzed: 2 }), 80)
          setTimeout(() => emit('sync_finished', {}), 120)
          return { started: true, sources: ['chesscom'] }
        },
      }
    case 'sync-failed':
      return {
        start_sync: (_p, emit) => {
          setTimeout(() => emit('sync_progress', { phase: 'fetching', source: 'chesscom', done: 0, total: 0 }), 20)
          setTimeout(() => emit('sync_error', { source: 'chesscom', message: 'Chess.com did not answer (HTTP 503).' }), 80)
          setTimeout(() => emit('sync_finished', {}), 120)
          return { started: true, sources: ['chesscom'] }
        },
      }
    case 'no-book': {
      const st = fx.responses[fixtureKey('books_status', {})] as { books: Record<string, unknown>[] }
      return {
        books_status: () => ({
          ...st,
          active: null,
          books: st.books.map((b) => ({ ...b, active: false, installed: false })),
        }),
        // the trainer's no-book state (E3)
        trainer_lobby: () => ({ ...(fx.responses[fixtureKey('trainer_lobby', {})] as object), bookAvailable: false, bookId: null }),
      }
    }
    case 'book-downloading':
    case 'book-failed': {
      return {
        book_use: (p, emit) => {
          if (scenario === 'book-downloading')
            setTimeout(() => emit('book_progress', { id: p.id, phase: 'download', done: 214_000_000, total: 572_067_472 }), 50)
          else setTimeout(() => emit('book_error', { id: p.id, message: 'The download stopped: the connection was reset.' }), 50)
          return { started: true, id: p.id }
        },
      }
    }
    // Settings' username check (UI-BUILD-3 G): Chess.com has no such player, Lichess has; or
    // neither site can be reached (the sidecar's own words for a timeout).
    case 'username-missing':
      return {
        check_usernames: (p) => ({
          chesscom: p.chesscom ? { status: 'not_found', message: null } : null,
          lichess: p.lichess ? { status: 'found', message: null } : null,
        }),
      }
    case 'username-checking':
      return { check_usernames: () => new Promise(() => {}) }
    case 'username-unreachable':
      return {
        check_usernames: (p) =>
          new Promise((done) =>
            setTimeout(
              () =>
                done({
                  chesscom: p.chesscom ? { status: 'unreachable', message: 'timed out' } : null,
                  lichess: p.lichess ? { status: 'unreachable', message: 'HTTP 503' } : null,
                }),
              300,
            ),
          ),
      }
    // Exploring / Analyse a position (UI-BUILD-3 C/D): the live search fails, or never answers
    case 'live-error':
      return {
        analyze_fen: (p, emit) => {
          setTimeout(() => emit('analysis_error', { fen: p.fen, message: 'The engine stopped unexpectedly (exit code -11) and has been restarted — try again.' }), 60)
          return { ok: true }
        },
      }
    case 'live-illegal':
      // a FEN chess.js reads but the sidecar refuses (VAL-FEN legality)
      return {
        analyze_fen: () => {
          throw new Error('Illegal position: the side not to move is in check.')
        },
      }
    case 'live-pending':
      return { analyze_fen: () => ({ ok: true }) }
    case 'no-engine':
      return {
        engine_status: () => ({ ok: false, path: null, source: null, name: null }),
      }
    // Play's states (UI-BUILD-2)
    case 'engine-starting':
      return { engine_status: () => new Promise(() => {}) }
    case 'play-start-error':
      return {
        new_game: () => {
          throw new Error('Stockfish did not answer the new game.')
        },
      }
    // A sidecar from before the clocks (UI-BUILD-3 F): user_move refuses clock_ms with the old
    // dispatch's own TypeError; Play resends without it and the game goes on.
    case 'old-sidecar': {
      const play = playHandlers({ gameId: main })
      return {
        ...play,
        user_move: (p, emit) => {
          if ('clock_ms' in p) throw new Error("Server.rpc_user_move() got an unexpected keyword argument 'clock_ms'")
          return play.user_move(p, emit)
        },
      }
    }
    case 'engine-stops':
      return playHandlers({ gameId: main, engineFails: true })
    case 'engine-mates':
      return playHandlers({ gameId: main, engineEnds: true, replyMs: 1200 })
    default:
      return {}
  }
}

/** The ready event a scenario sends instead of the fixtures' (undefined: the fixtures'). */
export function scenarioReady(scenario: string | undefined): Record<string, unknown> | null | undefined {
  if (scenario === 'no-engine') return { ok: false, error: 'Stockfish not found' }
  if (scenario === 'engine-starting') return null
  return undefined
}
