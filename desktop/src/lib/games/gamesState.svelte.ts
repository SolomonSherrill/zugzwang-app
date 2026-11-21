/** The Games screen's filters and place, kept at module scope so they survive opening a game's
 *  review and coming back (the screen unmounts; this does not). */
import { defaultFilters, PAGE, type GamesFilters } from './gamesModel'

export const gamesView = $state<{ filters: GamesFilters; moreOpen: boolean; loaded: number; selected: number; scrollTop: number }>({
  filters: defaultFilters(),
  moreOpen: false,
  loaded: PAGE,
  selected: -1,
  scrollTop: 0,
})

/** Clear every filter and the search; the sort stays. */
export function clearFilters(): void {
  const sort = gamesView.filters.sort
  gamesView.filters = { ...defaultFilters(), sort }
}
