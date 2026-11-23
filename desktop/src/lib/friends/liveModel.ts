/** Pure helpers of FRIENDS-2's screens (the game, the banner, the popover), unit-tested in liveModel.test.ts. */
import type { Colour, GameState, StartRating, TimeControl } from './friendsApi'

export const other = (c: Colour): Colour => (c === 'white' ? 'black' : 'white')

/** "1446", "≈1390", or null when unknown (R3: blank) */
export function ratingText(r: StartRating | null | undefined): string | null {
  if (!r || r.rating == null) return null
  return (r.estimated ? '≈' : '') + r.rating
}

/** "Chess.com blitz" for the ratings line */
export function speedWord(tc: TimeControl): 'bullet' | 'blitz' | 'rapid' {
  const [m, s] = tc.split('+').map(Number)
  const est = m * 60 + 40 * s
  return est < 180 ? 'bullet' : est < 600 ? 'blitz' : 'rapid'
}

/** The ratings line (MinimalFriends-challenge.html): "Ratings shown in the game: you 1438, maxk 1446 (Chess.com blitz)." */
export function ratingsLine(you: StartRating | null, them: StartRating | null, handle: string, tc: TimeControl): string {
  const y = ratingText(you) ?? '—'
  const t = ratingText(them) ?? '—'
  const est = you?.estimated || them?.estimated ? ', ≈ from Lichess' : ''
  return `Ratings shown in the game: you ${y}, ${handle} ${t} (Chess.com ${speedWord(tc)}${est}).`
}

/** "m:ss" for a clock; tenths under 10 s ("0:07.4") as the clock runs out */
export function clockText(ms: number): string {
  const v = Math.max(0, ms)
  if (v < 10_000) return `0:${String(Math.floor(v / 1000)).padStart(2, '0')}.${Math.floor((v % 1000) / 100)}`
  const s = Math.ceil(v / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return (h ? `${h}:${String(m).padStart(2, '0')}` : String(m)) + ':' + String(s % 60).padStart(2, '0')
}

export function mmss(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** The game-over panel's two lines (MinimalPlayGame-friend-over.html): "You won" / "maxk resigned". */
export function overLines(s: GameState): { title: string; reason: string } {
  const opp = s[other(s.you)].handle
  const won = s.winner === s.you
  const loser = s.winner ? other(s.winner) : null
  const who = (c: Colour | null) => (c === s.you ? 'You' : opp)
  const title = s.result === '*' ? 'Aborted' : s.winner === null ? 'Draw' : won ? 'You won' : 'You lost'
  const reasons: Record<string, string> = {
    checkmate: 'Checkmate',
    resign: loser === s.you ? 'You resigned' : `${opp} resigned`,
    timeout: loser === s.you ? 'You ran out of time' : `${opp} ran out of time`,
    timeout_vs_insufficient: `${who(s.turn)} ran out of time, with no mating material left against them`,
    agreed: 'Draw by agreement',
    stalemate: 'Stalemate',
    repetition: 'Threefold repetition',
    fifty_moves: 'The fifty-move rule',
    insufficient: 'Neither side can mate',
    abandoned: s.winner === s.you ? `${opp} left the game` : 'You left the game',
    abandoned_draw: s.winner === null ? `${opp} left; called a draw` : 'Called a draw',
    aborted: 'No first move in time, so nothing was saved',
  }
  return { title, reason: reasons[s.termination ?? ''] ?? (s.termination_text ?? '') }
}

/** What the footer shows (MinimalPlayGame-friend*.html): the four states, plus the first moves */
export type Footer = 'waiting' | 'playing' | 'draw-offered' | 'opponent-left' | 'over'
export function footerState(s: GameState): Footer {
  if (s.status === 'over') return 'over'
  if (s.status === 'waiting') return 'waiting'
  if (!s.opponent.connected && s.opponent.gone_since != null) return 'opponent-left'
  if (s.draw_offer && s.draw_offer !== s.you) return 'draw-offered'
  return 'playing'
}

/** seconds until the claim (P1) is possible, by the server's clock run on locally */
export function claimIn(s: GameState, skew: number, now = Date.now()): number | null {
  if (s.claim_at == null) return null
  return Math.max(0, (s.claim_at - (now - skew)) / 1000)
}
