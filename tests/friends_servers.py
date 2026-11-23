"""A local stand-in for api.chess.com and lichess.org (FRIENDS-1 E): the friends' games of
`friends_fixtures`, the profile field the Chess.com code check reads, and Lichess's OAuth endpoints.
Used by the Friends tests and the headless end-to-end run (sidecar/friends_e2e.py); never the network.
"""
from __future__ import annotations

import json
import secrets
import threading
import urllib.parse
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _QuickServer(ThreadingHTTPServer):
    """No reverse-DNS lookup of the address at bind (HTTPServer's getfqdn took 35 s here)."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


class PlatformServer:
    def __init__(self) -> None:
        self.chesscom: dict[str, dict] = {}      # user -> {archive url: {"games": [...]}}
        self.chesscom_profile: dict[str, dict] = {}
        self.lichess: dict[str, list] = {}       # user -> games (ndjson objects)
        self.lichess_created: dict[str, int] = {}
        self.lichess_tokens: dict[str, str] = {}  # token -> username
        #: the Lichess account an OAuth sign-in signs in as (set per test)
        self.oauth_user: str | None = None
        self.codes: dict[str, str] = {}
        self.fail_next_429 = 0
        self.requests: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code: int, body, ctype="application/json", headers=None):
                data = body if isinstance(body, bytes) else (
                    body.encode() if isinstance(body, str) else json.dumps(body).encode())
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_a):
                return

            def do_GET(self):  # noqa: N802
                outer.requests.append("GET " + self.path)
                if outer.fail_next_429 > 0:
                    outer.fail_next_429 -= 1
                    return self._send(429, {"error": "slow down"}, headers={"Retry-After": "1"})
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
                if parts[:2] == ["pub", "player"] and len(parts) == 5 and parts[4] == "archives":
                    user = parts[2].lower()
                    if user not in outer.chesscom:
                        return self._send(404, {"message": "not found"})
                    return self._send(200, {"archives": list(outer.chesscom[user])})
                if parts[:2] == ["pub", "player"] and len(parts) == 6 and parts[3] == "games":
                    user = parts[2].lower()
                    full = outer.base + u.path
                    return self._send(200, outer.chesscom.get(user, {}).get(full, {"games": []}))
                if parts[:2] == ["pub", "player"] and len(parts) == 3:
                    user = parts[2].lower()
                    prof = outer.chesscom_profile.get(user)
                    return self._send(200, prof) if prof else self._send(404, {"message": "not found"})
                if parts[:3] == ["api", "games", "user"] and len(parts) == 4:
                    user = parts[3].lower()
                    since = int(q.get("since", ["0"])[0])
                    until = int(q.get("until", [str(10 ** 15)])[0])
                    rows = [g for g in outer.lichess.get(user, []) if since <= g["createdAt"] <= until]
                    rows.sort(key=lambda g: -g["createdAt"])
                    return self._send(200, "\n".join(json.dumps(g) for g in rows) + ("\n" if rows else ""),
                                      "application/x-ndjson")
                if parts[:2] == ["api", "user"] and len(parts) == 3:
                    user = parts[2].lower()
                    if user not in outer.lichess:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, {"id": user, "username": user,
                                            "createdAt": outer.lichess_created.get(user, 1)})
                if parts == ["api", "account"]:
                    tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                    name = outer.lichess_tokens.get(tok)
                    return self._send(200, {"id": name.lower(), "username": name}) if name else \
                        self._send(401, {"error": "No such token"})
                if parts == ["oauth"]:
                    code = secrets.token_urlsafe(8)
                    outer.codes[code] = outer.oauth_user or ""
                    target = q["redirect_uri"][0] + "?" + urllib.parse.urlencode(
                        {"code": code, "state": q["state"][0]})
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                return self._send(404, {"error": "no route"})

            def do_POST(self):  # noqa: N802
                outer.requests.append("POST " + self.path)
                n = int(self.headers.get("Content-Length") or 0)
                form = urllib.parse.parse_qs(self.rfile.read(n).decode())
                if self.path == "/api/token":
                    user = outer.codes.pop(form.get("code", [""])[0], None)
                    if not user or not form.get("code_verifier"):
                        return self._send(400, {"error": "invalid_grant"})
                    tok = "lio_" + secrets.token_urlsafe(12)
                    outer.lichess_tokens[tok] = user
                    return self._send(200, {"access_token": tok, "token_type": "Bearer"})
                return self._send(404, {"error": "no route"})

            def do_DELETE(self):  # noqa: N802
                outer.requests.append("DELETE " + self.path)
                if self.path == "/api/token":
                    tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                    outer.lichess_tokens.pop(tok, None)
                    return self._send(204, b"")
                return self._send(404, {"error": "no route"})

        self.httpd = _QuickServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
