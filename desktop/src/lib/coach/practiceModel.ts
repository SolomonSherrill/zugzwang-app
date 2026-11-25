/** COACH-2 C: Practice's words, fixed templates over the item's facts (no theme before the answer, ruling 6). */
import type { PracticeItem, PracticeStatus } from '../api'
import { coachDate } from './coachModel'

export const FORM: Record<PracticeItem['kind'], string> = { find: 'Find the move', threat: 'Spot the threat' }

const SIDE = { white: 'White', black: 'Black' } as const
const other = (s: 'white' | 'black') => (s === 'white' ? 'Black' : 'White')

/** the prompt under "<Side> to move" */
export function promptText(it: PracticeItem): string {
  if (it.source === 'probe') return 'A new position, not from your games. Find the best move.'
  if (it.kind === 'find') return 'There was a better move here than the one you played. Find it.'
  const before = it.oppMove ? `${other(it.side)} just played ${it.oppMove}. ` : ''
  return `${before}Your move in the game let ${other(it.side)} win by force. Find one that deals with the threat.`
}

export function sideText(it: Pick<PracticeItem, 'side'>): string {
  return `${SIDE[it.side]} to move`
}

/** "From your game against <opponent>, 15 Nov. You played 9. Bf4." (the name a link, so split in parts) */
export function sourceParts(it: PracticeItem, now: Date = new Date()): { before: string; name: string | null; after: string } | null {
  if (it.source === 'probe') return null
  const date = it.date ? coachDate(it.date, now) : ''
  const after = `${date ? ', ' + date : ''}.${it.played ? ` You played ${it.played}.` : ''}`
  return { before: 'From your game against ', name: it.opponent ?? 'an unknown opponent', after }
}

/** "About 3 minutes left" */
export function minutesLeft(left: number, secondsEach: number): string {
  if (left <= 0) return ''
  const m = Math.max(1, Math.round((left * secondsEach) / 60))
  return `About ${m} ${m === 1 ? 'minute' : 'minutes'} left`
}

/** the panel's head: "7 due today, about 5 minutes" (the figure apart) */
export function dueLine(s: Pick<PracticeStatus, 'due' | 'minutes'>): string {
  if (!s.due) return 'due today'
  return `due today, about ${s.minutes} ${s.minutes === 1 ? 'minute' : 'minutes'}`
}

export function percent(x: number | null): string {
  return x === null ? '—' : `${Math.round(x * 100)}%`
}
