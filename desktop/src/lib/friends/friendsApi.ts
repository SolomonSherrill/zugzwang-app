/** The sidecar's friends_ methods (FRIENDS-1 C; sidecar/main.py "Friends"). A refusal by the Friends
 *  server arrives as {error: {code, message}} and is raised as FriendsError, so a screen can say what
 *  happened (a taken handle, no connection) instead of a stack trace. */
import { sidecar } from '../api'

export class FriendsError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

/** a deferred friends_ answer: the result, or the server's refusal raised as FriendsError */
async function call<T>(p: Promise<T>): Promise<T> {
  const out = (await p) as T & { error?: { code: string; message: string } }
  if (out && typeof out === 'object' && 'error' in out && out.error) throw new FriendsError(out.error.code, out.error.message)
  return out as T
}

export type Site = 'chesscom' | 'lichess'
export interface Linked {
  site: Site
  username: string
  verified?: boolean
}
export interface FriendsStatus {
  enabled: boolean
  configured: boolean
  server: string | null
  keystore: { kind: string; label: string; available: boolean }
  signedIn: boolean
  handle: string | null
  settings: { shareGames: boolean; appearOffline: boolean; chatEnabled: boolean }
  ratingSource: { source: string; url: string; retrieved: string }
}
export interface ListRating {
  speed: string
  rating: number
  approx: boolean
  lichess?: number
}
export interface Record3 {
  games: number
  won: number
  drawn: number
  lost: number
  score: number | null
}
export interface Friend {
  handle: string
  since: number
  online: boolean
  last_seen: number | null
  linked: Linked[]
  ratings: ListRating[]
  record: Record3
  lastGame: string | null
  hasData: boolean
}
export interface FriendRequest {
  id: number
  handle: string
  created: number
}
export interface FriendsList {
  server_time: number
  friends: Friend[]
  incoming: FriendRequest[]
  outgoing: FriendRequest[]
  blocked: { handle: string; created: number }[]
}
export interface Rating {
  site: Site
  speed: string
  rating: number
  games: number
  delta30: number | null
  estimate: number | null
  /** the sparkline: ratings over the last 30 days, in game order; [] for no line (FRIENDS-1B D) */
  spark: number[]
}
export type Outcome = 'won' | 'drawn' | 'lost'
export interface TogetherGame {
  id: number
  site: Site
  where: string
  result: Outcome | null
  /** your colour in the game (its square, FRIENDS-1B D) */
  color: 'white' | 'black' | null
  time_control: string | null
  opening: string | null
  eco: string | null
  ended_at: string | null
}
export interface OpeningRow extends Record3 {
  opening: string
  eco: string | null
}
export interface RecentGame {
  id: number
  site: Site
  where: string
  result: Outcome | null
  white: string | null
  black: string | null
  white_elo: number | null
  black_elo: number | null
  player: string
  opening: string | null
  eco: string | null
  time_control: string | null
  ended_at: string | null
}
export interface Split {
  games: number
  pct: number
  by: { mate: number; resigned: number; time: number; other: number }
}
export interface Profile {
  friend: Friend
  ratings: Rating[]
  listRatings: ListRating[]
  record: Record3
  together: TogetherGame[]
  scouting: { asWhite: OpeningRow[]; vsE4: OpeningRow[]; vsD4: OpeningRow[]; games: number; sites: Record<string, number>; oldest: string | null }
  bySpeed: ({ speed: string } & Record3)[]
  endings: { games: number; draws: { games: number; pct: number }; won: Split; lost: Split }
  recent: RecentGame[]
  recentTotal: number
  data: { fetchedAt: string | null; stale: boolean; fetching: boolean; complete: boolean; oldest: string | null }
}
export interface FriendGame {
  id: number
  site: Site
  white: string | null
  black: string | null
  whiteElo: number | null
  blackElo: number | null
  result: string | null
  opening: string | null
  eco: string | null
  endedAt: string | null
  timeControl: string | null
  startFen: string
  moves: string[]
}
export type Mine = Partial<Record<Site, string>>
/** The pending Chess.com link (BETA-5 ruling K3; core/friends/chesscom_link.py): "code" until the first
 *  check, "waiting" while Chess.com has not shown it (checked every 15 minutes while the app is open),
 *  "expired" after its 24 hours, "linked" once found (until the message is dismissed). */
