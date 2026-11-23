"""The signed client of the Friends server (FRIENDS.md ruling V2; server/src/auth.ts is the other half).

Each request carries X-Zz-Key (the public key), X-Zz-Time (ms), X-Zz-Nonce and X-Zz-Sig, the Ed25519
signature over `zugzwang-friends-v1\n<METHOD>\n<path and query>\n<time>\n<nonce>\n<sha256 of body>`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import zugzwang.config as C
from zugzwang.core.friends.identity import Identity, b64url

SIG_PREFIX = "zugzwang-friends-v1"


class FriendsError(Exception):
    """The server said no, or could not be reached. `code` is the server's error code
    (`unreachable` when there was no answer, `not_configured` when there is no server)."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status": self.status}


def server_url() -> str:
    """ZUGZWANG_FRIENDS_URL, else config.FRIENDS_SERVER_URL (empty until the server is deployed)."""
    return (os.environ.get("ZUGZWANG_FRIENDS_URL") or C.FRIENDS_SERVER_URL or "").rstrip("/")


def canonical(method: str, path: str, t: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([SIG_PREFIX, method.upper(), path, t, nonce,
                      hashlib.sha256(body).hexdigest()]).encode("utf-8")


class FriendsClient:
    def __init__(self, base: str, identity: Identity | None, *, timeout: float = 15.0) -> None:
        self.base = base.rstrip("/")
        self.identity = identity
        self.timeout = timeout

    def signed_headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        """The four X-Zz headers for one request (also a WebSocket's GET, FRIENDS-2)."""
        if self.identity is None:
            raise FriendsError("no_identity", "There is no Friends account on this computer.")
        t = str(int(time.time() * 1000))
        nonce = b64url(os.urandom(16))
        sig = self.identity.sign(canonical(method, path, t, nonce, body))
        return {"X-Zz-Key": self.identity.public_key_b64, "X-Zz-Time": t, "X-Zz-Nonce": nonce,
                "X-Zz-Sig": b64url(sig)}

    def ws_url(self, path: str) -> str:
        if not self.base:
            raise FriendsError("not_configured", "No Friends server is set up for this app yet.")
        return ("wss" + self.base[5:] if self.base.startswith("https") else "ws" + self.base[4:]) + path

    def request(self, method: str, path: str, body: dict | None = None, *,
                signed: bool = True) -> dict:
        if not self.base:
            raise FriendsError("not_configured", "No Friends server is set up for this app yet.")
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": C.SYNC_USER_AGENT}
        if data:
            headers["Content-Type"] = "application/json"
        if signed:
            headers.update(self.signed_headers(method, path, data))
        req = urllib.request.Request(self.base + path, data=data or None, headers=headers,
                                     method=method.upper())
        from zugzwang.core.platform_sync import _tls_context
        ctx = _tls_context() if self.base.startswith("https:") else None
        extra = {"context": ctx} if ctx is not None else {}
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, **extra) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read() or b"{}")
            except ValueError:
                err = {}
            raise FriendsError(str(err.get("error") or f"http_{exc.code}"),
                               str(err.get("message") or f"The Friends server answered HTTP {exc.code}."),
                               exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FriendsError("unreachable", "The Friends server could not be reached. Check the "
                               "connection and try again.") from exc
        try:
            out = json.loads(raw or b"{}")
        except ValueError as exc:
            raise FriendsError("bad_answer", "The Friends server sent an answer the app cannot read.") from exc
        return out if isinstance(out, dict) else {"value": out}

    # the endpoints (server/README.md)
    def handle_available(self, handle: str) -> dict:
        return self.request("GET", "/v1/handles/" + urllib.parse.quote(handle, safe=""), signed=False)

    def signup(self, handle: str) -> dict:
        return self.request("POST", "/v1/signup", {"handle": handle, "age_confirmed": True,
                                                   "terms_accepted": True})

    def me(self) -> dict:
        return self.request("GET", "/v1/me")

    def friends(self) -> dict:
        return self.request("GET", "/v1/friends")

    def send_request(self, handle: str) -> dict:
        return self.request("POST", "/v1/requests", {"handle": handle})

    def answer(self, request_id: int, accept: bool) -> dict:
        return self.request("POST", f"/v1/requests/{int(request_id)}/{'accept' if accept else 'decline'}")

    def cancel(self, request_id: int) -> dict:
        return self.request("DELETE", f"/v1/requests/{int(request_id)}")

    def remove_friend(self, handle: str) -> dict:
        return self.request("DELETE", "/v1/friends/" + urllib.parse.quote(handle, safe=""))

    def block(self, handle: str) -> dict:
        return self.request("POST", "/v1/blocks", {"handle": handle})

    def unblock(self, handle: str) -> dict:
        return self.request("DELETE", "/v1/blocks/" + urllib.parse.quote(handle, safe=""))

    def heartbeat(self) -> dict:
        return self.request("POST", "/v1/heartbeat")

    def set_appear_offline(self, on: bool) -> dict:
        return self.request("PUT", "/v1/presence", {"appear_offline": bool(on)})

    def link_lichess(self, token: str) -> dict:
        return self.request("POST", "/v1/link/lichess", {"token": token})

    def chesscom_start(self, username: str) -> dict:
        return self.request("POST", "/v1/link/chesscom/start", {"username": username})

    def chesscom_verify(self, username: str) -> dict:
        return self.request("POST", "/v1/link/chesscom/verify", {"username": username})

    def unlink(self, site: str) -> dict:
        return self.request("DELETE", "/v1/link/" + urllib.parse.quote(site, safe=""))

    def delete_account(self) -> dict:
        return self.request("DELETE", "/v1/account")

    # FRIENDS-2: the switches, challenges, games (server/README.md "Live games")
    def set_settings(self, *, chat_on: bool) -> dict:
        """ "Chat in friend games" (H3). BETA-6 (ruling SG1): the server keeps no shared games and no sharing switch."""
        return self.request("PUT", "/v1/settings", {"chat_on": bool(chat_on)})

    def challenge(self, handle: str, tc: str, colour: str) -> dict:
        return self.request("POST", "/v1/challenges", {"handle": handle, "tc": tc, "colour": colour})

    def challenge_answer(self, challenge_id: str, accept: bool) -> dict:
        return self.request("POST", f"/v1/challenges/{urllib.parse.quote(challenge_id, safe='')}/"
                            + ("accept" if accept else "decline"))

    def challenge_cancel(self, challenge_id: str) -> dict:
        return self.request("DELETE", f"/v1/challenges/{urllib.parse.quote(challenge_id, safe='')}")

    def game(self, game_id: str) -> dict:
        return self.request("GET", f"/v1/games/{urllib.parse.quote(game_id, safe='')}")

    def game_ack(self, game_id: str) -> dict:
        return self.request("POST", f"/v1/games/{urllib.parse.quote(game_id, safe='')}/ack")

    def rematch(self, game_id: str) -> dict:
        return self.request("POST", f"/v1/games/{urllib.parse.quote(game_id, safe='')}/rematch")