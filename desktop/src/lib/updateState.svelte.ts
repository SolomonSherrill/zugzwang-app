/** Shared between the launch-time update check and Settings (BETA item 8). */
export const updateState = $state<{ lastCheck: string; checkNow: (() => Promise<void>) | null }>({
  lastCheck: '',
  checkNow: null,
})
