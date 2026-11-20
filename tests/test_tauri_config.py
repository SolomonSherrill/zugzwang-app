"""The Tauri configurations (fix/dev-launch, 2026-11-13).

After the beta merge the owner's dev run could not start its sidecar ("No such file or
directory (os error 2)"). Cause, established by test (src-tauri/src/dev_spawn_test.rs): with
no `app.security.capabilities` list, Tauri enables every file in `capabilities/` (Tauri 2
docs, "Capabilities": "All capabilities inside the capabilities directory are automatically
enabled by default"), so the dev build also loaded `beta.json`, whose `zugzwang-sidecar` entry
points at `$RESOURCE/sidecar/…`; the shell scope takes the first entry with the name.

These checks are static and cheap. The spawn itself is `cargo test` in desktop/src-tauri.
"""
import json
from pathlib import Path

from zugzwang import config as C

TAURI = Path(C.REPO_ROOT) / "desktop" / "src-tauri"

#: The beta's app id. Testers' data folders (Windows: %LOCALAPPDATA%\<id>), WebKit storage
#: and the updater's install target hang on it: it never changes.
BETA_IDENTIFIER = "dev.zugzwang.desktop"


def _load(name: str) -> dict:
    return json.loads((TAURI / name).read_text())


def _merge_patch(target, patch):
    """RFC 7396 JSON Merge Patch, which is how `tauri build --config` merges a file."""
    if not isinstance(patch, dict):
        return patch
    out = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = _merge_patch(out.get(k), v)
    return out


def _beta(os_name: str) -> dict:
    conf = _merge_patch(_load("tauri.conf.json"), _load("tauri.beta.conf.json"))
    return _merge_patch(conf, _load(f"tauri.beta.{os_name}.conf.json"))


def test_beta_identifier_is_frozen():
    for os_name in ("macos", "windows"):
        assert _beta(os_name)["identifier"] == BETA_IDENTIFIER


def test_dev_run_has_its_own_identifier():
    dev = _load("tauri.conf.json")["identifier"]
    assert dev != BETA_IDENTIFIER
    assert not dev.endswith(".app")  # Tauri rejects an id ending in .app on macOS


def test_capabilities_are_listed_explicitly():
    """No list means every capability file loads, which is the 2026-11-13 failure."""
    assert _load("tauri.conf.json")["app"]["security"]["capabilities"] == ["default"]
    for os_name in ("macos", "windows"):
        assert _beta(os_name)["app"]["security"]["capabilities"] == ["beta"]
    files = {json.loads(p.read_text())["identifier"] for p in (TAURI / "capabilities").glob("*.json")}
    assert files == {"default", "beta"}, "a new capability file must be listed by one config"


def test_dev_interpreter_path_names_no_home_directory():
    """The public scan forbids /Users paths; the dev run names its venv through $HOME."""
    cap = _load("capabilities/default.json")
    spawn = next(p for p in cap["permissions"]
                 if isinstance(p, dict) and p["identifier"] == "shell:allow-spawn")
    (entry,) = [e for e in spawn["allow"] if e["name"] == "zugzwang-sidecar"]
    assert entry["cmd"] == "$HOME/zugzwang/.venv/bin/python"
