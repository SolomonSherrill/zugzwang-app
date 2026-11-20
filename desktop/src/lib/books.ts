/** Opening books (BOOK-DL, owner ruling D, 2026-11-19): pure helpers for the Settings card and
 *  the trainer lobby's no-book prompt. */
import type { BookInfo, BookJob } from './api'

/** "151 MB", "1.3 GB": decimal units, as the sizes were ruled. */
export function formatBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`
  return `${Math.round(n / 1e6)} MB`
}

/** One line for a book: its name, the games floor, the size. */
export function bookLine(b: BookInfo): string {
  return `${b.label}: moves played at least ${b.minGames} times · ${formatBytes(b.bytes)}`
}

/** The button for a book that is not in use. */
export function bookAction(b: BookInfo): string {
  return b.installed ? 'Use this book' : `Download and use (${formatBytes(b.bytes)})`
}

/** What a job in flight is doing, for the progress line. */
export function jobText(job: BookJob, books: BookInfo[]): string {
  const name = books.find((b) => b.id === job.id)?.label ?? job.id
  if (job.phase === 'download') {
    const pct = job.total ? Math.floor((job.done * 100) / job.total) : 0
    return `Downloading ${name}: ${formatBytes(job.done)} of ${formatBytes(job.total)} (${pct}%)`
  }
  if (job.phase === 'backup') return `Backing up your database before switching to ${name}…`
  return `Marking book moves in your games: ${job.done} of ${job.total} analysed games`
}

/** 0–1 for a progress bar. */
export function jobFraction(job: BookJob): number {
  return job.total ? Math.min(1, job.done / job.total) : 0
}
