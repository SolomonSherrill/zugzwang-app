#!/usr/bin/env bash
# Put Stockfish 18 at stockfish/stockfish-macos-m1-apple-silicon (gitignored).
#
#   tools/get_stockfish.sh          fetch the official sf_18 release binary (default)
#   tools/get_stockfish.sh build    build it from the upstream sf_18 tag instead
#
# Why pinned: every engine measurement in this repo was taken on Stockfish 18
# (CLAUDE.md, "Every engine measurement so far was taken on Stockfish 18"). A
# different build plays at a different strength and evaluates on a different scale.
#
# Verification:
#   fetch — sha256 must equal RELEASE_SHA256, the hash of the binary the measurements
#           ran on (recorded prefix bc0cac905ecdf214, matched in full 2026-11-06).
#   build — the binary is not byte-identical to the release, so it is checked by
#           behaviour: `bench` must report BENCH_NODES, the signature in the sf_18
#           commit message. The release binary reports the same figure.
# Both: `uci` must answer "Stockfish 18".
#
# Needs: gh (fetch) or git + clang/make (build). macOS Apple Silicon only; another
# platform needs its own release asset and hash.
set -euo pipefail

TAG=sf_18
ASSET=stockfish-macos-m1-apple-silicon
RELEASE_SHA256=bc0cac905ecdf2147fe22055c733bcd999b1e3f7c399fbaf7fb9055786563590
BENCH_NODES=2050811
REPO_URL=https://github.com/official-stockfish/Stockfish

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="$ROOT/stockfish"
DEST="$DEST_DIR/$ASSET"
MODE="${1:-fetch}"

if [[ "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
  echo "error: this script knows only the macOS Apple Silicon build" >&2; exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

case "$MODE" in
  fetch)
    gh release download "$TAG" -R official-stockfish/Stockfish -p "$ASSET.tar" -D "$WORK"
    tar -xf "$WORK/$ASSET.tar" -C "$WORK"
    BIN="$WORK/stockfish/$ASSET"
    got="$(shasum -a 256 "$BIN" | cut -d' ' -f1)"
    if [[ "$got" != "$RELEASE_SHA256" ]]; then
      echo "error: sha256 $got != expected $RELEASE_SHA256" >&2; exit 1
    fi
    echo "sha256 ok: $got"
    ;;
  build)
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" "$REPO_URL" "$WORK/src"
    make -C "$WORK/src/src" -j"$(sysctl -n hw.ncpu)" profile-build ARCH=apple-silicon COMP=clang >"$WORK/build.log" 2>&1 \
      || { tail -20 "$WORK/build.log" >&2; exit 1; }
    BIN="$WORK/src/src/stockfish"
    nodes="$("$BIN" bench 2>&1 | awk -F': *' '/Nodes searched/ {print $2}')"
    if [[ "$nodes" != "$BENCH_NODES" ]]; then
      echo "error: bench $nodes != expected $BENCH_NODES" >&2; exit 1
    fi
    echo "bench ok: $nodes nodes"
    ;;
  *) echo "usage: $0 [fetch|build]" >&2; exit 2 ;;
esac

uci_out="$(printf 'uci\nquit\n' | "$BIN")"
id="${uci_out%%$'\n'*}"
[[ "$id" == "Stockfish 18 "* ]] || { echo "error: binary says '$id'" >&2; exit 1; }

mkdir -p "$DEST_DIR"
install -m 0755 "$BIN" "$DEST"
echo "installed $DEST ($id)"
