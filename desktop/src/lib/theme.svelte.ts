/** Dark/light theme state, persisted to localStorage (the PyQt app keeps the
 *  same toggle in QSettings). Dark is the default. */

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'zugzwang-theme'

function initial(): ThemeMode {
  const saved = localStorage.getItem(STORAGE_KEY)
  return saved === 'light' ? 'light' : 'dark'
}

export const theme = $state<{ mode: ThemeMode }>({ mode: initial() })

export function applyTheme(): void {
  document.documentElement.dataset.theme = theme.mode
}

export function toggleTheme(): void {
  theme.mode = theme.mode === 'dark' ? 'light' : 'dark'
  localStorage.setItem(STORAGE_KEY, theme.mode)
  applyTheme()
}
