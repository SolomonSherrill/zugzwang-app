/**
 * COACH-1 C: the Coach page and the report's "Your patterns in this game" in the browser harness. Synthetic
 * (no owner data): an overview with three focus items and the moments behind them, opponents named from the
 * fixtures' games (so ?names=long lengthens them); the main game's report with three patterns on its own key
 * moments. Scenarios: coach-learning (nothing passes the bar yet, with games still being read), coach-building
 * (no overview yet).
 *
 * COACH-2 C: Practice. practice_status (7 due: 5 Find the move, 2 Spot the threat), practice_session (a Find the move
 * from the main game's opponent, a Spot the threat, a transfer probe; scenarios practice-threat and practice-probe put
 * that one first, practice-empty answers an empty queue), practice_answer (the reveal), and judge_move judged against
 * the item's answer (the harness's own; any other move is "not quite").
 */
import { fixtureKey, type Fixtures } from './fakeSidecar'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

const THEMES: [string, string, string, string][] = [
  ['threat:knightFork', 'threat', 'knightFork', 'Knight fork'],
  ['threat:backRankMate', 'threat', 'backRankMate', 'Back-rank mate'],
  ['chance:discoveredAttack', 'chance', 'discoveredAttack', 'Discovered attack'],
]
const TITLES: Record<string, string> = {
  'threat:knightFork': 'Knight forks against you',
  'threat:backRankMate': 'Back-rank mates against you',
  'chance:discoveredAttack': 'Your own discovered attacks',
}

