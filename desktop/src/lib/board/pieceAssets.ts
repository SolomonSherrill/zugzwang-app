/**
 * The piece sets' file URLs (ruling 20), from the SVGs shipped in `src/assets/pieces/<id>/`.
 * Vite turns each into a hashed asset URL; nothing loads from the network.
 */
import { PIECE_FILES, pieceSet, pieceSetVars, type PieceFile, type PieceSetId } from './pieceSets'

const files = import.meta.glob('../../assets/pieces/*/*.svg', { eager: true, query: '?url', import: 'default' }) as Record<
  string,
  string
>

/** URLs of one set's twelve files, by lila's file name (wP … bK). */
export function pieceUrls(id: PieceSetId): Partial<Record<PieceFile, string>> {
  const set = pieceSet(id).id
  const out: Partial<Record<PieceFile, string>> = {}
  for (const f of PIECE_FILES) {
    const url = files[`../../assets/pieces/${set}/${f}.svg`]
    if (url) out[f] = url
  }
  return out
}

/** The board wrapper's CSS variables for a set. */
export function pieceVars(id: PieceSetId): string {
  return pieceSetVars(pieceUrls(id))
}
