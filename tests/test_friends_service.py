"""FRIENDS-1 C: the account on this computer against a stand-in Friends server that checks every
signature as the real one does (server/src/auth.ts); the real Worker is checked end to end by
sidecar/friends_e2e.py."""
import hashlib
import json
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from zugzwang.core.friends import ed25519
from zugzwang.core.friends import settings as fsettings
from zugzwang.core.friends.client import SIG_PREFIX, FriendsError
from zugzwang.core.friends.identity import Identity
from zugzwang.core.friends.keystore import FileKeystore
from zugzwang.core.friends.service import FriendsService
import base64


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class FakeFriendsServer:
    def __init__(self):
        self.accounts = {}      # key -> handle
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                return

            def _reply(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                if self.path.startswith("/v1/handles/"):
                    h = self.path.rsplit("/", 1)[1]
                    taken = h.lower() in {v.lower() for v in outer.accounts.values()}
                    return self._reply(200, {"handle": h, "available": not taken,
                                             "reason": "taken" if taken else None})
                key, t, nonce, sig = (self.headers.get(k) for k in ("X-Zz-Key", "X-Zz-Time", "X-Zz-Nonce", "X-Zz-Sig"))
                msg = "\n".join([SIG_PREFIX, method, self.path, t or "", nonce or "",
                                 hashlib.sha256(body).hexdigest()]).encode()
                if not (key and sig and ed25519.verify(_unb64(key), msg, _unb64(sig))):
                    return self._reply(401, {"error": "bad_signature", "message": "bad"})
                if abs(int(t) - time.time() * 1000) > 60000:
                    return self._reply(401, {"error": "stale", "message": "stale"})
                outer.seen.append((method, self.path))
                data = json.loads(body or b"{}")
                if self.path == "/v1/signup":
                    if data.get("handle", "").lower() in {v.lower() for v in outer.accounts.values()}:
                        return self._reply(409, {"error": "handle_taken", "message": "That handle is taken."})
                    outer.accounts[key] = data["handle"]
                    return self._reply(201, {"handle": data["handle"], "created": 1})
                if key not in outer.accounts:
                    return self._reply(401, {"error": "no_account", "message": "No account has this key."})
                if self.path == "/v1/me":
                    return self._reply(200, {"handle": outer.accounts[key], "linked": [], "appear_offline": False})
                if self.path == "/v1/account" and method == "DELETE":
                    del outer.accounts[key]
                    return self._reply(200, {"status": "deleted"})
                if self.path == "/v1/friends":
                    return self._reply(200, {"friends": [], "incoming": [], "outgoing": [], "blocked": []})
                return self._reply(404, {"error": "not_found", "message": "no"})

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

            def do_DELETE(self):  # noqa: N802
                self._handle("DELETE")

        class S(ThreadingHTTPServer):
            def server_bind(self):
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

        self.httpd = S(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def fake():
    s = FakeFriendsServer()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


def test_sign_up_keeps_the_key_in_the_keystore_and_never_the_database(fake, tmp_path):
    ks = FileKeystore(tmp_path / "keys.json")
    svc = FriendsService(keystore=ks, base=fake.base)
    assert svc.check_handle("pawn_one") == {"handle": "pawn_one", "available": True, "reason": None}
    out = svc.signup("pawn_one", age_confirmed=True, terms_accepted=True, share_games=True)
    assert out["handle"] == "pawn_one"
    assert Identity.from_code(out["recoveryCode"]).secret.hex() == ks.get()
    st = svc.state()
    assert st["signedIn"] and st["handle"] == "pawn_one" and st["settings"]["shareGames"] is True
    assert fake.seen[0] == ("POST", "/v1/signup")
    # the database and the settings file never hold the secret
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.name != "keys.json":
            assert ks.get() not in p.read_bytes().decode("utf-8", "replace")


def test_sign_up_needs_both_boxes(fake, tmp_path):
    svc = FriendsService(keystore=FileKeystore(tmp_path / "k.json"), base=fake.base)
    with pytest.raises(FriendsError) as e:
        svc.signup("x_one", age_confirmed=False, terms_accepted=True)
    assert e.value.code == "age_required"
    with pytest.raises(FriendsError) as e:
        svc.signup("x_one", age_confirmed=True, terms_accepted=False)
    assert e.value.code == "terms_required"
    assert fake.seen == []


def test_a_refused_sign_up_leaves_no_key(fake, tmp_path):
    FriendsService(keystore=FileKeystore(tmp_path / "a.json"), base=fake.base).signup(
        "taken_one", age_confirmed=True, terms_accepted=True)
    ks = FileKeystore(tmp_path / "b.json")
    with pytest.raises(FriendsError) as e:
        FriendsService(keystore=ks, base=fake.base).signup("TAKEN_ONE", age_confirmed=True, terms_accepted=True)
    assert e.value.code == "handle_taken" and ks.get() is None


def test_recovery_on_another_computer_then_delete(fake, tmp_path, monkeypatch):
    a = FriendsService(keystore=FileKeystore(tmp_path / "a.json"), base=fake.base)
    code = a.signup("roamer", age_confirmed=True, terms_accepted=True)["recoveryCode"]
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr("zugzwang.config.USER_DIR", other)
    b = FriendsService(keystore=FileKeystore(other / "k.json"), base=fake.base)
    assert not b.state()["signedIn"]
    with pytest.raises(FriendsError) as e:
        b.recover("not a code")
    assert e.value.code == "bad_code"
    assert b.recover(code.lower()) == {"handle": "roamer"}
    assert b.state()["signedIn"] and b.state()["handle"] == "roamer"
    assert b.recovery_code() == code
    assert b.delete_account() == {"deleted": True}
    assert not b.state()["signedIn"] and fsettings.load()["handle"] is None
    assert FileKeystore(other / "k.json").get() is None
    with pytest.raises(FriendsError) as e:
        a.me()
    assert e.value.code == "no_account"


def test_the_app_names_the_deployed_server():
    """FRIENDS-1B ruling V8 (2026-11-22): dev and beta builds use https://api.zugzwangapp.com. Read from the
    source: the suite's conftest blanks the constant so that no test reaches the real server."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "zugzwang/config.py").read_text()
    assert re.search(r'^FRIENDS_SERVER_URL = "https://api\.zugzwangapp\.com"$', src, re.M)


def test_no_server_configured(tmp_path):
    svc = FriendsService(keystore=FileKeystore(tmp_path / "k.json"), base="")
    assert svc.state()["configured"] is False
    with pytest.raises(FriendsError) as e:
        svc.check_handle("abc")
    assert e.value.code == "not_configured"


def test_sidecar_refuses_friends_methods_when_friends_is_off(monkeypatch):
    from tests.test_sidecar_rpc import sidecar
    frames = []
    monkeypatch.setattr(sidecar, "_send", lambda obj: frames.append(obj))
    server = object.__new__(sidecar.Server)
    monkeypatch.setattr(sidecar.C, "FRIENDS_ENABLED", False)
    server._handle_request({"id": 7, "method": "friends_status", "params": {}})
    assert frames == [{"id": 7, "error": {"message": "Friends is not in this build of Zugzwang."}}]
