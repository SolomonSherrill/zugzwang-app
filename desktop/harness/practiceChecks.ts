/**
 * COACH-2 C: DOM checks of Practice in the harness browser (Chromium, or WebKit with ZUGZWANG_HARNESS_BROWSER=webkit),
 * 1280 x 720 and 1440 x 900, longest names (?names=long). The Coach page's Practice panel and the sidebar's due count;
 * a session played through: the theme absent from the page until the answer, a right answer made on the board (two
 * clicks), "Spot the threat" with its answer shown, a probe answered wrong, the end; Practise on a focus card; "Added
 * to Practice" in the report. Layout: nothing in the panel overflows its box; a cut name carries its whole text as
 * title; the board square and inside its column. Shots of the states the scripted cases cannot reach (Right, Not
 * quite on a threat, the end) go beside the results: review/scratch/ui/coach2/practice/<browser>/.
 *
 *   cd desktop && node harness/practiceChecks.ts
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { Page } from 'playwright'
import { harnessBrowser, harnessBrowserName } from './browser.ts'
import { SIZES } from './beta6Specs.ts'
import { openCase } from './beta6Checks.ts'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', '..', 'review', 'scratch', 'ui', 'coach2', 'practice', harnessBrowserName)
const port = Number(process.env.ZUGZWANG_HARNESS_PORT ?? 5260)
const server = await createServer({ configFile: resolve(here, '..', 'vite.harness.config.ts'), server: { port }, logLevel: 'silent' })
await server.listen()
const browser = await harnessBrowser.launch({ headless: true })
const base = `http://localhost:${port}`
const lines: string[] = []
let fails = 0
const check = (ok: boolean, what: string) => {
  lines.push(`${ok ? 'PASS' : 'FAIL'}  ${what}`)
  if (!ok) fails++
}
const text = (page: Page, sel: string) => page.locator(sel).first().innerText().catch(() => '')

/** every element under *sel* whose content overflows it (text cut without an ellipsis, or a box spilling out) */
async function overflow(page: Page, sel: string): Promise<string[]> {
  return page.evaluate((s) => {
    const root = document.querySelector(s)
    if (!root) return ['no ' + s]
    const r0 = root.getBoundingClientRect()
    const bad: string[] = []
    for (const el of root.querySelectorAll('*')) {
      const h = el as HTMLElement
      const r = h.getBoundingClientRect()
      if (!r.width || !r.height) continue
      if (r.right > r0.right + 1 || r.left < r0.left - 1) bad.push(`${h.tagName.toLowerCase()}.${h.className} outside by ${Math.round(Math.max(r.right - r0.right, r0.left - r.left))} px`)
      const st = getComputedStyle(h)
      if (h.scrollWidth > h.clientWidth + 1 && st.overflowX !== 'auto' && st.overflowX !== 'scroll' && st.textOverflow !== 'ellipsis' && h.children.length === 0)
        bad.push(`${h.tagName.toLowerCase()}.${h.className} "${(h.textContent ?? '').slice(0, 30)}" overflows by ${h.scrollWidth - h.clientWidth} px`)
      if (st.textOverflow === 'ellipsis' && h.scrollWidth > h.clientWidth + 1 && !h.title && !h.closest('[title]')) bad.push(`cut without a title: "${(h.textContent ?? '').slice(0, 30)}"`)
    }
    return bad
  }, sel)
}

async function clickSquare(page: Page, sq: string, orientation: 'white' | 'black') {
  const b = await page.locator('[data-testid=practice] cg-board').boundingBox()
  if (!b) throw new Error('no board')
  const f = sq.charCodeAt(0) - 97
  const r = Number(sq[1]) - 1
  const col = orientation === 'white' ? f : 7 - f
  const row = orientation === 'white' ? 7 - r : r
  const s = b.width / 8
  await page.mouse.click(b.x + (col + 0.5) * s, b.y + (row + 0.5) * s)
  await page.waitForTimeout(150)
}

