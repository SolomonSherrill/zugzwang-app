"""A small WebSocket client (RFC 6455), standard library only, for the Friends live connection (FRIENDS-2 C).

Enough for the Friends server: a client handshake with extra headers (the signed request's), text frames,
masked as a client must, ping / pong / close, and messages split over continuation frames. TLS through the
same certificate store as the rest of the app (`platform_sync._tls_context`). No new dependency, so the
packaged sidecar freezes as before.
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
import urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(Exception):
    """The connection failed or was closed. `status` is the HTTP status of a refused handshake (0 else),
    `body` its answer."""

    def __init__(self, message: str, status: int = 0, body: bytes = b"") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class WebSocket:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._send_lock = threading.Lock()
        self._buf = b""
        self.closed = False
        self.close_code: int | None = None

    # ── connect ─────────────────────────────────────────────────────────────
    @classmethod
    def connect(cls, url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> "WebSocket":
        u = urllib.parse.urlsplit(url)
        secure = u.scheme in ("wss", "https")
        host = u.hostname or ""
        port = u.port or (443 if secure else 80)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            if secure:
                from zugzwang.core.platform_sync import _tls_context
                ctx = _tls_context() or ssl.create_default_context()
                raw = ctx.wrap_socket(raw, server_hostname=host)
            key = base64.b64encode(os.urandom(16)).decode()
            lines = [f"GET {path} HTTP/1.1", f"Host: {u.netloc}", "Upgrade: websocket", "Connection: Upgrade",
                     f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
            lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
            raw.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
            ws = cls(raw)
            head = ws._read_until(b"\r\n\r\n")
            status_line, *hdrs = head.decode("latin-1").split("\r\n")
            parts = status_line.split(" ", 2)
            status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            fields = {}
            for h in hdrs:
                if ":" in h:
                    k, v = h.split(":", 1)
                    fields[k.strip().lower()] = v.strip()
            if status != 101:
                n = int(fields.get("content-length", "0") or 0)
                body = ws._buf[:n] if n else ws._buf
                try:
                    while n and len(body) < n:
                        more = raw.recv(n - len(body))
                        if not more:
                            break
                        body += more
                except OSError:
                    pass
                raise WebSocketError(f"the server refused the WebSocket (HTTP {status})", status, body)
            want = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            if fields.get("sec-websocket-accept") != want:
                raise WebSocketError("the server's WebSocket handshake did not match")
            raw.settimeout(None)
            return ws
        except BaseException:
            try:
                raw.close()
            except OSError:
                pass
            raise

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WebSocketError("the connection closed during the handshake")
            self._buf += chunk
        head, self._buf = self._buf.split(marker, 1)
        return head

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise WebSocketError("the connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    # ── frames ──────────────────────────────────────────────────────────────
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            if self.closed:
                raise WebSocketError("the connection is closed")
            try:
                self.sock.sendall(head + mask + masked)
            except OSError as exc:
                self.closed = True
                raise WebSocketError(f"send failed: {exc}") from None

    def send(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def ping(self) -> None:
        self._send_frame(0x9, b"")

    def recv(self) -> str:
        """The next text message; answers pings on the way. Raises WebSocketError once closed."""
        parts: list[bytes] = []
        while True:
            try:
                b0, b1 = self._read_exact(2)
            except OSError as exc:
                self.closed = True
                raise WebSocketError(f"the connection failed: {exc}") from None
            fin, opcode = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if b1 & 0x80 else b""
            data = self._read_exact(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                self.close_code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None
                try:
                    self._send_frame(0x8, data[:2])
                except WebSocketError:
                    pass
                self.closed = True
                self._shut()
                raise WebSocketError(f"closed by the server ({self.close_code})")
            if opcode == 0x9:
                try:
                    self._send_frame(0xA, data)
                except WebSocketError:
                    pass
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", errors="replace")

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            try:
                self._send_frame(0x8, struct.pack("!H", code))
            except WebSocketError:
                pass
        self.closed = True
        self._shut()

    def _shut(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
