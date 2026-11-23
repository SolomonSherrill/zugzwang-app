/** The Worker's entry point. The Workers runtime allows only handlers as this module's exports (and the
 *  Durable Object classes it binds), so the logic and its constants live in app.ts, lobby.ts and game.ts. */
import { handle, type Env } from './app'

export { Lobby } from './lobby'
export { Game } from './game'

export default {
  fetch(req: Request, env: Env): Promise<Response> {
    return handle(req, env)
  },
} satisfies ExportedHandler<Env>
