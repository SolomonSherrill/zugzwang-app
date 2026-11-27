"""
Central configuration: paths, palette, constants.
Nothing here depends on Qt — importable from core modules.
"""

import os
import platform
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

#: True inside the packaged app (PyInstaller sets `sys.frozen`), False in a checkout.
FROZEN = bool(getattr(sys, "frozen", False))

APP_DIR = Path(__file__).parent
REPO_ROOT = APP_DIR.parent
ASSETS_DIR = APP_DIR / "assets"
PIECES_DIR = ASSETS_DIR / "pieces"
OPENINGS_DIR = ASSETS_DIR / "openings"
# No opening book ships with the app (BOOK-DL, owner ruling D, 2026-11-19): the user downloads
# one of three from Settings into `<data dir>/books/`, and `core/books.py` says which is in use
# (`books.active_book_path()`, None for no book). The lost `book_mingame3.bin` is not read.
#
# The ply at which the book's coverage ends; the game report uses it to say "the book ends
# here" rather than "the book has no move here". 24 is the cap the books are built to (owner
# ruling B5, 2026-11-19; the old book's measured 20, review/scratch/overhaul_stage0_bookcap.out).
# A position first seen at ply <= 24 can recur later by transposition, so a few book plies lie
# past it (OPENING_DATA.md, "Step 2").
BOOK_HORIZON_PLY = 24
OPENINGS_ECO_DIR = OPENINGS_DIR / "eco"

#: The Windows data folder's name: the beta build's Tauri identifier
#: (desktop/src-tauri/tauri.beta.conf.json; fixed forever: testers' data and updates use it).
WINDOWS_DATA_DIR_NAME = "dev.zugzwang.desktop"


def _user_dir() -> Path:
    """Where the database, settings, logs, backups and flags live (BETA, M4).

    `$ZUGZWANG_DATA_DIR` wins. A checkout keeps `~/.zugzwang` on every OS, so the owner's
    dev run and his database are untouched. The packaged app uses the per-user folder each
    OS expects: `~/Library/Application Support/Zugzwang` on macOS and
    `%LOCALAPPDATA%\\dev.zugzwang.desktop` on Windows — local, not roaming (the database is
    large and belongs to the machine); named by the app identifier because the per-user
    installer puts the program itself in `%LOCALAPPDATA%\\Zugzwang`, and its uninstaller's
    "delete app data" option removes `%LOCALAPPDATA%\\<identifier>` (Tauri's
    `installer.nsi`)."""
    env = os.environ.get("ZUGZWANG_DATA_DIR")
    if env:
        return Path(env)
    if not FROZEN:
        return Path.home() / ".zugzwang"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / WINDOWS_DATA_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Zugzwang"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "zugzwang"


USER_DIR = _user_dir()
DB_PATH = USER_DIR / "zugzwang.db"

# ── Stockfish 18, per OS and CPU (BETA item 1) ───────────────────────────────
# The official sf_18 release asset for each target, and the binary's sha256. Every
# measurement in this repo ran on the arm64 binary (CLAUDE.md, "Every engine measurement
# so far was taken on Stockfish 18"). For Intel Macs and Windows the build that runs on the
# widest range of CPUs is chosen (plain x86-64: no popcnt, AVX or BMI2 requirement); its
# bench signature, asserted in CI, is the arm64 binary's, so it searches identically —
# slower, never differently. `tools/get_stockfish.py` fetches and checks these.
STOCKFISH_BENCH_NODES = 2050811
STOCKFISH_ASSETS: dict[tuple[str, str], dict[str, str]] = {
    ("darwin", "arm64"): {
        "asset": "stockfish-macos-m1-apple-silicon.tar",
        "asset_sha256": "4d77c4aa3ad9bd1ea8111f2ac5a4620fe7ebf998d6893bf828d49ccd579c8cb0",
        "binary": "stockfish-macos-m1-apple-silicon",
        "binary_sha256": "bc0cac905ecdf2147fe22055c733bcd999b1e3f7c399fbaf7fb9055786563590",
    },
    ("darwin", "x86_64"): {
        "asset": "stockfish-macos-x86-64.tar",
        "asset_sha256": "e7d7a2bca13915419d41ac6cb8cedb123dd2ba1c39a22c574df7a2aa3f526592",
        "binary": "stockfish-macos-x86-64",
        "binary_sha256": "b272a010918b4580ac671bbdc111320ed85b7679f7522471bccaa5dba0e7ddc4",
    },
    ("windows", "x86_64"): {
        "asset": "stockfish-windows-x86-64.zip",
        "asset_sha256": "40cc975817e7eee270b03f354810d20956df565420d320f6dd37d454dc81a139",
        "binary": "stockfish-windows-x86-64.exe",
        "binary_sha256": "9bde420202717ce083412027fbfb8c5c935b537591d712be8a8a8bae92f6e8d6",
    },
}
#: The second build shipped for x86-64 (BETA-PUB Q6, owner 2026-11-12: if the widest build
#: is more than 25 % slower than the fastest that runs on the CI machines, ship both and
#: choose at startup by CPU feature, falling back to the wide build). Measured on CI
#: (`tools/engine_speed.py`, BETA.md "Q6"): the wide build takes about +80 % time per game
#: at depth 14. The AVX-512 builds are faster still on an Intel runner but crash on the AMD
#: one, so the second build is AVX2, which ran on every CI machine. Same bench signature.
STOCKFISH_FAST_VARIANT = "avx2"
STOCKFISH_FAST_ASSETS: dict[tuple[str, str], dict[str, str]] = {
    ("darwin", "x86_64"): {
        "asset": "stockfish-macos-x86-64-avx2.tar",
        "asset_sha256": "41d30e0860ad924a6ceb422c3a36eba43bbe5ae87d3310840da50e71c53f35d9",
        "binary": "stockfish-macos-x86-64-avx2",
        "binary_sha256": "8701a8048304a2f17d2912609099d8aebba7eccc6fa3d03a5f6ff540d35a342d",
    },
    ("windows", "x86_64"): {
        "asset": "stockfish-windows-x86-64-avx2.zip",
        "asset_sha256": "6f6c272ebd6ea594377715235c8a7326f75940ef4f4f856f45106028fe6ae900",
        "binary": "stockfish-windows-x86-64-avx2.exe",
        "binary_sha256": "c86215fa1977d53b82ed854540a4c7b025be4cd042276c85ba3de53fb9118911",
    },
}
STOCKFISH_SOURCE_URL = "https://github.com/official-stockfish/Stockfish/tree/sf_18"

