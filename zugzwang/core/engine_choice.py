"""Which bundled Stockfish build to run (BETA-PUB Q6, owner 2026-11-12).

On x86-64 two official sf_18 builds ship: the widest (plain x86-64, runs on any 64-bit x86
CPU) and AVX2 (about 45 % faster per game at depth 14 on the CI machines; BETA.md, "Q6").
Both have the bench signature 2050811, so they search identically and labels do not depend
on the choice — only speed does. Chosen once per process:

1. `ZUGZWANG_ENGINE_BUILD=wide` forces the wide build (a tester's escape hatch).
2. The CPU must report AVX2 with the OS's support for it: macOS `hw.optional.avx2_0`,
   Windows `IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE)`. Unknown is no.
3. The AVX2 build must then finish a short search (`go depth 8`) and answer `bestmove`,
   so an engine killed by an instruction the CPU lacks is caught here, not mid-analysis.

Anything else falls back to the wide build, as the ruling says. Nothing here runs on Apple
silicon, which ships one build.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

#: winnt.h: PF_AVX2_INSTRUCTIONS_AVAILABLE. Windows versions that predate the constant
#: answer FALSE, which falls back to the wide build.
PF_AVX2_INSTRUCTIONS_AVAILABLE = 40


def cpu_has_avx2() -> bool:
    """True only when the CPU and the OS both support AVX2; False when unknown."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.optional.avx2_0"], capture_output=True,
                                 text=True, timeout=5)
            return out.returncode == 0 and out.stdout.strip() == "1"
        if sys.platform == "win32":
            return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(  # type: ignore[attr-defined]
                PF_AVX2_INSTRUCTIONS_AVAILABLE))
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return any(line.startswith("flags") and " avx2" in line for line in f)
    except Exception:
        logger.exception("AVX2 detection failed; using the wide engine build")
        return False


def probe(path: Path, timeout: float = 30) -> bool:
    """The engine answers `uci`, then finishes a depth-8 search from the start position."""
    from .engine_locator import popen_args
    try:
        out = subprocess.run(
            [str(path)], input="uci\nisready\nposition startpos\ngo depth 8\n",
            capture_output=True, text=True, timeout=timeout, **popen_args())
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("engine probe failed for %s: %s", path, exc)
        return False
    ok = "uciok" in out.stdout and "bestmove" in out.stdout
    if not ok:
        logger.warning("engine probe failed for %s: exit %s, %r", path, out.returncode,
                       out.stdout[-200:])
    return ok


@lru_cache(maxsize=8)
def choose(wide: Path | None, fast: Path | None) -> tuple[Path | None, str]:
    """(the build to run, why). Cached per pair: decided once per process."""
    if fast is None:
        return wide, "single build"
    if wide is None:
        return (fast, "AVX2 build (no wide build present)") if cpu_has_avx2() and probe(fast) \
            else (None, "AVX2 build unusable and no wide build present")
    if os.environ.get("ZUGZWANG_ENGINE_BUILD", "").lower() == "wide":
        return wide, "wide build (ZUGZWANG_ENGINE_BUILD=wide)"
    if not cpu_has_avx2():
        return wide, "wide build (the CPU does not report AVX2)"
    if not probe(fast):
        return wide, "wide build (the AVX2 build failed its probe)"
    return fast, "AVX2 build (the CPU reports AVX2)"
