"""Lichess sign-in for linking an account (FRIENDS.md ruling K1): OAuth 2 with PKCE, no client
secret, no scopes (reading the username needs none), the redirect to a one-off listener on
127.0.0.1. The token goes to the Friends server once (it reads the username and revokes the token) and
is never stored here.

The browser is opened by `webbrowser.open` when the user presses "Sign in with Lichess". For the
headless end-to-end run, ZUGZWANG_OAUTH_OPENER=fetch follows the address with urllib instead (the
fixture server answers it); nothing else sets it.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import threading
import urllib.parse
import urllib.request
import webbrowser

from zugzwang.core.friends.platform_games import lichess_api

CLIENT_ID = "zugzwang-desktop"
TIMEOUT_S = 300


class OAuthError(Exception):
    pass


class _Listener(http.server.HTTPServer):
    """The redirect's listener. No reverse-DNS lookup of 127.0.0.1 at bind (HTTPServer's getfqdn
    can take half a minute on a Mac)."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _open(url: str) -> None:
    if os.environ.get("ZUGZWANG_OAUTH_OPENER") == "fetch":
        threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=30).read(),
                         daemon=True).start()
        return
    if not webbrowser.open(url):
        raise OAuthError("No web browser could be opened for the Lichess sign-in.")


def sign_in(timeout: float = TIMEOUT_S) -> str:
    """Run the sign-in and return Lichess's access token."""
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    got: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got["code"] = q.get("code", [None])[0]
                got["error"] = q.get("error", [None])[0]
                done.set()
            body = ("<html><body style='font-family:sans-serif'><p>You can close this tab and go "
                    "back to Zugzwang.</p></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):     # never log the query (it holds the code)
            return

    server = _Listener(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_address[1]}/"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        url = f"{lichess_api()}/oauth?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect,
            "code_challenge_method": "S256", "code_challenge": challenge, "state": state})
        _open(url)
        if not done.wait(timeout):
            raise OAuthError("The Lichess sign-in was not finished in time.")
        if not got.get("code"):
            raise OAuthError("Lichess sign-in was cancelled." if got.get("error") else
                             "Lichess did not send a sign-in code.")
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": got["code"], "code_verifier": verifier,
            "redirect_uri": redirect, "client_id": CLIENT_ID}).encode()
        req = urllib.request.Request(f"{lichess_api()}/api/token", data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token = json.loads(resp.read()).get("access_token")
        except Exception as exc:
            raise OAuthError("Lichess did not accept the sign-in.") from exc
        if not token:
            raise OAuthError("Lichess did not send a token.")
        return token
    finally:
        server.shutdown()
        server.server_close()
