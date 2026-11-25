/**
 * FIX-B7 B5: the acceptance checks in the browser harness, shared by src/lib/review/fixb7.browser.test.ts (the
 * suite) and harness/fixb7Accept.ts (the run's figures, review/scratch/fixb7_accept_<browser>.out).
 *
 * (a) a game whose report lists two patterns at one move opens to the report and shows both rows;
 * (b) each game of the seeded sample from the 'before' list opens to the report;
 * (c) a report built to throw while drawing shows Review's error (ruling HF2) within 2 s, not "Opening the game…",
 *     and the Coach page built to throw once shows the generic error, whose "Try again" redraws it;
 * (d) the error, with its stack, is sent to the sidecar's log (client_error; the sidecar side is
 *     tests/test_sidecar_log.py).
 */
import type { Browser, Page } from 'playwright'

type Logged = { method: string; params: Record<string, unknown> }

export interface Opened {
  gameId: number
  ms: number
  report: boolean
  opening: boolean
  failed: boolean
  errors: string[]
  patterns: { move: string; say: string }[]
}

async function newPage(browser: Browser): Promise<{ page: Page; errors: string[] }> {
  const page = await browser.newPage({ viewport: { width: 1440, height: 940 } })
  const errors: string[] = []
  page.on('pageerror', (e: Error) => errors.push(e.message))
  return { page, errors }
}

const opening = (page: Page) => page.evaluate(() => document.body.innerText.includes('Opening the game…'))

/** Open a game in Review and wait until it leaves "Opening the game…" (or the timeout). */
export async function openGame(browser: Browser, base: string, gameId: number, timeoutMs = 8000): Promise<Opened> {
  const { page, errors } = await newPage(browser)
  const t0 = Date.now()
  await page.goto(`${base}/?screen=review&game=${gameId}`)
  await page
    .waitForFunction(
      () => !!document.querySelector('[role=tab]') && !document.body.innerText.includes('Opening the game…'),
      undefined,
      { timeout: timeoutMs },
    )
    .catch(() => {})
  const ms = Date.now() - t0
  const shown = await page.evaluate(() => ({
    report: !!document.querySelector('section.headline, .headline, [aria-label="Key moments"], section.patterns, [aria-label="Game report"] dl'),
    failed: !!document.querySelector('[data-testid="screen-failed"]'),
    patterns: [...document.querySelectorAll('[data-testid="report-pattern"]')].map((li) => ({
      move: li.querySelector('.pmove')?.textContent?.trim() ?? '',
      say: li.querySelector('.say')?.textContent?.trim() ?? '',
    })),
  }))
  const out = { gameId, ms, opening: await opening(page), errors, ...shown }
  await page.close()
  return out
}

export interface FailedReview {
  ms: number | null
  opening: boolean
  sentence: boolean
  sub: string
  back: boolean
  logged: { screen: string; message: string; stackLines: number } | null
}

/** (c) and (d) on Review: the main game with ?state=report-throws. */
export async function failedReview(browser: Browser, base: string): Promise<FailedReview> {
  const { page } = await newPage(browser)
  const t0 = Date.now()
  await page.goto(`${base}/?screen=review&game=main&state=report-throws`)
  const ms = await page
    .getByText('This game could not be opened.')
    .waitFor({ timeout: 2000 })
    .then(() => Date.now() - t0)
    .catch(() => null)
  await page.waitForTimeout(200)
  const box = page.locator('[data-testid="screen-failed"]')
  const out: FailedReview = {
    ms,
    opening: await opening(page),
    sentence: await page.getByText('This game could not be opened.').isVisible().catch(() => false),
    sub: ((await box.locator('.sub').textContent().catch(() => '')) ?? '').trim(),
    back: await box.getByRole('button', { name: 'Back to games' }).isVisible().catch(() => false),
    logged: await clientError(page),
  }
  await page.close()
  return out
}

async function clientError(page: Page): Promise<FailedReview['logged']> {
  const log = (await page.evaluate(
    () => (window as unknown as { __harness: { requestLog: Logged[] } }).__harness.requestLog,
  )) as Logged[]
  const e = log.find((r) => r.method === 'client_error')
  if (!e) return null
  return {
    screen: String(e.params.screen),
    message: String(e.params.message),
    stackLines: String(e.params.stack ?? '').split('\n').filter((l) => l.trim()).length,
  }
}

export interface FailedScreen {
  ms: number | null
  sentence: boolean
  sub: string
  logged: FailedReview['logged']
  redrawn: boolean
  failedAfter: boolean
}

/** (c) on another screen: the Coach page with ?state=coach-throws-once, then "Try again". */
export async function failedCoach(browser: Browser, base: string): Promise<FailedScreen> {
  const { page } = await newPage(browser)
  const t0 = Date.now()
  await page.goto(`${base}/?screen=coach&state=coach-throws-once`)
  const ms = await page
    .getByText('This screen could not be opened.')
    .waitFor({ timeout: 2000 })
    .then(() => Date.now() - t0)
    .catch(() => null)
  const box = page.locator('[data-testid="screen-failed"]')
  const sentence = await page.getByText('This screen could not be opened.').isVisible().catch(() => false)
  const sub = ((await box.locator('.sub').textContent().catch(() => '')) ?? '').trim()
  const logged = await clientError(page)
  await box.getByRole('button', { name: 'Try again' }).click({ timeout: 2000 }).catch(() => {})
  const redrawn = await page
    .locator('[data-testid="coach-focus-item"]')
    .first()
    .waitFor({ timeout: 3000 })
    .then(() => true)
    .catch(() => false)
  const failedAfter = await box.isVisible().catch(() => false)
  await page.close()
  return { ms, sentence, sub, logged, redrawn, failedAfter }
}
