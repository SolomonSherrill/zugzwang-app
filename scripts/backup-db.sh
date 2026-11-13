#!/usr/bin/env bash
# Back up the Zugzwang database: a consistent snapshot, verified, timestamped, rotated.
#
#   scripts/backup-db.sh                    local copy into ~/.zugzwang/backups
#   scripts/backup-db.sh /Volumes/SANDISK   off-machine copy into <path>/zugzwang-backups
#
# Environment:
#   ZUGZWANG_DB      database to back up        (default ~/.zugzwang/zugzwang.db)
#   BACKUP_KEEP      how many backups to keep   (default 10; 0 keeps everything)
#
# Why not cp: the database is in WAL mode, so the .db file alone can be missing committed
# pages that still sit in the -wal file, and a copy taken mid-write is torn (W3). sqlite3's
# .backup takes a consistent snapshot through SQLite itself, safe with the app running.
#
# The copy is converted to journal_mode=DELETE so it is one self-contained file that opens
# anywhere (no -wal/-shm needed), then checked: PRAGMA integrity_check must say "ok", and
# the row counts of games, analysis_runs and move_analyses must equal the live database's.
# Only a copy that passes is given its final name; a failed one is deleted and the script
# exits non-zero. settings.json is copied alongside when present.
#
# Local and off-machine copies catch different failures: a bad migration eating data
# (local is enough, and quick to roll back from) versus losing the drive (only an
# off-machine copy survives that).
set -euo pipefail

SRC="${ZUGZWANG_DB:-$HOME/.zugzwang/zugzwang.db}"
KEEP="${BACKUP_KEEP:-10}"
if [[ $# -ge 1 ]]; then
    [[ -d "$1" ]] || { echo "error: destination $1 is not a directory (is the drive mounted?)" >&2; exit 2; }
    DEST="${1%/}/zugzwang-backups"
else
    DEST="$HOME/.zugzwang/backups"
fi
TABLES=(games analysis_runs move_analyses)

[[ -f "$SRC" ]] || { echo "error: no database at $SRC" >&2; exit 2; }
[[ "$KEEP" =~ ^[0-9]+$ ]] || { echo "error: BACKUP_KEEP must be a whole number" >&2; exit 2; }
[[ "$SRC$DEST" != *"'"* ]] || { echo "error: paths containing ' are not supported" >&2; exit 2; }
command -v sqlite3 >/dev/null || { echo "error: sqlite3 not found" >&2; exit 2; }
mkdir -p "$DEST"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/zugzwang-$STAMP.db"
TMP="$OUT.partial"
cleanup_sidecars() {  # SQLite's -shm/-wal/-journal for the temp copy, and macOS's ._ twins on exFAT
    local x
    for x in -journal -wal -shm; do
        rm -f "$TMP$x" "$DEST/._$(basename "$TMP")$x"
    done
}
trap 'rm -f "$TMP" "$DEST/._$(basename "$TMP")"; cleanup_sidecars' EXIT

counts() {  # counts <db>: "games=N analysis_runs=N move_analyses=N"
    local db="$1" t n line=""
    for t in "${TABLES[@]}"; do
        n="$(sqlite3 -readonly "$db" "SELECT count(*) FROM $t;" 2>/dev/null || true)"
        [[ "$n" =~ ^[0-9]+$ ]] || n="UNREADABLE"
        line+="$t=$n "
    done
    echo "${line% }"
}

echo "source:      $SRC"
echo "destination: $DEST"

sqlite3 "$SRC" ".timeout 10000" ".backup '$TMP'"
LIVE="$(counts "$SRC")"
sqlite3 "$TMP" "PRAGMA journal_mode=DELETE;" >/dev/null
cleanup_sidecars   # no data in them once the copy is in rollback mode; macOS can leave an empty -shm

INTEGRITY="$(sqlite3 -readonly "$TMP" "PRAGMA integrity_check;")"
COPY="$(counts "$TMP")"
cleanup_sidecars
echo "integrity:   $(printf '%s\n' "$INTEGRITY" | head -n 5)"
echo "live rows:   $LIVE"
echo "copy rows:   $COPY"

if [[ "$INTEGRITY" != "ok" ]]; then
    echo "FAILED: integrity_check on the copy did not return ok" >&2; exit 1
fi
if [[ "$LIVE$COPY" == *UNREADABLE* ]]; then
    echo "FAILED: a table could not be counted" >&2; exit 1
fi
if [[ "$LIVE" != "$COPY" ]]; then
    echo "FAILED: row counts differ (the app may have written during the backup; run again)" >&2; exit 1
fi

mv "$TMP" "$OUT"
[[ -f "$DEST/._$(basename "$TMP")" ]] && mv "$DEST/._$(basename "$TMP")" "$DEST/._$(basename "$OUT")"
SETTINGS="$(dirname "$SRC")/settings.json"
if [[ -f "$SETTINGS" ]]; then
    cp "$SETTINGS" "$DEST/zugzwang-$STAMP.settings.json"
fi
echo "wrote:       $OUT ($(stat -f %z "$OUT" 2>/dev/null || stat -c %s "$OUT") bytes)"

if [[ "$KEEP" -gt 0 ]]; then
    # Timestamped names sort chronologically; drop all but the newest $KEEP.
    # (BSD head has no negative count, so compute how many to drop.)
    ALL=()
    for f in "$DEST"/zugzwang-*.db; do [[ -f "$f" ]] && ALL+=("$f"); done
    DROP=$(( ${#ALL[@]} - KEEP ))
    i=0
    while [[ $i -lt $DROP ]]; do
        rm -f "${ALL[$i]}" "${ALL[$i]%.db}.settings.json"
        echo "rotated out: ${ALL[$i]}"
        i=$((i + 1))
    done
fi
echo "ok"
