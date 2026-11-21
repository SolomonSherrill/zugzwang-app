/**
 * Exploring in the harness (UI-BUILD-3 C/D): `probe_move` over chess.js (the sidecar's is
 * python-chess; both answer legality, SAN and the FEN after), and `analyze_fen` answered with
 * canned lines: three legal lines of six moves from the position, captures and checks first,
 * with fixed scores. A stand-in for the engine so the screens render; not an evaluation.
 */
import { Chess, type Move } from 'chess.js'

type Emit = (event: string, data: Record<string, unknown>) => void

export function probeMove(p: Record<string, unknown>): unknown {
  const c = new Chess(String(p.fen))
  const uci = String(p.uci)
  try {
    const m = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] })
    return { legal: true, fen: c.fen(), san: m.san, check: c.inCheck(), gameOver: c.isGameOver() }
  } catch {
    return { legal: false }
  }
}

const rank = (m: Move) => (m.san.includes('#') ? 0 : m.san.includes('+') ? 1 : m.captured ? 2 : 3)
const ordered = (c: Chess) => c.moves({ verbose: true }).sort((a, b) => rank(a) - rank(b) || a.san.localeCompare(b.san))

/** Three lines of six moves: the i-th move by the order above, then each side's first. */
export function cannedLines(fen: string) {
  const firsts = ordered(new Chess(fen)).slice(0, 3)
  const scores = [34, 12, -21]
  return firsts.map((first, i) => {
    const c = new Chess(fen)
    const uci: string[] = []
    const san: string[] = []
    let m: Move | undefined = first
    while (m && uci.length < 6) {
      c.move(m)
      uci.push(m.from + m.to + (m.promotion ?? ''))
      san.push(m.san)
      m = ordered(c)[0]
    }
    return { cp: scores[i], mate: null, uci, san }
  })
}

/** analyze_fen: refuses an unreadable FEN as the sidecar does, then answers after `ms`. */
export function analyzeFen(ms = 120) {
  return (p: Record<string, unknown>, emit: Emit) => {
    const fen = String(p.fen)
    try {
      new Chess(fen)
    } catch (e) {
      throw new Error(`Illegal position: ${(e as Error).message}`)
    }
    const lines = cannedLines(fen)
    setTimeout(
      () => emit('fen_analyzed', { fen, bestUci: lines[0]?.uci[0] ?? null, cp: lines[0]?.cp ?? null, mate: null, lines, depth: 18 }),
      ms,
    )
    return { ok: true }
  }
}
