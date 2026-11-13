# Zugzwang beta — for testers

Thank you for trying Zugzwang. It is a chess app that fetches your games from Lichess or
Chess.com, analyses every move with Stockfish **on your own computer**, and explains what
happened in each game. This is a beta: you will see rough edges and the occasional error —
that is expected, and telling us about them is the point.

What to try: **Review** (open a game from Past Games), the **game report**, **Insights**,
and **Play** against the engine. Puzzles are optional. The opening trainer is switched off
in this beta.

---

## 1. Download

Download from **<https://github.com/SolomonSherrill/zugzwang-app/releases/latest>** (under
**Assets**). Pick the file for your computer:

| Your computer | File |
|---|---|
| Mac with Apple silicon (M1, M2, M3, M4…) | `Zugzwang_<version>_aarch64.dmg` |
| Mac with an Intel processor | `Zugzwang_<version>_x64.dmg` |
| Windows 10 or 11 (64-bit) | `Zugzwang_<version>_x64-setup.exe` |

Not sure which Mac you have? Apple menu → **About This Mac**: "Chip: Apple M…" is Apple
silicon; "Processor: Intel" is Intel. Macs need macOS 11 or later.

## 2. Install and open it (the app is not signed by Apple or Microsoft)

The beta is not paid-signed, so your computer will warn you the first time. This is
expected for this build.

### macOS

1. Open the `.dmg` and drag **Zugzwang** into **Applications**.
2. Open Zugzwang from Applications. macOS says it cannot verify the developer — click
   **Done** (or **Cancel**), not *Move to Bin*.
3. Open **System Settings → Privacy & Security**, scroll to the message about Zugzwang,
   and click **Open Anyway**; confirm with your password. Then open the app again.

If macOS instead says the app "is damaged and can't be opened", run this once in
**Terminal**, then open it again:

```
xattr -dr com.apple.quarantine /Applications/Zugzwang.app
```

### Windows

1. Run `Zugzwang_<version>_x64-setup.exe`.
2. If **"Windows protected your PC"** appears, click **More info**, then **Run anyway**.
3. The installer needs no administrator rights; it installs for your user only. Open
   Zugzwang from the Start menu.

## 3. First run

1. On the Home screen, under **Start with your own games**, type your Lichess and/or
   Chess.com username and click **Connect and analyse my games**.
2. Zugzwang fetches your games, then analyses your **100 most recent** games, newest
   first. Games appear in **Past Games** as soon as they are fetched; each game's review
   appears when its analysis finishes. You can use the app meanwhile. Analysis uses your
   processor, so the fan may run.
3. Older games are not analysed automatically. In **Past Games**, **Analyse more…**
   analyses the next batch (you choose how many, newest first) or all of them.
4. Open a game in **Past Games** → **Review**: move-by-move labels and explanations, and
   the **Report** tab.

Nothing is uploaded anywhere: your games are downloaded from Lichess/Chess.com's public
APIs and everything else happens on your computer. You can change usernames, re-sync and
choose the analysis depth in **Settings**.

## 4. Flag anything that looks wrong

Next to every move label, explanation, comparison and report line there is a small
**⚑**. Click it, type one line about what is wrong or confusing (optional), and press
**Save flag**. Flags are saved in a file on your computer — **nothing is sent**.

To send them: **Settings → About this build → Flags → Show in folder**, and attach
`zugzwang-flags.jsonl` to a message. Each flag records which game and move it was about,
what the screen said, and the app version, so a one-word note is enough.

## 5. If something breaks: the log

**Settings → About this build → Log file → Show in folder** opens the folder with
`sidecar.log`. Please attach it (and say roughly when it happened). It contains your chess
usernames, game ids, and file paths on your computer (which include your account name).

If the app cannot start its backend at all, the log is here:

- macOS: `~/Library/Application Support/Zugzwang/logs/sidecar.log`
  (in Finder: **Go → Go to Folder…** and paste the path)
- Windows: `%LOCALAPPDATA%\dev.zugzwang.desktop\logs\sidecar.log`
  (paste into the File Explorer address bar)

## 6. Updates

When a new beta is out, Zugzwang tells you on launch: "Zugzwang X is available — you have
Y". Click **Update and restart** (or **Later**). Updates are signed; the app refuses one
that is not. Your games and settings are kept. If a new version changes how moves are
labelled, the app re-labels your stored games once, in the background, after making a
backup, and shows its progress at the bottom of the window. You can also check from
**Settings → About this build → Check now**.

## 7. Where your data lives, and uninstalling

| | macOS | Windows |
|---|---|---|
| The app | `/Applications/Zugzwang.app` | `%LOCALAPPDATA%\Zugzwang\` |
| Your games, analysis, settings, log, flags, backups | `~/Library/Application Support/Zugzwang/` | `%LOCALAPPDATA%\dev.zugzwang.desktop\` |
| Connected usernames and display preferences | `~/Library/WebKit/dev.zugzwang.desktop/` | `%LOCALAPPDATA%\dev.zugzwang.desktop\EBWebView\` |

**Uninstall on macOS:** quit Zugzwang, drag it from Applications to the Bin, then delete
the two folders above if you want your data gone too.

**Uninstall on Windows:** Settings → Apps → Installed apps → Zugzwang → Uninstall. Tick
**Delete the application data** to remove your games and settings as well; leave it unticked
to keep them for a later install.

## Licences

Zugzwang is free software under the GNU GPL, version 3 or later; its source is at
<https://github.com/SolomonSherrill/zugzwang-app>. It includes Stockfish 18, free software
under the GNU GPL v3. The licence text, a
link to the exact Stockfish source, and the other components' licences are in
**Settings → About this build → Licences**.
