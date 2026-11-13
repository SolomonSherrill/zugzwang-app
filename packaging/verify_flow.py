#!/usr/bin/env python3
"""Drive a packaged sidecar through a tester's first session and time it (BETA, VERIFY).

    python packaging/verify_flow.py --sidecar <app's sidecar executable> --chesscom <handle>
                                    [--lichess <handle>] [--games 5]

The webview's calls, in its order, against the sidecar it spawns: `ready` (engine found) →
`start_sync` (fetch, then analysis) → wait until N games have a complete run → `cancel_sync`
→ `list_games` → for the newest analysed game `get_game` (the Review screen),
`explain_move` on every analysed ply, `game_report` (the Report tab) → `flag_item` on one
shown line → the flags file read back. Run it with a bare environment (`env -i HOME=<empty>
PATH=/usr/bin:/bin`) to stand in for a machine with no Python, Node or Stockfish. Every
game it reports is named by platform game id (the house rule). Not a GUI test: it proves
the backend the window drives, not the clicks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


class Sidecar:
    def __init__(self, exe: str) -> None:
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                  encoding="utf-8")
        self.events: list[dict] = []
        self.replies: dict[int, dict] = {}
        self.cv = threading.Condition()
        self.n = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.p.stdout:
            m = json.loads(line)
            with self.cv:
                (self.events.append(m) if "event" in m else self.replies.__setitem__(m["id"], m))
                self.cv.notify_all()

    def call(self, method: str, timeout: float = 120, **params):
        self.n += 1
        i = self.n
        self.p.stdin.write(json.dumps({"id": i, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        with self.cv:
            if not self.cv.wait_for(lambda: i in self.replies, timeout):
                raise TimeoutError(method)
            r = self.replies.pop(i)
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error']['message']}")
        return r["result"]

    def wait_event(self, name: str, timeout: float) -> dict:
        with self.cv:
            ok = self.cv.wait_for(lambda: any(e["event"] == name for e in self.events), timeout)
            if not ok:
                raise TimeoutError(name)
            return next(e for e in self.events if e["event"] == name)["data"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", required=True)
    ap.add_argument("--chesscom", default="")
    ap.add_argument("--lichess", default="")
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--depth", type=int, default=14)
    a = ap.parse_args()
    t0 = time.monotonic()
    lap = lambda: f"{time.monotonic() - t0:7.1f} s"  # noqa: E731

    s = Sidecar(a.sidecar)
    ready = s.wait_event("ready", 60)
    print(f"{lap()}  ready: engine ok={ready['ok']} at {ready.get('stockfish')}")
    info = s.call("app_info")
    print(f"{lap()}  app_info: {info['version']} beta={info['beta']} frozen={info['frozen']} "
          f"data={info['dataDir']}")

    s.call("start_sync", lichess=a.lichess, chesscom=a.chesscom, depth=a.depth)
    print(f"{lap()}  start_sync({a.chesscom or a.lichess}, depth {a.depth})")
    fetched_at = None
    while True:
        time.sleep(3)
        st = s.call("sync_status", depth=a.depth)
        src = st["chesscom"] if a.chesscom else st["lichess"]
        if fetched_at is None and src["synced"] and any(
                e["event"] == "sync_progress" and e["data"].get("phase") == "analyzing"
                for e in s.events):
            fetched_at = lap()
            print(f"{fetched_at}  fetched {src['synced']} games; analysis started")
        done = src["synced"] - src["unanalysed"] if src["synced"] else 0
        if fetched_at and done >= a.games:
            print(f"{lap()}  {done} games analysed")
            break
        if any(e["event"] == "sync_error" for e in s.events):
            raise SystemExit(f"sync_error: {[e for e in s.events if e['event'] == 'sync_error']}")
        if time.monotonic() - t0 > 3600:
            raise SystemExit("timeout waiting for analysis")
    s.call("cancel_sync")
    analysed = [g for g in s.call("list_games")["games"] if g["analyzed"]]
    print(f"{lap()}  list_games: {len(analysed)} analysed: "
          + ", ".join(f"{g['source']} {g['externalId']}" for g in analysed))
    ids = [(analysed[0]["id"], s.call("get_game", game_id=analysed[0]["id"]))]
    gid, detail = ids[0]
    ext = analysed[0]["externalId"]
    moves = detail["analysis"]["moves"]
    labels = {}
    for m in moves:
        labels[m["classification"]] = labels.get(m["classification"], 0) + 1
    t = time.monotonic()
    said = 0
    shown = None
    for m in moves:
        r = s.call("explain_move", game_id=gid, ply=m["ply"])
        texts = [c["text"] for c in (r.get("claims") or [])] + \
                [d["text"] for d in (r.get("descriptions") or [])]
        if texts:
            said += 1
            shown = shown or (m["ply"], m["classification"], texts[0])
    print(f"{lap()}  Review: game {gid} (platform {ext}), {len(moves)} plies, labels {labels}; "
          f"{said} plies explained ({(time.monotonic() - t) * 1000 / len(moves):.0f} ms/ply)")
    t = time.monotonic()
    rep = s.call("game_report", game_id=gid)
    print(f"{lap()}  game_report: analysed={rep.get('analysed')}, "
          f"{len(rep.get('lines') or [])} story lines, "
          f"{len((rep.get('moments') or {}).get('shown') or [])} moments "
          f"({(time.monotonic() - t) * 1000:.0f} ms)")
    ply, label, text = shown or (moves[0]["ply"], moves[0]["classification"], "label")
    f = s.call("flag_item", kind="claim", shown=text, note="verify run", game_id=gid,
               ply=ply, label=label)
    rec = json.loads(Path(f["path"]).read_text(encoding="utf-8").splitlines()[-1])
    print(f"{lap()}  flag_item → {f['path']}: platform {rec['platform_game_id']} ply "
          f"{rec['ply']} ({rec['move']}), label {rec['label']}, app {rec['app_version']}, "
          f"classifier {rec['run_classifier_version']}, rules {rec['rule_version']}")
    print(f"{lap()}  log: {info['logPath']} exists={Path(info['logPath']).exists()}")
    s.p.stdin.close()
    s.p.wait(timeout=30)


if __name__ == "__main__":
    main()
