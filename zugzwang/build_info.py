"""What build is running: version, commit, beta flag (BETA).

The packaged app carries `build_info.json` beside this module, written by
`packaging/build_sidecar.py` at build time. A checkout has none and reports itself as a dev
run; its commit is read from git by `provenance.code_commit`, as before.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

_FILE = Path(__file__).parent / "build_info.json"


@functools.lru_cache(maxsize=1)
def info() -> dict:
    """{"version", "commit", "beta", "built_at", "target"}; `version` is "dev" in a checkout."""
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"version": str(data.get("version") or "unknown"),
                    "commit": data.get("commit"), "beta": bool(data.get("beta")),
                    "built_at": data.get("built_at"), "target": data.get("target")}
    except (OSError, ValueError):
        pass
    return {"version": "dev", "commit": None, "beta": False, "built_at": None, "target": None}
