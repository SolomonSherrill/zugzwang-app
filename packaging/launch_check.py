#!/usr/bin/env python3
"""Launch the built app and confirm its window and its sidecar start (BETA items 7, VERIFY).

    python packaging/launch_check.py --exe <app executable> [--timeout 120]

Starts the app as a user would (no environment overrides, so it uses the real per-user
data folder), then polls until all of these hold, or fails at the timeout:

  1. a window owned by the app is on screen (Windows: the process's `MainWindowTitle`;
     macOS: CoreGraphics' window list, via a tiny Swift script — no permission needed
     for owner names);
  2. the sidecar process is running (`zugzwang-sidecar`), spawned by the webview;
  3. the sidecar's log in the per-user data folder says it started, and Stockfish answered
     (`ready` is logged as "engine ready" by `EngineWorker`), with a `stockfish` process up.

Then it closes the app and prints what it saw, with timings. Used by CI on every target;
on macOS also by hand (VERIFY in BETA.md).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SWIFT_WINDOWS = r'''
import CoreGraphics
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in list { if let o = w[kCGWindowOwnerName as String] as? String { print(o) } }
'''


def data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "dev.zugzwang.desktop"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Zugzwang"
    return Path.home() / ".local" / "share" / "zugzwang"


def processes() -> str:
    if sys.platform == "win32":
        return subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                              text=True).stdout.lower()
    return subprocess.run(["ps", "-axo", "comm"], capture_output=True, text=True).stdout.lower()


def window_up(name: str) -> bool:
    if sys.platform == "win32":
        ps = (f"(Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
              "Where-Object { $_.MainWindowTitle -ne '' } | Select-Object -First 1)."
              "MainWindowTitle")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True).stdout.strip()
        return bool(out)
    if sys.platform == "darwin":
        out = subprocess.run(["swift", "-e", SWIFT_WINDOWS], capture_output=True,
                             text=True, timeout=120).stdout
        return any(line.strip() == name for line in out.splitlines())
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--name", default="Zugzwang", help="the app process / window owner name")
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args()

    log = data_dir() / "logs" / "sidecar.log"
    start_size = log.stat().st_size if log.exists() else 0
    t0 = time.monotonic()
    proc = subprocess.Popen([a.exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen: dict[str, float] = {}
    try:
        while time.monotonic() - t0 < a.timeout and len(seen) < 4:
            time.sleep(2)
            if proc.poll() is not None:
                raise SystemExit(f"FAIL: the app exited with code {proc.returncode}")
            procs = processes()
            text = ""
            if log.exists():
                with log.open(encoding="utf-8", errors="replace") as fh:
                    fh.seek(start_size)
                    text = fh.read()
            checks = {
                "sidecar process": "zugzwang-sidecar" in procs,
                "sidecar log: started": "sidecar starting" in text,
                "engine ready": "engine ready" in text and "stockfish" in procs,
                "window": "window" in seen or window_up(a.name),
            }
            for k, ok in checks.items():
                if ok and k not in seen:
                    seen[k] = round(time.monotonic() - t0, 1)
                    print(f"  {k}: after {seen[k]} s", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"data folder: {data_dir()}\nlog: {log}")
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace")[start_size:].splitlines()[-12:]
        print("log tail:\n  " + "\n  ".join(tail))
    missing = [k for k in ("window", "sidecar process", "sidecar log: started", "engine ready")
               if k not in seen]
    if missing:
        raise SystemExit(f"FAIL: not seen within {a.timeout:.0f} s: {', '.join(missing)}")
    print("OK: window, sidecar and engine all up")


if __name__ == "__main__":
    main()
