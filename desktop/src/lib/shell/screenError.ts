/**
 * FIX-B7 (ruling HF2): a screen that fails while drawing shows an error instead of its loading state
 * (ScreenBoundary.svelte), and the error and its stack go to the sidecar's log at ERROR (`client_error`), so the next
 * stuck screen can be diagnosed from logs/sidecar.log alone.
 */
import { api } from '../api'

/** The error's own words, for the line under the sentence. */
export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message || e.name
  return typeof e === 'string' ? e : String(e)
}

/** Send the error and its stack to the sidecar log; never throws (the sidecar may be down too). */
export function reportScreenError(screen: string, e: unknown): void {
  const message = errorText(e)
  const stack = e instanceof Error ? (e.stack ?? '') : ''
  console.error(`[${screen}] failed while drawing:`, e)
  try {
    void api.clientError(screen, message, stack).catch(() => {})
  } catch {
    // the sidecar is not started: the console has it
  }
}
