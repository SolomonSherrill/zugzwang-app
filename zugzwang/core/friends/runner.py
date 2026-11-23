"""The sidecar's Friends threads (FRIENDS-1 C). Two daemon threads, so the dispatch loop never waits on
the network:

- **server**: every call to the Friends server, in order, and the heartbeat (every
  FRIENDS_HEARTBEAT_S while signed in: POST /v1/heartbeat, then the friends list, announced as the
  `friends_update` event with the incoming request count for the sidebar).
- **fetch**: friends' public games from Chess.com and Lichess, one request at a time
  (`platform_games`), reading what is stored through its own read-only connection and handing new
  rows to the app thread (`post_call`), which alone writes the database. Progress is the
  `friend_data` event.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import zugzwang.config as C
from zugzwang.core.friends import platform_games as PG
from zugzwang.core.friends import scouting
from zugzwang.core.friends.client import FriendsError
from zugzwang.core.friends.service import FriendsService

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def linked_players(entry: dict | None) -> list[tuple[str, str]]:
    return [(l["site"], l["username"].lower()) for l in (entry or {}).get("linked", [])
            if l.get("site") in PG.SITES and l.get("username")]


class FriendsRunner:
    def __init__(self, post_call: Callable, emit: Callable[[str, dict], None],
                 db_path: Callable[[], Path | None], service: FriendsService | None = None) -> None:
        self.post_call = post_call
        self.emit = emit
        self.db_path = db_path
        self._service = service
        self._jobs: queue.Queue = queue.Queue()
        self._fetches: queue.Queue = queue.Queue()
        self._fetching: set[str] = set()
        self._started = False
        self._stop = threading.Event()
        self.heartbeat_s = C.FRIENDS_HEARTBEAT_S

    @property
    def service(self) -> FriendsService:
        if self._service is None:
            self._service = FriendsService()
        return self._service

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._serve, name="friends-server", daemon=True).start()
        threading.Thread(target=self._fetch_loop, name="friends-fetch", daemon=True).start()
        threading.Thread(target=self._beat, name="friends-heartbeat", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        self._fetches.put(None)

    # ── the server thread ───────────────────────────────────────────────────
    def submit(self, fn: Callable[[], dict], reply: Callable[[dict], None],
               fail: Callable[[str], None]) -> None:
        """Run *fn* on the server thread; a FriendsError replies {"error": {code, message, status}},
        anything else fails the request."""
        self.start()
        self._jobs.put((fn, reply, fail))

    def _serve(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            fn, reply, fail = job
            try:
                out = fn()
            except FriendsError as exc:
                reply({"error": exc.as_dict()})
                continue
            except Exception as exc:
                logger.exception("friends call failed")
                fail(str(exc))
                continue
            if out is not None:
                reply(out)

    def _beat(self) -> None:
        while not self._stop.is_set():
            try:
                if self.service.state()["signedIn"] and self.service.base:
                    done = threading.Event()

                    def beat() -> None:
                        try:
                            self.service.heartbeat()
                            lst = self.service.friends()
                            self.emit("friends_update", {
                                "incoming": len(lst.get("incoming", [])),
                                "online": sum(1 for f in lst.get("friends", []) if f.get("online")),
                            })
                        except FriendsError as exc:
                            logger.info("friends heartbeat: %s", exc.code)
                        try:
                            self.tick_chesscom()
                        except FriendsError as exc:
                            logger.info("friends chesscom check: %s", exc.code)
                        finally:
                            done.set()
                        return None

                    self._jobs.put((beat, lambda _r: None, lambda _m: None))
                    done.wait(30)
            except Exception:
                logger.exception("friends heartbeat failed")
            if self._stop.wait(self.heartbeat_s):
                return

    def tick_chesscom(self) -> dict | None:
        """On the server thread, from the heartbeat: a pending Chess.com link is checked when a check is
        due (at most every 15 minutes, BETA-5 ruling K3); a check, or a code running out, is announced as
        the `friends_link` event."""
        link = self.service.chesscom
        rec = link.record()
        if rec is None or rec.get("state") not in ("code", "waiting"):
            return None
        st = link.check(force=False) if link.due() else link.state()
        if st.get("state") != rec.get("state") or st.get("lastCheck") != rec.get("last_check"):
            self.emit("friends_link", st)
            return st
        return None

    # ── the fetch thread ────────────────────────────────────────────────────
    def refresh(self, handle: str, players: list[tuple[str, str]], *, older: bool = False) -> bool:
        """Queue a fetch of these players' games for *handle*'s profile; False when one is queued."""
        key = handle.lower() + (":older" if older else "")
        if key in self._fetching:
            return False
        self.start()
        self._fetching.add(key)
        self._fetches.put((key, handle, players, older))
        return True

    def fetching(self, handle: str) -> bool:
        return any(k.split(":")[0] == handle.lower() for k in self._fetching)

    def _fetch_loop(self) -> None:
        eco = None
        while True:
            job = self._fetches.get()
            if job is None:
                return
            key, handle, players, older = job
            try:
                if eco is None:
                    eco = PG.eco_only_book()
                self._fetch_one(handle, players, older, eco)
            except Exception as exc:
                logger.warning("friends fetch for a profile failed: %s", exc)
                self.emit("friend_data", {"handle": handle, "state": "error", "message": str(exc)})
            finally:
                self._fetching.discard(key)

    def _fetch_one(self, handle: str, players: list[tuple[str, str]], older: bool, eco) -> None:
        from zugzwang.core.database import Database
        path = self.db_path()
        if path is None:
            return
        now = datetime.now(timezone.utc)
        ro = Database(path, read_only=True)
        try:
            states = {p: ro.friend_player(*p) for p in players}
            latest = {p: ro.latest_friend_game(*p) for p in players}
        finally:
            ro.close()
        added = 0
        for (site, user) in players:
            self.emit("friend_data", {"handle": handle, "state": "fetching", "site": site})
            st = states[(site, user)] or {}
            rows: list[dict]
            oldest: str | None = st.get("oldest")
            complete = bool(st.get("complete"))
            if site == "chesscom":
                if older and oldest:
                    y, m = int(oldest[:4]), int(oldest[5:7])
                    res = PG.fetch_chesscom(user, now=now, older_than=(y, m), eco_book=eco)
                elif st.get("fetched_at") and oldest:
                    lt = _parse_iso(latest[(site, user)]) or now
                    res = PG.fetch_chesscom(user, now=now, newer_than=(lt.year, lt.month), eco_book=eco)
                    res["oldest"] = (int(oldest[:4]), int(oldest[5:7]))
                    res["complete"] = complete
                else:
                    res = PG.fetch_chesscom(user, now=now, eco_book=eco)
                rows = res["rows"]
                y, m = res["oldest"]
                oldest_s = f"{y:04d}-{m:02d}-01T00:00:00Z"
                complete = res["complete"]
            else:
                if older and oldest:
                    until = _parse_iso(oldest) or now
                    since = until.replace(year=until.year - 1)
                elif st.get("fetched_at") and oldest:
                    since = _parse_iso(latest[(site, user)]) or PG.window_start(now)
                    until = None
                else:
                    since, until = PG.window_start(now), None
                rows = PG.fetch_lichess(user, since=since, until=until, eco_book=eco)
                created = PG.lichess_created(user) if (older or not st.get("fetched_at")) else None
                keep_oldest = _parse_iso(oldest)
                new_oldest = since if not keep_oldest or since < keep_oldest else keep_oldest
                oldest_s = new_oldest.strftime("%Y-%m-%dT%H:%M:%SZ")
                if created is not None:
                    complete = new_oldest.timestamp() <= created
            done = threading.Event()
            box = {"n": 0}

            def store(rows=rows, site=site, user=user, oldest_s=oldest_s, complete=complete) -> None:
                try:
                    db = self._app_db()
                    if db is not None:
                        box["n"] = db.save_friend_games(rows)
                        db.set_friend_player(site, user, fetched_at=_now_iso(), oldest=oldest_s,
                                             complete=complete)
                finally:
                    done.set()

            self.post_call(store)
            done.wait(60)
            added += box["n"]
        self.emit("friend_data", {"handle": handle, "state": "done", "added": added})

    #: set by the sidecar: the app thread's Database (only called on the app thread)
    _app_db: Callable = staticmethod(lambda: None)


def profile_payload(db, entry: dict, mine: dict[str, str], *, recent_limit: int = 10,
                    recent_offset: int = 0, fetching: bool = False) -> dict:
    """A friend's profile from stored games (app thread)."""
    players = linked_players(entry)
    rows = db.friend_games_of(players)
    now = datetime.now(timezone.utc)
    p = scouting.profile(rows, mine, now, recent_limit=recent_limit, recent_offset=recent_offset)
    states = {f"{s}:{u}": db.friend_player(s, u) for s, u in players}
    fetched = [st.get("fetched_at") for st in states.values() if st and st.get("fetched_at")]
    oldest_fetch = min(fetched) if fetched and len(fetched) == len(players) else None
    age = (now - _parse_iso(oldest_fetch)).total_seconds() if oldest_fetch else None
    return {
        "friend": entry,
        **p,
        "data": {
            "fetchedAt": oldest_fetch,
            "stale": bool(players) and (age is None or age > C.FRIENDS_STALE_S),
            "fetching": fetching,
            "complete": bool(players) and all(st and st.get("complete") for st in states.values()),
            "oldest": min((st.get("oldest") for st in states.values() if st and st.get("oldest")),
                          default=None),
        },
    }


def list_payload(db, lst: dict, mine: dict[str, str]) -> dict:
    """The friends list, each friend with their ratings column, your record and your last game."""
    now = datetime.now(timezone.utc)
    friends = []
    for f in lst.get("friends", []):
        rows = db.friend_games_of(linked_players(f))
        r = scouting.ratings(rows, now)
        games, rec = scouting.together(rows, mine)
        friends.append({**f, "ratings": scouting.list_ratings(r), "record": rec,
                        "lastGame": games[0]["ended_at"] if games else None,
                        "hasData": bool(rows)})
    return {**lst, "friends": friends}
