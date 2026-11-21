#!/usr/bin/env bash
# tools/run_status.sh [since-ref] — where a run stands (TOKENS-1 item 4). Bash and git only (no venv),
# so it runs from the orchestrator's Linux VM as well as on the Mac. Prints: main vs origin/main
# (as last fetched; no network), the main checkout's tree, every worktree and branch with
# merged/unmerged into main, the latest gate summary, and screenshots added on main since since-ref.
set -u
MAIN=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd) || exit 2
SINCE=${1:-}
g() { git -C "$MAIN" "$@"; }

# resolve_wt RECORDED: the recorded worktree path under $MAIN, found by dropping leading path components
# (/a/b/repo/.work/wt_a -> $MAIN/b/repo/.work/wt_a, $MAIN/repo/.work/wt_a, $MAIN/.work/wt_a, ...); empty if none.
resolve_wt() {
  local rest=${1#/}
  while [ -n "$rest" ]; do
    [ -d "$MAIN/$rest" ] && { echo "$MAIN/$rest"; return; }
    case "$rest" in */*) rest=${rest#*/} ;; *) rest="" ;; esac
  done
}
# wt_git DIR RECORDED ARGS...: git in a worktree; when the worktree's .git file names an absolute gitdir
# that does not exist here, use its admin dir under the common dir (the one whose gitdir file names RECORDED).
wt_git() {
  local dir=$1 rec=$2; shift 2
  if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then git -C "$dir" "$@"; return; fi
  local cd adm
  cd=$(git -C "$MAIN" rev-parse --path-format=absolute --git-common-dir)
  for adm in "$cd"/worktrees/*; do
    [ "$(cat "$adm/gitdir" 2>/dev/null)" = "$rec/.git" ] && { git --git-dir="$adm" --work-tree="$dir" "$@"; return; }
  done
  return 1
}

echo "== main ($MAIN)"
echo "  main $(g rev-parse --short=12 main) — $(g log -1 --format='%s (%cr)' main | cut -c1-90)"
if g rev-parse -q --verify origin/main >/dev/null; then
  set -- $(g rev-list --left-right --count main...origin/main)
  echo "  vs origin/main $(g rev-parse --short=12 origin/main): $1 ahead, $2 behind (as last fetched)"
else
  echo "  no origin/main ref"
fi
CUR=$(g rev-parse --abbrev-ref HEAD)
N=$(g status --porcelain | wc -l | tr -d ' ')
if [ "$CUR" = "main" ] && [ "$N" = "0" ]; then echo "  checkout: on main, clean"
else echo "  checkout: on $CUR, $N uncommitted paths   <-- CLAUDE.md: must be main and clean"; fi
if [ -f "$MAIN/tools/claude-root-settings.json" ]; then
  if cmp -s "$MAIN/tools/claude-root-settings.json" "$MAIN/.claude/settings.json" 2>/dev/null; then
    echo "  instruction-file exclusions (.claude/settings.json): installed"
  else
    echo "  instruction-file exclusions: NOT installed (cp tools/claude-root-settings.json .claude/settings.json)"
  fi
fi

echo "== worktrees (merged = its HEAD is in main)"
g worktree list --porcelain | awk '/^worktree /{p=substr($0,10)} /^HEAD /{h=$2} /^branch /{b=substr($0,19)} /^detached/{b="(detached)"} /^$/{print p"\t"h"\t"b; p=h=b=""} END{if(p!="")print p"\t"h"\t"b}' |
while IFS="$(printf '\t')" read -r path head br; do
  [ "$path" = "$MAIN" ] && continue
  set -- "$path"
  if g merge-base --is-ancestor "$head" main 2>/dev/null; then m="merged  "; else m="UNMERGED"; fi
  shown="${path#$MAIN/}"
  if [ ! -d "$path" ]; then
    # Recorded on another machine (the Mac's absolute path, read from the orchestrator's VM): resolve
    # it against the repo root this script runs from by dropping leading components until one exists.
    r=$(resolve_wt "$path")
    if [ -n "$r" ]; then path="$r"; shown="${r#$MAIN/} (recorded as $shown)"; fi
  fi
  if [ -d "$path" ]; then d=$(wt_git "$path" "$1" status --porcelain 2>/dev/null | wc -l | tr -d ' '); else d="missing"; fi
  printf '  %s %-28s %-12s dirty:%-4s %s\n' "$m" "$br" "$(printf %.12s "$head")" "$d" "$shown"
done

echo "== branches without a worktree"
INWT=$(g worktree list --porcelain | awk '/^branch /{print substr($0,19)}')
UN=""; MC=0
for b in $(g for-each-ref --format='%(refname:short)' refs/heads/); do
  echo "$INWT" | grep -qx "$b" && continue
  [ "$b" = "main" ] && continue
  if g merge-base --is-ancestor "$b" main; then MC=$((MC+1)); else UN="$UN $b"; fi
done
echo "  merged into main: $MC"
echo "  unmerged:${UN:- none}" | fold -s -w 110 | sed '2,$s/^/    /'

echo "== latest gate summary"
LAST=$(ls -t "$MAIN"/.work/gates/*.txt 2>/dev/null | head -1)
if [ -n "$LAST" ]; then
  echo "  ($LAST)"
  sed 's/^/  /' "$LAST"
else
  echo "  none in $MAIN/.work/gates"
fi

echo "== screenshots added on main since ${SINCE:-<no ref given>}"
if [ -n "$SINCE" ]; then
  S=$(g diff --name-only --diff-filter=A "$SINCE" main -- '*.png' '*.jpg' '*.jpeg' '*.webp')
  if [ -n "$S" ]; then echo "$S" | sed 's/^/  /'; echo "  ($(echo "$S" | wc -l | tr -d ' ') files)"; else echo "  none"; fi
else
  echo "  (pass a ref, for example the commit the run started from)"
fi
