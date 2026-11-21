/**
 * Live engine lines for positions no stored run covers (UI-BUILD-3 C and D): a variation, a
 * game position with no stored lines, a FEN. The old Review screen's path, reused: `analyze_fen`
 * asks the sidecar's live-analysis runner, which supersedes whatever it was searching (a stale
 * search emits nothing), and the answer arrives as `fen_analyzed` for that FEN. Answers are
 * kept per FEN while the screen is open, so stepping back and forth asks once per position.
 */
import { api, sidecar, type FenAnalyzedEvent } from '../api'

export type LiveState =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | { kind: 'done'; ev: FenAnalyzedEvent }
  | { kind: 'error'; message: string }
  /** the sidecar refused the position itself (VAL-FEN legality) */
  | { kind: 'illegal'; message: string }

export class LiveLines {
  private results = $state<Record<string, FenAnalyzedEvent>>({})
  private errors = $state<Record<string, { message: string; illegal: boolean }>>({})
  private pending = $state<string | null>(null)

  /** What is known about `fen` now. */
  state(fen: string | null): LiveState {
    if (!fen) return { kind: 'idle' }
    const r = this.results[fen]
    if (r) return { kind: 'done', ev: r }
    const e = this.errors[fen]
    if (e) return e.illegal ? { kind: 'illegal', message: e.message } : { kind: 'error', message: e.message }
    return this.pending === fen ? { kind: 'pending' } : { kind: 'idle' }
  }

  /** Ask for `fen` unless it is known or already being searched. */
  request(fen: string): void {
    if (this.results[fen] || this.errors[fen] || this.pending === fen) return
    this.pending = fen
    api.analyzeFen(fen).catch((e: unknown) => {
      // The RPC itself fails only when the sidecar refuses the position (legal_board);
      // engine failures arrive later as analysis_error events.
      this.errors = { ...this.errors, [fen]: { message: e instanceof Error ? e.message : String(e), illegal: true } }
      if (this.pending === fen) this.pending = null
    })
  }

  /** Forget a failure and ask again. */
  retry(fen: string): void {
    const { [fen]: _drop, ...rest } = this.errors
    this.errors = rest
    if (this.pending === fen) this.pending = null
    this.request(fen)
  }

  private onAnalyzed = (d: Record<string, unknown>) => {
    const e = d as unknown as FenAnalyzedEvent
    this.results = { ...this.results, [e.fen]: e }
    if (this.pending === e.fen) this.pending = null
  }
  private onError = (d: Record<string, unknown>) => {
    // Only the FEN path's failures name a fen; a game analysis's are Review's own.
    const fen = typeof d.fen === 'string' ? d.fen : null
    if (fen === null || fen !== this.pending) return
    this.errors = { ...this.errors, [fen]: { message: String(d.message ?? 'The engine stopped.'), illegal: false } }
    this.pending = null
  }

  attach(): () => void {
    sidecar.on('fen_analyzed', this.onAnalyzed)
    sidecar.on('analysis_error', this.onError)
    return () => {
      sidecar.off('fen_analyzed', this.onAnalyzed)
      sidecar.off('analysis_error', this.onError)
    }
  }
}
