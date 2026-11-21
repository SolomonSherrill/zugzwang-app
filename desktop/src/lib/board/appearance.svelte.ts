/** Appearance choices (ruling 20), persisted to localStorage like the other UI settings.
 *  Settings → Appearance writes these; every board reads them. */
import { DEFAULT_BOARD_THEME, boardTheme, type BoardThemeId } from './boardThemes'
import { DEFAULT_PIECE_SET, pieceSet, type PieceSetId } from './pieceSets'

const KEY = 'zugzwang.boardTheme'
const PIECES_KEY = 'zugzwang.pieceSet'

function load(): BoardThemeId {
  try {
    return boardTheme(globalThis.localStorage?.getItem(KEY)).id
  } catch {
    return DEFAULT_BOARD_THEME
  }
}

function loadPieces(): PieceSetId {
  try {
    return pieceSet(globalThis.localStorage?.getItem(PIECES_KEY)).id
  } catch {
    return DEFAULT_PIECE_SET
  }
}

export const appearance = $state<{ boardTheme: BoardThemeId; pieceSet: PieceSetId }>({
  boardTheme: load(),
  pieceSet: loadPieces(),
})

export function setBoardTheme(id: BoardThemeId): void {
  appearance.boardTheme = id
  try {
    globalThis.localStorage?.setItem(KEY, id)
  } catch {
    /* private mode: the choice lasts the session */
  }
}

export function setPieceSet(id: PieceSetId): void {
  appearance.pieceSet = pieceSet(id).id
  try {
    globalThis.localStorage?.setItem(PIECES_KEY, appearance.pieceSet)
  } catch {
    /* private mode: the choice lasts the session */
  }
}
