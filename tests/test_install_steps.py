"""FIX-B9 E (owner, 2026-11-27; BETA.md "FIX-B9"): the Mac install steps in TESTERS.md, the public README and every
release's notes lead with System Settings → Privacy & Security → Open Anyway, say why, and fall back to exactly one
command, on the app alone: nothing broader, ever."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
XATTR = "xattr -dr com.apple.quarantine /Applications/Zugzwang.app"
WHY = "Zugzwang isn't notarized by Apple yet. This is a one-time step; updates install normally afterwards."
BROADER = re.compile(r"spctl|master-disable|sudo |xattr -c|xattr -rc|xattr -cr|/Applications/\*|/Applications\s*$|~/Downloads",
                     re.M)


def _notes(new: str = ""):
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "packaging/release_notes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.notes("v0.1.0-beta.99", "owner/repo", new=new)


def _texts():
    return {"TESTERS.md": (ROOT / "TESTERS.md").read_text(), "README.md": (ROOT / "README.md").read_text(),
            "release notes": _notes()}


@pytest.mark.parametrize("where", ["TESTERS.md", "README.md", "release notes"])
def test_open_anyway_leads_the_why_is_said_and_the_one_fallback_is_exact(where):
    text = _texts()[where]
    assert "System Settings → Privacy & Security → Open Anyway" in text
    assert WHY in text
    assert text.index("Open Anyway") < text.index(XATTR)
    assert re.findall(r"^.*\bxattr\b.*$", text, re.M) == [XATTR]        # the command, once, and nothing else
    assert not BROADER.search(text)


def test_the_notes_carry_the_tag_and_whats_new_only_when_there_is_some():
    with_new = _notes("<!-- a comment -->\n- Fewer misleading explanations.\n")
    assert "## What's new\n\n- Fewer misleading explanations.\n" in with_new
    assert "blob/v0.1.0-beta.99/TESTERS.md" in with_new and "@" not in with_new.replace("@users", "")
    assert "What's new" not in _notes("<!-- only a comment -->\n")


def test_the_ci_draft_uses_these_notes():
    wf = (ROOT / ".github/workflows/beta.yml").read_text()
    assert 'python packaging/release_notes.py "$TAG" "$GITHUB_REPOSITORY" > release-notes.md' in wf
    assert "--notes-file release-notes.md" in wf
