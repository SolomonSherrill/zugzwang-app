# Zugzwang

A chess app that reviews **your own games**. It fetches them from Lichess or Chess.com,
analyses every move with Stockfish 18 on your computer, labels each move, explains what
went wrong where it can prove it, and writes a short report per game. It also has Play
against the engine and Insights across your games. Nothing is uploaded anywhere.

**Status: beta.** It works, and it has rough edges. Builds are for macOS (Apple silicon and
Intel) and Windows 10/11, unsigned, with automatic updates.

## Testers: start here

Download the latest build from **[Releases](https://github.com/SolomonSherrill/zugzwang-app/releases/latest)**
and follow **[TESTERS.md](TESTERS.md)** — which file to pick, how to open an unsigned app, the
first run, and how to flag anything that looks wrong.

## Building from source

Python 3.12+ (CI uses 3.15), Node 24, and a Rust toolchain.

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python tools/get_stockfish.py --bench                   # Stockfish 18 by sha256; bench 2050811
python -m pytest tests/ -q
cd desktop && npm ci && npm test && npm run check
```

- **The packaged app** (what testers get): `pip install pyinstaller==6.22.3`, then
  `python packaging/build_app.py`. Release builds come from CI
  (`.github/workflows/beta.yml`) on a `v*` tag; the tag is the exact source of that release.
- **The dev run**: `cd desktop && npm run tauri dev`. It spawns `sidecar/main.py` with the
  checkout's `.venv` Python, named in `desktop/src-tauri/capabilities/default.json` as
  `$HOME/zugzwang/.venv/bin/python`; a checkout elsewhere edits that line. The dev run keeps
  its data in `~/.zugzwang`.

## How it is built

A Tauri 2 app: `desktop/` is the Svelte 5 + TypeScript front end with a thin Rust shell;
`sidecar/` is a Python process running the core (`zugzwang/core/`), talking to the window
over newline-delimited JSON on stdio. Games and analysis are stored in SQLite. The packaged
sidecar is frozen with PyInstaller. Move labels come from Stockfish 18 at depth 14, one
thread; the bench signature is checked for every engine build shipped, so a label means the
same on every machine.

## Licence

Copyright (C) 2026 Solomon Sherrill. Zugzwang is free software under the **GNU General
Public License, version 3 or any later version** ([LICENSE](LICENSE)). It bundles Stockfish 18
(GPLv3) and uses python-chess and chessground (GPL-3.0-or-later); the full list is in
[desktop/public/licenses/THIRD-PARTY.txt](desktop/public/licenses/THIRD-PARTY.txt) and in the
app under **Settings → About this build → Licences**.
