#!/usr/bin/env python3
"""The release's notes, as the public CI's draft release shows them (FIX-B9 E, owner 2026-11-27; BETA.md "FIX-B9").

    python packaging/release_notes.py <tag> <owner/repo>  >  notes.md

`packaging/release_notes.md` with the tag, the repository and `packaging/whats_new.md`'s bullets (as "What's new";
left out when there are none). The Mac steps lead with System Settings → Privacy & Security → Open Anyway; the only
fallback is the one `xattr` command on the app itself (owner, 2026-11-27: nothing broader, ever)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def whats_new(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return ("## What's new\n\n" + "\n".join(lines) + "\n\n") if lines else ""


def notes(tag: str, repo: str, template: str | None = None, new: str | None = None) -> str:
    template = (HERE / "release_notes.md").read_text() if template is None else template
    new = (HERE / "whats_new.md").read_text() if new is None else new
    return (template.replace("@WHATS_NEW@\n", whats_new(new))
            .replace("@TAG@", tag).replace("@REPO@", repo))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.stdout.write(notes(sys.argv[1], sys.argv[2]))
