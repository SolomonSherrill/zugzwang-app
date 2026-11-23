#!/usr/bin/env python3
"""A test opponent for games against friends (FRIENDS-2 F): a throwaway Friends account that plays you.

    .venv/bin/python sidecar/friends_bot.py <server> <your handle> [--pace S] [--games N]

It signs up a throwaway account (handle `testbot-<6 hex>`, a key made in memory, never written anywhere),
sends <your handle> a friend request and stays online (a heartbeat every 60 s). Accept the request in
Zugzwang (Friends), then challenge it: it accepts your challenge, plays legal moves at a human pace (a few
seconds a move, quicker when its clock runs low; python-chess, captures and checks a little preferred, no
engine), answers chat, offers a draw once (after move 15), accepts a draw you offer, and after a game
accepts a rematch. **On exit or Ctrl-C it deletes its account** (every row about it on the server).

Nothing here opens a window or a browser. The key exists only in this process: if it is killed with
SIGKILL the account stays until removed (`node server/scripts/admin.mjs remove <handle> <server>`).
--games N exits after N games (the tests use it); --pace S scales the thinking time (default 1.0).
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import random
import signal
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import chess  # noqa: E402

from zugzwang.core.friends.client import FriendsClient, FriendsError  # noqa: E402
from zugzwang.core.friends.identity import Identity  # noqa: E402
from zugzwang.core.friends.ws import WebSocket, WebSocketError  # noqa: E402

REPLIES = {
    "good luck": "thanks, you too!",
    "gl": "gl hf",
    "hi": "hi! ready when you are",
    "hello": "hello! ready when you are",
    "gg": "gg, thanks for the game",
    "rematch": "sure, send it",
    "draw": "I'll think about it",
}
GENERIC = ["nice move", "hmm, let me think", "interesting", "ok!", "I see what you're doing"]
DRAW_AFTER_PLY = 30


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def reply_to(text: str) -> str:
    t = text.lower()
    for key, answer in REPLIES.items():
        if key in t:
            return answer
    return random.choice(GENERIC)


def choose_move(fen: str, rnd: random.Random) -> str:
    """A legal move: captures and checks weighted up a little, so it plays like a beginner, not a wall."""
    board = chess.Board(fen)
    moves = list(board.legal_moves)
    for m in moves:                       # a mate in one is never missed
        board.push(m)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return m.uci()
    weights = []
    for m in moves:
        w = 1.0
        if board.is_capture(m):
            w += 2.5
        if board.gives_check(m):
            w += 1.5
        if m.promotion == chess.QUEEN:
            w += 5
        weights.append(w)
    return rnd.choices(moves, weights)[0].uci()


def think_seconds(remaining_ms: int, pace: float, rnd: random.Random) -> float:
    """A human pace: 2 to 8 s a move, never more than a thirtieth of the clock left."""
    want = rnd.uniform(2.0, 8.0) * pace
    return max(0.2 * pace, min(want, remaining_ms / 1000 / 30))


class Bot:
    def __init__(self, server: str, owner: str, *, pace: float = 1.0, games: int | None = None, seed: int | None = None) -> None:
        self.server = server.rstrip("/")
        self.owner = owner
        self.pace = pace
        self.games_left = games
        self.rnd = random.Random(seed)
        self.ident = Identity.new()
        self.client = FriendsClient(self.server, self.ident)
        self.handle = "testbot-" + os.urandom(3).hex()
        self.stop = threading.Event()
        self.signed_up = False
        self.deleted = False
        self._lock = threading.Lock()

    # ── the account ────────────────────────────────────────────────────────
    def sign_up(self) -> None:
        self.client.signup(self.handle)
        self.signed_up = True
        self.client.set_settings(chat_on=True)
        log(f"signed up as {self.handle} (a throwaway account; deleted when this stops)")
        out = self.client.send_request(self.owner)
        if out.get("status") == "friends":
            log(f"already friends with {self.owner}")
        else:
            log(f"friend request sent to {self.owner}: accept it in Zugzwang (Friends), then challenge {self.handle}")
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self) -> None:
        while not self.stop.is_set():
            try:
                self.client.heartbeat()
            except FriendsError as exc:
                log(f"heartbeat: {exc.code}")
            self.stop.wait(60)

    def delete(self) -> None:
        with self._lock:
            if not self.signed_up or self.deleted:
                return
            self.deleted = True
        try:
            self.client.delete_account()
            log(f"deleted the account {self.handle}")
        except FriendsError as exc:
            log(f"could not delete {self.handle} ({exc.code}): remove it with server/scripts/admin.mjs")

    # ── sockets ────────────────────────────────────────────────────────────
    def _open(self, path: str) -> WebSocket:
        return WebSocket.connect(self.client.ws_url(path), self.client.signed_headers("GET", path))

    def _pinger(self, ws: WebSocket) -> None:
        while not ws.closed and not self.stop.is_set():
            time.sleep(10)
            try:
                ws.send("ping")
            except WebSocketError:
                return

    def run(self) -> None:
        self.sign_up()
        while not self.stop.is_set():
            try:
                lobby = self._open("/v1/live")
            except (WebSocketError, OSError) as exc:
                log(f"lobby: {exc}; trying again in 5 s")
                self.stop.wait(5)
                continue
            threading.Thread(target=self._pinger, args=(lobby,), daemon=True).start()
            try:
                self._lobby_loop(lobby)
            except WebSocketError as exc:
                if not self.stop.is_set():
                    log(f"lobby closed ({exc}); reconnecting")
            finally:
                lobby.close()
            if self.games_left is not None and self.games_left <= 0:
                return

    def _lobby_loop(self, lobby: WebSocket) -> None:
        while not self.stop.is_set():
            text = lobby.recv()
            if text == "pong":
                continue
            m = json.loads(text)
            if m.get("t") == "hello":
                for c in m.get("challenges", []):
                    self._maybe_accept(c)
            elif m.get("t") == "challenge":
                self._maybe_accept(m["challenge"])
            elif m.get("t") == "game_start":
                gid = m["game"]["id"]
                self.play(gid)
                if self.games_left is not None:
                    self.games_left -= 1
                    if self.games_left <= 0:
                        return
                log(f"waiting for another challenge from {self.owner} (a rematch is fine)")

    def _maybe_accept(self, c: dict) -> None:
        if c.get("to_handle", "").lower() != self.handle.lower():
            return
        if c.get("from_handle", "").lower() != self.owner.lower():
            log(f"a challenge from {c.get('from_handle')}, not {self.owner}: declined")
            try:
                self.client.challenge_answer(c["id"], False)
            except FriendsError:
                pass
            return
        log(f"{self.owner} challenges me to a {c['tc']} game: accepted")
        try:
            self.client.challenge_answer(c["id"], True)
        except FriendsError as exc:
            log(f"could not accept: {exc.message}")

    # ── a game ─────────────────────────────────────────────────────────────
    def play(self, gid: str) -> None:
        ws = self._open(f"/v1/games/{gid}/live")
        threading.Thread(target=self._pinger, args=(ws,), daemon=True).start()
        offered = False
        greeted = False
        last_ply_played = -1
        st: dict = {}
        try:
            while not self.stop.is_set():
                text = ws.recv()
                if text == "pong":
                    continue
                m = json.loads(text)
                if m.get("t") == "chat":
                    if m.get("from") != st.get("you"):
                        log(f"chat from {m.get('handle')}: {m.get('text')}")
                        self._say_later(ws, reply_to(str(m.get("text", ""))))
                    continue
                if m.get("t") == "error":
                    log(f"server: {m.get('error')}: {m.get('message')}")
                    continue
                if m.get("t") != "state":
                    continue
                st = m
                if not greeted:
                    greeted = True
                    log(f"game {gid[:6]}: I play {st['you']}, {st['tc']}")
                    self._say_later(ws, "hi! good luck", 1.0)
                if st["status"] == "over":
                    log(f"game over: {st['result']} ({st.get('termination_text')})")
                    self._say_later(ws, "gg!", 0.5)
                    time.sleep(1.5 * self.pace)
                    try:
                        self.client.game_ack(gid)
                    except FriendsError:
                        pass
                    return
                if st.get("draw_offer") and st["draw_offer"] != st["you"]:
                    log("a draw offered: accepted")
                    ws.send(json.dumps({"t": "draw_accept"}))
                    continue
                ply = len(st["moves"])
                if st["turn"] == st["you"] and ply != last_ply_played:
                    if not offered and ply >= DRAW_AFTER_PLY and st.get("can_offer_draw"):
                        offered = True
                        log("offering a draw (once)")
                        ws.send(json.dumps({"t": "draw_offer"}))
                    last_ply_played = ply
                    threading.Thread(target=self._move_later, args=(ws, st), daemon=True).start()
        finally:
            ws.close()

    def _move_later(self, ws: WebSocket, st: dict) -> None:
        remaining = st["clock"][st["you"]]
        delay = 0.3 * self.pace if st["status"] == "waiting" else think_seconds(remaining, self.pace, self.rnd)
        if self.stop.wait(delay):
            return
        uci = choose_move(st["fen"], self.rnd)
        try:
            ws.send(json.dumps({"t": "move", "uci": uci, "ply": len(st["moves"])}))
        except WebSocketError:
            pass

    def _say_later(self, ws: WebSocket, text: str, base: float = 1.5) -> None:
        def go():
            if self.stop.wait(base * self.pace + self.rnd.uniform(0, 1.5) * self.pace):
                return
            try:
                ws.send(json.dumps({"t": "chat", "text": text}))
            except WebSocketError:
                pass
        threading.Thread(target=go, daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("server", help="the Friends server, e.g. https://api.zugzwangapp.com")
    ap.add_argument("owner", help="your handle: the bot befriends and plays you")
    ap.add_argument("--pace", type=float, default=1.0, help="thinking-time scale (default 1.0, a human pace)")
    ap.add_argument("--games", type=int, default=None, help="stop after this many games")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    bot = Bot(a.server, a.owner, pace=a.pace, games=a.games, seed=a.seed)
    atexit.register(bot.delete)

    def on_signal(signum, _frame):
        log("stopping")
        bot.stop.set()
        bot.delete()
        os._exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        bot.run()
    except FriendsError as exc:
        log(f"the server said no: {exc.code}: {exc.message}")
        return 1
    finally:
        bot.stop.set()
        bot.delete()
    return 0


if __name__ == "__main__":
    sys.exit(main())
