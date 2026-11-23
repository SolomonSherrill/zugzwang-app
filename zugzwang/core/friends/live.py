"""The app's live connection to the Friends server (FRIENDS-2 C): the lobby socket (challenges, games
starting and ending) and one socket per live game (its state, chat, errors), each a signed WebSocket opened
from the sidecar, so **the account key never leaves the sidecar** (the webview only sees events and calls
RPCs; no ticket is needed because the connection does not run in the webview).

Events to the webview:
- `friends_live`  {kind: hello | challenge | challenge_gone | game_start | game_over | connection, ...,
                   live: the snapshot (connected, challenges, games)}
- `friend_game`   {id, kind: state | chat | error | ratings | saved | closed, ...}

Chat is kept in this process's memory only, for the game's screen, and never written anywhere (H2).
A finished game is saved to the library at once (`save_game`, the app thread) and acknowledged to the
server when its screen is closed, a new game starts, or ACK_AFTER_S later, so the game's chat and a rematch
offer still reach the game screen after the end; the server deletes the game once both apps acknowledged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

from zugzwang.core.friends import start_ratings
from zugzwang.core.friends.client import FriendsError
from zugzwang.core.friends.ws import WebSocket, WebSocketError

logger = logging.getLogger(__name__)

PING_S = 10.0
ACK_AFTER_S = 600.0
CHAT_KEEP = 200
GAME_MESSAGES = {"move", "resign", "draw_offer", "draw_accept", "draw_decline", "claim_win", "call_draw",
                 "chat", "mute", "sync"}


class _Socket:
    """One signed WebSocket, kept open while wanted: reconnects with a growing wait; a "ping" text every
    PING_S (answered by the server without waking its object)."""

    def __init__(self, name: str, client_fn: Callable, path: str, on_msg: Callable[[dict], None],
                 on_conn: Callable[[bool], None], on_gone: Callable[[int], None] | None = None) -> None:
        self.name = name
        self.client_fn = client_fn
        self.path = path
        self.on_msg = on_msg
        self.on_conn = on_conn
        self.on_gone = on_gone
        self.want = True
        self.ws: WebSocket | None = None
        self.connected = False
        self._wake = threading.Event()
        threading.Thread(target=self._run, name=f"friends-ws-{name}", daemon=True).start()

    def _run(self) -> None:
        wait = 1.0
        while self.want:
            try:
                client = self.client_fn()
                self.ws = WebSocket.connect(client.ws_url(self.path), client.signed_headers("GET", self.path))
            except WebSocketError as exc:
                if exc.status in (401, 403, 404):
                    self.want = False
                    if self.on_gone:
                        self.on_gone(exc.status)
                    return
                logger.info("friends live %s: %s", self.name, exc)
            except (FriendsError, OSError) as exc:
                logger.info("friends live %s: %s", self.name, exc)
            else:
                wait = 1.0
                self.connected = True
                self.on_conn(True)
                pinger = threading.Thread(target=self._ping, args=(self.ws,), daemon=True)
                pinger.start()
                try:
                    while self.want:
                        text = self.ws.recv()
                        if text == "pong":
                            continue
                        try:
                            msg = json.loads(text)
                        except ValueError:
                            continue
                        try:
                            self.on_msg(msg)
                        except Exception:
                            logger.exception("friends live %s: a message failed", self.name)
                except WebSocketError as exc:
                    logger.info("friends live %s: %s", self.name, exc)
                finally:
                    self.connected = False
                    self.ws.close()
                    self.on_conn(False)
            if not self.want:
                return
            self._wake.wait(wait)
            self._wake.clear()
            wait = min(30.0, wait * 2)

    def _ping(self, ws: WebSocket) -> None:
        while self.want and not ws.closed:
            time.sleep(PING_S)
            try:
                ws.send("ping")
            except WebSocketError:
                return

    def send(self, msg: dict) -> None:
        ws = self.ws
        if not self.connected or ws is None:
            raise FriendsError("not_connected", "Not connected to the game: trying again.")
        try:
            ws.send(json.dumps(msg, separators=(",", ":")))
        except WebSocketError:
            raise FriendsError("not_connected", "Not connected to the game: trying again.") from None

    def stop(self) -> None:
        self.want = False
        self._wake.set()
        if self.ws is not None:
            self.ws.close()

    def drop(self) -> None:
        """Close the connection as if the network went (tests, the end-to-end run); it reconnects."""
        if self.ws is not None:
            self.ws.close(4000)


class LiveLink:
    """The lobby connection and the game connections of one signed-in app."""

    def __init__(self, client_fn: Callable, emit: Callable[[str, dict], None],
                 save_game: Callable[[str, dict, dict | None], int | None],
                 *, ratings_fn: Callable[[dict], dict] = start_ratings.at_start) -> None:
        self.client_fn = client_fn
        self.emit = emit
        self.save_game = save_game
        self.ratings_fn = ratings_fn
        self.lock = threading.RLock()
        self.lobby: _Socket | None = None
        self.sockets: dict[str, _Socket] = {}
        self.challenges: dict[str, dict] = {}
        self.games: dict[str, dict] = {}
        self.states: dict[str, dict] = {}
        self.chat: dict[str, list] = {}
        self.ratings: dict[str, dict] = {}
        self.saved: dict[str, int | None] = {}
        self.acked: set[str] = set()
        self._ack_timers: dict[str, threading.Timer] = {}

    # ── the lobby ──────────────────────────────────────────────────────────
    def ensure(self) -> None:
        with self.lock:
            if self.lobby is None or not self.lobby.want:
                self.lobby = _Socket("lobby", self.client_fn, "/v1/live", self._on_lobby, self._on_lobby_conn,
                                     on_gone=lambda _s: None)

    def stop(self) -> None:
        with self.lock:
            for s in [self.lobby, *self.sockets.values()]:
                if s is not None:
                    s.stop()
            self.lobby = None
            self.sockets.clear()
            for t in self._ack_timers.values():
                t.cancel()
            self._ack_timers.clear()
            self.challenges.clear()
            self.games.clear()

    def snapshot(self) -> dict:
        with self.lock:
            return {"connected": bool(self.lobby and self.lobby.connected),
                    "challenges": sorted(self.challenges.values(), key=lambda c: c.get("created", 0)),
                    "games": list(self.games.values())}

    def _on_lobby_conn(self, up: bool) -> None:
        self.emit("friends_live", {"kind": "connection", "connected": up, "live": self.snapshot()})

    def _on_lobby(self, m: dict) -> None:
        t = m.get("t")
        with self.lock:
            if t == "hello":
                self.challenges = {c["id"]: c for c in m.get("challenges", [])}
                self.games = {g["id"]: g for g in m.get("games", [])}
                for g in list(self.games.values()):
                    if g.get("status") == "live":
                        self.open_game(g["id"])
                    elif g["id"] not in self.saved:
                        threading.Thread(target=self._fetch_result, args=(g["id"],), daemon=True).start()
            elif t == "challenge":
                c = m["challenge"]
                self.challenges[c["id"]] = c
            elif t == "challenge_gone":
                self.challenges.pop(m.get("id"), None)
            elif t == "game_start":
                g = m["game"]
                # a new game: the finished ones are acknowledged now (their screens are left)
                for old in [gid for gid in self.states if gid != g["id"]]:
                    self.ack(old)
                self.games[g["id"]] = g
                self.open_game(g["id"])
            elif t == "game_over":
                g = self.games.get(m.get("id"))
                if g:
                    g["status"] = "over"
        self.emit("friends_live", {**m, "kind": t, "live": self.snapshot()})

    def _fetch_result(self, gid: str) -> None:
        """A game that ended while this app was away: saved from the server's view of it."""
        try:
            st = self.client_fn().game(gid)
        except FriendsError as exc:
            logger.info("friends live: the result of a game: %s", exc.code)
            return
        self._on_state(gid, st)

    # ── games ──────────────────────────────────────────────────────────────
    def open_game(self, gid: str) -> None:
        with self.lock:
            s = self.sockets.get(gid)
            if s is not None and s.want:
                return
            self.chat.setdefault(gid, [])
            self.sockets[gid] = _Socket("game-" + gid[:6], self.client_fn, f"/v1/games/{gid}/live",
                                        lambda m, gid=gid: self._on_game(gid, m),
                                        lambda up, gid=gid: self._on_game_conn(gid, up),
                                        on_gone=lambda status, gid=gid: self._on_game_gone(gid, status))

    def close_game(self, gid: str) -> None:
        """The game's screen was left: a finished game is acknowledged (the server may delete it)."""
        st = self.states.get(gid)
        if st and st.get("status") == "over":
            self.ack(gid)

    def _on_game_conn(self, gid: str, up: bool) -> None:
        self.emit("friend_game", {"id": gid, "kind": "connection", "connected": up})

    def _on_game_gone(self, gid: str, status: int) -> None:
        with self.lock:
            self.sockets.pop(gid, None)
        self.emit("friend_game", {"id": gid, "kind": "closed", "status": status})

    def _on_game(self, gid: str, m: dict) -> None:
        t = m.get("t")
        if t == "state":
            self._on_state(gid, m)
        elif t == "chat":
            with self.lock:
                lines = self.chat.setdefault(gid, [])
                lines.append({k: m.get(k) for k in ("from", "handle", "text", "at")})
                del lines[:-CHAT_KEEP]
                line = lines[-1]
            self.emit("friend_game", {"id": gid, "kind": "chat", "line": line})
        elif t == "error":
            self.emit("friend_game", {"id": gid, "kind": "error", "error": m.get("error"), "message": m.get("message")})

    def _on_state(self, gid: str, st: dict) -> None:
        with self.lock:
            first = gid not in self.states
            self.states[gid] = st
        if first and gid not in self.ratings:
            # R3: taken at the game's start (when this app first sees the game)
            threading.Thread(target=self._take_ratings, args=(gid, st), daemon=True).start()
        self.emit("friend_game", {"id": gid, "kind": "state", "state": st, "ratings": self.ratings.get(gid)})
        if st.get("status") == "over":
            self._finished(gid, st)

    def _take_ratings(self, gid: str, st: dict) -> None:
        try:
            r = self.ratings_fn(st)
        except Exception:
            logger.exception("friends live: ratings at the start")
            r = {"white": {"rating": None, "estimated": False}, "black": {"rating": None, "estimated": False}}
        with self.lock:
            self.ratings[gid] = r
        self.emit("friend_game", {"id": gid, "kind": "ratings", "ratings": r})

    def _finished(self, gid: str, st: dict) -> None:
        with self.lock:
            if gid in self.saved:
                return
            self.saved[gid] = None
        if not st.get("pgn"):
            # aborted (P2): nothing to save; acknowledged at once so the server can delete it
            self.ack(gid)
            return
        ratings = self.ratings.get(gid)
        if ratings is None:
            self._take_ratings(gid, st)
            ratings = self.ratings.get(gid)
        try:
            lib_id = self.save_game(gid, st, ratings)
        except Exception:
            logger.exception("friends live: saving a finished game")
            with self.lock:
                self.saved.pop(gid, None)
            return
        with self.lock:
            self.saved[gid] = lib_id
            if gid not in self._ack_timers and gid not in self.acked:
                timer = threading.Timer(ACK_AFTER_S, self.ack, args=(gid,))
                timer.daemon = True
                self._ack_timers[gid] = timer
                timer.start()
        self.emit("friend_game", {"id": gid, "kind": "saved", "gameId": lib_id})
        if gid not in self.sockets:
            self.ack(gid)

    def ack(self, gid: str) -> None:
        with self.lock:
            if gid in self.acked or gid not in self.saved:
                return
            self.acked.add(gid)
            t = self._ack_timers.pop(gid, None)
            if t:
                t.cancel()
            s = self.sockets.pop(gid, None)
        if s is not None:
            s.stop()
        try:
            self.client_fn().game_ack(gid)
        except FriendsError as exc:
            logger.info("friends live: acknowledging a game: %s", exc.code)
            with self.lock:
                self.acked.discard(gid)

    def send(self, gid: str, msg: dict) -> dict:
        if msg.get("t") not in GAME_MESSAGES:
            raise FriendsError("bad_message", "Unknown game message.")
        with self.lock:
            s = self.sockets.get(gid)
        if s is None:
            raise FriendsError("no_such_game", "That game is not open.")
        s.send(msg)
        return {"sent": True}

    # ── the ratings line before a game (the banner, the Challenge popover; R1-R3) ─────────
    _rating_cache: dict = {}
    RATING_CACHE_S = 600.0

    def preview_ratings(self, mine: list[dict], theirs: list[dict], tc: str) -> dict:
        """Both players' ratings for a time control, as the game will show them: {"you": ..., "them": ...}.
        Cached ten minutes per player and time control, so a banner asks the sites once."""
        out = {}
        for key, linked in (("you", mine), ("them", theirs)):
            ck = (tuple(sorted((l.get("site"), (l.get("username") or "").lower()) for l in linked or [])), tc)
            hit = self._rating_cache.get(ck)
            if hit is None or time.monotonic() - hit[0] > self.RATING_CACHE_S:
                hit = (time.monotonic(), start_ratings.rating_for(linked or [], tc))
                self._rating_cache[ck] = hit
            out[key] = hit[1]
        return out

    def game_view(self, gid: str) -> dict:
        with self.lock:
            return {"id": gid, "state": self.states.get(gid), "chat": list(self.chat.get(gid, [])),
                    "ratings": self.ratings.get(gid), "savedGameId": self.saved.get(gid),
                    "connected": bool(self.sockets.get(gid) and self.sockets[gid].connected)}
