import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const DEPTH_KEY = 'zugzwang-analysis-depth'

/** Install a fresh localStorage before each import. The depth store reads it at
 *  module scope, so the value has to be in place before `await import`. */
function withStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial))
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  return store
}

async function loadDepth(initial?: Record<string, string>) {
  withStorage(initial)
  vi.resetModules()
  return (await import('./settings.svelte')).analysisDepth.value
}

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllGlobals())

describe('initial analysis depth', () => {
  it('is the default on a fresh install, with nothing stored', async () => {
    // The regression: `Number(null)` is 0, which *passes* Number.isFinite, so
    // the default branch was unreachable and 0 clamped to the floor of 8. Every
    // new install analysed below the shallowest preset the UI offers.
    expect(await loadDepth({})).toBe(14)
  })

  it('is the default when the key holds an empty string', async () => {
    // Same trap by another route: Number('') is also 0.
    expect(await loadDepth({ [DEPTH_KEY]: '' })).toBe(14)
  })

  it('is the default when the key holds something unparseable', async () => {
    expect(await loadDepth({ [DEPTH_KEY]: 'abc' })).toBe(14)
  })

  it('reads a stored preset back', async () => {
    expect(await loadDepth({ [DEPTH_KEY]: '10' })).toBe(10)
    expect(await loadDepth({ [DEPTH_KEY]: '18' })).toBe(18)
  })

  it('clamps a stored value to the range the sidecar accepts', async () => {
    expect(await loadDepth({ [DEPTH_KEY]: '99' })).toBe(18)
    expect(await loadDepth({ [DEPTH_KEY]: '3' })).toBe(8)
  })
})

describe('saving the analysis depth', () => {
  it('persists the clamped value, so a reload agrees with the session', async () => {
    withStorage({})
    vi.resetModules()
    const mod = await import('./settings.svelte')
    mod.saveAnalysisDepth(99)
    expect(mod.analysisDepth.value).toBe(18)
    expect(localStorage.getItem(DEPTH_KEY)).toBe('18')
  })
})

describe('depth presets', () => {
  it('stay inside the sidecar clamp range', async () => {
    withStorage({})
    vi.resetModules()
    const { DEPTH_PRESETS } = await import('./settings.svelte')
    for (const p of DEPTH_PRESETS) {
      expect(p.depth).toBeGreaterThanOrEqual(8)
      expect(p.depth).toBeLessThanOrEqual(18)
    }
  })

  it('include the default, so Settings always shows one selected', async () => {
    withStorage({})
    vi.resetModules()
    const { DEPTH_PRESETS, analysisDepth } = await import('./settings.svelte')
    expect(DEPTH_PRESETS.map((p) => p.depth)).toContain(analysisDepth.value)
  })
})