#: Zugzwang's own source, published under GPL-3.0-or-later (BETA-PUB Q1/Q5, owner
#: 2026-11-12). Every release is one commit there, tagged `v<version>`, and the release's
#: builds are made from that tag, so the tag is the exact source of the build.
PUBLIC_REPO_URL = "https://github.com/SolomonSherrill/zugzwang-app"


def source_url(version: str | None) -> str:
    """The published source of *version*: its tag, or the repository for a dev run."""
    if version and version[0].isdigit():
        return f"{PUBLIC_REPO_URL}/tree/v{version}"
    return PUBLIC_REPO_URL


def host_target() -> tuple[str, str]:
    """(os, cpu) for the running machine, in STOCKFISH_ASSETS' vocabulary."""
    system = {"Darwin": "darwin", "Windows": "windows"}.get(platform.system(),
                                                            platform.system().lower())
    machine = platform.machine().lower()
    cpu = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    return system, cpu


def _bundled_stockfish() -> Path | None:
    """The engine this build ships for this OS and CPU, or None.

    Packaged: Stockfish is the app's Tauri `externalBin`, installed beside the app's own
    executable without its target triple — `Contents/MacOS/stockfish` on macOS,
    `<install dir>\\stockfish.exe` on Windows — while this sidecar runs from the
    `sidecar/` resource folder (`Contents/Resources/sidecar/`, `<install dir>\\sidecar\\`).
    Checkout: the official binary for this machine under `stockfish/`, then the legacy
    names."""
    exe = ".exe" if sys.platform == "win32" else ""
    if FROZEN:
        here = Path(sys.executable).resolve().parent
        candidates = [here / f"stockfish{exe}", here.parent / f"stockfish{exe}",
                      here.parent.parent / "MacOS" / f"stockfish{exe}"]
    else:
        spec = STOCKFISH_ASSETS.get(host_target())
        candidates = [REPO_ROOT / "stockfish" / spec["binary"]] if spec else []
        candidates.append(REPO_ROOT / "stockfish" / f"stockfish{exe}")
    return next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def _bundled_fast_stockfish() -> Path | None:
    """The AVX2 build shipped beside the wide one on x86-64 (BETA-PUB Q6), or None. Whether
    it is used is decided at startup (`core/engine_choice.py`), never here: packaged, it is
    the second externalBin, `stockfish-avx2` beside `stockfish`; in a checkout, the official
    AVX2 binary under `stockfish/` if `tools/get_stockfish.py --variant avx2` fetched it."""
    exe = ".exe" if sys.platform == "win32" else ""
    name = f"stockfish-{STOCKFISH_FAST_VARIANT}{exe}"
    if FROZEN:
        here = Path(sys.executable).resolve().parent
        candidates = [here / name, here.parent / name, here.parent.parent / "MacOS" / name]
    else:
        spec = STOCKFISH_FAST_ASSETS.get(host_target())
        candidates = [REPO_ROOT / "stockfish" / spec["binary"]] if spec else []
    return next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


BUNDLED_STOCKFISH = _bundled_stockfish()
BUNDLED_FAST_STOCKFISH = _bundled_fast_stockfish()

# ── Palette ───────────────────────────────────────────────────────────────────
# The redesign's tokens (DESIGN.md; design/tokens.json → desktop/src/lib/styles/tokens.css),
# dark only: the light theme went with the redesign (UI-BUILD A6). app.css's legacy names
# resolve to these tokens; tests/test_palette_mirror.py keeps the three in step.

