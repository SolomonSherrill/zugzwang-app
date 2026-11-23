#!/usr/bin/env python3
"""Friends against the DEPLOYED server, from the app's own code (FRIENDS-1B C): two app identities —
two real sidecars, each with its own temp database, data folder and file keystore — sign up, send and
accept a request, see each other's presence (online, then Appear offline), delete both accounts, and
then every server table is counted (`wrangler d1 execute --remote`; it needs CLOUDFLARE_API_TOKEN in the
environment, which this script never prints).

    .venv/bin/python sidecar/friends_live_check.py https://api.zugzwangapp.com [--out FILE] [--no-tables]

Nothing touches a real keychain, a real database or the screen; the test handles are `live-<random>`.
Exit 0 when every check passed. The local, network-free run is sidecar/friends_e2e.py.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sidecar"))

import friends_e2e as E  # noqa: E402

TABLES = ["accounts", "linked_accounts", "friend_requests", "friendships", "blocks", "presence"]


def remote_counts() -> dict:
    # one row of subqueries: D1 refuses a compound SELECT of six terms
    sql = "SELECT " + ", ".join(f"(SELECT COUNT(*) FROM {t}) AS {t}" for t in TABLES)
    out = subprocess.run(["npx", "wrangler", "d1", "execute", "zugzwang-friends", "--remote", "--json",
                          "--command", sql], cwd=REPO / "server", capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, WRANGLER_SEND_METRICS="false", CI="1"))
    if out.returncode != 0:
        raise RuntimeError("wrangler d1 execute failed: " + (out.stderr or out.stdout)[-400:])
    return json.loads(out.stdout)[0]["results"][0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-tables", action="store_true", help="skip the table count (no Cloudflare token)")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    t0 = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="zz-friends-live-"))
    tag = secrets.token_hex(3)
    ha, hb = f"live-a-{tag}", f"live-b-{tag}"
    # BETA-6: the server has real users now, so the tables are compared with their counts before the run
    before = None if a.no_tables else remote_counts()
    apps: list = []
    signed: list = []
    try:
        extra = {"ZUGZWANG_FRIENDS_URL": url}
        A, B = E.App("a", root, extra), E.App("b", root, extra)
        apps += [A, B]
        for x in (A, B):
            x.wait_event("ready", timeout=60)
        st = A.call("friends_status")
        E.check("the app reads the deployed server's address", st["configured"] and not st["signedIn"], url)
        E.check("the handle is free", A.call("friends_check_handle", {"handle": ha})["available"] is True)
        sa = A.call("friends_signup", {"handle": ha, "ageConfirmed": True, "termsAccepted": True})
        E.check("A signs up and gets a recovery code", sa.get("handle") == ha and len(sa.get("recoveryCode", "")) == 44, ha)
        signed.append(A)
        sb = B.call("friends_signup", {"handle": hb, "ageConfirmed": True, "termsAccepted": True})
        E.check("B signs up", sb.get("handle") == hb, hb)
        signed.append(B)
        r = A.call("friends_request", {"handle": hb})
        E.check("A sends B a request", r.get("status") == "sent")
        inc = B.call("friends_list", {"mine": {}}).get("incoming", [])
        E.check("B sees it", len(inc) == 1 and inc[0]["handle"] == ha)
        acc = B.call("friends_answer", {"id": inc[0]["id"], "accept": True})
        E.check("B accepts", acc.get("status") == "friends")
        fb = next((f for f in A.call("friends_list", {"mine": {}}).get("friends", []) if f["handle"] == hb), None)
        E.check("A's list has B, online", fb is not None and fb["online"] is True, f"online={fb and fb['online']}")
        B.call("friends_appear_offline", {"on": True})
        fb2 = next(f for f in A.call("friends_list", {"mine": {}})["friends"] if f["handle"] == hb)
        E.check("B appears offline to A", fb2["online"] is False and fb2["last_seen"] is None)
        da, db_ = A.call("friends_delete_account"), B.call("friends_delete_account")
        E.check("A and B delete their accounts", da.get("deleted") is True and db_.get("deleted") is True)
        signed.clear()
        E.check("A's handle is free again", B.call("friends_check_handle", {"handle": ha})["available"] is True)
        if not a.no_tables:
            counts = remote_counts()
            E.check("every server table is as it was before the run (nothing left of A or B)", counts == before,
                    json.dumps({"before": before, "after": counts}))
    except Exception as exc:
        E.check("no exception", False, repr(exc))
        for x in signed:   # never leave a test account behind
            try:
                x.call("friends_delete_account")
            except Exception:
                pass
    finally:
        for x in apps:
            x.close()
    secs = time.monotonic() - t0
    summary = f"{len(E.results) - E.failed} checks passed, {E.failed} failed, {secs:.0f} s"
    print(summary)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(f"# sidecar/friends_live_check.py {url}, "
                         f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                         + "\n".join(E.results) + "\n" + summary + "\n")
    return 1 if E.failed else 0


if __name__ == "__main__":
    sys.exit(main())
