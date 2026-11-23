/** The Friends screens' shots (FRIENDS-1 E), each beside its mockup and each with the DOM layout
 *  check (harness/layoutCheck.ts): written to review/scratch/ui/friends/ and its layout_check.out.
 *  The data is friends_fixtures.json (synthetic). "you_demo" stands in for the saved usernames. */
import type { Page } from 'playwright'
import type { Shot } from './shots.ts'

const STORAGE = { 'zugzwang-accounts': JSON.stringify({ chesscom: 'you_demo', lichess: '' }) }
const TALL = { width: 1440, height: 1240 }

async function signupFilled(p: Page): Promise<void> {
  await p.locator('#hdl').fill('pawn_one')
  await p.getByText('Available').waitFor()
  await p.getByLabel('I’m 13 or older').check()
  await p.locator('label.cb').nth(1).locator('input').check()
}

export const FRIENDS_SHOTS: Shot[] = [
  { dir: 'friends', name: 'friends', url: '/?screen=friends', mockup: 'MinimalFriends.html', storage: STORAGE, check: true },
  {
    dir: 'friends',
    name: 'signup',
    url: '/?screen=friends&state=friends-signup',
    mockup: 'MinimalFriends-signup.html',
    storage: STORAGE,
    check: true,
    act: signupFilled,
  },
  {
    dir: 'friends',
    name: 'recovery',
    url: '/?screen=friends&state=friends-signup',
    mockup: 'MinimalFriends-recovery.html',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await signupFilled(p)
      await p.getByRole('button', { name: 'Create account' }).click()
      await p.getByText('Save your recovery code').waitFor()
    },
  },
  {
    dir: 'friends',
    name: 'signup-recover',
    url: '/?screen=friends&state=friends-signup',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: /Use your recovery code/ }).click()
    },
  },
  { dir: 'friends', name: 'friend', url: '/?screen=friend&friend=maxk', mockup: 'MinimalFriend.html', storage: STORAGE, size: TALL, check: true },
  {
    dir: 'friends',
    name: 'friend-vs-e4',
    url: '/?screen=friend&friend=noa_p',
    storage: STORAGE,
    size: TALL,
    check: true,
    act: async (p) => {
      await p.getByRole('tab', { name: 'Against 1.e4' }).click()
    },
  },
  { dir: 'friends', name: 'friend-lichess-only', url: '/?screen=friend&friend=benji', storage: STORAGE, size: TALL, check: true },
  { dir: 'friends', name: 'friend-no-links', url: '/?screen=friend&friend=hannah_k', storage: STORAGE, check: true },
  {
    dir: 'friends',
    name: 'friend-menu',
    url: '/?screen=friend&friend=maxk',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: /More: Remove friend/ }).click()
    },
  },
  {
    dir: 'friends',
    name: 'friend-analyse',
    url: '/?screen=friend&friend=maxk',
    storage: STORAGE,
    check: true,
    waitMs: 1200,
    act: async (p) => {
      const row = p.locator('.rrow').nth(1)
      await row.hover()
      await row.getByRole('button', { name: 'Analyse' }).click()
      await p.getByRole('region', { name: 'Board' }).locator('cg-board').waitFor()
    },
  },
  {
    dir: 'friends',
    name: 'settings-friends',
    url: '/?screen=settings',
    mockup: 'MinimalSettings.html',
    storage: STORAGE,
    size: TALL,
    check: true,
  },
  {
    dir: 'friends',
    name: 'settings-recovery-shown',
    url: '/?screen=settings',
    storage: STORAGE,
    size: TALL,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Show', exact: true }).click()
    },
  },
  {
    dir: 'friends',
    name: 'settings-delete-confirm',
    url: '/?screen=settings',
    storage: STORAGE,
    size: TALL,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Delete account' }).click()
    },
  },
  {
    dir: 'friends',
    name: 'legal-privacy',
    url: '/?screen=settings',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Privacy policy' }).click()
    },
  },
  {
    dir: 'friends',
    name: 'legal-terms',
    url: '/?screen=friends&state=friends-signup',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Terms of use' }).click()
    },
  },
  { dir: 'friends', name: 'unconfigured', url: '/?screen=friends&state=friends-unconfigured', storage: STORAGE, check: true },
  { dir: 'friends', name: 'friends-1280x720', url: '/?screen=friends', storage: STORAGE, size: { width: 1280, height: 720 }, check: true },
  { dir: 'friends', name: 'friend-1280x720', url: '/?screen=friend&friend=maxk', storage: STORAGE, size: { width: 1280, height: 720 }, check: true },
  { dir: 'friends', name: 'home-sidebar', url: '/?screen=home', storage: STORAGE, check: true },
  // BETA-5: "Save as a file" through the save dialog (answered as the dialog would be), the Chess.com
  // link waiting for Chess.com (ruling K3), and Remove friend / Block asking first (ruling S5)
  {
    dir: 'friends',
    name: 'recovery-saved',
    url: '/?screen=friends&state=friends-signup',
    storage: STORAGE,
    check: true,
    before: async (p) => {
      await p.addInitScript(() => {
        ;(window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {
          invoke: async (cmd: string) => (cmd === 'plugin:dialog|save' ? '/home/demo/Documents/zugzwang-recovery-code.txt' : null),
          transformCallback: () => 0,
        }
      })
    },
    act: async (p) => {
      await signupFilled(p)
      await p.getByRole('button', { name: 'Create account' }).click()
      await p.getByRole('button', { name: 'Save as a file' }).click()
      await p.locator('p.note').waitFor()
    },
  },
  { dir: 'friends', name: 'link-code', url: '/?screen=friends&state=friends-cc-code', storage: STORAGE, check: true },
  { dir: 'friends', name: 'link-waiting', url: '/?screen=friends&state=friends-cc-waiting', storage: STORAGE, check: true },
  { dir: 'friends', name: 'link-expired', url: '/?screen=friends&state=friends-cc-expired', storage: STORAGE, check: true },
  {
    dir: 'friends',
    name: 'friend-remove-confirm',
    url: '/?screen=friend&friend=maxk',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: /More: Remove friend/ }).click()
      await p.getByRole('menuitem', { name: 'Remove friend' }).click()
    },
  },
  {
    dir: 'friends',
    name: 'friend-block-confirm',
    url: '/?screen=friend&friend=maxk',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: /More: Remove friend/ }).click()
      await p.getByRole('menuitem', { name: 'Block' }).click()
    },
  },
]
