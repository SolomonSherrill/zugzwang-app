import { describe, expect, it } from 'vitest'
import { bookAction, bookLine, formatBytes, jobFraction, jobText } from './books'
import type { BookInfo } from './api'

const book = (over: Partial<BookInfo> = {}): BookInfo => ({
  id: 'all-20', label: 'Standard', minGames: 20, bytes: 151_320_480, sha256: 'x', url: 'u',
  default: true, installed: false, active: false, ...over,
})

describe('opening books', () => {
  it('states sizes in decimal units', () => {
    expect(formatBytes(151_320_480)).toBe('151 MB')
    expect(formatBytes(572_067_472)).toBe('572 MB')
    expect(formatBytes(1_323_905_200)).toBe('1.3 GB')
  })
  it('names the floor and the size', () => {
    expect(bookLine(book())).toBe('Standard: moves played at least 20 times · 151 MB')
  })
  it('offers a download only when the book is not installed', () => {
    expect(bookAction(book())).toBe('Download and use (151 MB)')
    expect(bookAction(book({ installed: true }))).toBe('Use this book')
  })
  it('describes each phase of a switch', () => {
    const books = [book()]
    expect(jobText({ id: 'all-20', phase: 'download', done: 75_660_240, total: 151_320_480 }, books))
      .toBe('Downloading Standard: 76 MB of 151 MB (50%)')
    expect(jobText({ id: 'all-20', phase: 'backup', done: 0, total: 1 }, books))
      .toBe('Backing up your database before switching to Standard…')
    expect(jobText({ id: 'all-20', phase: 'relabel', done: 10, total: 40 }, books))
      .toBe('Marking book moves in your games: 10 of 40 analysed games')
    expect(jobFraction({ id: 'all-20', phase: 'relabel', done: 10, total: 40 })).toBe(0.25)
    expect(jobFraction({ id: 'all-20', phase: 'backup', done: 0, total: 0 })).toBe(0)
  })
})
