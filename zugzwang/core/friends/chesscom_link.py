"""Linking Chess.com by the profile code, while Chess.com catches up (BETA-5 ruling K3, FRIENDS.md).

Chess.com's public API refreshes a profile at most once every 12 hours, so the code the server makes lasts
24 hours (the server's `LINK_CODE_HOURS`) and the app keeps checking until the code is found or expires:

- **code**: the server made a code (`start`); the user puts it in their profile's Location and checks.
- **waiting**: a check found no code. The app checks again on its own **at most once per 15 minutes**
  (`CHECK_EVERY_MS`), from the Friends heartbeat while the app is open; **Check now** checks at once (and
  the next check on its own is 15 minutes after it).
- **expired**: the code's 24 hours ran out before Chess.com showed it; checks stop and the app says so.
- **linked**: the server found the code; the app says the code can come out of the Location.

The record (username, code, when it expires, the last check) is kept in Friends' local settings
(`settings.json` beside the database), so a pending link and its code survive a restart. Every check is a
request to the Friends server (which reads the public profile), made on the Friends server thread, so
checks are one request at a time. The clock is injectable (tests use a fake one).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from zugzwang.core.friends import settings as fsettings
from zugzwang.core.friends.client import FriendsError

#: at most one check per pending link in this many milliseconds (on its own; Check now always checks)
CHECK_EVERY_MS = 15 * 60_000
#: Check now runs at most once in this many milliseconds (FRIENDS.md ruling Z4, owner 2026-11-22): a press
#: sooner sends no request and says when it can be pressed again (`checkNowAt`)
CHECK_NOW_GAP_MS = 30_000
#: the setting the record is kept under
KEY = "chesscom_link"


def _now_ms() -> int:
    return int(time.time() * 1000)


class ChesscomLink:
    """The pending Chess.com link. *client* returns the signed Friends client (its chesscom_start,
    chesscom_verify, me and unlink); *clock* returns Unix time in ms."""

    def __init__(self, client: Callable, clock: Callable[[], int] = _now_ms) -> None:
        self.client = client
        self.clock = clock
        self._lock = threading.Lock()

    # ── the record ──────────────────────────────────────────────────────────
    def record(self) -> dict | None:
        rec = fsettings.load().get(KEY)
        return rec if isinstance(rec, dict) and rec.get("state") in ("code", "waiting", "expired", "linked") else None

    def _save(self, rec: dict | None) -> dict | None:
        fsettings.save(**{KEY: rec})
        return rec

    def state(self) -> dict:
        """The record as the app shows it (`{"state": "none"}` without one); a code past its time is
        marked expired here, with no request."""
        rec = self.record()
        if rec is None:
            return {"state": "none"}
        if rec["state"] in ("code", "waiting") and self.clock() >= int(rec.get("expires") or 0):
            rec = self._save({**rec, "state": "expired", "error": None})
        return self._public(rec)

    def _public(self, rec: dict) -> dict:
        last = rec.get("last_check")
        nxt = (int(last) + CHECK_EVERY_MS) if rec["state"] == "waiting" and last is not None else None
        forced = rec.get("last_forced")
        now_at = int(forced) + CHECK_NOW_GAP_MS if forced is not None else None
        return {"state": rec["state"], "username": rec.get("username"), "code": rec.get("code"),
                "expires": rec.get("expires"), "lastCheck": last, "nextCheck": nxt,
                "checkNowAt": now_at if now_at is not None and now_at > self.clock() else None,
                "error": rec.get("error")}

    # ── what the user does ─────────────────────────────────────────────────
    def start(self, username: str) -> dict:
        out = self.client().chesscom_start(username)
        rec = {"state": "code", "username": out.get("username", username), "code": out["code"],
               "expires": int(out["expires"]), "started": self.clock(), "last_check": None, "error": None}
        self._save(rec)
        return {**out, **self._public(rec)}

    def check(self, *, force: bool = True) -> dict:
        """One check: *force* (Check, Check now) checks whenever a code is pending; otherwise only a
        waiting link whose last check is CHECK_EVERY_MS old. Never two requests at once."""
        if not self._lock.acquire(blocking=False):
            return {**self.state(), "checking": True}
        try:
            cur = self.state()
            rec = self.record()
            if rec is None or cur["state"] not in ("code", "waiting"):
                return cur
            now = self.clock()
            if not force and (rec["state"] != "waiting"
                              or now < int(rec.get("last_check") or 0) + CHECK_EVERY_MS):
                return cur
            if force:
                # Z4: Check now at most once every 30 s; a press sooner checks nothing
                if rec.get("last_forced") is not None and now < int(rec["last_forced"]) + CHECK_NOW_GAP_MS:
                    return cur
                rec = self._save({**rec, "last_forced": now})
            try:
                out = self.client().chesscom_verify(rec["username"])
            except FriendsError as exc:
                now = self.clock()
                if now >= int(rec["expires"]):
                    return self._public(self._save({**rec, "state": "expired", "last_check": now, "error": None}))
                if exc.code == "code_not_found":
                    return self._public(self._save({**rec, "state": "waiting", "last_check": now, "error": None}))
                # no answer, or another refusal: said under the link; a waiting link keeps waiting
                return self._public(self._save({**rec, "last_check": now, "error": exc.message}))
            linked = {**rec, "state": "linked", "username": out.get("username", rec["username"]),
                      "last_check": self.clock(), "error": None}
            return {**self._public(self._save(linked)), "site": "chesscom", "verified": True}
        finally:
            self._lock.release()

    def due(self) -> bool:
        """Whether a check on its own is due now (the heartbeat asks this before queueing one)."""
        rec = self.record()
        if rec is None or rec["state"] != "waiting":
            return False
        now = self.clock()
        return now < int(rec.get("expires") or 0) and now >= int(rec.get("last_check") or 0) + CHECK_EVERY_MS

    def cancel(self) -> dict:
        """Forget the pending link here; an unproven name the server keeps for it is unlinked (a proven one
        never is). After "linked" this only dismisses the message."""
        rec = self.record()
        self._save(None)
        if rec is not None and rec["state"] != "linked":
            try:
                me = self.client().me()
                cc = next((l for l in me.get("linked", []) if l.get("site") == "chesscom"), None)
                if cc is not None and not cc.get("verified"):
                    self.client().unlink("chesscom")
            except FriendsError:
                pass            # the local record is gone either way; the unproven name proves nothing
        return {"state": "none"}
