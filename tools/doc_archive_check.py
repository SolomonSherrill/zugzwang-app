#!/usr/bin/env python3
"""Proves a split of the big plan documents dropped nothing (TOKENS-2 E, item 8; review/TOKENS.md).

    python3 tools/doc_archive_check.py BASE      # BASE: the commit before the split (or before a later archive pass)

For each document (review/FIXPLAN.md, EXPLANATIONS.md, GAME_REPORT.md, ANALYSIS_ARCHITECTURE.md, ARCHITECTURE.md)
its family is the document plus every file under review/archive/ or architecture/ it links to. Three checks:

1. Lines: every non-blank line of the document at BASE is still in its family now, as many times as it was
   (a multiset: lines may be added, such as a current-state section, never lost).
2. Blocks: each heading block of the document at BASE (a heading to the next heading of any level) is either
   still contiguous, word for word, in one file of the family, or listed as split (its lines are still all
   there by check 1: a table whose done rows moved, a preamble cut in two).
3. References: every FIXPLAN row id (FIXPLAN \x60ID\x60, FIXPLAN row \x60ID\x60, FIXPLAN rows \x60A\x60, \x60B\x60, FIXPLAN ID) and every
   quoted section ("DOC.md \"Title\"", "DOC \"Title\"", "DOC.md §N") written anywhere in the tracked text files
   that resolved against the documents at BASE resolves against the families now. A row id resolves where a
   line holds it in bold or as a table's first cell; a title, where a heading contains it.

Exit 1 on any lost line or newly unresolved reference.
"""
from __future__ import annotations

import collections
import os
import re
import subprocess
import sys

DOCS = ["review/FIXPLAN.md", "EXPLANATIONS.md", "GAME_REPORT.md", "ANALYSIS_ARCHITECTURE.md", "ARCHITECTURE.md"]
NAMES = {os.path.basename(d)[:-3]: d for d in DOCS}
TEXT = (".md", ".py", ".ts", ".svelte", ".sh", ".json", ".txt", ".out", ".rs", ".toml", ".yml", ".yaml")


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout


def at(ref, path):
    try:
        return git("show", "%s:%s" % (ref, path))
    except subprocess.CalledProcessError:
        return ""


def family(doc):
    """The document and the archive or area pages it links to (now)."""
    text = open(doc, encoding="utf-8").read()
    files = {doc: text}
    for m in re.finditer(r"\]\(([^)#\s]+\.md)\)", text):
        p = os.path.normpath(os.path.join(os.path.dirname(doc), m.group(1)))
        if (p.startswith("review/archive/") or p.startswith("architecture/")) and os.path.exists(p):
            files[p] = open(p, encoding="utf-8").read()
    return files


def blocks(text):
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if re.match(r"^#{1,6} ", l)]
    out, starts = [], [0] + heads
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        body = "\n".join(lines[s:e]).strip("\n")
        if body.strip():
            out.append((lines[s] if s in heads else "(preamble)", body))
    return out


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[*\x60_]", "", s)).strip().lower()


def headings(texts):
    return [norm(l.lstrip("#")) for t in texts for l in t.split("\n") if re.match(r"^#{1,6} ", l)]


ROW_REF = re.compile(r"FIXPLAN(?:\.md)?(?: rows?)?[:,]? ((?:\x60[^\x60\n]{1,60}\x60(?:,? (?:and |or )?|/| \+ )?)+)")
TITLE_REF = re.compile(r"\b(" + "|".join(sorted(NAMES, key=len, reverse=True)) +
                       r")(?:\.md)?(?:'s)?,? (?:§ ?)?\"([^\"\n]{3,140})\"")
SECT_REF = re.compile(r"\b(" + "|".join(sorted(NAMES, key=len, reverse=True)) + r")(?:\.md)? §\s?(\d+(?:\.\d+)*)")


BARE_ROW_REF = re.compile(r"FIXPLAN(?:\.md)?(?: rows?)?:? ([A-Z][A-Z0-9]*(?:[-.][A-Z0-9]+)*[a-z]?)\b")