export interface ChesscomLink {
  state: 'none' | 'code' | 'waiting' | 'expired' | 'linked'
  username?: string | null
  code?: string | null
  /** Unix ms */
  expires?: number | null
  lastCheck?: number | null
  nextCheck?: number | null
  /** why the last check got no answer (Chess.com unreachable, …); null when it simply found no code */
  error?: string | null
  /** a check was already running, so this call made none */
  checking?: boolean
  verified?: boolean
}

export const friendsApi = {
  status: () => sidecar.request<FriendsStatus>('friends_status'),
  checkHandle: (handle: string) =>
    call(sidecar.request<{ handle: string; available: boolean; reason: 'invalid' | 'reserved' | 'taken' | null }>('friends_check_handle', { handle })),
  signup: (p: { handle: string; ageConfirmed: boolean; termsAccepted: boolean; shareGames: boolean }) =>
    call(sidecar.request<{ handle: string; recoveryCode: string }>('friends_signup', p)),
  recoveryCode: () => sidecar.request<{ code: string }>('friends_recovery_code'),
  recover: (code: string) => call(sidecar.request<{ handle: string }>('friends_recover', { code })),
  me: () => call(sidecar.request<{ handle: string; created: number; appear_offline: boolean; linked: Linked[] }>('friends_me')),
  list: (mine: Mine) => call(sidecar.request<FriendsList>('friends_list', { mine })),
  request: (handle: string) => call(sidecar.request<{ status: 'sent' | 'friends'; handle: string }>('friends_request', { handle })),
  answer: (id: number, accept: boolean) => call(sidecar.request<{ status: string }>('friends_answer', { id, accept })),
  cancel: (id: number) => call(sidecar.request<{ status: string }>('friends_cancel', { id })),
  remove: (handle: string) => call(sidecar.request<{ status: string }>('friends_remove', { handle })),
  block: (handle: string) => call(sidecar.request<{ status: string }>('friends_block', { handle })),
  unblock: (handle: string) => call(sidecar.request<{ status: string }>('friends_unblock', { handle })),
  appearOffline: (on: boolean) => call(sidecar.request<{ appear_offline: boolean }>('friends_appear_offline', { on })),
  setSettings: (p: { shareGames?: boolean; chatEnabled?: boolean }) => sidecar.request<FriendsStatus>('friends_set_settings', p),
  linkLichess: () => call(sidecar.request<{ site: 'lichess'; username: string; verified: boolean }>('friends_link_lichess')),
  chesscomStart: (username: string) =>
    call(sidecar.request<ChesscomLink & { site: 'chesscom'; username: string; code: string; field: string; expires: number }>('friends_chesscom_start', { username })),
  /** Check / Check now: one check of the pending link */
  chesscomVerify: (username: string) => call(sidecar.request<ChesscomLink>('friends_chesscom_verify', { username })),
  chesscomLink: () => sidecar.request<ChesscomLink>('friends_chesscom_link'),
  chesscomCancel: () => call(sidecar.request<ChesscomLink>('friends_chesscom_cancel')),
  /** the sidecar writes the recovery code to the path the save dialog chose (BETA-5 B) */
  saveRecovery: (path: string) => call(sidecar.request<{ path: string }>('friends_save_recovery', { path })),
  unlink: (site: Site) => call(sidecar.request<{ status: string }>('friends_unlink', { site })),
  deleteAccount: () => call(sidecar.request<{ deleted: boolean; friendGamesDeleted?: number }>('friends_delete_account')),
  profile: (handle: string, mine: Mine, recentLimit = 10, recentOffset = 0, refresh = true) =>
    call(sidecar.request<Profile>('friends_profile', { handle, mine, recentLimit, recentOffset, refresh })),
  refresh: (handle: string, older = false) => sidecar.request<{ started: boolean }>('friends_refresh', { handle, older }),
  game: (id: number) => sidecar.request<FriendGame>('friends_game', { id }),
}
