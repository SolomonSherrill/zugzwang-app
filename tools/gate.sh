#!/usr/bin/env bash
# tools/gate.sh [base-ref] — the merge gate in one command (TOKENS-1 item 5, review/TOKENS.md).
#
# Runs, on the COMMITTED tree of this checkout (a worktree is fine), each as sessions ran it:
#   python   .venv/bin/python -m pytest tests/ -q
#   smoke    .venv/bin/python sidecar/smoke_test.py
#   vitest   (desktop) npm test
#   check    (desktop) npm run check
#   cargo    (desktop/src-tauri) cargo test --lib
#   scan     release/export_public.py, then release/scan_public.py over the published files that
#            changed since base-ref (every published file when no base-ref is given)
#   rpcmap   tools/rpc_map.py --check: RPC_MAP.md is what the script writes (TOKENS-2 B)
#   server   (server) npm test and npm run check: the Friends Worker's tests in the local Workers
#            runtime, and tsc (FRIENDS-1 B); npm ci there first when it has no node_modules
#   e2e      .venv/bin/python sidecar/friends_e2e.py: two app identities (real sidecars) against the
#            Worker under `wrangler dev --local` and a local Chess.com/Lichess stand-in, no network
#            (FRIENDS-1 E; in the gate since FRIENDS-1B E, 14 s measured 2026-11-22)
# Full logs go to <main checkout>/.work/gates/<sha>/<check>.log; the summary goes to
# <main checkout>/.work/gates/<sha>.txt and stdout: one line per check (PASS/FAIL, measured counts,
# seconds) and, for a failure, the failing tests with at most 40 lines each. Exit 1 on any failure.
#
# A worktree has no venv, no stockfish/ and no node_modules (all gitignored): the gate uses the main
# checkout's venv, copies stockfish/ in and links desktop/node_modules, as gates have done by hand;
# with no complete node_modules to link it runs npm ci in the worktree's desktop/ (BETA-4 D).
# Environment: GATE_ALLOW_DIRTY=1 runs on a dirty tree (the summary says so); GATE_SCAN_DB=<db>
# picks the database copy the scan draws names and ids from (default: the newest local backup);
# GATE_ONLY="python smoke" runs a subset (the summary says so).
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2
MAIN=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
BASE=${1:-}
SHA=$(git rev-parse --short=12 HEAD)
GATES="$MAIN/.work/gates"
LOGS="$GATES/$SHA"
SUMMARY="$GATES/$SHA.txt"
PY="$MAIN/.venv/bin/python"
ALL="python smoke vitest check cargo scan rpcmap server e2e"
ONLY=${GATE_ONLY:-$ALL}
mkdir -p "$LOGS"
: > "$SUMMARY"
FAILED=0

