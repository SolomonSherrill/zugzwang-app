"""Where the recovery secret lives (FRIENDS.md ruling A2): the OS keychain, never the database or its
backups.

- macOS: the login Keychain, through `/usr/bin/security` (the secret goes in on stdin, `security -i`,
  never on a command line other processes can read).
- Windows: the Credential Manager (`CredWriteW` / `CredReadW` / `CredDeleteW`, a generic credential).
- Linux: the Secret Service through `secret-tool` when it is installed; otherwise none.
- `ZUGZWANG_KEYSTORE=file:<path>`: a JSON file, **for tests and the headless end-to-end run only** (the
  test suite sets it for every test, tests/conftest.py, so no test touches a real keychain).
  `ZUGZWANG_KEYSTORE=none`: no keystore (Friends says it cannot keep a key on this computer).

One entry: service `dev.zugzwang.friends` (a checkout's dev run) or `dev.zugzwang.desktop.friends` (a
packaged build, named by the beta's app identifier), account `identity`; the value is the secret in hex.
The two differ so a dev run and an installed beta on the same computer never share, or overwrite, one
key (BETA-5 C), as their app ids and data folders differ.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import zugzwang.config as C

SERVICE_DEV = "dev.zugzwang.friends"
SERVICE_PACKAGED = "dev.zugzwang.desktop.friends"
SERVICE = SERVICE_PACKAGED if C.FROZEN else SERVICE_DEV
ACCOUNT = "identity"


class KeystoreError(RuntimeError):
    """The keystore could not be read or written (the message is for the user)."""


class Keystore:
    kind = "none"
    #: shown in Settings: where the key is kept
    label = "nowhere: this computer has no keychain Zugzwang can use"
    available = False

    def get(self) -> str | None:
        return None

    def set(self, value: str) -> None:
        raise KeystoreError("This computer has no keychain Zugzwang can use, so it cannot keep a "
                            "Friends key.")

    def delete(self) -> None:
        return None


class FileKeystore(Keystore):
    kind = "file"
    available = True

    def __init__(self, path: Path) -> None:
        self.path = path
        self.label = f"a test file ({path.name})"

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self) -> str | None:
        return self._read().get(SERVICE, {}).get(ACCOUNT)

    def set(self, value: str) -> None:
        data = self._read()
        data.setdefault(SERVICE, {})[ACCOUNT] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def delete(self) -> None:
        data = self._read()
        if data.get(SERVICE, {}).pop(ACCOUNT, None) is not None:
            self.path.write_text(json.dumps(data))


class MacKeychain(Keystore):
    kind = "macos"
    label = "the macOS Keychain"
    available = True
    SECURITY = "/usr/bin/security"

    def __init__(self, keychain: str | None = None) -> None:
        #: an explicit keychain file (tests); None is the user's default (login) keychain
        self.keychain = keychain

    def _tail(self) -> list[str]:
        return [self.keychain] if self.keychain else []

    def get(self) -> str | None:
        r = subprocess.run([self.SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", SERVICE,
                            "-w", *self._tail()], capture_output=True, text=True, timeout=30)
        if r.returncode == 44:          # errSecItemNotFound
            return None
        if r.returncode != 0:
            raise KeystoreError(f"The Keychain could not be read ({r.stderr.strip() or r.returncode}).")
        return r.stdout.strip() or None

    def set(self, value: str) -> None:
        if not all(c in "0123456789abcdef" for c in value):
            raise ValueError("the stored value is hex")
        tail = (" " + self.keychain) if self.keychain else ""
        cmd = f"add-generic-password -U -a {ACCOUNT} -s {SERVICE} -l Zugzwang-Friends -w {value}{tail}\n"
        r = subprocess.run([self.SECURITY, "-i"], input=cmd, capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise KeystoreError(f"The Keychain refused the key ({(r.stderr or '').strip() or r.returncode}).")

    def delete(self) -> None:
        subprocess.run([self.SECURITY, "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE,
                        *self._tail()], capture_output=True, text=True, timeout=30)


class WindowsCredentials(Keystore):
    kind = "windows"
    label = "the Windows Credential Manager"
    available = True
    TARGET = f"{SERVICE}/{ACCOUNT}"

    def _api(self):
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        adv = ctypes.WinDLL("advapi32", use_last_error=True)   # type: ignore[attr-defined]
        return ctypes, CREDENTIAL, adv

    def get(self) -> str | None:
        ctypes, CREDENTIAL, adv = self._api()
        p = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(self.TARGET, 1, 0, ctypes.byref(p)):
            if ctypes.get_last_error() == 1168:     # ERROR_NOT_FOUND
                return None
            raise KeystoreError(f"The Credential Manager could not be read ({ctypes.get_last_error()}).")
        try:
            c = p.contents
            return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("ascii")
        finally:
            adv.CredFree(p)

    def set(self, value: str) -> None:
        ctypes, CREDENTIAL, adv = self._api()
        blob = value.encode("ascii")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        c = CREDENTIAL()
        c.Type = 1                       # CRED_TYPE_GENERIC
        c.TargetName = self.TARGET
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        c.Persist = 2                    # CRED_PERSIST_LOCAL_MACHINE
        c.UserName = ACCOUNT
        if not adv.CredWriteW(ctypes.byref(c), 0):
            raise KeystoreError(f"The Credential Manager refused the key ({ctypes.get_last_error()}).")

    def delete(self) -> None:
        _ctypes, _c, adv = self._api()
        adv.CredDeleteW(self.TARGET, 1, 0)


class SecretTool(Keystore):
    kind = "secret-service"
    label = "the Secret Service (secret-tool)"
    available = True

    def get(self) -> str | None:
        r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "account", ACCOUNT],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, value: str) -> None:
        r = subprocess.run(["secret-tool", "store", "--label=Zugzwang Friends", "service", SERVICE,
                            "account", ACCOUNT], input=value, capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            raise KeystoreError(f"The Secret Service refused the key ({r.stderr.strip()}).")

    def delete(self) -> None:
        subprocess.run(["secret-tool", "clear", "service", SERVICE, "account", ACCOUNT],
                       capture_output=True, text=True, timeout=30)


def select_keystore() -> Keystore:
    env = os.environ.get("ZUGZWANG_KEYSTORE", "")
    if env.startswith("file:"):
        return FileKeystore(Path(env[5:]))
    if env == "none":
        return Keystore()
    if sys.platform == "darwin" and Path(MacKeychain.SECURITY).exists():
        return MacKeychain()
    if sys.platform == "win32":
        return WindowsCredentials()
    if shutil.which("secret-tool"):
        return SecretTool()
    return Keystore()