export function coachHandlers(fx: Fixtures, scenario: string | undefined): Record<string, Handler> {
  const main = fx.meta.mainGameId
  const list = (fx.responses[fixtureKey('list_games', {})] as { games: { id: number; white: string | null; black: string | null; playerColor: string | null; playedAt: string }[] } | undefined)?.games ?? []
  const opp = (g: (typeof list)[number]) => (g.playerColor === 'black' ? g.white : g.black) ?? null
  const rowsFor = (key: string, kind: string, name: string, n: number, missed: number) =>
    list.slice(0, n).map((g, i) => ({
      gameId: g.id, ply: 20 + (i % 7) * 2 + (kind === 'threat' ? 1 : 0), date: g.playedAt, opponent: opp(g),
      move: `${11 + (i % 7)}${kind === 'threat' ? '...' : '.'} Nd5`, theme: name, kind,
      outcome: i < missed ? 'missed' : 'caught', key,
    }))
  const focus = THEMES.map(([key, kind, theme, name], k) => {
    const total = [14, 9, 11][k]
    const missed = [9, 6, 7][k]
    const rows = rowsFor(key, kind, name, total, missed)
    return {
      key, kind, theme, title: TITLES[key], name, missed, total, recentCaught: [4, 2, 1][k], recentTotal: 5,
      rows, rowCount: rows.length,
    }
  })
  const behind = focus.flatMap((f) => f.rows).sort((a, b) => (a.date < b.date ? 1 : -1))
  // ── COACH-2 C: Practice ──
  const PRACTICE = [
    { id: 101, kind: 'find', source: 'game', fen: 'r3k3/pp3ppp/8/1N6/8/8/PPP2PPP/4K3 w - - 0 21', side: 'white', hintSquare: 'b5',
      gameId: fx.meta.mainGameId, ply: 40, date: list[0]?.playedAt ?? null, opponent: list[0] ? opp(list[0]) : 'Someone', played: '21. Kd2',
      oppMove: null, puzzleRating: null, answer: 'b5c7', theme: 'Knight fork', focus: true,
      right: 'You found it: 21. Nc7+ starts a knight fork.', notQuite: 'Not 21. Kd2: 21. Nc7+ starts a knight fork.' },
    { id: 102, kind: 'threat', source: 'game', fen: 'r3k2r/ppp2ppp/8/3N4/8/8/PPP2PPP/R3K2R b KQkq - 1 9', side: 'black', hintSquare: 'd5',
      gameId: fx.meta.mainGameId, ply: 17, date: list[1]?.playedAt ?? null, opponent: list[1] ? opp(list[1]) : 'Someone', played: '9... Kd8',
      oppMove: '9. Nd5', puzzleRating: null, answer: 'a8c8', theme: 'Knight fork', focus: true,
      right: '9... Rc8 keeps you safe. In the game, 9... Kd8 allowed a knight fork: 10. Nxc7.',
      notQuite: 'In the game, 9... Kd8 allowed a knight fork: 10. Nxc7. A move that deals with it: 9... Rc8.' },
    { id: 103, kind: 'find', source: 'probe', fen: 'r3k3/8/8/8/8/8/1N6/4K3 w - - 2 2', side: 'white', hintSquare: 'b2', gameId: null, ply: null,
      date: null, opponent: null, played: null, oppMove: '1... Kd8', puzzleRating: 1512, answer: 'b2c4', theme: 'Fork', focus: false,
      right: 'You found it: 2. Nc4.', notQuite: 'The move is 2. Nc4.' },
  ]
  const first = scenario === 'practice-threat' ? 102 : scenario === 'practice-probe' ? 103 : 101
  const queue = scenario === 'practice-empty' ? [] : [...PRACTICE.filter((p) => p.id === first), ...PRACTICE.filter((p) => p.id !== first)]
  let judge = 0
  const status = {
    due: 7, reviews: 3, new: 4, find: 5, threat: 2, minutes: 5, rightWeek: 0.68, weekAttempts: 25, learned: 41, items: 412,
    next: null, nextText: null, probes: true, newPerDay: 10,
  }
  const out: Record<string, Handler> = {
    practice_status: () => (scenario === 'practice-empty' ? { ...status, due: 0, reviews: 0, new: 0, find: 0, threat: 0, minutes: 0, nextText: 'Tomorrow' } : status),
    practice_session: () => ({
      items: queue.map(({ answer: _a, theme: _t, focus: _f, right: _r, notQuite: _n, ...v }) => v),
      secondsEach: 30,
      session: '2026-11-24T15:00:00+00:00',
    }),
    judge_move: (p, emit) => {
      const token = ++judge
      const it = PRACTICE.find((x) => x.fen === p.fen)
      setTimeout(() => emit('move_judged', { token, fen: p.fen, uci: p.uci, accepted: !!it && it.answer === p.uci, loss: it && it.answer === p.uci ? 0 : 0.4 }), 50)
      return { token }
    },
    practice_answer: (p) => {
      const it = PRACTICE.find((x) => x.id === p.item_id)!
      const right = !!p.correct && !p.revealed
      return {
        verdict: right ? 'right' : 'notQuite', sentence: right ? it.right : it.notQuite, theme: it.theme, focus: it.focus,
        comesBack: right ? 'Comes back in 4 days.' : 'Comes back tomorrow.', due: '', dueText: right ? 'In 4 days' : 'Tomorrow',
        answerUci: it.answer, line: [it.answer], revealed: !!p.revealed,
      }
    },
    coach_overview: () =>
      scenario === 'coach-building'
        ? { status: 'building' }
        : scenario === 'coach-learning'
          ? { status: 'ready', games: 23, windowGames: 23, windowDays: 365, pending: 412, moments: 40, focus: [], behind: [] }
          : { status: 'ready', games: list.length || 60, windowGames: list.length || 60, windowDays: 365, pending: 0, moments: 120, focus, behind },
    game_report: (p) => {
      const base = fx.responses[fixtureKey('game_report', p)] as Record<string, unknown> & {
        analysed?: boolean
        moments?: { shown: { ply: number; san: string | null; side: string; yours: boolean | null }[] }
      }
      if (p.game_id !== main || !base?.analysed) return base
      const shown = base.moments?.shown ?? []
      const items = shown.slice(0, 3).map((m, i) => {
        const [key, kind, theme, name] = THEMES[i]
        const move = m.san ?? 'Nd5'
        return {
          ply: m.ply, kind, outcome: i === 1 ? 'caught' : 'missed', theme, name, focus: i < 2,
          sentence: i === 1 ? `${move} dealt with the threat of a back-rank mate (Rd8#).` : `${move} allowed a knight fork: Nc7+.`,
          history: i < 2 ? (i === 1 ? 'You had missed this 6 of the last 9 times.' : 'You had missed this 9 of the last 14 times.') : null,
          move, key, practice: i !== 1,
        }
      })
      return { ...base, patterns: { items } }
    },
  }
  return out
}