say() { printf '%s\n' "$*" | tee -a "$SUMMARY"; }
cap() { # cap FILE START [STOP]: at most 40 lines of each block (a block begins at a START line)
  awk -v start="$2" -v stop="${3:-__never_matches__}" '
    $0 ~ stop { exit }
    $0 ~ start { n = 0; on = 1 }
    on { n++; if (n <= 40) print "    " $0; else if (n == 41) print "    ... (block cut at 40 lines)" }' "$1"
}
wanted() { case " $ONLY " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
line() { printf '%-4s  %-6s  %-66s %5ss\n' "$1" "$2" "$3" "$4" | tee -a "$SUMMARY"; }

say "gate $SHA ($(git log -1 --format=%s HEAD | cut -c1-70))"
say "  $ROOT, branch $(git rev-parse --abbrev-ref HEAD), $(date -u +%Y-%m-%dT%H:%M:%SZ), base ${BASE:-none}"
[ "$ONLY" != "$ALL" ] && say "  SUBSET: $ONLY"
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$DIRTY" != "0" ]; then
  if [ "${GATE_ALLOW_DIRTY:-}" = "1" ]; then
    say "  WARNING: $DIRTY uncommitted paths; these results are not the committed tree's"
  else
    say "FAIL  tree    $DIRTY uncommitted paths: commit first (or GATE_ALLOW_DIRTY=1)"
    exit 1
  fi
fi
if [ ! -x "$PY" ]; then say "FAIL  setup   no venv at $PY"; exit 1; fi
if [ ! -e "$ROOT/stockfish" ] && [ -d "$MAIN/stockfish" ]; then
  cp -R "$MAIN/stockfish" "$ROOT/stockfish" && say "  setup: copied stockfish/ from $MAIN"
fi
deps_ok() { # deps_ok NODE_MODULES: every dependency in desktop/package.json is installed there
  "$PY" - "$ROOT/desktop/package.json" "$1" <<'EOF'
import json, os, sys
p = json.load(open(sys.argv[1]))
need = list(p.get("dependencies", {})) + list(p.get("devDependencies", {}))
sys.exit(0 if all(os.path.isfile(os.path.join(sys.argv[2], n, "package.json")) for n in need) else 1)
EOF
}
NM="$ROOT/desktop/node_modules"
if [ -L "$NM" ] && ! deps_ok "$NM"; then rm "$NM" && say "  setup: unlinked desktop/node_modules (it lacks packages desktop/package.json needs)"; fi
if [ ! -e "$NM" ]; then
  for c in "$MAIN/desktop/node_modules" $(ls -td "$MAIN"/.work/*/desktop/node_modules 2>/dev/null); do
    [ -d "$c" ] && [ ! -L "$c" ] && [ "$c" != "$NM" ] && deps_ok "$c" && { ln -s "$c" "$NM"; say "  setup: linked desktop/node_modules to $c"; break; }
  done
fi
# BETA-4 D (FIXPLAN TOOL-GATE-CI): no complete node_modules to link, so install one here, in this
# worktree (never in the main checkout, whose node_modules the owner's dev run uses).
if [ -e "$NM" ] && ! deps_ok "$NM"; then
  if [ "$ROOT" != "$MAIN" ] && [ ! -L "$NM" ]; then rm -rf "$NM"; fi
fi
if [ ! -e "$NM" ]; then
  if [ "$ROOT" = "$MAIN" ]; then
    say "  setup: no node_modules with every package of desktop/package.json: run npm ci in desktop/ (not run in the main checkout)"
  elif (cd "$ROOT/desktop" && npm ci --no-audit --no-fund) > "$LOGS/npm-ci.log" 2>&1; then
    say "  setup: ran npm ci in desktop/ (no complete node_modules to link; log $LOGS/npm-ci.log)"
  else
    say "  setup: npm ci in desktop/ FAILED (log $LOGS/npm-ci.log)"
  fi
fi
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$MAIN/.work/cargo-target}

run() { # run NAME DIR CMD...: CMD in DIR, output to $LOGS/NAME.log; sets RC and SECS
  local name=$1 dir=$2 t0
  shift 2
  t0=$(date +%s)
  ( cd "$dir" && "$@" ) > "$LOGS/$name.log" 2>&1
  RC=$?
  SECS=$(( $(date +%s) - t0 ))
}
strip() { sed -E 's/\x1b\[[0-9;]*m//g; s/ +/ /g; s/^ //'; }

if wanted python; then
  run python "$ROOT" "$PY" -m pytest tests/ -q
  L=$LOGS/python.log
  COUNTS=$(grep -E '^(=+ )?[0-9]+ (passed|failed|error)|^(=+ )?no tests ran' "$L" | tail -1 | sed -E 's/^=+ //; s/ =+$//; s/ in [0-9.]+s.*//')
  if [ $RC -eq 0 ]; then line PASS python "${COUNTS:-?}" "$SECS"; else
    FAILED=1; line FAIL python "${COUNTS:-exit $RC}" "$SECS"
    grep -E '^(FAILED|ERROR) ' "$L" | head -50 | sed 's/^/  /' | tee -a "$SUMMARY"
    cap "$L" '^_{3,} .+ _{3,}$' '(warnings summary|short test summary info) ={3,}$' | tee -a "$SUMMARY"
  fi
fi

if wanted smoke; then
  run smoke "$ROOT" "$PY" sidecar/smoke_test.py
  L=$LOGS/smoke.log
  OK=$(grep -c '^✓' "$L"); BAD=$(grep -c '^✗' "$L")
  if [ $RC -eq 0 ]; then line PASS smoke "$OK checks passed, $BAD failed" "$SECS"; else
    FAILED=1; line FAIL smoke "$OK checks passed, $BAD failed (exit $RC)" "$SECS"
    cap "$L" '^✗' '^(All checks passed|FAILED \()' | tee -a "$SUMMARY"
    grep -E '^FAILED \(' "$L" | sed 's/^/  /' | tee -a "$SUMMARY"
    [ "$BAD" = "0" ] && tail -40 "$L" | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
fi

if wanted vitest; then
  run vitest "$ROOT/desktop" npm test
  L=$LOGS/vitest.log
  F=$(grep -E '^ *Test Files ' "$L" | tail -1 | strip)
  T=$(grep -E '^ *Tests ' "$L" | tail -1 | strip)
  if [ $RC -eq 0 ]; then line PASS vitest "${F:-?}; ${T:-?}" "$SECS"; else
    FAILED=1; line FAIL vitest "${F:-exit $RC}; ${T:-}" "$SECS"
    awk '/Failed (Tests|Suites)/ {on=1} on' "$L" | strip > "$LOGS/vitest.failures"
    if [ -s "$LOGS/vitest.failures" ]; then cap "$LOGS/vitest.failures" '^FAIL ' '^Test Files ' | tee -a "$SUMMARY"
    else tail -40 "$L" | sed 's/^/    /' | tee -a "$SUMMARY"; fi
  fi
fi

if wanted check; then
  run check "$ROOT/desktop" npm run check
  L=$LOGS/check.log
  C=$(grep -E 'svelte-check found|COMPLETED [0-9]+ FILES' "$L" | tail -1 | strip | sed -E 's/.*svelte-check found //; s/^[0-9]+ COMPLETED ([0-9]+) FILES ([0-9]+) ERRORS ([0-9]+) WARNINGS.*/\2 errors and \3 warnings in \1 files/')
  if [ $RC -eq 0 ]; then line PASS check "svelte-check: ${C:-?}; tsc: ok" "$SECS"; else
    FAILED=1; line FAIL check "svelte-check: ${C:-?} (exit $RC)" "$SECS"
    grep -E '(^| )(Error|ERROR|error TS[0-9]+)' "$L" | head -200 | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
fi

if wanted cargo; then
  run cargo "$ROOT/desktop/src-tauri" cargo test --lib
  L=$LOGS/cargo.log
  C=$(grep -E '^test result:' "$L" | awk '{for(i=1;i<NF;i++){if($(i+1) ~ /^passed;?$/)p+=$i; if($(i+1) ~ /^failed;?$/)f+=$i}} END{if(NR) printf "%d passed, %d failed", p, f}')
  if [ $RC -eq 0 ]; then line PASS cargo "${C:-?}" "$SECS"; else
    FAILED=1; line FAIL cargo "${C:-exit $RC}" "$SECS"
    if grep -q '^---- ' "$L"; then cap "$L" '^---- ' '^failures:$' | tee -a "$SUMMARY"
    else grep -E '^error' -A8 "$L" | head -40 | sed 's/^/    /' | tee -a "$SUMMARY"; fi
  fi
fi

if wanted scan; then
  T0=$(date +%s)
  DB=${GATE_SCAN_DB:-$(ls -t "$HOME"/.zugzwang/backups/*.db 2>/dev/null | head -1)}
  EXP=$(mktemp -d "${TMPDIR:-/tmp}/gate_export.XXXXXX") && rmdir "$EXP"
  "$PY" release/export_public.py "$EXP" --ref HEAD > "$LOGS/scan.log" 2>&1
  RC=$?
  SUB="$EXP"
  NOTE="every published file"
  if [ $RC -eq 0 ] && [ -n "$BASE" ]; then
    SUB="$EXP.changed"
    mkdir -p "$SUB"
    git diff --name-only --diff-filter=d "$BASE" HEAD | while IFS= read -r f; do
      if [ -f "$EXP/$f" ]; then mkdir -p "$SUB/$(dirname "$f")" && cp "$EXP/$f" "$SUB/$f"; fi
    done
    NOTE="published, changed since $BASE"
  fi
  if [ $RC -ne 0 ]; then :
  elif [ -z "$DB" ]; then RC=1; echo "no database copy for the scan (set GATE_SCAN_DB, or keep a backup in ~/.zugzwang/backups)" >> "$LOGS/scan.log"
  else "$PY" release/scan_public.py "$SUB" --db "$DB" >> "$LOGS/scan.log" 2>&1; RC=$?; fi
  SECS=$(( $(date +%s) - T0 ))
  L=$LOGS/scan.log
  N=$(grep -E '^scanned [0-9]+ files' "$L" | sed -E 's/^scanned ([0-9]+) files.*/\1/')
  HITS=$(awk '/^[^ ].*: [0-9]+$/ {s += $NF} END {print s+0}' "$L")
  if [ $RC -eq 0 ]; then line PASS scan "${N:-0} files ($NOTE), $HITS findings" "$SECS"; else
    FAILED=1; line FAIL scan "${N:-?} files ($NOTE), $HITS findings (exit $RC)" "$SECS"
    awk '/^[^ ].*: [1-9][0-9]*$/ {print "    " $0; n=0; on=1; next} /^[^ ]/ {on=0} on && n++ < 40 {print "    " $0}' "$L" | tee -a "$SUMMARY"
    grep -vE '^( |$|scanned |exported |[^ ].*: [0-9]+$)' "$L" | head -20 | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
  rm -rf "$EXP" "$EXP.changed" "$EXP.manifest"
fi

if wanted rpcmap; then
  run rpcmap "$ROOT" "$PY" tools/rpc_map.py --check
  L=$LOGS/rpcmap.log
  if [ $RC -eq 0 ]; then line PASS rpcmap "$(tail -1 "$L")" "$SECS"; else
    FAILED=1; line FAIL rpcmap "$(tail -1 "$L")" "$SECS"
    tail -40 "$L" | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
fi

server_deps() { # server/node_modules for the server and e2e checks (gitignored: a worktree has none)
  if [ ! -d "$ROOT/server/node_modules" ]; then
    if (cd "$ROOT/server" && npm ci --no-audit --no-fund) > "$LOGS/npm-ci-server.log" 2>&1; then
      say "  setup: ran npm ci in server/ (log $LOGS/npm-ci-server.log)"
    else
      say "  setup: npm ci in server/ FAILED (log $LOGS/npm-ci-server.log)"
    fi
  fi
}

if wanted server && [ -d "$ROOT/server" ]; then
  server_deps
  run server "$ROOT/server" sh -c 'npm test && npm run check'
  L=$LOGS/server.log
  F=$(grep -E '^ *Test Files ' "$L" | tail -1 | strip)
  T=$(grep -E '^ *Tests ' "$L" | tail -1 | strip)
  if [ $RC -eq 0 ]; then line PASS server "${F:-?}; ${T:-?}; tsc: ok" "$SECS"; else
    FAILED=1; line FAIL server "${F:-exit $RC}; ${T:-}" "$SECS"
    tail -40 "$L" | strip | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
fi

if wanted e2e && [ -d "$ROOT/server" ]; then
  server_deps
  run e2e "$ROOT" "$PY" sidecar/friends_e2e.py
  L=$LOGS/e2e.log
  OK=$(grep -c '^✓' "$L"); BAD=$(grep -c '^✗' "$L")
  if [ $RC -eq 0 ]; then line PASS e2e "$OK checks passed, $BAD failed" "$SECS"; else
    FAILED=1; line FAIL e2e "$OK checks passed, $BAD failed (exit $RC)" "$SECS"
    grep '^✗' "$L" | head -40 | sed 's/^/    /' | tee -a "$SUMMARY"
    [ "$BAD" = "0" ] && tail -40 "$L" | sed 's/^/    /' | tee -a "$SUMMARY"
  fi
fi

if [ $FAILED -eq 0 ]; then say "gate $SHA: GREEN (full logs: $LOGS/)"; else say "gate $SHA: RED (full logs: $LOGS/)"; fi
exit $FAILED
