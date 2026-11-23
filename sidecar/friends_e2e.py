#!/usr/bin/env python3
"""Friends, end to end and headless (FRIENDS-1 E): two app identities — two real sidecars, each with
its own temp database, data folder and file keystore — against the Friends Worker run locally by
`wrangler dev --local` (Miniflare, a fresh local D1), with a local stand-in for Chess.com and Lichess
(tests/friends_servers.py, synthetic games). Nothing touches the network, a real keychain, a real
database or the owner's screen.

Checks, in order: sign up (both), handle taken, request, accept, presence (online, then Appear
offline), linking (Lichess by its sign-in, Chess.com by the profile code), a friend's profile from
the fixture games (fetched, then figures), Analyse's moves, recovery on a third identity, delete (both)
and every table empty after.

    .venv/bin/python sidecar/friends_e2e.py [--out review/scratch/friends/e2e.out]

Needs server/node_modules (cd server && npm ci). Exit 0 when every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests import friends_fixtures as FX  # noqa: E402
from tests.friends_servers import PlatformServer  # noqa: E402

SIDECAR = REPO / "sidecar" / "main.py"
SERVER = REPO / "server"
results: list[str] = []
failed = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global failed
    results.append(f"{'✓' if ok else '✗'} {name}" + (f"  ({detail})" if detail else ""))
    print(results[-1], flush=True)
    if not ok:
        failed += 1
    return ok


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class App:
    """One app identity: a sidecar with its own data, keystore and the Friends server's address."""

    def __init__(self, name: str, root: Path, env_extra: dict) -> None:
        self.name = name
        d = root / name
        d.mkdir(parents=True, exist_ok=True)     # FRIENDS-2's run restarts an app on its own data
        env = dict(os.environ, ZUGZWANG_DB=str(d / "zugzwang.db"), ZUGZWANG_DATA_DIR=str(d),
                   ZUGZWANG_KEYSTORE="file:" + str(d / "keystore.json"), **env_extra)
        self.proc = subprocess.Popen([sys.executable, str(SIDECAR)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     bufsize=1, env=env)
        self.responses: dict = {}
        self.events: list = []
        self.cond = threading.Condition()
        self.n = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            msg = json.loads(line)
            with self.cond:
                (self.events.append(msg) if "event" in msg else self.responses.__setitem__(msg["id"], msg))
                self.cond.notify_all()

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.n += 1
        rid = self.n
        self.proc.stdin.write(json.dumps({"id": rid, "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        with self.cond:
            if not self.cond.wait_for(lambda: rid in self.responses, timeout):
                raise TimeoutError(f"{self.name}: no answer to {method}")
            msg = self.responses.pop(rid)
        if "error" in msg:
            raise RuntimeError(f"{self.name}: {method}: {msg['error']['message']}")
        return msg["result"]

    def wait_event(self, name: str, pred=lambda d: True, timeout: float = 90) -> dict:
        end = time.monotonic() + timeout
        with self.cond:
            while True:
                for i, ev in enumerate(self.events):
                    if ev["event"] == name and pred(ev["data"]):
                        return self.events.pop(i)["data"]
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"{self.name}: no {name} event")
                self.cond.wait(left)

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()


def d1(persist: Path, sql: str) -> list:
    out = subprocess.run(["npx", "wrangler", "d1", "execute", "zugzwang-friends", "--local",
                          "--persist-to", str(persist), "--json", "--command", sql],
                         cwd=SERVER, capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, WRANGLER_SEND_METRICS="false"))
    return json.loads(out.stdout)[0]["results"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    t0 = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="zz-friends-e2e-"))
    now = datetime.now(timezone.utc)
    sites = PlatformServer()
    # identity A plays on Lichess as a_lichess_demo; B on Chess.com as b_chesscom_demo; they have
    # played each other on Chess.com (A's Chess.com name is in B's games), as S3's head-to-head needs
    sites.chesscom["b_chesscom_demo"] = FX.chesscom_archives(
        "b_chesscom_demo", now, n=80, seed=21, base=sites.base,
        opponents=["a_chesscom_demo", "rook_lift_demo", "pawnstar_demo"])
    sites.chesscom_profile["b_chesscom_demo"] = {"username": "b_chesscom_demo", "location": "Nowhere"}
    sites.lichess["a_lichess_demo"] = FX.lichess_games("a_lichess_demo", now, n=30, seed=22)
    sites.lichess_created["a_lichess_demo"] = 1
    sites.oauth_user = "a_lichess_demo"

    persist = root / "d1"
    env_w = dict(os.environ, WRANGLER_SEND_METRICS="false")
    subprocess.run(["npx", "wrangler", "d1", "migrations", "apply", "zugzwang-friends", "--local",
                    "--persist-to", str(persist)], cwd=SERVER, check=True, capture_output=True, env=env_w)
    port = free_port()
    worker = subprocess.Popen(["npx", "wrangler", "dev", "--local", "--port", str(port), "--ip", "127.0.0.1",
                               "--persist-to", str(persist), "--var", f"LICHESS_API:{sites.base}",
                               "--var", f"CHESSCOM_API:{sites.base}", "--var", "LINK_SECRET:e2e-secret"],
                              cwd=SERVER, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env_w)
    url = f"http://127.0.0.1:{port}"
    apps: list[App] = []
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(url + "/v1/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.5)
        check("the local Worker answers /v1/health", True, url)
        extra = {"ZUGZWANG_FRIENDS_URL": url, "ZUGZWANG_CHESSCOM_API": sites.base,
                 "ZUGZWANG_LICHESS_API": sites.base, "ZUGZWANG_OAUTH_OPENER": "fetch"}
        A, B = App("a", root, extra), App("b", root, extra)
        apps += [A, B]
        for x in (A, B):
            x.wait_event("ready", timeout=60)
        st = A.call("friends_status")
        check("not signed in at first; a file keystore; the server set", not st["signedIn"] and st["configured"]
              and st["keystore"]["kind"] == "file", st["keystore"]["kind"])
        ha, hb = "e2e_alpha", "e2e_bravo"
        check("handle available", A.call("friends_check_handle", {"handle": ha})["available"] is True)
        check("a reserved handle is refused", A.call("friends_check_handle", {"handle": "support"})["reason"] == "reserved")
        no = A.call("friends_signup", {"handle": ha, "ageConfirmed": True, "termsAccepted": False})
        check("sign-up without the Terms box is refused", no.get("error", {}).get("code") == "terms_required")
        sa = A.call("friends_signup", {"handle": ha, "ageConfirmed": True, "termsAccepted": True})
        code_a = sa.get("recoveryCode", "")
        check("A signs up and gets a recovery code", sa.get("handle") == ha and len(code_a) == 44, code_a[:4] + "…")
        sb = B.call("friends_signup", {"handle": hb, "ageConfirmed": True, "termsAccepted": True})
        check("B signs up", sb.get("handle") == hb)
        taken = B.call("friends_check_handle", {"handle": ha.upper()})
        check("A's handle is taken, ignoring case", taken["available"] is False and taken["reason"] == "taken")
        key_a = json.loads((root / "a" / "keystore.json").read_text())
        db_bytes = (root / "a" / "zugzwang.db").read_bytes()
        secret = next(iter(key_a.values()))["identity"]
        check("the key is in the keystore, not the database", secret.encode() not in db_bytes)

        r = A.call("friends_request", {"handle": hb})
        check("A sends B a request", r.get("status") == "sent")
        lb = B.call("friends_list", {"mine": {"chesscom": "b_chesscom_demo"}})
        inc = lb.get("incoming", [])
        check("B sees it", len(inc) == 1 and inc[0]["handle"] == ha)
        acc = B.call("friends_answer", {"id": inc[0]["id"], "accept": True})
        check("B accepts", acc.get("status") == "friends")
        la = A.call("friends_list", {"mine": {"chesscom": "a_chesscom_demo"}})
        fb = next((f for f in la.get("friends", []) if f["handle"] == hb), None)
        check("A's list has B, online (B's heartbeat)", fb is not None and fb["online"] is True,
              f"online={fb and fb['online']}")

        # linking: A by Lichess's sign-in (the opener follows the address headlessly), B by the code
        li = A.call("friends_link_lichess")
        check("A links Lichess by its sign-in", li.get("verified") is True and li.get("username") == "a_lichess_demo")
        check("the Lichess token was revoked after use", not sites.lichess_tokens)
        cs = B.call("friends_chesscom_start", {"username": "b_chesscom_demo"})
        sites.chesscom_profile["b_chesscom_demo"]["location"] = "Here " + cs["code"]
        cv = B.call("friends_chesscom_verify", {"username": "b_chesscom_demo"})
        check("B links Chess.com by the profile code", cv.get("verified") is True)

        # A opens B's profile: no data yet, so it fetches (one request at a time), then shows figures
        p0 = A.call("friends_profile", {"handle": hb, "mine": {"chesscom": "a_chesscom_demo"}})
        check("the profile starts a fetch of B's games", p0.get("data", {}).get("fetching") is True)
        A.wait_event("friend_data", lambda d: d.get("handle") == hb and d.get("state") == "done")
        p = A.call("friends_profile", {"handle": hb, "mine": {"chesscom": "a_chesscom_demo"}})
        n_b = sum(len(v["games"]) for v in sites.chesscom["b_chesscom_demo"].values())
        check("profile: B's games stored and counted", p["recentTotal"] > 0 and p["recentTotal"] <= n_b,
              f"{p['recentTotal']} of {n_b} served")
        check("profile: head-to-head from the linked accounts", p["record"]["games"] > 0, f"{p['record']}")
        check("profile: scouting, endings, results by time control", bool(p["scouting"]["asWhite"]) and
              p["endings"]["games"] == p["recentTotal"] and bool(p["bySpeed"]))
        check("profile: data fresh after the fetch", p["data"]["stale"] is False)
        gid = p["recent"][0]["id"]
        g = A.call("friends_game", {"id": gid})
        check("Analyse gets the game's moves", len(g["moves"]) > 3 and g["startFen"].startswith("rnbqkbnr"))
        a_games = A.call("list_games", {})
        check("B's games are not in A's Games", len(a_games.get("games", [])) == 0)

        # presence: Appear offline hides B
        B.call("friends_appear_offline", {"on": True})
        la2 = A.call("friends_list", {"mine": {}})
        fb2 = next(f for f in la2["friends"] if f["handle"] == hb)
        check("B appears offline to A", fb2["online"] is False and fb2["last_seen"] is None)

        # recovery: a third computer, A's code
        C = App("c", root, extra)
        apps.append(C)
        C.wait_event("ready", timeout=60)
        rc = C.call("friends_recover", {"code": code_a.lower()})
        check("recovery on another computer finds A", rc.get("handle") == ha)
        check("…with the same recovery code", C.call("friends_recovery_code")["code"] == code_a)
        C.close()

        # delete both: no row about either in any table
        tables = ["accounts", "linked_accounts", "friend_requests", "friendships", "blocks", "presence"]
        da = A.call("friends_delete_account")
        db_ = B.call("friends_delete_account")
        check("A and B delete their accounts", da.get("deleted") is True and db_.get("deleted") is True,
              f"A's local friend games deleted: {da.get('friendGamesDeleted')}")
        counts = {t: d1(persist, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tables}
        check("every server table is empty after", all(v == 0 for v in counts.values()), json.dumps(counts))
        check("A is signed out locally", A.call("friends_status")["signedIn"] is False)
        check("A's handle is free again", B.call("friends_check_handle", {"handle": ha})["available"] is True)
    except Exception as exc:
        check("no exception", False, repr(exc))
    finally:
        for x in apps:
            x.close()
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except Exception:
            worker.kill()
        sites.close()
    secs = time.monotonic() - t0
    summary = (f"{len(results) - failed} checks passed, {failed} failed, {secs:.0f} s"
               if results else "no checks ran")
    print(summary)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(f"# sidecar/friends_e2e.py, {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                         + "\n".join(results) + "\n" + summary + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