BG_DEEP     = "#101113"   # --bg
BG_SURFACE  = "#16171a"   # --surface
BG_RAISED   = "#1c1d21"   # --raised
ACCENT      = "#ededef"   # --primary (the one filled action per screen)
TEXT        = "#ededef"   # --text
TEXT_MUTED  = "#85858f"   # --text-3
DIVIDER     = "#222327"   # --border
DANGER      = "#f87171"   # --loss

BOARD_LIGHT = "#d9d5cc"   # --board-stone-light (Stone, the default board, ruling 20)
BOARD_DARK  = "#8f897d"   # --board-stone-dark

# ── Time controls ─────────────────────────────────────────────────────────────

# (label, initial_seconds, increment_seconds)
TIME_CONTROLS: list[tuple[str, int, int]] = [
    ("1 + 0  — Bullet",    60,   0),
    ("2 + 1  — Bullet",   120,   1),
    ("3 + 0  — Blitz",    180,   0),
    ("3 + 2  — Blitz",    180,   2),
    ("5 + 0  — Blitz",    300,   0),
    ("5 + 3  — Blitz",    300,   3),
    ("10 + 0 — Rapid",    600,   0),
    ("10 + 5 — Rapid",    600,   5),
    ("15 + 10 — Rapid",   900,  10),
    ("30 + 0 — Classical", 1800, 0),
]
TIME_CONTROL_DEFAULT = 6   # index into TIME_CONTROLS (10+0)

# ── Engine ────────────────────────────────────────────────────────────────────

SKILL_MIN = 0
SKILL_MAX = 20
SKILL_DEFAULT = 10

# Stockfish's own UCI_Elo bounds (engine.cpp). Anything outside is clamped by
# the engine, which would silently flatten the ends of the ladder.
ENGINE_ELO_MIN = 1320
ENGINE_ELO_MAX = 3190

# One think-time for every level, because think-time is not a strength control
# here: under UCI_LimitStrength the engine picks its move at a shallow root
# depth it reaches in microseconds, so 200 ms and 3 s play the same (measured —
# review/scratch/f5_mechanism.py). This value sets the bot's pace, nothing else.
ENGINE_MOVE_TIME_MS = 1000

# Draw offers against Stockfish and the coach (COACH.md ruling 8, owner 2026-11-23): accepted only from this
# full move on, and only when the engine's own evaluation (its last move's search, from its side) does not
# favour it: no mate for itself and at most DRAW_FAVOUR_CP centipawns. 20 cp, a fifth of a pawn, is read as
# level (decided by COACH-1 D, for the owner to confirm).
DRAW_FROM_MOVE = 30
DRAW_FAVOUR_CP = 20

# Which level→Elo ladder a game was played on. Stamped on every locally-played
# game so a stored level can be read honestly later: the number alone does not
# survive a ladder change (old Level 10 was Elo 1800, this one is 2304). This is
# version 1 because it is the first ladder that was *recorded*, not the first
# that existed — games saved before this carry NULL and cannot be mapped here.
ENGINE_LADDER_VERSION = 1

def skill_to_elo(skill: int) -> int | None:
    """UCI_Elo for a level; None at the top level means no strength limit.

    Levels spread evenly across the engine's whole UCI_Elo range. UCI_Elo is the
    only strength knob that does anything: with UCI_LimitStrength on, Stockfish
    derives its internal skill from UCI_Elo and ignores the `Skill Level` option
    outright (`Skill::Skill`, stockfish/src/search.h). That derivation is a
    cubic with no real roots in its derivative, so it is strictly increasing and
    the ladder is monotone by construction.

    These numbers are not human ratings and must never be shown as one — the bot
    finds tactics far above its nominal rating and drops pieces far below it.
    See ARCHITECTURE.md.
    """
    if skill >= SKILL_MAX:
        return None
    span = ENGINE_ELO_MAX - ENGINE_ELO_MIN
    return round(ENGINE_ELO_MIN + skill / (SKILL_MAX - 1) * span)

# ── Analysis ──────────────────────────────────────────────────────────────────

ANALYSIS_DEPTH = 18
ANALYSIS_MULTIPV = 3   # 3 lines needed for brilliant-detection difficulty check
# Half-moves of each engine line stored per ply (STORE-PVCAP, owner ruling 2026-10-23:
# the cap goes up, generous beats tuned). At 6, ARCH-0.3 found 10.2 % of material
# combinations cut before they resolve and 4.3 % pointing the wrong way at the cut; at
# 20, none of 1 681 sampled. The engine's own PV is often shorter (median 13 at depth 14),
# so this is a ceiling, not a length. Display is separate: the review panel shows 6.
ANALYSIS_PV_STORE_LEN = 20

