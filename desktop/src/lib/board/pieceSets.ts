/**
 * Piece sets (owner ruling 20, 2026-11-20): five sets from lichess-org/lila `public/piece`,
 * each shipped unmodified under `src/assets/pieces/<id>/` with its LICENSE.txt. The authors and
 * licences are lila's COPYING.md entries, checked 2026-11-20. Never a non-commercial set
 * (CC BY-NC-SA, e.g. alpha): it cannot ship in a GPL app.
 *
 * Pure: the file URLs come from `pieceAssets.ts` (Vite), so this module tests in plain Node.
 */

export type PieceSetId = 'cburnett' | 'merida' | 'chessnut' | 'mpchess' | 'fantasy'

export interface PieceSet {
  id: PieceSetId
  /** as Settings shows it */
  name: string
  author: string
  /** short licence name for the swatch's title and the credit line */
  licence: string
  /** where the files came from */
  source: string
}

const LILA = 'https://github.com/lichess-org/lila/tree/master/public/piece/'

export const PIECE_SETS: PieceSet[] = [
  { id: 'cburnett', name: 'Cburnett', author: 'Colin M.L. Burnett', licence: 'GPLv2+', source: LILA + 'cburnett' },
  { id: 'merida', name: 'Merida', author: 'Armando Hernandez Marroquin', licence: 'GPLv2+', source: LILA + 'merida' },
  { id: 'chessnut', name: 'Chessnut', author: 'Alexis Luengas', licence: 'Apache 2.0', source: LILA + 'chessnut' },
  { id: 'mpchess', name: 'Mpchess', author: 'Maxime Chupin', licence: 'GPLv3+', source: LILA + 'mpchess' },
  { id: 'fantasy', name: 'Fantasy', author: 'Maurizio Monge', licence: 'MIT', source: LILA + 'fantasy' },
]

export const DEFAULT_PIECE_SET: PieceSetId = 'cburnett'

/** Licences a set may carry. A set under anything else (a non-commercial licence above all)
 *  must not be added: the test fails on it. */
export const SHIPPABLE_LICENCES = new Set(['GPLv2+', 'GPLv3+', 'Apache 2.0', 'MIT'])

export function pieceSet(id: string | null | undefined): PieceSet {
  return PIECE_SETS.find((s) => s.id === id) ?? PIECE_SETS[0]
}

/** The twelve files of a set, as lila names them: colour then piece letter. */
export const PIECE_FILES = ['wP', 'wN', 'wB', 'wR', 'wQ', 'wK', 'bP', 'bN', 'bB', 'bR', 'bQ', 'bK'] as const
export type PieceFile = (typeof PIECE_FILES)[number]

const ROLE: Record<string, string> = { P: 'pawn', N: 'knight', B: 'bishop', R: 'rook', Q: 'queen', K: 'king' }

/** The CSS variable a board reads for one piece (chessground's classes: colour and role). */
export function pieceVar(f: PieceFile): string {
  return `--pc-${f[0] === 'w' ? 'white' : 'black'}-${ROLE[f[1]]}`
}

/** The CSS variables a board wrapper sets for a set, from the set's file URLs; a piece with no
 *  URL is left out, so chessground's own cburnett image shows instead of an empty square. */
export function pieceSetVars(urls: Partial<Record<PieceFile, string>>): string {
  return PIECE_FILES.filter((f) => urls[f])
    .map((f) => `${pieceVar(f)}: url("${urls[f]}");`)
    .join(' ')
}

/** The credit line under the sets in Settings (ruling 20: credited). */
export function creditLine(sets: PieceSet[] = PIECE_SETS): string {
  return `Piece sets from Lichess: ${sets.map((s) => `${s.name} by ${s.author} (${s.licence})`).join(', ')}.`
}
