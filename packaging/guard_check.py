"""The live-database guard, checked on the real frozen sidecar (BETA-PUB).

    python packaging/guard_check.py <path to zugzwang-sidecar[.exe]>

Starts the frozen sidecar the way a script would — no `--app`, no `ZUGZWANG_DB`, no
`ZUGZWANG_DATA_DIR` — with HOME (and Windows' profile folders) pointed at an empty temp
folder, so the default data folder it would open is a throwaway one. Passes only if it
exits with status 2, says why, and created nothing there. Then `--app` must open that
folder's database, which proves the refusal is the guard and not a broken build.
`tests/test_live_db_guard.py` checks the same in a checkout."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def default_data_dir(home: Path) -> Path:
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "dev.zugzwang.desktop"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Zugzwang"
    return home / ".local" / "share" / "zugzwang"


def run(exe: str, home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ZUGZWANG_DB", "ZUGZWANG_DATA_DIR")}
    env.update(HOME=str(home), USERPROFILE=str(home),
               LOCALAPPDATA=str(home / "AppData" / "Local"),
               APPDATA=str(home / "AppData" / "Roaming"))
    return subprocess.run([exe, *args], input="", capture_output=True, text=True,
                          timeout=120, env=env)


def main() -> int:
    exe = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        data = default_data_dir(home)
        for args in ((), ("--help",)):
            p = run(exe, home, *args)
            made = sorted(str(x) for x in data.rglob("*")) if data.exists() else []
            print(f"no --app {list(args)}: exit {p.returncode}; "
                  f"stderr: {p.stderr.strip()[-200:]!r}; created: {made}")
            if p.returncode != 2 or "refusing" not in p.stderr or data.exists():
                print("FAIL: the frozen sidecar did not refuse the default database")
                return 1
        p = run(exe, home, "--app")
        ok = p.returncode == 0 and (data / "zugzwang.db").exists()
        print(f"--app: exit {p.returncode}; database created: {(data / 'zugzwang.db').exists()}")
        if not ok:
            print("FAIL: launched as the app, it did not open its database")
            print(p.stderr[-2000:])
            return 1
    print("guard check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
