"""FRIENDS-2 C: the sidecar's WebSocket client (core/friends/ws.py) against a small local server."""
from __future__ import annotations

import base64
import hashlib
import socket
import struct
import threading
import time

import pytest

from zugzwang.core.friends.ws import GUID, WebSocket, WebSocketError


def _frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    head += bytes([n]) if n < 126 else bytes([126]) + struct.pack("!H", n)
    return head + payload


def _read_frame(conn: socket.socket) -> tuple[int, bytes]:
    def exact(k):
        b = b""
        while len(b) < k:
            c = conn.recv(k - len(b))
            if not c:
                raise EOFError
            b += c
        return b
    b0, b1 = exact(2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", exact(2))[0]
    mask = exact(4)
    data = bytes(x ^ mask[i % 4] for i, x in enumerate(exact(n)))
    assert b1 & 0x80, "a client frame is masked"
    return b0 & 0x0F, data


class Server:
    """Accepts one connection; `script(conn, headers)` plays the server's part."""

    def __init__(self, script, status: int = 101):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.headers: dict[str, str] = {}
        self.status = status
        self.script = script
        self.got: list = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.sock.accept()
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += conn.recv(4096)
        lines = buf.split(b"\r\n\r\n")[0].decode().split("\r\n")
        self.request_line = lines[0]
        self.headers = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:])}
        if self.status != 101:
            body = b'{"error":"no_such_game"}'
            conn.sendall(f"HTTP/1.1 {self.status} Not Found\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
            conn.close()
            return
        accept = base64.b64encode(hashlib.sha1((self.headers["sec-websocket-key"] + GUID).encode()).digest()).decode()
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        try:
            self.script(conn, self)
        finally:
            conn.close()


def test_handshake_sends_the_signed_headers_and_messages_go_both_ways():
    def script(conn, srv):
        op, data = _read_frame(conn)
        srv.got.append((op, data))
        conn.sendall(_frame(0x1, b'{"t":"hello"}'))
        # a message in two frames, with a ping between
        conn.sendall(_frame(0x1, b'{"t":"ch', fin=False) + _frame(0x9, b"x") + _frame(0x0, b'unk"}'))
        srv.got.append(_read_frame(conn))      # the pong
        conn.sendall(_frame(0x1, ("é" * 200).encode()))
        conn.sendall(_frame(0x8, struct.pack("!H", 1000)))
        srv.got.append(_read_frame(conn))      # the close echoed
    srv = Server(script)
    ws = WebSocket.connect(f"ws://127.0.0.1:{srv.port}/v1/live?x=1", {"X-Zz-Key": "k1", "X-Zz-Sig": "s1"})
    assert srv.request_line == "GET /v1/live?x=1 HTTP/1.1"
    assert srv.headers["x-zz-key"] == "k1" and srv.headers["x-zz-sig"] == "s1"
    ws.send("ping")
    assert ws.recv() == '{"t":"hello"}'
    assert ws.recv() == '{"t":"chunk"}'
    assert ws.recv() == "é" * 200
    with pytest.raises(WebSocketError):
        ws.recv()
    assert ws.close_code == 1000 and ws.closed
    for _ in range(200):          # the server's thread records the echoed close
        if len(srv.got) == 3:
            break
        time.sleep(0.01)
    assert srv.got[0] == (0x1, b"ping")
    assert srv.got[1] == (0xA, b"x")
    assert srv.got[2][0] == 0x8


def test_a_refused_handshake_reports_the_status_and_body():
    srv = Server(lambda c, s: None, status=404)
    with pytest.raises(WebSocketError) as e:
        WebSocket.connect(f"ws://127.0.0.1:{srv.port}/v1/games/x/live")
    assert e.value.status == 404 and b"no_such_game" in e.value.body


def test_sending_after_close_raises():
    srv = Server(lambda c, s: _read_frame(c))
    ws = WebSocket.connect(f"ws://127.0.0.1:{srv.port}/")
    ws.close()
    with pytest.raises(WebSocketError):
        ws.send("x")
