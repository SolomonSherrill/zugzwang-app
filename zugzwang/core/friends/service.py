"""Friends, as the sidecar uses it: the account (keychain, recovery code, sign-up, recovery, delete),
the server's friends list and requests, presence, and linking accounts. Every network call here blocks:
the sidecar runs them on its Friends thread, never on the dispatch thread.
"""
from __future__ import annotations

import logging
import threading

import zugzwang.config as C
from zugzwang.core.friends import settings as fsettings
from zugzwang.core.friends.chesscom_link import ChesscomLink
from zugzwang.core.friends.client import FriendsClient, FriendsError, server_url
from zugzwang.core.friends.identity import Identity, RecoveryCodeError
from zugzwang.core.friends.keystore import Keystore, KeystoreError, select_keystore

logger = logging.getLogger(__name__)


class FriendsService:
    def __init__(self, keystore: Keystore | None = None, base: str | None = None) -> None:
        self.keystore = keystore or select_keystore()
        self.base = server_url() if base is None else base
        self._identity: Identity | None = None
        self._loaded = False
        self._lock = threading.Lock()
        #: the last friends list the server sent (a friend's profile reads its linked accounts)
        self.last_list: dict | None = None
        #: the pending Chess.com link (BETA-5 ruling K3), kept in the local settings
        self.chesscom = ChesscomLink(lambda: self.client())

    # ── the key ──────────────────────────────────────────────────────────────
    def identity(self) -> Identity | None:
        with self._lock:
            if not self._loaded:
                try:
                    hexed = self.keystore.get()
                    self._identity = Identity(bytes.fromhex(hexed)) if hexed else None
                except (KeystoreError, ValueError) as exc:
                    logger.warning("friends: the keystore could not be read: %s", exc)
                    self._identity = None
                self._loaded = True
            return self._identity

    def _store(self, ident: Identity | None) -> None:
        with self._lock:
            if ident is None:
                self.keystore.delete()
            else:
                self.keystore.set(ident.secret.hex())
            self._identity = ident
            self._loaded = True

    def client(self, ident: Identity | None = None) -> FriendsClient:
        return FriendsClient(self.base, ident or self.identity())

    def state(self) -> dict:
        s = fsettings.load()
        ident = self.identity()
        return {
            "enabled": C.FRIENDS_ENABLED,
            "configured": bool(self.base),
            "server": self.base or None,
            "keystore": {"kind": self.keystore.kind, "label": self.keystore.label,
                         "available": self.keystore.available},
            "signedIn": ident is not None and bool(s.get("handle")),
            "handle": s.get("handle") if ident is not None else None,
            "settings": {"shareGames": bool(s["share_games"]), "appearOffline": bool(s["appear_offline"]),
                         "chatEnabled": bool(s["chat_enabled"])},
        }

    # ── account ──────────────────────────────────────────────────────────────
    def check_handle(self, handle: str) -> dict:
        return self.client().handle_available(handle)

    def signup(self, handle: str, *, age_confirmed: bool, terms_accepted: bool,
               share_games: bool = False) -> dict:
        if not age_confirmed:
            raise FriendsError("age_required", "Confirm you are 13 or older to sign up.")
        if not terms_accepted:
            raise FriendsError("terms_required", "Agree to the Terms of use and the Privacy policy to sign up.")
        if self.identity() is not None and fsettings.load().get("handle"):
            raise FriendsError("signed_in", "This computer already has a Friends account.")
        if not self.keystore.available:
            raise FriendsError("no_keystore", "This computer has no keychain Zugzwang can use, so it "
                               "cannot keep a Friends key.")
        ident = Identity.new()
        # Into the keychain first: an account whose key was lost the moment it was made would be
        # unreachable. A refused sign-up takes the key out again.
        self._store(ident)
        try:
            out = self.client(ident).signup(handle)
        except BaseException:
            self._store(None)
            raise
        fsettings.save(handle=out.get("handle", handle), share_games=bool(share_games),
                       appear_offline=False)
        return {"handle": out.get("handle", handle), "recoveryCode": ident.recovery_code}

    def recovery_code(self) -> str:
        ident = self.identity()
        if ident is None:
            raise FriendsError("no_identity", "There is no Friends account on this computer.")
        return ident.recovery_code

    def save_recovery_code(self, path: str) -> dict:
        """Write the recovery code to *path*, which the save dialog chose (BETA-5 B: the webview cannot
        save a file itself). Owner-only permissions (0600) where the OS has them; on Windows the file
        takes its folder's permissions (the user's own folders are the user's)."""
        import os
        if not isinstance(path, str) or not path.strip() or not os.path.isabs(path):
            raise FriendsError("bad_path", "The app was not given a full path to save the code to.")
        text = ("Zugzwang Friends recovery code\n\n" + self.recovery_code() +
                "\n\nKeep it private: it is the only way back into your account.\n")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
            fd = os.open(path, flags, 0o600)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)        # a file that was there already keeps no wider mode
                os.write(fd, text.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as exc:
            raise FriendsError("save_failed", f"The code could not be saved to {path}: "
                               f"{exc.strerror or exc}.") from None
        return {"path": path}

    def recover(self, code: str) -> dict:
        try:
            ident = Identity.from_code(code)
        except RecoveryCodeError as exc:
            raise FriendsError("bad_code", str(exc)) from None
        me = self.client(ident).me()          # no_account when the code is not an account's
        if not self.keystore.available:
            raise FriendsError("no_keystore", "This computer has no keychain Zugzwang can use.")
        self._store(ident)
        fsettings.save(handle=me.get("handle"), appear_offline=bool(me.get("appear_offline")))
        return {"handle": me.get("handle")}

    def me(self) -> dict:
        return self.client().me()

    def delete_account(self) -> dict:
        try:
            self.client().delete_account()
        except FriendsError as exc:
            if exc.code != "no_account":      # already gone on the server: finish the local part
                raise
        self.forget_local()
        return {"deleted": True}

    def forget_local(self) -> None:
        self._store(None)
        fsettings.clear()           # the pending Chess.com link with the rest
        self.last_list = None

    # ── friends ──────────────────────────────────────────────────────────────
    def friends(self) -> dict:
        out = self.client().friends()
        self.last_list = out
        return out

    def heartbeat(self) -> dict:
        return self.client().heartbeat()

    def set_appear_offline(self, on: bool) -> dict:
        out = self.client().set_appear_offline(on)
        fsettings.save(appear_offline=bool(on))
        return out

    def friend_entry(self, handle: str, *, fresh: bool = False) -> dict | None:
        """The friend's entry in the friends list (their linked accounts, presence); *fresh* asks the
        server again rather than using the last list."""
        lst = self.friends() if fresh or not self.last_list else self.last_list
        for f in lst.get("friends", []):
            if f.get("handle", "").lower() == handle.lower():
                return f
        return None

    def link_lichess(self) -> dict:
        from zugzwang.core.friends import lichess_oauth
        try:
            token = lichess_oauth.sign_in()
        except lichess_oauth.OAuthError as exc:
            raise FriendsError("lichess_sign_in", str(exc)) from None
        return self.client().link_lichess(token)
