/** Whether a move the user played satisfies the current solution step.
 *
 *  Pure and side-effect free so it can be tested without mounting the session.
 *  It deliberately contains no chess knowledge: which moves mate is decided by
 *  python-chess in the sidecar and arrives as `finalMates`, so everything here
 *  is string and set comparison.
 */
export type MoveVerdict = { ok: true; uci: string } | { ok: false }

export interface UserMoveInput {
  /** Full UCI of the solution move at the current index, e.g. 'e7e8n'. */
  expected: string
  /** What the user played: 4 characters, or 5 when they chose a promotion piece. */
  played: string
  /** Whether this is the last move of the solution. */
  isFinal: boolean
  /** Every move that mates in place of the final one; empty unless it mates. */
  finalMates?: string[]
}

const pieceOf = (uci: string) => (uci.length === 5 ? uci[4] : null)

export function resolveUserMove({
  expected,
  played,
  isFinal,
  finalMates,
}: UserMoveInput): MoveVerdict {
  if (played === expected) return { ok: true, uci: expected }

  const uci4 = played.slice(0, 4)
  const playedPiece = pieceOf(played)
  const expectedPiece = pieceOf(expected)

  // The user reached the promotion square but named no piece. Assuming the
  // expected one is what F8 was about: on a puzzle whose answer is g7g8r, that
  // silently substituted the rook and taught the opposite of the lesson. Only
  // the queen may be assumed, because auto-queen is the universal default.
  if (playedPiece === null && expectedPiece !== null && uci4 === expected.slice(0, 4)) {
    return expectedPiece === 'q' ? { ok: true, uci: expected } : { ok: false }
  }

  // Lichess accepts any mate on a puzzle's *final* move. The sidecar worked out
  // which moves those are at fetch time, so this is set membership rather than
  // chess reasoning done in the frontend.
  if (isFinal) {
    const alts = finalMates ?? []
    // A stated piece is honoured exactly — never widened to a different one.
    if (playedPiece !== null) {
      return alts.includes(played) ? { ok: true, uci: played } : { ok: false }
    }
    const cands = alts.filter((m) => m.startsWith(uci4))
    if (cands.length) {
      // Prefer the stored move when it is among the candidates; otherwise this
      // is a genuinely different mate, so default to queen among promotions.
      const chosen =
        cands.find((m) => m === expected) ?? cands.find((m) => m.endsWith('q')) ?? cands[0]
      return { ok: true, uci: chosen }
    }
  }

  return { ok: false }
}
