#!/usr/bin/env python3
"""Token audit over Claude Code's session logs for this project (TOKENS-1, item 1).

Stdlib only. Reads ~/.claude/projects/<project>/*.jsonl and each session's
subagents/*.jsonl, keeps requests inside the window (default: the last 30 days),
and prints AGGREGATES ONLY: counts, token totals, file paths, command heads and
sizes. No conversation text is printed.

    python3 tools/token_audit.py                       # last 30 days, this project
    python3 tools/token_audit.py --days 7 --project-dir ~/.claude/projects/-Users-x
    python3 tools/token_audit.py --out review/scratch/tokens/baseline.out

Definitions (as measured, not estimated):
- a request is one assistant API response, deduplicated by requestId (a response
  is logged once per content block, each record carrying the same usage); the
  '<synthetic>' records a REPL script's inner tool calls leave, all-zero usage,
  are not requests;
- input / cache-write 5m / cache-write 1h / cache-read / output are the API's own
  usage fields summed over those requests;
- a compaction is a system record with subtype compact_boundary;
- an image is an image block in a user message, at top level or inside a tool
  result, i.e. an image the model was sent;
- the startup prefix is the first request's input + cache-write + cache-read:
  everything sent before the first prompt was answered;
- a subagent gap is the time between two consecutive requests of one subagent
  log; over 300 s the 5-minute cache has expired.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

def _main_checkout():
    """The main checkout of the repository this file is in (a worktree's main repo too)."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        common = subprocess.run(["git", "-C", here, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        return os.path.dirname(common)
    except (OSError, subprocess.CalledProcessError):
        return os.path.dirname(here)


MAIN = _main_checkout()
# Claude Code keeps a project's logs under ~/.claude/projects/<its path, '/' and '.' as '-'>.
DEFAULT_PROJECT = os.path.join(os.path.expanduser("~/.claude/projects"), re.sub(r"[/.]", "-", MAIN))
REPO_PREFIXES = (re.compile("^" + re.escape(MAIN) + r"/\.work/[^/]+/"), re.compile("^" + re.escape(MAIN) + "/"))


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def norm_path(p, keep_worktree=False):
    """A path relative to the repository (a worktree's prefix dropped, or kept as '.work/*/')."""
    for rx in REPO_PREFIXES:
        if rx.match(p):
            return (".work/*/" if keep_worktree and rx is REPO_PREFIXES[0] else "") + rx.sub("", p)
    return p


def cmd_head(cmd, n=90):
    one = " ".join(cmd.split())
    return one[:n] + ("…" if len(one) > n else "")


_SKIP_PREFIX = re.compile(r"^\s*(cd\s+\S+\s*(&&|;)\s*|(export\s+)?[A-Za-z_][A-Za-z0-9_]*=\S*\s*(&&|;)?\s*|env\s+|time\s+)+")


def cmd_kind(cmd):
    """A coarse name for a command: its program, plus a sub-command for the multi-tools."""
    c = _SKIP_PREFIX.sub("", cmd.strip())
    toks = c.split()
    if not toks:
        return "(empty)"
    prog = os.path.basename(toks[0].strip("'\""))
    rest = [t for t in toks[1:] if not t.startswith("<<")]
    heredoc = any(t.startswith("<<") for t in toks[1:3])
    if prog in ("git", "npm", "npx", "cargo", "gh", "brew", "pip"):
        sub = next((t for t in rest if not t.startswith("-")), "")
        if prog == "git" and sub == "-C":
            sub = rest[2] if len(rest) > 2 else ""
        return f"{prog} {sub}".strip()
    if prog.startswith("python"):
        if rest[:1] == ["-m"] and len(rest) > 1:
            return f"python -m {rest[1]}"
        if rest[:1] == ["-c"]:
            return "python -c"
        if heredoc and not rest:
            return "python <<heredoc"
        script = next((t for t in rest if not t.startswith("-")), "")
        return f"python {norm_path(script)}".strip()
    return prog


class Session:
    def __init__(self, sid):
        self.sid = sid
        self.req = {}          # requestId -> (ts, usage, is_sub, agent_file)
        self.compactions = 0
        self.images = 0
        self.first_ts = None
        self.first_prefix = None
        self.cwd = None


def load(project_dir, since, until):
    sessions = {}
    reads = collections.defaultdict(lambda: [0, 0])          # path -> [count, bytes]
    bash_out = []                                             # (size, head, via_repl, sid)
    bash_kinds = collections.Counter()
    sub_gaps = []                                             # (gap_s, cache_write_after, sid, agent)
    sub_requests_total = 0
    nested = collections.defaultdict(lambda: [0, 0, set()])  # instruction file -> [loads, chars, sessions]
    files = [(f, False) for f in glob.glob(os.path.join(project_dir, "*.jsonl"))]
    files += [(f, True) for f in glob.glob(os.path.join(project_dir, "*", "subagents", "*.jsonl"))]
    for path, is_sub in sorted(files):
        sid = os.path.basename(os.path.dirname(os.path.dirname(path))) if is_sub else os.path.basename(path)[:-6]
        s = sessions.setdefault(sid, Session(sid))
        tool_inputs = {}
        agent_reqs = {}
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("type")
                ts = parse_ts(o.get("timestamp"))
                if ts is not None and (ts < since or ts > until):
                    continue
                if t == "system" and o.get("subtype") == "compact_boundary":
                    s.compactions += 1
                elif t == "attachment" and (o.get("attachment") or {}).get("type") == "nested_memory":
                    att = o["attachment"]
                    body = att.get("content")
                    body = body.get("content", "") if isinstance(body, dict) else str(body or "")
                    rec = nested[norm_path(str(att.get("path") or "?"), keep_worktree=True)]
                    rec[0] += 1
                    rec[1] += len(body)
                    rec[2].add(sid)
                elif t == "assistant":
                    m = o.get("message") or {}
                    rid = o.get("requestId") or m.get("id")
                    u = m.get("usage")
                    if rid and u and ts and any(tok(u).values()):
                        prev = s.req.get(rid)
                        s.req[rid] = (prev[0] if prev else ts, u, is_sub, path)
                        if is_sub:
                            agent_reqs.setdefault(rid, (ts, u))
                        if not is_sub and (s.first_ts is None or ts < s.first_ts):
                            s.first_ts = ts
                            cc = u.get("cache_creation_input_tokens") or 0
                            s.first_prefix = (u.get("input_tokens") or 0) + cc + (u.get("cache_read_input_tokens") or 0)
                            s.cwd = o.get("cwd")
                    for b in m.get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tool_inputs[b.get("id")] = (b.get("name"), b.get("input") or {})
                elif t == "user":
                    m = o.get("message") or {}
                    cont = m.get("content")
                    tur = o.get("toolUseResult")
                    if isinstance(cont, list):
                        for b in cont:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") == "image":
                                s.images += 1
                            elif b.get("type") == "tool_result":
                                inner = b.get("content")
                                if isinstance(inner, list):
                                    s.images += sum(1 for x in inner if isinstance(x, dict) and x.get("type") == "image")
                                name, inp = tool_inputs.get(b.get("tool_use_id"), (None, {}))
                                if isinstance(inner, list):
                                    got = sum(len(str(x.get("text") or "").encode("utf-8")) for x in inner if isinstance(x, dict))
                                else:
                                    got = len(str(inner or "").encode("utf-8"))
                                if name == "Read" and isinstance(tur, dict) and isinstance(tur.get("file"), dict):
                                    fp = norm_path(str(inp.get("file_path") or tur["file"].get("filePath") or "?"))
                                    r = reads[fp]
                                    r[0] += 1
                                    r[1] += len(str(tur["file"].get("content") or "").encode("utf-8")) or got
                                elif name == "Bash" and isinstance(tur, dict):
                                    cmd = str(inp.get("command") or "")
                                    size = tur.get("persistedOutputSize")
                                    if not isinstance(size, int):
                                        size = len(str(tur.get("stdout") or "").encode("utf-8")) + len(str(tur.get("stderr") or "").encode("utf-8"))
                                    bash_out.append((size, cmd_head(cmd), bool(o.get("isVirtual")), sid, got))
                                    bash_kinds[cmd_kind(cmd)] += 1
        if is_sub and agent_reqs:
            seq = sorted(agent_reqs.values(), key=lambda x: x[0])
            sub_requests_total += len(seq)
            for (t0, _), (t1, u1) in zip(seq, seq[1:]):
                sub_gaps.append(((t1 - t0).total_seconds(), u1.get("cache_creation_input_tokens") or 0,
                                 sid, os.path.basename(path)[:-6]))
    return sessions, reads, bash_out, bash_kinds, sub_gaps, sub_requests_total, nested


def tok(u):
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    total_w = u.get("cache_creation_input_tokens") or 0
    if w5 is None and w1 is None:
        w5, w1 = total_w, 0
    return dict(inp=u.get("input_tokens") or 0, w5=w5 or 0, w1=w1 or 0,
                cr=u.get("cache_read_input_tokens") or 0, out=u.get("output_tokens") or 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-dir", default=DEFAULT_PROJECT)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--now", help="ISO time the window ends (default: now, UTC)")
    ap.add_argument("--out", help="also write the report to this file")
    a = ap.parse_args(argv)
    now = parse_ts(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=a.days)
    sessions, reads, bash_out, bash_kinds, sub_gaps, sub_n, nested = load(a.project_dir, since, now)
    lines = []
    p = lines.append
    p(f"# token_audit.py — {a.project_dir}")
    p(f"# window: {since.isoformat(timespec='seconds')} .. {now.isoformat(timespec='seconds')} ({a.days} days); "
      f"generated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    p("# aggregates only: no conversation text. Tokens are the API's usage fields; a request is one response (requestId).")
    p("")
    hdr = ("session", "start (UTC)", "req", "sub req", "input", "cw 5m", "cw 1h", "cache read", "output",
           "sub share", "compact", "images", "startup prefix", "start cwd")
    p("## Per session (sub share = subagent tokens / all tokens; tokens = input + cache write + cache read + output)")
    p("| " + " | ".join(hdr) + " |")
    p("|" + "---|" * len(hdr))
    T = collections.Counter()
    TS = collections.Counter()
    rows = []
    for s in sessions.values():
        if not s.req:
            continue
        c, cs = collections.Counter(), collections.Counter()
        nsub = 0
        for ts, u, is_sub, _ in s.req.values():
            k = tok(u)
            c.update(k)
            if is_sub:
                cs.update(k)
                nsub += 1
        allt = sum(c.values())
        subt = sum(cs.values())
        T.update(c)
        TS.update(cs)
        T["req"] += len(s.req)
        T["subreq"] += nsub
        T["compact"] += s.compactions
        T["images"] += s.images
        start = min(v[0] for v in s.req.values())
        cwd = norm_path((s.cwd or "?") + "/") or "(repo root)"
        rows.append((start, f"| {s.sid} | {start.strftime('%Y-%m-%d %H:%M')} | {len(s.req)} | {nsub} | {c['inp']:,} | {c['w5']:,} | "
                     f"{c['w1']:,} | {c['cr']:,} | {c['out']:,} | {100 * subt / allt if allt else 0:.1f} % | "
                     f"{s.compactions} | {s.images} | {s.first_prefix if s.first_prefix is not None else '-'} | {cwd} |"))
    for _, r in sorted(rows):
        p(r)
    allT = T["inp"] + T["w5"] + T["w1"] + T["cr"] + T["out"]
    allS = sum(TS.values())
    p(f"| **all ({len(rows)} sessions)** | | {T['req']:,} | {T['subreq']:,} | {T['inp']:,} | {T['w5']:,} | {T['w1']:,} | "
      f"{T['cr']:,} | {T['out']:,} | {100 * allS / allT if allT else 0:.1f} % | {T['compact']} | {T['images']} | | |")
    p("")
    p("## Totals")
    p(f"- requests: {T['req']:,} ({T['subreq']:,} by subagents, {100 * T['subreq'] / max(T['req'], 1):.1f} %)")
    for key, name in (("inp", "uncached input"), ("w5", "cache write 5m"), ("w1", "cache write 1h"), ("cr", "cache read"), ("out", "output")):
        p(f"- {name}: {T[key]:,} (subagents {TS[key]:,}; {100 * TS[key] / max(T[key], 1):.1f} %)")
    p(f"- all tokens: {allT:,}; subagents' share {100 * allS / max(allT, 1):.1f} %")
    p(f"- compactions: {T['compact']}; images sent to the model: {T['images']}")
    p("")
    p("## The 25 files read most (Read tool, direct or from a REPL script; path relative to the repo or its worktree;")
    p("## bytes = the content Read returned)")
    p("| reads | bytes | path |")
    p("|---|---|---|")
    for fp, (n, b) in sorted(reads.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:25]:
        p(f"| {n} | {b:,} | {fp} |")
    tr = sum(v[0] for v in reads.values())
    tb = sum(v[1] for v in reads.values())
    p(f"(all Read calls: {tr:,}, {tb:,} bytes over {len(reads):,} distinct paths)")
    p("")
    p("## The 25 files with the most bytes read")
    p("| bytes | reads | path |")
    p("|---|---|---|")
    for fp, (n, b) in sorted(reads.items(), key=lambda kv: -kv[1][1])[:25]:
        p(f"| {b:,} | {n} | {fp} |")
    p("")
    p("## The 25 largest Bash outputs (bytes of stdout+stderr, or the persisted size; via REPL = run inside a REPL script,")
    p("## whose output reaches the model only as far as the script returns it)")
    p("| output bytes | bytes the model got (direct calls) | via REPL | session | command head |")
    p("|---|---|---|---|---|")
    for size, head, via, sid, got in sorted(bash_out, key=lambda x: -x[0])[:25]:
        p(f"| {size:,} | {'-' if via else f'{got:,}'} | {'yes' if via else 'no'} | {sid[:8]} | {head.replace('|', '\\|')} |")
    p(f"(all Bash calls: {len(bash_out):,}; {sum(x[0] for x in bash_out):,} bytes; "
      f"direct {sum(1 for x in bash_out if not x[2]):,}, via REPL {sum(1 for x in bash_out if x[2]):,}; "
      f"returned to the model directly: {sum(x[4] for x in bash_out if not x[2]):,} bytes)")
    p("")
    p("## The 10 most-run commands (program, plus the sub-command of git/npm/cargo/gh/python -m)")
    p("| runs | command |")
    p("|---|---|")
    for k, n in bash_kinds.most_common(10):
        p(f"| {n} | {k} |")
    p("")
    over = [g for g in sub_gaps if g[0] > 300]
    p("## Subagent request gaps (consecutive requests of one subagent)")
    p(f"- subagent requests: {sub_n:,}; gaps between consecutive requests: {len(sub_gaps):,}")
    p(f"- gaps over 5 minutes: {len(over):,} ({100 * len(over) / max(len(sub_gaps), 1):.1f} %), in "
      f"{len({(g[2], g[3]) for g in over})} of {len({(g[2], g[3]) for g in sub_gaps})} subagents")
    p(f"- gaps over 1 hour: {sum(1 for g in sub_gaps if g[0] > 3600):,}")
    if sub_gaps:
        gs = sorted(g[0] for g in sub_gaps)
        p(f"- gap median {gs[len(gs) // 2]:.0f} s, 99th percentile {gs[int(len(gs) * 0.99)]:.0f} s, longest {gs[-1]:.0f} s")
    p(f"- cache written by the request after a gap over 5 minutes: {sum(g[1] for g in over):,} tokens")
    if over:
        buckets = collections.Counter()
        for g in over:
            m = g[0] / 60
            buckets["5-10 min" if m <= 10 else "10-30 min" if m <= 30 else "30-60 min" if m <= 60 else "> 60 min"] += 1
        p("- by length: " + ", ".join(f"{k} {buckets[k]}" for k in ("5-10 min", "10-30 min", "30-60 min", "> 60 min")))
    p("")
    p("## Instruction files loaded on demand (nested CLAUDE.md, 'nested_memory'); .work/*/ = a worktree's copy,")
    p("## which a session started in the repository root loads a second time when it reads a file there")
    p("| loads | chars | sessions | file |")
    p("|---|---|---|---|")
    for fp, (n, ch, ss) in sorted(nested.items(), key=lambda kv: -kv[1][0]):
        p(f"| {n} | {ch:,} | {len(ss)} | {fp} |")
    if not nested:
        p("| 0 | 0 | 0 | (none) |")
    p("")
    p("## Sessions read (ids)")
    p(", ".join(sorted(s.sid for s in sessions.values() if s.req)))
    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
