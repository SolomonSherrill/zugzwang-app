/** FRIENDS-2 D's shots: the challenge banner, the Challenge popover, Play's "A friend" and the game screen in
 *  each state, each beside its stage-2 mockup where there is one, each with the DOM layout check
 *  (harness/layoutCheck.ts) written to review/scratch/ui/friends2/layout_check.out (and the WebKit pass's to
 *  review/scratch/ui/webkit/friends2/). The data is synthetic (friends_fixtures.json, friendsHarness.ts). */
import type { Shot } from './shots.ts'

const STORAGE = { 'zugzwang-accounts': JSON.stringify({ chesscom: 'you_demo', lichess: '' }) }
const TALL = { width: 1440, height: 1240 }

export const FRIENDS2_SHOTS: Shot[] = [
  { dir: 'friends2', name: 'banner-friends', url: '/?screen=friends&state=friends-challenge', mockup: 'MinimalFriends-challenge.html', storage: STORAGE, check: true },
  { dir: 'friends2', name: 'banner-home', url: '/?screen=home&state=friends-challenge', storage: STORAGE, check: true },
  { dir: 'friends2', name: 'banner-play', url: '/?screen=play&state=friends-challenge', storage: STORAGE, check: true },
  {
    dir: 'friends2',
    name: 'popover-profile',
    url: '/?screen=friend&friend=maxk',
    mockup: 'MinimalFriend-challenge.html',
    storage: STORAGE,
    size: TALL,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Challenge', exact: true }).click()
      await p.getByRole('dialog', { name: 'Challenge maxk' }).waitFor()
    },
  },
  {
    dir: 'friends2',
    name: 'popover-list',
    url: '/?screen=friends',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.locator('li.fli', { hasText: 'maxk' }).getByRole('button', { name: 'Challenge', exact: true }).click()
      await p.getByRole('dialog', { name: 'Challenge maxk' }).waitFor()
    },
  },
  {
    dir: 'friends2',
    name: 'popover-waiting',
    url: '/?screen=friends',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.locator('li.fli', { hasText: 'maxk' }).getByRole('button', { name: 'Challenge', exact: true }).click()
      await p.getByRole('dialog', { name: 'Challenge maxk' }).getByRole('button', { name: 'Send challenge' }).click()
      await p.getByText(/Waiting for maxk to answer/).waitFor()
    },
  },
  {
    dir: 'friends2',
    name: 'play-setup-friend',
    url: '/?screen=play',
    mockup: 'MinimalPlaySetup-friend.html',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('radio', { name: 'A friend' }).click()
      await p.getByRole('heading', { name: 'New game against a friend' }).waitFor()
    },
  },
  { dir: 'friends2', name: 'game', url: '/?screen=play&state=fgame', mockup: 'MinimalPlayGame-friend.html', storage: STORAGE, check: true },
  { dir: 'friends2', name: 'game-draw', url: '/?screen=play&state=fgame-draw', mockup: 'MinimalPlayGame-friend-draw.html', storage: STORAGE, check: true },
  { dir: 'friends2', name: 'game-left', url: '/?screen=play&state=fgame-left', mockup: 'MinimalPlayGame-friend-left.html', storage: STORAGE, check: true },
  { dir: 'friends2', name: 'game-over', url: '/?screen=play&state=fgame-over', mockup: 'MinimalPlayGame-friend-over.html', storage: STORAGE, check: true },
  {
    dir: 'friends2',
    name: 'game-chat-collapsed',
    url: '/?screen=play&state=fgame-collapsed',
    mockup: 'MinimalPlayGame-friend-chat-collapsed.html',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('region', { name: 'Chat' }).getByRole('button', { name: /^Chat/ }).click()
      await p.getByLabel('1 unread').waitFor()
    },
  },
  { dir: 'friends2', name: 'game-1280x720', url: '/?screen=play&state=fgame', storage: STORAGE, size: { width: 1280, height: 720 }, check: true },
  { dir: 'friends2', name: 'game-over-1280x720', url: '/?screen=play&state=fgame-over', storage: STORAGE, size: { width: 1280, height: 720 }, check: true },
  {
    dir: 'friends2',
    name: 'check-now-wait',
    url: '/?screen=friends&state=friends-cc-waiting',
    storage: STORAGE,
    check: true,
    act: async (p) => {
      await p.getByRole('button', { name: 'Check now' }).click()
      await p.getByRole('button', { name: /Check again in/ }).waitFor()
    },
  },
]
