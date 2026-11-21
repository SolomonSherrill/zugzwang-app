/** Build-time facts (BETA item 4). `__BETA__` is injected by `vite.config.ts`: true only
 *  for `vite build --mode beta`, which the packaged build runs. Read it from here, never
 *  from the global, so tests can see one place. */
declare const __BETA__: boolean

export const BETA: boolean = typeof __BETA__ === 'boolean' ? __BETA__ : false

/** Whether the opening trainer (Openings in the sidebar and ⌘K, Home's Train, the trainer
 *  route) is shown. Beta builds hid it until beta.4 (BETA scope item 2: there was no book);
 *  beta.4 shows it in every build (DESIGN.md ruling 13, FIXPLAN BETA-4-TRAINER): with no book
 *  installed the trainer offers the book download (BOOK-DL). One switch, so a later build can
 *  hide it again in one place. */
export const SHOW_TRAINER: boolean = true

/** Only for the local end-to-end updater proof (BETA item 8): a build made with
 *  `ZUGZWANG_UPDATE_AUTOCONFIRM=1` installs an offered update without the click. Never
 *  set in CI or for testers. */
declare const __UPDATE_AUTOCONFIRM__: boolean

export const UPDATE_AUTOCONFIRM: boolean =
  typeof __UPDATE_AUTOCONFIRM__ === 'boolean' ? __UPDATE_AUTOCONFIRM__ : false
