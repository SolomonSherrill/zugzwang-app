/** Friends' shared state (FRIENDS-1 C): the local status, the last friends list, and the incoming
 *  request count the sidebar shows (ruling S1), kept fresh by the sidecar's `friends_update`
 *  event (its heartbeat, once a minute). */
import { sidecar } from '../api'
import { accounts } from '../settings.svelte'
import { friendsApi, FriendsError, type ChesscomLink, type FriendsList, type FriendsStatus, type Mine } from './friendsApi'

export const friendsState = $state<{
  status: FriendsStatus | null
  list: FriendsList | null
  /** the count from the last heartbeat, before a list is loaded */
  incomingHint: number
  error: string | null
  loading: boolean
  /** set right after sign-up: the recovery code screen shows it once */
  recoveryCode: string | null
  /** the pending Chess.com link (BETA-5 ruling K3), kept fresh by the sidecar's `friends_link` event */
  chesscomLink: ChesscomLink
}>({ status: null, list: null, incomingHint: 0, error: null, loading: false, recoveryCode: null, chesscomLink: { state: 'none' } })

export async function refreshChesscomLink(): Promise<void> {
  try {
    friendsState.chesscomLink = await friendsApi.chesscomLink()
  } catch {
    /* no sidecar answer: keep what is shown */
  }
}

/** your own usernames, from Settings → Accounts, for "your games together" */
export function mine(): Mine {
  const m: Mine = {}
  if (accounts.chesscom) m.chesscom = accounts.chesscom
  if (accounts.lichess) m.lichess = accounts.lichess
  return m
}

export function incomingCount(): number {
  return friendsState.list ? friendsState.list.incoming.length : friendsState.incomingHint
}

export function errorText(e: unknown): string {
  if (e instanceof FriendsError) return e.message
  return e instanceof Error ? e.message : String(e)
}

export async function refreshStatus(): Promise<FriendsStatus | null> {
  try {
    friendsState.status = await friendsApi.status()
  } catch (e) {
    friendsState.error = errorText(e)
  }
  return friendsState.status
}

export async function refreshList(): Promise<void> {
  if (!friendsState.status?.signedIn) return
  friendsState.loading = true
  try {
    friendsState.list = await friendsApi.list(mine())
    friendsState.error = null
  } catch (e) {
    friendsState.error = errorText(e)
  } finally {
    friendsState.loading = false
  }
}

let wired = false
/** Once, at start: the status, the list when signed in (which starts the heartbeat), and the events. */
export function startFriends(): void {
  if (wired) return
  wired = true
  sidecar.on('friends_update', (d: { incoming: number }) => {
    friendsState.incomingHint = d.incoming
    if (friendsState.list && d.incoming !== friendsState.list.incoming.length) void refreshList()
  })
  // a check made by the heartbeat (every 15 minutes at most), or the code running out
  sidecar.on('friends_link', (d: ChesscomLink) => {
    friendsState.chesscomLink = d
  })
  void refreshStatus().then((s) => {
    if (s?.signedIn) {
      void refreshList()
      void refreshChesscomLink()
    }
  })
}
