/**
 * COACH-2 D (ruling CB2): the sync card that stayed on "Syncing: fetching your games…" after a sync ended. The
 * sidecar emitted sync_finished while the run's thread still lived, so the sync_status asked on sync_finished said
 * syncing: true and the card was re-created with no progress. The sidecar now says running: false from
 * sync_finished on (sidecar/main.py SyncRunner); this side holds too, whatever the sidecar says:
 *
 * - a status never revives a run whose end was announced: every event and status carries the run's id, and the
 *   ids seen on an end are remembered;
 * - a status that says nothing is running closes a card still showing one, unless the card was started after the
 *   status was asked (its answer predates the run).
 */
export interface RunStatus {
  running: boolean
  /** the current or last run's id (absent from an older sidecar) */
  run?: number | null
}

export type Verdict = 'revive' | 'close' | 'keep'

export class RunGuard {
  private ended = new Set<number>()
  private epoch = 0

  /** an end was announced (sync_finished, sync_cancelled, an import's done, cancelled or error) */
  end(run: number | null | undefined): void {
    if (typeof run === 'number') this.ended.add(run)
  }

  /** the view started a run, or learnt of one from its events: statuses asked before now say nothing of it */
  started(): void {
    this.epoch++
  }

  /** call before asking for a status; pass the token to verdict() */
  ask(): number {
    return this.epoch
  }

  /** is the status's run live: running, and not a run whose end was announced */
  live(st: RunStatus | null | undefined): boolean {
    if (!st?.running) return false
    return !(typeof st.run === 'number' && this.ended.has(st.run))
  }

  /** what a status answer means for a card that is (cardRunning) or is not showing a running run */
  verdict(st: RunStatus, asked: number, cardRunning: boolean): Verdict {
    const live = this.live(st)
    if (live && !cardRunning) return 'revive'
    if (!live && cardRunning && asked === this.epoch) return 'close'
    return 'keep'
  }
}
