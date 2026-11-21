/**
 * Which browser the harness drives (UI-BUILD-4 E, the WebKit pass): headless Chromium by default,
 * Playwright's WebKit with ZUGZWANG_HARNESS_BROWSER=webkit. The macOS app renders in WKWebView, so
 * WebKit is the engine the owner sees; Windows' WebView2 is Chromium. Read by harness/shoot.ts and
 * the *.browser.test.ts files:
 *
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit ZUGZWANG_HARNESS_PORT=5211 node harness/shoot.ts
 *   cd desktop && ZUGZWANG_HARNESS_BROWSER=webkit npx vitest run browser.test
 */
import { existsSync } from 'node:fs'
import { chromium, webkit, type BrowserType } from 'playwright'

export type HarnessBrowserName = 'chromium' | 'webkit'

function pick(): HarnessBrowserName {
  const v = (process.env.ZUGZWANG_HARNESS_BROWSER ?? 'chromium').trim().toLowerCase()
  if (v === '' || v === 'chromium') return 'chromium'
  if (v === 'webkit') return 'webkit'
  throw new Error(`ZUGZWANG_HARNESS_BROWSER=${v}: use chromium or webkit`)
}

export const harnessBrowserName: HarnessBrowserName = pick()
export const harnessBrowser: BrowserType = harnessBrowserName === 'webkit' ? webkit : chromium

/** The chosen browser is installed (`npx playwright install webkit` when not). */
export function harnessBrowserInstalled(): boolean {
  try {
    return existsSync(harnessBrowser.executablePath())
  } catch {
    return false
  }
}