# Bulk analysis (platform sync): shallower depth, sufficient for classification.
# This is the default when the user hasn't chosen a sync-analysis depth preset.
ANALYSIS_BULK_DEPTH = 14
# Bounds for the user-configurable sync-analysis depth. The lower bound keeps
# classification meaningful; the upper bound matches single-game review depth.
ANALYSIS_DEPTH_MIN = 8
ANALYSIS_DEPTH_MAX = ANALYSIS_DEPTH  # 18
# Analyse again (DESIGN.md ruling 7) offers 14, 18 and 24 for one game; the sync clamp above
# (8..18) is unchanged. `rpc_analyze_game` refuses a depth outside 8..24 (UI-BUILD B4).
ANALYSIS_AGAIN_DEPTHS = (14, 18, 24)
ANALYSIS_AGAIN_DEPTH_MAX = 24
# RUNS-DEPTH (owner, 2026-11-20; DESIGN.md "RUNS-DEPTH", rulings 7 and 17): every game's
# **standard run** is at this depth, and every aggregate (Insights, Home, the patterns card,
# the games list's figures) reads only standard runs. A deeper Analyse again run is kept
# beside it. Sync and "Analyse more" always analyse at this depth, whatever a client sends.
ANALYSIS_STANDARD_DEPTH = 14
# Engine resources for every analysis engine (ENG-ALLOC, owner ruling 2026-10-22).
#
# **One thread.** Every analysis path searches to a fixed *depth*, and Stockfish's
# Lazy SMP buys strength at a fixed *time*: extra threads widen the tree, so time to
# depth gets worse. Measured on game 285 (Apple M4): Re-analyse at depth 18 took
# 57.0 s on 1 thread, 93.6 s on 4, 168.9 s on 9 (`review/scratch/engine_config_*.out`).
# A single-threaded search is also the only reproducible one — 20/20 identical scores
# across fresh runs, against 0/20 at 9 threads (`engine_reproducibility.out`).
# Throughput comes from several single-threaded engines side by side instead
# (`ENGINE_BUDGET_CORES`, sidecar `EngineBudget`).
#
# **Hash 16 MB**, Stockfish's own default, set explicitly so every analysis engine
# runs the same configuration. 256 MB measured no different at these depths.
ANALYSIS_THREADS = 1
ANALYSIS_HASH_MB = 16

# Engine death (FIXPLAN VAL-DEATH, approved 2026-10-22). A dead engine is respawned
# after each of these delays in turn until one start succeeds; the search it died on is
# then retried once, and a search that kills it twice is poison. A bulk run stops when
# more than ENGINE_BREAKER_DEATHS deaths fall within its last ENGINE_BREAKER_WINDOW_GAMES
# games — a broken binary or memory pressure is systemic, and retrying it burns hours.
ENGINE_RESPAWN_BACKOFF_S = (0.5, 2.0, 5.0)
ENGINE_BREAKER_DEATHS = 3
ENGINE_BREAKER_WINDOW_GAMES = 50
# A game whose position kills the engine twice is skipped and stays queued, so a
# transient crash gets another chance on a later sync. After this many such runs under
# the same engine version it is a deterministic crash: sync stops queuing it and reports
# it as needing attention (VAL-DEATH-2). A different binary starts the count again.
ENGINE_POISON_MAX_ATTEMPTS = 2


