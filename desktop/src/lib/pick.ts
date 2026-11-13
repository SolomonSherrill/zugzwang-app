import { open } from '@tauri-apps/plugin-dialog'

/** Normalise the dialog's three outcomes to two.
 *
 * `open` returns `string | string[] | null` depending on options; with
 * `multiple: false` it is `string | null`, but the type does not say so. Every
 * caller here wants one path or nothing, so the narrowing lives in one place
 * rather than at three call sites. */
async function pick(title: string, filters: { name: string; extensions: string[] }[]) {
  const picked = await open({ title, multiple: false, directory: false, filters })
  return typeof picked === 'string' ? picked : null
}

export const pickPgn = () =>
  pick('Import PGN', [{ name: 'PGN', extensions: ['pgn'] }])

export const pickPuzzleCsv = () =>
  pick('Locate the Lichess puzzle CSV', [
    // `.zst` is offered because that is how Lichess ships the file; the importer
    // cannot read it, so picking one must fail with a readable message rather
    // than be silently unselectable in the dialog.
    { name: 'Puzzle database', extensions: ['csv', 'zst'] },
  ])

/** No extension filter: a Unix executable has none, and on macOS the binary may
 *  sit inside a `.app` bundle the user has to navigate into. */
export const pickEngine = () =>
  pick('Locate Stockfish', [{ name: 'All files', extensions: ['*'] }])
