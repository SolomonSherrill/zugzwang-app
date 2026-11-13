"""Platform-sync fetch-layer tests (Phase 2, priority 5).

The network is mocked at urllib.request.urlopen (for _http_get) and at
_http_get_json (for the Chess.com archive walk), so these tests exercise retry/
error handling and the variant/setup filters without any real HTTP.
"""

import email.message
import urllib.error

import pytest

from zugzwang.core import platform_sync as ps
from zugzwang.core.platform_sync import (
    SyncError,
    _http_get,
    _tag_rated,
    fetch_chesscom_pgn,
    fetch_lichess_pgn,
    _CHESSCOM_STANDARD_SETUP,
)


class FakeResp:
    def __init__(self, body: str):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, f"status {code}", hdrs, None)


# ── _http_get ────────────────────────────────────────────────────────────────

def test_http_get_returns_decoded_body(monkeypatch):
    monkeypatch.setattr(ps.urllib.request, "urlopen", lambda *a, **k: FakeResp("hello"))
    assert _http_get("http://x", {}) == "hello"


def test_http_get_404_is_user_not_found(monkeypatch):
    def boom(*a, **k):
        raise _http_error(404)
    monkeypatch.setattr(ps.urllib.request, "urlopen", boom)
    with pytest.raises(SyncError, match="User not found"):
        _http_get("http://x", {})


def test_http_get_url_error_is_network_error(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(ps.urllib.request, "urlopen", boom)
    with pytest.raises(SyncError, match="Network error"):
        _http_get("http://x", {})


def test_http_get_other_http_error_propagates_code(monkeypatch):
    def boom(*a, **k):
        raise _http_error(500)
    monkeypatch.setattr(ps.urllib.request, "urlopen", boom)
    with pytest.raises(SyncError, match="HTTP 500"):
        _http_get("http://x", {})


def test_http_get_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}
    slept = []

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, retry_after=7)
        return FakeResp("ok")

    monkeypatch.setattr(ps.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(ps.time, "sleep", lambda s: slept.append(s))
    assert _http_get("http://x", {}) == "ok"
    assert calls["n"] == 2
    assert slept == [7.0]   # honoured the Retry-After header


def test_http_get_persistent_429_gives_up(monkeypatch):
    def always_429(*a, **k):
        raise _http_error(429, retry_after=1)
    monkeypatch.setattr(ps.urllib.request, "urlopen", always_429)
    monkeypatch.setattr(ps.time, "sleep", lambda s: None)
    with pytest.raises(SyncError, match="HTTP 429"):
        _http_get("http://x", {})


# ── _tag_rated ───────────────────────────────────────────────────────────────

def test_tag_rated_true_and_false():
    assert _tag_rated("[Event \"x\"]", True).startswith('[Rated "true"]\n')
    assert _tag_rated("[Event \"x\"]", False).startswith('[Rated "false"]\n')
    assert _tag_rated("body", None).startswith('[Rated "false"]\n')  # bool(None) -> False


# ── empty-username guards ────────────────────────────────────────────────────

def test_fetch_lichess_empty_username():
    with pytest.raises(SyncError, match="No Lichess username"):
        fetch_lichess_pgn("   ")


def test_fetch_chesscom_empty_username():
    with pytest.raises(SyncError, match="No Chess.com username"):
        fetch_chesscom_pgn("   ")


# ── Chess.com variant / setup filtering ──────────────────────────────────────

def _game(event, *, rules="chess", setup=_CHESSCOM_STANDARD_SETUP, rated=True):
    pgn = f'[Event "{event}"]\n\n1. e4 e5 *'
    g = {"rules": rules, "pgn": pgn, "rated": rated}
    if setup is not None:
        g["initial_setup"] = setup
    return g


def _mock_archives(monkeypatch, games):
    archives_url = "https://api.chess.com/pub/player/bob/games/archives"

    def fake_json(url):
        if url == archives_url:
            return {"archives": ["https://api.chess.com/month/1"]}
        return {"games": games}

    monkeypatch.setattr(ps, "_http_get_json", fake_json)


def test_chesscom_excludes_variants_and_custom_setups(monkeypatch):
    games = [
        _game("Standard", rated=True),
        _game("Chess960", rules="chess960"),
        _game("Odds", setup="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN1 w Qkq - 0 1"),
        _game("Casual", rated=False),
    ]
    _mock_archives(monkeypatch, games)
    out = fetch_chesscom_pgn("bob")
    assert "Standard" in out
    assert "Casual" in out
    assert "Chess960" not in out
    assert "Odds" not in out


def test_chesscom_tags_rated_flag(monkeypatch):
    _mock_archives(monkeypatch, [_game("Rated", rated=True), _game("Unrated", rated=False)])
    out = fetch_chesscom_pgn("bob")
    assert '[Rated "true"]' in out
    assert '[Rated "false"]' in out


def test_chesscom_respects_max_games(monkeypatch):
    games = [_game(f"G{i}") for i in range(5)]
    _mock_archives(monkeypatch, games)
    out = fetch_chesscom_pgn("bob", max_games=2)
    # Exactly two games collected -> two PGN blocks.
    assert out.count("[Event") == 2


def test_chesscom_missing_setup_treated_as_standard(monkeypatch):
    # A game with no initial_setup key at all must be kept (defaults to standard).
    _mock_archives(monkeypatch, [_game("NoSetup", setup=None)])
    out = fetch_chesscom_pgn("bob")
    assert "NoSetup" in out
