import { open, save } from '@tauri-apps/plugin-dialog'

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
  pick('Choose the Lichess puzzle file', [
    // the .zst as Lichess ships it (decompressed as it is read, FIX-B6 B) or the CSV
    { name: 'Puzzle database', extensions: ['zst', 'csv'] },
  ])

/** The save dialog (BETA-5 B): a path, or null when cancelled. The webview cannot write files (a
 *  download link does nothing in Tauri's macOS webview), so the sidecar writes to the path. */
export async function pickSavePath(title: string, defaultPath: string, filters: { name: string; extensions: string[] }[]) {
  const picked = await save({ title, defaultPath, filters })
  return typeof picked === 'string' && picked ? picked : null
}

/** No extension filter: a Unix executable has none, and on macOS the binary may
 *  sit inside a `.app` bundle the user has to navigate into. */
export const pickEngine = () =>
  pick('Locate Stockfish', [{ name: 'All files', extensions: ['*'] }])
