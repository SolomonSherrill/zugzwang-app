/**
 * COACH-2 C: the Practice counts the sidebar's Coach item (ruling 6: the number due) and the Coach page read. Read at
 * start and whenever the backend comes up; practice_updated carries new counts after an answer or new items, and
 * coach_updated (a new Focus can reorder the feed) asks again.
 */
import { api, sidecar, type PracticeStatus } from '../api'

export const practice = $state<{ status: PracticeStatus | null }>({ status: null })

export function refreshPractice(): void {
  api
    .practiceStatus()
    .then((s) => (practice.status = s))
    .catch(() => {})
}

let started = false
export function startPractice(): () => void {
  if (started) return () => {}
  started = true
  const onUpdated = (d: Record<string, unknown>) => {
    if (typeof d.due === 'number') practice.status = d as unknown as PracticeStatus
    else refreshPractice()
  }
  const onCoach = () => refreshPractice()
  sidecar.on('practice_updated', onUpdated)
  sidecar.on('coach_updated', onCoach)
  refreshPractice()
  return () => {
    sidecar.off('practice_updated', onUpdated)
    sidecar.off('coach_updated', onCoach)
    started = false
  }
}

/** the sidebar's count: due today, or nothing */
export function dueCount(): number {
  return practice.status?.due ?? 0
}