def row_ids(s):
    return [x.strip() for x in re.findall(r"\x60([^\x60\n]{1,60})\x60", s)]


def row_resolves(rid, texts):
    pat = re.compile(r"(\*\*" + re.escape(rid) + r"\*\*|^\| *" + re.escape(rid) + r" *\||^#{1,6} .*" + re.escape(rid) + r")", re.M)
    return any(pat.search(t) for t in texts)


def title_resolves(title, texts):
    n = norm(title)
    return any(n in h for h in headings(texts))


def sect_resolves(num, texts):
    return any(re.match(r"^" + re.escape(num) + r"[. ]", h) for h in headings(texts))


def references(files_text):
    refs = set()
    for path, t in files_text.items():
        for m in ROW_REF.finditer(t):
            for rid in row_ids(m.group(1)):
                refs.add(("row", "FIXPLAN", rid))
        for m in BARE_ROW_REF.finditer(t):
            refs.add(("row", "FIXPLAN", m.group(1)))
        for m in TITLE_REF.finditer(t):
            refs.add(("title", m.group(1), m.group(2)))
        for m in SECT_REF.finditer(t):
            refs.add(("sect", m.group(1), m.group(2)))
    return refs


def resolves(ref, texts_of):
    kind, doc, key = ref
    texts = texts_of(NAMES[doc])
    if kind == "row":
        return row_resolves(key, texts)
    if kind == "title":
        return title_resolves(key, texts)
    return sect_resolves(key, texts)


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    base = argv[0]
    bad = 0
    print("base %s (%s)" % (git("rev-parse", "--short=12", base).strip(), git("log", "-1", "--format=%s", base).strip()[:70]))
    fam = {d: family(d) for d in DOCS}
    for d in DOCS:
        old = at(base, d)
        now = fam[d]
        have = collections.Counter(l for t in now.values() for l in t.split("\n") if l.strip())
        want = collections.Counter(l for l in old.split("\n") if l.strip())
        lost = want - have
        joined = list(now.values())
        contiguous, split = 0, []
        for h, body in blocks(old):
            if any(body in t for t in joined):
                contiguous += 1
            else:
                split.append(h)
        print("%s: %d lines at base (%d non-blank), family now %s; lost %d; blocks contiguous %d, split %d%s" % (
            d, len(old.split("\n")), sum(want.values()), ", ".join(sorted(now)), sum(lost.values()), contiguous,
            len(split), (": " + "; ".join(x[:60] for x in split)) if split else ""))
        for l, n in list(lost.items())[:20]:
            print("    LOST x%d: %s" % (n, l[:160]))
        bad += sum(lost.values())
    # references in every tracked text file now (archives and pages included)
    files = [f for f in git("ls-files").split("\n") if f.endswith(TEXT) and os.path.exists(f)]
    files += [f for f in git("ls-files", "--others", "--exclude-standard").split("\n") if f.endswith(TEXT) and os.path.exists(f)]
    texts = {}
    for f in files:
        try:
            if os.path.getsize(f) < 5_000_000:
                texts[f] = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            pass
    refs = references(texts)
    base_texts = {d: [at(base, d)] for d in DOCS}
    now_texts = {d: list(fam[d].values()) for d in DOCS}
    counts = collections.Counter()
    newly = []
    for r in sorted(refs):
        b = resolves(r, lambda d: base_texts[d])
        n = resolves(r, lambda d: now_texts[d])
        counts[(r[0], b, n)] += 1
        if b and not n:
            newly.append(r)
    for kind in ("row", "title", "sect"):
        print("references %-5s: resolved at base and now %d; newly unresolved %d; unresolved at base (left as they were) %d" % (
            kind, counts[(kind, True, True)], counts[(kind, True, False)],
            counts[(kind, False, False)] + counts[(kind, False, True)]))
    for r in newly:
        print("    NEWLY UNRESOLVED: %s %s %r" % r)
    bad += len(newly)
    print("doc_archive_check: %s" % ("OK" if not bad else "FAILED (%d)" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
