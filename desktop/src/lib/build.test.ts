import { describe, expect, it } from 'vitest'
import { BETA, SHOW_TRAINER, UPDATE_AUTOCONFIRM } from './build'

// BETA item 4: the beta switch is a build setting (`vite build --mode beta`). Every other
// mode — the owner's `tauri dev`, `npm run build`, and these tests — must see it off.
describe('build flags', () => {
  it('beta and update auto-confirm are off outside the beta build', () => {
    expect(BETA).toBe(false)
    expect(UPDATE_AUTOCONFIRM).toBe(false)
  })
  // BETA-4-TRAINER (DESIGN.md ruling 13): beta.4 shows the opening trainer in every build.
  it('the opening trainer is shown, beta or not', () => {
    expect(SHOW_TRAINER).toBe(true)
  })
})