async function boardOk(page: Page, sz: string, what: string) {
  const g = await page.evaluate(() => {
    const b = document.querySelector('[data-testid=practice] cg-board')?.getBoundingClientRect()
    const c = document.querySelector('[data-testid=practice] .board-col')?.getBoundingClientRect()
    return b && c ? { w: b.width, h: b.height, inside: b.left >= c.left - 1 && b.right <= c.right + 1 && b.top >= c.top - 1 && b.bottom <= c.bottom + 1 } : null
  })
  check(!!g && Math.abs(g.w - g.h) <= 1 && g.inside, `${sz} ${what}: the board square (${g ? Math.round(g.w) + ' x ' + Math.round(g.h) : 'none'}) and inside its column`)
}

for (const size of SIZES) {
  const sz = `${size.width}x${size.height}`
  const shot = (page: Page, name: string) => {
    const p = resolve(out, sz, name + '.png')
    mkdirSync(dirname(p), { recursive: true })
    return page.screenshot({ path: p })
  }

  // the Coach page: Practice panel, the sidebar's count
  const coach = await openCase(browser, base, { name: 'coach', path: '/?screen=coach' }, size)
  const panel = await text(coach, '[data-testid=coach-practice]')
  check(/7\s*due today, about 5 minutes/.test(panel) && panel.includes('Find the move') && panel.includes('68%') && panel.includes('41'), `${sz} coach: the Practice panel's figures`)
  check((await text(coach, '[data-testid=coach-due]')) === '7', `${sz} coach: the sidebar's Coach item shows 7 due`)
  const cnt = await coach.evaluate(() => {
    const c = document.querySelector('[data-testid=coach-due]')?.getBoundingClientRect()
    const it = document.querySelector('[data-testid=coach-due]')?.closest('button')?.getBoundingClientRect()
    return c && it ? c.left >= it.left && c.right <= it.right + 1 && c.top >= it.top && c.bottom <= it.bottom : false
  })
  check(cnt, `${sz} coach: the count inside its sidebar item`)
  const ov0 = await overflow(coach, '[data-testid=coach-practice]')
  check(ov0.length === 0, `${sz} coach: nothing overflows the Practice panel${ov0.length ? ': ' + ov0.slice(0, 3).join('; ') : ''}`)

  // a session
  await coach.getByRole('button', { name: 'Start practice' }).click()
  await coach.waitForTimeout(500)
  const body0 = await coach.locator('[data-testid=practice]').innerText()
  check(body0.includes('1 of 3') && body0.includes('About 2 minutes left') && body0.includes('Find the move') && body0.includes('White to move'), `${sz} session: 1 of 3, About 2 minutes left, Find the move, White to move`)
  check(!body0.includes('Knight fork') && !body0.includes('fork'), `${sz} session: no theme on the page before the answer`)
  check(body0.includes('The theme shows after you answer.'), `${sz} session: "The theme shows after you answer."`)
  await boardOk(coach, sz, 'session')
  const ov1 = await overflow(coach, '[data-testid=practice] aside')
  check(ov1.length === 0, `${sz} session: nothing overflows the panel${ov1.length ? ': ' + ov1.slice(0, 3).join('; ') : ''}`)
  // Hint, then the right move on the board
  await coach.keyboard.press('h')
  await coach.waitForTimeout(150)
  check(await coach.getByRole('button', { name: /^Hint/ }).isDisabled(), `${sz} session: H shows the hint once`)
  await clickSquare(coach, 'b5', 'white')
  await clickSquare(coach, 'c7', 'white')
  await coach.waitForTimeout(600)
  const right = await text(coach, '[data-testid=practice] .verdict')
  check(right.includes('Right') && right.includes('You found it: 21. Nc7+ starts a knight fork.') && right.includes('Knight fork') && right.includes('One of your focus themes') && right.includes('Comes back in 4 days.'), `${sz} session: Right, the sentence, the theme, focus, when it comes back`)
  check((await text(coach, '[data-testid=practice] .earlier')).includes('In 4 days'), `${sz} session: Earlier this session lists it`)
  const ov2 = await overflow(coach, '[data-testid=practice] aside')
  check(ov2.length === 0, `${sz} session, Right: nothing overflows the panel${ov2.length ? ': ' + ov2.slice(0, 3).join('; ') : ''}`)
  await shot(coach, 'practice-right')
  // Next: Spot the threat, the answer shown
  await coach.keyboard.press('Enter')
  await coach.waitForTimeout(400)
  const t = await coach.locator('[data-testid=practice]').innerText()
  check(t.includes('2 of 3') && t.includes('Spot the threat') && t.includes('Black to move') && t.includes('White just played 9. Nd5.'), `${sz} session: Spot the threat, Black to move, White just played 9. Nd5.`)
  // the answered item's theme stays in "Earlier this session"; the position being answered shows none
  const tp = await text(coach, '[data-testid=practice] .prompt')
  check(!tp.includes('Knight fork') && !/fork/i.test(tp), `${sz} session: the threat's theme hidden before the answer`)
  await boardOk(coach, sz, 'threat')
  await coach.getByRole('button', { name: 'Show the answer' }).click()
  await coach.waitForTimeout(400)
  const nq = await text(coach, '[data-testid=practice] .verdict')
  check(nq.includes('Not quite') && nq.includes('A move that deals with it: 9... Rc8.') && nq.includes('Comes back tomorrow.'), `${sz} session: the answer shown is Not quite, with the move`)
  await shot(coach, 'practice-threat-not-quite')
  // Next: the probe, a wrong move
  await coach.keyboard.press('Enter')
  await coach.waitForTimeout(400)
  const p = await coach.locator('[data-testid=practice]').innerText()
  check(p.includes('3 of 3') && p.includes('A new position, not from your games.') && !p.includes('From your game against'), `${sz} session: the probe says it is not from your games`)
  await clickSquare(coach, 'e1', 'white')
  await clickSquare(coach, 'e2', 'white')
  await coach.waitForTimeout(600)
  check((await text(coach, '[data-testid=practice] .verdict')).includes('The move is 2. Nc4.'), `${sz} session: a wrong move on the probe is Not quite, with its move`)
  await coach.getByRole('button', { name: 'Finish' }).click()
  await coach.waitForTimeout(300)
  check((await text(coach, '[data-testid=practice] .prompt')).includes('1 of 2 right') || (await text(coach, '[data-testid=practice] .prompt')).includes('1 of 3 right'), `${sz} session: Done for today with the tally`)
  await shot(coach, 'practice-done')
  await coach.getByRole('button', { name: 'Back to Coach' }).click()
  await coach.waitForTimeout(300)
  check((await coach.locator('[data-testid=coach-practice]').count()) === 1, `${sz} session: Back to Coach`)
  await coach.context().close()

  // Practise on a focus card
  const fc = await openCase(browser, base, { name: 'coach', path: '/?screen=coach' }, size)
  await fc.getByRole('button', { name: 'Practise', exact: true }).first().click()
  await fc.waitForTimeout(400)
  const crumb = await fc.locator('[data-testid=practice] .title').getAttribute('title')
  check(crumb === 'Practice: Knight forks against you', `${sz} focus card: Practise opens "${crumb}"`)
  await fc.context().close()

  // the report: Added to Practice
  const rv = await openCase(browser, base, { name: 'review', path: '/?screen=review&game=main' }, size)
  const added = await rv.locator('[data-testid=added-to-practice]').count()
  check(added === 2 && (await rv.locator('.patterns .pnote').innerText()).startsWith('Missed moments go to Practice.'), `${sz} report: "Added to Practice" on the 2 missed moments, and the note`)
  await rv.context().close()
}
mkdirSync(out, { recursive: true })
writeFileSync(resolve(out, 'practice_checks.out'), `# COACH-2 C, ${harnessBrowserName}: harness/practiceChecks.ts\n` + lines.join('\n') + `\n${lines.length - fails} of ${lines.length} checks pass\n`)
console.log(lines.filter((l) => l.startsWith('FAIL')).join('\n'))
console.log(`${harnessBrowserName}: ${lines.length - fails} of ${lines.length} checks pass`)
await browser.close()
await server.close()
