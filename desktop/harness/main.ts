/**
 * The browser harness's entry (UI-BUILD A5): the real App over a fake sidecar.
 *
 *   ?screen=review&game=main|unanalysed|played|<id>[&ply=N]   open a screen (default home)
 *   ?screen=review&fen=<FEN>                                  Analyse a position
 *   ?screen=review&game=promo, ?state=promotion        promotion positions (promotionHarness.ts)
 *   ?state=<scenario>                                  see fakeSidecar.ts
 *   ?latency=<ms>                                      delay every answer (loading states)
 *   ?cold=1                                            mount the app before the sidecar starts, as
 *                                                      the real app does (FIX-STARTUP; harness/coldStart.ts)
 *   ?spawnMs=<ms>                                      how long the spawn takes (with cold, the window
 *                                                      in which screens ask before the process is up)
 *
 * `window.__harness` exposes the request log so a script can wait for the page to settle.
 */
import { mount } from 'svelte'
import 'chessground/assets/chessground.base.css'
import 'chessground/assets/chessground.cburnett.css'
import '../src/lib/styles/fonts.css'
import '../src/lib/styles/tokens.css'
import '../src/app.css'
import App from '../src/App.svelte'
import { sidecar } from '../src/lib/api'
import { fakeTransport, flagLog, requestLog, type Fixtures } from './fakeSidecar'
import { scenarioHandlers, scenarioReady } from './scenarios'
import { puzzleHandlers, type PuzzleFixtures } from './puzzlesHarness'
import { gamesHandlers, type GamesFixtures } from './gamesHarness'
import { PROMO_GAME_ID, promotionHandlers } from './promotionHarness'

const q = new URLSearchParams(location.search)
const fx = (await (await fetch('/fixtures.json')).json()) as Fixtures
// A game played in the app, with its clocks (UI-BUILD-3 F; review/ui_fixtures/record_played_fixtures.py),
// optional: its Review responses join the fixtures and `game=played` opens it.
const played = (await fetch('/played_fixtures.json')
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)) as { meta: { playedGameId: number }; responses: Record<string, unknown> } | null
if (played) Object.assign(fx.responses, played.responses)
const gameParam = q.get('game')
const gameId =
  gameParam === 'main'
    ? fx.meta.mainGameId
    : gameParam === 'promo'
      ? PROMO_GAME_ID
    : gameParam === 'played' && played
      ? played.meta.playedGameId
    : gameParam === 'unanalysed'
      ? fx.meta.unanalysedGameId
      : gameParam
        ? Number(gameParam)
        : undefined
const scenario = q.get('state') ?? undefined
// Puzzles (UI-BUILD-2 E2): their own fixture file, optional.
const pfx = (await fetch('/puzzles_fixtures.json')
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)) as PuzzleFixtures | null
// Games (UI-BUILD-3 E): its own fixture file, optional.
const gfx = (await fetch('/games_fixtures.json')
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)) as GamesFixtures | null
sidecar.useTransport(
  fakeTransport(fx, {
    scenario,
    latencyMs: Number(q.get('latency') ?? 0),
    handlers: { ...puzzleHandlers(pfx, scenario), ...gamesHandlers(gfx, scenario, fx.meta.mainGameId), ...scenarioHandlers(fx, scenario), ...promotionHandlers(fx, scenario, gameParam) },
    ready: scenarioReady(scenario),
    spawnDelayMs: Number(q.get('spawnMs') ?? 0),
  }),
)
;(window as unknown as { __harness: unknown }).__harness = { requestLog, flagLog, fixtures: fx.meta }
// By default started before mounting, so a screen's first request never meets a sidecar that is
// still starting. That hid FIX-STARTUP: the real app mounts first and App's onMount starts the
// sidecar after the screens' own onMounts have asked. ?cold=1 does it the app's way.
const cold = q.get('cold') === '1'
if (!cold) await sidecar.start()

type Route = 'home' | 'play' | 'games' | 'review' | 'puzzles' | 'trainer' | 'insights' | 'settings'
mount(App, {
  target: document.getElementById('app')!,
  props: {
    initial: {
      route: (q.get('screen') ?? 'home') as Route,
      gameId,
      ply: q.get('ply') != null ? Number(q.get('ply')) : undefined,
      // Analyse a position (UI-BUILD-3 D): ?screen=review&fen=<FEN>
      fen: q.get('fen') ?? undefined,
    },
  },
})