def _performance_cores() -> int:
    """Performance cores on Apple silicon (`hw.perflevel0.physicalcpu`), where the
    efficiency cores are much slower; elsewhere half the logical CPUs, which is the
    physical count on a machine with SMT. Never below 2."""
    if sys.platform == "darwin":        # `sysctl` exists only here (BETA, M7)
        try:
            import subprocess
            out = subprocess.run(
                ["sysctl", "-n", "hw.perflevel0.physicalcpu"],
                capture_output=True, text=True, timeout=2,
            )
            if out.returncode == 0 and out.stdout.strip().isdigit():
                return max(2, int(out.stdout.strip()))
        except Exception:
            pass
    return max(2, (os.cpu_count() or 4) // 2)


# The shared engine budget: how many single-threaded engines may search at once.
# Sized to the performance cores (4 on the M4 this was measured on): two engines
# side by side gave 15.0 games/min at depth 14 against 4.1 for one 9-thread engine,
# at a 15 % cost to live play's nodes per move against 54 %
# (`review/scratch/engine_parallel.out`).
ENGINE_BUDGET_CORES = _performance_cores()

# How many bulk engines may run while **no interactive screen is open** (owner ruling
# 2026-11-07, FIXPLAN ENGINE-BUDGET-M4B). Re-measured on the 10-core M4 (4P + 6E),
# depth 14, one thread each, plies/s: 4 engines 33.89, 8 42.24, 10 42.90 — so 4→8 buys
# 25 % and 8→10 under 2 % (`review/scratch/engine_budget_m4_2026_11.out`). With Play,
# Review or a puzzle open, the reserve is unchanged: bulk gets ENGINE_BUDGET_CORES minus
# what the screen reserves. Never fewer than the performance-core budget, never more than 8.
#
# BETA item 3 (M8): and two logical CPUs left free. The ruling was measured on the M4 (10
# logical: min(8, 10 − 2) = 8, unchanged). On a tester's 4-thread laptop the old
# `min(8, cpu_count)` let idle bulk analysis take every CPU; now it takes the
# performance-core budget, max(2, 4 − 2) = 2.
def _idle_ceiling(cores: int, logical: int | None) -> int:
    return max(cores, min(8, (logical or 8) - 2))


ENGINE_BUDGET_IDLE_CEILING = _idle_ceiling(ENGINE_BUDGET_CORES, os.cpu_count())

# ── Descriptions (ARCH-1, ANALYSIS_ARCHITECTURE.md §3) ───────────────────────

# θ per descriptor: the smallest |played − best| difference, in the descriptor's own
# unit, at which it fires (owner ruling 1, 2026-11-07: a near-identical move shows
# nothing). SET FROM DATA, not by eye (owner, 2026-11-08): on a seeded half of the games
# (tune), θ = the value in 1..8 whose game-clustered 95 % bootstrap lower bound of the
# gradient is highest, among θ with ≥ 30 error-class firings; survival is then judged on
# the other half only (`review/scratch/description_gradient.out`). A θ of 1 marked "only
# θ" is the only value that fired often enough to measure. Set on the 2026-11 corpus,
# which has no book (W20): re-run the script after the backfill.
DESCRIPTION_THETA = {
    "castling_rights": 1,       # rights (only θ: θ2 had < 30 error firings)
    "pawn_shield": 1,           # pawns (only θ)
    "king_ring_attacked": 2,    # squares (θ2 lower bound 1.73 > θ1's 1.63)
    "pawn_structure": 1,        # (kind, square) changes (θ1 1.36 > θ2 1.14)
    "files": 2,                 # file state + heavy piece (θ2 1.36 > θ1 1.23)
    "reach": 7,                 # squares (θ7 1.14 on 65 firings; FAILED on the holdout)
    "no_forward_square": 1,     # squares ahead on B_best (every θ < 1: FAILED)
    "pawn_cover_gone": 1,       # pawns (only θ)
    "undeveloped": 2,           # minors + queen (θ2 1.11 > θ1 0.87; FAILED on the holdout)
}

# Descriptors not shipped. Owner ruling 2026-11-08 under the CORRECTED BAR
# (ANALYSIS_ARCHITECTURE.md, "the standing bar"): a descriptor must beat the move-type
# control and hold within move-type strata, not merely exceed 1.0. Kept: castling_rights
# (D1) and king_ring_attacked (D3), which hold in every split. Dropped: pawn_shield (fails
# within the plies where it can fire), pawn_structure and files (≈1.0 when the best move
# is a capture: the signal is the capture), reach and undeveloped (fail even ruling 3),
# pawn_cover_gone (weak everywhere), no_forward_square (a reversal; moved to GR-WW's
# candidate list, not deleted). `describe(..., all_descriptors=True)` keeps them all for
# measurement. Figures: `review/scratch/description_gradient.out`.
DESCRIPTION_DROPPED = frozenset({
    "pawn_shield", "pawn_structure", "files", "reach", "no_forward_square",
    "pawn_cover_gone", "undeveloped",
})

# ── PV reading (ARCH-2, stage 2) ──────────────────────────────────────────────

# The smallest material gap, in pawns, between the best line's settled end and the
# played line's at which PV reading fires (pv_reading.py). SET FROM DATA (2026-11-08) by
# the project standard: on the seeded tune half, θ in 1..5 with the highest lower bound of
# the gradient's 95 % interval — θ1 2.06, θ2 2.51, θ3 2.67, θ4 2.55, θ5 2.40 — so 3;
# judged on the held-out half: 2.93 [2.79, 3.08], holding within every move-type stratum
# (`review/scratch/pv_reading_measure.out`). No book in the corpus (W20).
PV_MATERIAL_THETA = 3.0

# The approved eval consistency check (owner, 2026-11-08): a PV reading of material is
# emitted only when the stored eval loss is at least this — the cut the evidence was
# measured at (83 % of material firings on `excellent` moves fell under it). Below it the
# engine sees compensation the material count does not, and announcing the loss is false.
PV_CONSISTENCY_MIN_CP = 100

# The October decided-position rule, applied to engine-line text (owner, 2026-11-08):
# no engine-line claim or description when max(p, 1 − p) before the move is at least this
# and the verdict held. Measured 2026-10-21 for the rule layer's sentences
# (`review/scratch/decided_v11.out`: 23.4 % of them at 0.95) and never shipped there; 0.95
# is the layer's own WINNING / LOST line. The scale's ceiling is win_prob's clamp, ~0.9754.
PV_DECIDED_MIN = 0.95

# A claim's line longer than this many half-moves is not printed: the sentence says by
# which move it wins, "by force" (owner, 2026-11-08). A description never summarises: an
# engine-line description whose line would be longer does not exist (sixth round; a forced
# line is trustworthy at any length, an unforced one is not).
PV_PRINT_MAX_PLIES = 6

# ── Move explanations ─────────────────────────────────────────────────────────

# Smallest material swing, in pawns, a finding may call a material win. One pawn
# keeps a bishop-for-knight trade from reading as winning material.
EXPLAIN_MIN_MATERIAL = 1.0
# How many findings stage 3 renders as text. The RPC returns all of them.
EXPLAIN_MAX_RENDERED = 3
# Smallest material swing, in pawns, a motif may call a fork, pin or skewer.
# Deliberately above EXPLAIN_MIN_MATERIAL: winning a pawn does not deserve to be
# named as a tactic, and the extra headroom is what keeps quiet exchanges out.
EXPLAIN_MIN_MOTIF_MATERIAL = 2.0

# ── Platform sync ───────────────────────────────────────────────────────────────

SYNC_MAX_GAMES: int | None = None  # cap on games fetched per platform; None = entire history
SYNC_USER_AGENT = "Zugzwang (open-source chess app; https://github.com/SolomonSherrill/zugzwang-app; contact: privacy@zugzwangapp.com)"

# ── Friends (FRIENDS.md, FRIENDS-1) ──────────────────────────────────────────
#: The Friends server (server/, a Cloudflare Worker), deployed 2026-11-22 at its custom domain
#: (FRIENDS.md ruling V8; server/README.md "Deploy"), for dev and beta builds alike;
#: ZUGZWANG_FRIENDS_URL overrides it (the tests, the end-to-end run).
FRIENDS_SERVER_URL = "https://api.zugzwangapp.com"
#: Friends is on in every build (BETA-5 ruling L9, 2026-11-22: the Privacy policy and the Terms of use
#: are approved, version 1; until then ruling L4 kept it out of packaged builds). The sidecar refuses
#: every friends_ method when this is False; one switch, so a build can turn Friends off in one place.
FRIENDS_ENABLED = True
#: how often the app tells the server it is online, and reads the friends list again
FRIENDS_HEARTBEAT_S = 60
#: a profile older than this refreshes when it is opened (ruling G4)
FRIENDS_STALE_S = 3600
# Settings' username check on Save (UI-BUILD-3 G, ruling 5): seconds each site gets to answer, and
# the check as a whole never runs past this plus a second (a DNS lookup is not covered by the
# socket timeout). Saving does not wait on it: the usernames are saved first.
USERNAME_CHECK_TIMEOUT_S = 5.0
# Below this fraction of plies carrying an [%eval], a game is treated as
# un-analysed and re-run locally with Stockfish instead of trusting evals.
SYNC_MIN_EVAL_COVERAGE = 0.8
# WPL at/under which an eval-classified move is counted "best" (no engine best
# move is available from evals alone, so a near-zero loss stands in for it).
SYNC_EVAL_BEST_WPL = 0.005
# A sync analyses automatically only the pending games among each account's this-many most
# recent games, newest first; older games wait for "Analyse more", in a step the user
# chooses or all (BETA-PUB Q4, owner 2026-11-12). Per account (per source). Also, up to this
# many pending games dated inside the span already analysed (FIX-B8 D, note 12:
# Database.games_pending_for_sync), which no sync analysed before.
SYNC_AUTO_ANALYSE_RECENT = 100

# ── Insights ──────────────────────────────────────────────────────────────────

# Game sources that count as the player's own games for Insights aggregation
# (excludes local games played against Stockfish, which would skew accuracy).
# FRIENDS-2 (ruling G2): games against friends count, with the "friends" source.
INSIGHTS_SOURCES = ("lichess", "chesscom", "imported", "friends")
# An opening must have at least this many games before it appears in the
# opening-performance breakdown.
INSIGHTS_MIN_OPENING_GAMES = 5

# ── Brilliant move detection ───────────────────────────────────────────────────

# BRILLIANT.md "W" (owner, 2026-11-19): B1 "nearly best" — the played move is the stored best or
# a stored line whose win probability is within this of line 1's. B5 (the 2nd and 3rd lines each
# 0.15 worse, BRILLIANT_MIN_GAP_2ND / _3RD) is dropped.
BRILLIANT_NEARLY_BEST_WPL = 0.02
# Positions already this winning cannot produce a brilliant move
BRILLIANT_MAX_WP_BEFORE = 0.90
# BRILLIANT.md "X" (owner, 2026-11-19, X1b): nor can a lost position — desperados and blocks; the
# same cut as BR-E2's X4.
BRILLIANT_MIN_WP_BEFORE = 0.30
# BRILLIANT.md B2 (owner ruling 9, 2026-11-11): not forced — at least this many legal
# moves. The version-2 detector's SACRIFICE_MATERIAL_THRESHOLD and
# BRILLIANT_CAPTURE_COST_CP went with its live engine search (`labelling.brilliant`).
# BR-D (owner, 2026-11-25, BRILLIANT.md "BRIL-1"; classifier version 9): "not the only legal
# move", 5 -> 2.
BRILLIANT_MIN_LEGAL = 2

# ── BRIL-1 switches (owner, 2026-11-25; BRILLIANT.md "BRIL-1"): rules that ADD brilliants are
# built behind a switch, off, and ship only after the owner's read of a seeded 20 (BR-G). ──
# BR-A + BR-C: the 0.90 ceiling and the 0.30 floor are judged on a rating-aware curve
# (`labelling.bound_win_prob`): the mover's expected score from the depth-14 evaluation at his
# rating band. Brilliant only; labels and accuracy keep the Lichess curve.
# ON since classifier version 10 (BRIL-2, owner 2026-11-26): the owner's read of 20 found 9 brilliant,
# 9 borderline and 2 not, below BR-G's 12; shipped as an owner-recorded exception (BRILLIANT.md "BRIL-2").
BRILLIANT_RATING_BOUNDS = True
# The fitted curve (review/scratch/bril1/fit_curve.py, the fit half): rows (lowest rating,
# highest rating, k) with expected score 1 / (1 + exp(-k * cp)), cp clamped as `win_prob`
# clamps it. A rating outside every row, an unknown rating, or a mate score uses the current
# curve (`classification.win_prob`).
BRILLIANT_RATING_CURVE: tuple[tuple[int, int, float], ...] = (
    (100, 399, 0.00094261),
    (400, 499, 0.00250454),
    (500, 599, 0.00198055),
    (600, 699, 0.00214080),
    (700, 799, 0.00274677),
    (800, 899, 0.00267696),
    (900, 999, 0.00272494),
    (1000, 1399, 0.00302786),
)
# BR-E: another piece (not a pawn, not the king, not the one that moved) newly left en prise,
# whose best capture fails the two-ply minimax (`labelling.other_piece_offered`).
# DROPPED (BRIL-2, owner 2026-11-26): 4 of 20 read brilliant; most of the owner's notes say the move
# attacks the queen or a rook, an obvious counter-threat. Kept off; W3's drop stands.
BRILLIANT_OTHER_PIECE = False
# BR-F: soundness by the engine's evaluation (`labelling.eval_sound`), all three checks:
# (1) the mover still a piece down this many plies into the played move's own stored line
# (N, B, R, Q counted, pawns not; read after the mover's own move, so odd: 5 is the mover's
# second move after the reply); (2) the evaluation after the move holds within
# WPL_EXCELLENT of the before-score at a verification search of this depth (Stockfish, one
# thread, the candidates only; the search is not run while labelling, its result is passed
# in); (3) BR-E2's failure shapes (an endgame, a queen offered, the exchange) excluded.
# Rebuilt in BRIL-2 (owner 2026-11-26): also not when the material was already lost, trapped or
# forked (`labelling.already_lost`). ON since classifier version 11 (BRIL-3, owner 2026-11-27): the owner's second
# read (review/reads/BRIL-2-verdicts.md) found 17 of 20 brilliant, past BR-G's 12. A ply whose depth-22 search is not
# stored yet keeps version 10's label; the app's backfill (core/brilliant_backfill.py) runs the search and relabels it.
BRILLIANT_EVAL_SOUND = True
# T1 (BRIL-3, owner 2026-11-27; BRILLIANT.md "BRIL-3"): BR-F's "already lost" also catches a piece lost on the
# opponent's next move after its best retreat, or where it stands (`labelling._trapped_next`). OFF, by the ruling's
# own condition: it excludes 12. Nxb6 but not 18. Nxb5, whose bishop's retreat (Bb3, then ...a4) still has a safe
# square on g8 by the SEE and two-ply tools (review/scratch/bril3/probe_t1.out). It kept every brilliant read.
BRILLIANT_T1 = False
# M1 (BRIL-3, owner 2026-11-27; BRILLIANT.md "BRIL-3"): "The only move that avoids mate." on a brilliant move's
# explanation, only when its stored proof holds (every other legal move, searched at depth 14, gives the opponent a
# forced mate; core/brilliant_backfill.only_move_proof). OFF until the owner reads review/reads/BRIL-3-only-move.md;
# the proofs are computed and stored either way.
ONLY_MOVE_AVOIDS_MATE = False
BRILLIANT_LINE_DOWN_PLIES = 5
BRILLIANT_VERIFY_DEPTH = 22

# ── Move classification colours ───────────────────────────────────────────────

CLASS_COLORS = {   # DESIGN.md, owner ruling 1 (UI-2, at the UI build's start, 2026-11-20)
    "book":       "#c4a57a",
    "brilliant":  "#34d3d3",
    "great":      "#60a5fa",
    "best":       "#4ade80",
    "excellent":  "#4ade80",
    "good":       "#86b89a",
    "inaccuracy": "#facc15",
    "mistake":    "#fb923c",
    "miss":       "#f472b6",
    "blunder":    "#f87171",
}

# ── Puzzle system ─────────────────────────────────────────────────────────────

# A checkout keeps the file at the repo root; the packaged app has no repo, so it looks in
# the data folder (the puzzle screen explains the download and offers a picker, BETA M9).
PUZZLE_CSV_PATH          = (USER_DIR if FROZEN else REPO_ROOT) / "lichess_db_puzzle.csv"
PUZZLE_RATING_DEFAULT    = 800.0
PUZZLE_RD_DEFAULT        = 350.0
PUZZLE_VOLATILITY_DEFAULT = 0.06
PUZZLE_TAU               = 0.5   # Glicko-2 system constant (controls volatility sensitivity)

PUZZLE_RATING_RANGES         = [50, 100, 200, 300]
PUZZLE_RATING_RANGE_DEFAULT  = 1   # index → ±100

PUZZLE_RUSH_TIMES   = [(180, "3 min"), (300, "5 min")]
PUZZLE_SETUP_DELAY_MS   = 600    # pause before opponent setup move plays
PUZZLE_IMPORT_BATCH     = 5_000  # rows per executemany commit
# Lichess's puzzle database, CC0, downloaded in the app (FIX-B6 PZ1; never hosted by us).
PUZZLE_LICHESS_URL        = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
PUZZLE_DOWNLOAD_TIMEOUT_S = 60       # per network read, not for the whole download
# Free disk an import needs, per byte of the file: the new set is built beside the old one, plus
# the write-ahead log. Measured 2026-11-23 (FIX-B6 B) on Lichess's file of 2026-11-01 (309,751,173
# bytes, 1,177,486,537 decompressed, 5,531,622 puzzles kept): the database's peak growth (file + WAL)
# was 1,583,996,232 bytes on a first download and 1,583,081,488 on an update over that set, so
# 5.11 bytes per .zst byte and 1.35 per CSV byte; the factors below add about a quarter.
PUZZLE_DISK_PER_ZST_BYTE  = 6.5
PUZZLE_DISK_PER_CSV_BYTE  = 1.7
PUZZLE_ZST_BYTES_FALLBACK = 400_000_000   # when the server gives no length

# ── Opening Trainer ───────────────────────────────────────────────────────────

TRAINER_WEIGHT_THRESHOLD = 0.10   # accept moves with weight ≥ 10% of top move
TRAINER_OPP_ANIM_MS      = 400    # opponent reply animation duration (ms)
TRAINER_SETUP_DELAY_MS   = 500    # pause before first opponent move when opp goes first

# Difficulty presets: label → threshold_fraction for accepted_book_moves()
# Strict: mainline only; Normal: balanced; Loose: most book moves accepted
TRAINER_DIFFICULTY_PRESETS: list[tuple[str, float]] = [
    ("Strict", 0.30),
    ("Normal", 0.10),
    ("Loose",  0.02),
]
TRAINER_DIFFICULTY_DEFAULT = 1   # index into TRAINER_DIFFICULTY_PRESETS (Normal)

# Curation parameters for curate_family()
TRAINER_CURATION_TARGET_LINES = 30   # binary-search toward this many lines per family
TRAINER_CURATION_DEPTH_MIN    = 6    # minimum half-moves in the line PGN
TRAINER_CURATION_DEPTH_MAX    = 16   # maximum half-moves

# Full-encyclopedia family lobby (name-grouped curation; see openings.family_index).
# Lower depth floor than curate_family so short-mainline systems (London, Torre,
# Trompowsky) keep their natural entry points instead of being filtered away.
TRAINER_FAMILY_DEPTH_MIN      = 4    # minimum half-moves for name-grouped lines
# Adaptive coverage thresholds: try the primary weight floor first; if it yields
# too few lines, drop to the fallback; if still too few, the family is "limited".
#
# Game counts (owner rulings 2026-10-22 and B4, 2026-11-19: 1,500 / 500 kept, read as games):
# the books are weighted by game count (B3), so a floor is how often a move was played in the
# two months, not a floor relative to the corpus. They were tuned in Polyglot units
# (win 2, draw 1) on the lost `book_mingame3.bin`; measured on the games-weighted books they give
# 66 trainable families (OPENING_DATA.md, "Step 2"). A relative floor would make the same line pass or
# fail depending on how many months were indexed, which is a worse failure than the current
# one. A move played 50 times is meaningful evidence whatever the corpus size. Absolute
# weights have the opposite fault: a bigger corpus passes more families under the same
# number (OPENING_DATA.md, stage 0).
TRAINER_FAMILY_PRIMARY_WEIGHT   = 1500
TRAINER_FAMILY_PRIMARY_MIN_LINES = 8
TRAINER_FAMILY_FALLBACK_WEIGHT   = 500
TRAINER_FAMILY_FALLBACK_MIN_LINES = 5
# The moves a family's list row shows (UI-BUILD-3 B2): the longest run of moves at least this
# share of its curated lines play in that order. 0.9 so that a few lines reaching the family by
# another move order do not cut it short (the Italian's four Scotch Gambit lines via 3. d4 of
# 81; measured on the dev run's default book, 2026-11-20).
TRAINER_FAMILY_SHARED_SHARE = 0.9

# Alias map for popular openings whose lines the ECO data files under a different
# top-level name (so name-prefix grouping would otherwise scatter or hide them).
# canonical family name → lowercase substrings; any ECO name containing one is
# reassigned to the canonical family. Checked before the ':'/',' prefix split.
TRAINER_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "London System":          ("london system",),
    "Colle System":           ("colle system", "colle-zukertort"),
    "Torre Attack":           ("torre attack",),
    "Richter-Veresov Attack": ("veresov",),
}

# Per-line mastery thresholds (tunable)
TRAINER_MASTERY_DISTINCT_LINES = 3     # unique book endpoints reached to call a line mastered
TRAINER_MASTERY_MIN_ACCURACY   = 0.75  # best_accuracy floor for mastery

CLASS_GLYPHS = {
    "book":       "☰",    # book/pages
    "brilliant":  "!!",
    "great":      "!",    # exclamation
    "best":       "★",    # star
    "excellent":  "Excellent",   # no emoji (ruling 7 of 2026-11-20, third): text says the word; the app draws the SVG thumbs-up
    "good":       "✓",    # checkmark
    "inaccuracy": "?!",
    "mistake":    "?",
    "miss":       "✗",
    "blunder":    "??",
}
