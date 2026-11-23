/** The Worker's entry point. The Workers runtime allows only handlers as this module's exports, so
 *  the logic and its constants live in app.ts. */
import { handle, type Env } from './app'

export default {
  fetch(req: Request, env: Env): Promise<Response> {
    return handle(req, env)
  },
} satisfies ExportedHandler<Env>
