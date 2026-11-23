"""FRIENDS-2 C: the app's live connection (core/friends/live.py), its ratings at a game's start
(core/friends/start_ratings.py, rulings R1-R3) and the friend game in the library (G2, migration v21)."""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import zugzwang.config as C
from zugzwang.core import games_list as GL
from zugzwang.core.database import Database
from zugzwang.core.friends import live as L
from zugzwang.core.friends import platform_games as PG
from zugzwang.core.friends import start_ratings as SR
from zugzwang.core.friends.client import FriendsError
from tests.friends_servers import PlatformServer

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_f2", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

_W, _B = "pa", "pb"
PGN = ('[Event "Zugzwang friend game"]\n[Site "Zugzwang"]\n[Date "2026.11.22"]\n[Round "-"]\n'
       + "".join(f'[{k} "{v}"]\n' for k, v in (("White", _W), ("Black", _B)))
       + '[Result "1-0"]\n[Rated "false"]\n[TimeControl "180+2"]\n'
       '[Termination "checkmate"]\n\n1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n')


def state(status="playing", **kw):
    s = {"t": "state", "id": "g" * 16, "you": "white", "tc": "3+2", "status": status, "moves": [],
         "white": {"handle": "pa", "linked": [{"site": "chesscom", "username": "pa_cc"}]},
         "black": {"handle": "pb", "linked": [{"site": "lichess", "username": "pb_li"}]},
         "result": None, "termination": None, "pgn": None, "created": 1_790_000_000_000}
    s.update(kw)
    return s


class FakeSocket:
    made: list["FakeSocket"] = []

    def __init__(self, name, client_fn, path, on_msg, on_conn, on_gone=None):
        self.name, self.path, self.on_msg, self.on_conn, self.on_gone = name, path, on_msg, on_conn, on_gone
        self.want, self.connected, self.sent = True, True, []
        FakeSocket.made.append(self)

    def send(self, msg):
        self.sent.append(msg)

    def stop(self):
        self.want = False


class FakeClient:
    def __init__(self):
        self.acked: list[str] = []
        self.results: dict[str, dict] = {}

    def game_ack(self, gid):
        self.acked.append(gid)
        return {"status": "saved"}

    def game(self, gid):
        return self.results[gid]


@pytest.fixture
def link(monkeypatch):
    FakeSocket.made = []
    monkeypatch.setattr(L, "_Socket", FakeSocket)
    events: list[tuple[str, dict]] = []
    saved: list[tuple] = []
    client = FakeClient()
    ratings_calls: list[str] = []

    def ratings(st):
        ratings_calls.append(st["id"])
        return {"white": {"rating": 1446, "estimated": False}, "black": {"rating": 1390, "estimated": True}}

    lk = L.LiveLink(lambda: client, lambda name, p: events.append((name, p)),
                    lambda gid, st, r: saved.append((gid, st, r)) or 77, ratings_fn=ratings)
    lk.ensure()
    return SimpleNamespace(lk=lk, events=events, saved=saved, client=client, ratings=ratings_calls)


def wait_for(pred, s=2.0):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_hello_lists_challenges_and_reopens_live_games(link):
    lobby = FakeSocket.made[0]
    assert lobby.path == "/v1/live"
    lobby.on_msg({"t": "hello", "challenges": [{"id": "c1", "created": 2}, {"id": "c0", "created": 1}],
                  "games": [{"id": "a" * 16, "status": "live"}]})
    snap = link.lk.snapshot()
    assert [c["id"] for c in snap["challenges"]] == ["c0", "c1"]
    assert FakeSocket.made[1].path == f"/v1/games/{'a' * 16}/live"
    assert link.events[-1][0] == "friends_live" and link.events[-1][1]["kind"] == "hello"


def test_a_challenge_arrives_and_goes_as_events(link):
    lobby = FakeSocket.made[0]
    lobby.on_msg({"t": "challenge", "challenge": {"id": "c9", "from_handle": "maxk", "tc": "5+0"}})
    assert link.events[-1][1]["kind"] == "challenge" and link.lk.snapshot()["challenges"][0]["id"] == "c9"
    lobby.on_msg({"t": "challenge_gone", "id": "c9", "reason": "expired"})
    assert link.events[-1][1]["reason"] == "expired" and link.lk.snapshot()["challenges"] == []


def test_the_ratings_are_taken_once_at_the_start_and_sent_with_the_state(link):
    gid = "g" * 16
    link.lk.open_game(gid)
    sock = FakeSocket.made[-1]
    sock.on_msg(state(status="waiting"))
    assert wait_for(lambda: gid in link.lk.ratings)
    sock.on_msg(state(moves=["e2e4"]))
    assert link.ratings == [gid]
    assert any(e[1].get("kind") == "ratings" for e in link.events)


def test_a_finished_game_is_saved_once_and_acknowledged_when_its_screen_closes(link):
    gid = "g" * 16
    link.lk.open_game(gid)
    sock = FakeSocket.made[-1]
    sock.on_msg(state(status="waiting"))
    over = state(status="over", result="1-0", termination="checkmate", pgn=PGN)
    sock.on_msg(over)
    sock.on_msg(over)
    assert len(link.saved) == 1 and link.saved[0][2]["white"]["rating"] == 1446
    assert ("friend_game", {"id": gid, "kind": "saved", "gameId": 77}) in link.events
    assert link.client.acked == []           # still open: chat and a rematch reach the screen
    link.lk.close_game(gid)
    assert link.client.acked == [gid] and not sock.want


def test_an_aborted_game_saves_nothing_and_is_acknowledged_at_once(link):
    gid = "h" * 16
    link.lk.open_game(gid)
    FakeSocket.made[-1].on_msg(state(id=gid, status="over", result="*", termination="aborted"))
    assert link.saved == [] and link.client.acked == [gid]


def test_a_game_that_ended_while_away_is_fetched_saved_and_acknowledged(link):
    gid = "i" * 16
    link.client.results[gid] = state(id=gid, status="over", result="1-0", termination="resign", pgn=PGN)
    FakeSocket.made[0].on_msg({"t": "hello", "challenges": [], "games": [{"id": gid, "status": "over"}]})
    assert wait_for(lambda: link.client.acked == [gid])
    assert link.saved[0][0] == gid


def test_a_new_game_acknowledges_the_finished_one(link):
    old, new = "j" * 16, "k" * 16
    link.lk.open_game(old)
    FakeSocket.made[-1].on_msg(state(id=old, status="over", result="1-0", pgn=PGN))
    FakeSocket.made[0].on_msg({"t": "game_start", "game": {"id": new, "status": "live"}})
    assert link.client.acked == [old]


def test_chat_is_kept_in_memory_only_and_capped(link):
    gid = "g" * 16
    link.lk.open_game(gid)
    sock = FakeSocket.made[-1]
    for n in range(L.CHAT_KEEP + 5):
        sock.on_msg({"t": "chat", "from": "black", "handle": "pb", "text": f"m{n}", "at": n})
    view = link.lk.game_view(gid)
    assert len(view["chat"]) == L.CHAT_KEEP and view["chat"][-1]["text"] == f"m{L.CHAT_KEEP + 4}"


def test_send_passes_game_messages_and_refuses_others(link):
    gid = "g" * 16
    link.lk.open_game(gid)
    link.lk.send(gid, {"t": "move", "uci": "e2e4", "ply": 0})
    assert FakeSocket.made[-1].sent == [{"t": "move", "uci": "e2e4", "ply": 0}]
    with pytest.raises(FriendsError):
        link.lk.send(gid, {"t": "takeback"})          # P4
    with pytest.raises(FriendsError):
        link.lk.send("z" * 16, {"t": "resign"})


# ── ratings at the start (R1-R3) ────────────────────────────────────────────────

@pytest.fixture
def sites(monkeypatch):
    s = PlatformServer()
    monkeypatch.setenv("ZUGZWANG_CHESSCOM_API", s.base)
    monkeypatch.setenv("ZUGZWANG_LICHESS_API", s.base)
    monkeypatch.setattr(PG, "GAP_S", 0.0)
    yield s
    s.close()


def test_r1_the_chesscom_rating_of_the_mode(sites):
    sites.chesscom_stats["maxk_cc"] = {"chess_blitz": {"last": {"rating": 1446}}, "chess_rapid": {"last": {"rating": 1520}}}
    linked = [{"site": "chesscom", "username": "MaxK_cc"}]
    assert SR.rating_for(linked, "5+0") == {"rating": 1446, "estimated": False, "site": "chesscom", "speed": "blitz"}
    assert SR.rating_for(linked, "30+0")["rating"] == 1520       # rapid (Chess.com has no classical)
    assert SR.rating_for(linked, "1+0")["rating"] is None        # R3: no bullet rating, blank


def test_r2_a_lichess_only_player_gets_the_estimate(sites):
    sites.lichess_perfs["benji"] = {"blitz": {"rating": 1700}, "classical": {"rating": 1900}}
    r = SR.rating_for([{"site": "lichess", "username": "benji"}], "3+2")
    from zugzwang.core.friends import rating_compare
    assert r == {"rating": rating_compare.lichess_to_chesscom(1700, "blitz"), "estimated": True,
                 "site": "lichess", "speed": "blitz"}
    assert SR.rating_for([{"site": "lichess", "username": "benji"}], "30+0")["rating"] == \
        rating_compare.lichess_to_chesscom(1900, "classical")


def test_r3_blank_when_unknown_or_unreachable(sites):
    assert SR.rating_for([], "5+0")["rating"] is None
    assert SR.rating_for([{"site": "chesscom", "username": "nobody"}], "5+0")["rating"] is None
    sites.lichess_perfs["x"] = {"blitz": {"rating": 99999}}       # off the ChessGoals table
    assert SR.rating_for([{"site": "lichess", "username": "x"}], "5+0")["rating"] is None


def test_lichess_modes_follow_lichess_own_estimate():
    assert [SR.lichess_speed(*SR.parse_tc(tc)) for tc in ("1+0", "2+1", "3+0", "5+3", "10+0", "15+10", "30+0")] == \
        ["bullet", "bullet", "blitz", "blitz", "rapid", "rapid", "classical"]


# ── the library (G2, migration v21) ─────────────────────────────────────────────

def test_friend_games_count_in_insights():
    assert "friends" in C.INSIGHTS_SOURCES


def test_migration_v21_and_the_start_ratings_columns(tmp_path):
    db = Database(tmp_path / "z.db")
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(games)")}
    assert {"start_white_rating", "start_black_rating", "start_white_est", "start_black_est"} <= cols
    Database(tmp_path / "z.db").close()         # re-running the migrations is harmless
    db.close()


def _fake_server(db):
    queued = []
    return SimpleNamespace(_db=db, _openings=None, queued=queued,
                           rpc_analyze_pending=lambda game_ids, depth: queued.append((game_ids, depth)))


def test_a_friend_game_is_saved_with_the_friends_source_and_queued_at_depth_14(tmp_path):
    db = Database(tmp_path / "z.db")
    fake = _fake_server(db)
    st = state(status="over", result="1-0", termination="checkmate", pgn=PGN, moves=["e2e4"] * 7)
    ratings = {"white": {"rating": 1446, "estimated": False}, "black": {"rating": 1390, "estimated": True}}
    gid = sidecar.Server._save_friend_game(fake, "g" * 16, st, ratings)
    again = sidecar.Server._save_friend_game(fake, "g" * 16, st, ratings)
    assert again == gid
    rec = db.get_game(gid)
    assert (rec.source, rec.external_id, rec.player_color, rec.result, rec.termination, rec.skill_level) == \
        ("friends", "g" * 16, "white", "1-0", "checkmate", 0)
    assert (rec.start_white_rating, rec.start_white_est, rec.start_black_rating, rec.start_black_est) == (1446, 0, 1390, 1)
    assert rec.played_at.startswith("2026-09-21")
    assert fake.queued == [([gid], C.ANALYSIS_STANDARD_DEPTH)] and C.ANALYSIS_STANDARD_DEPTH == 14
    d = sidecar._game_dict(rec)
    assert d["startRatings"] == {"white": {"rating": 1446, "estimated": False}, "black": {"rating": 1390, "estimated": True}}
    assert d["whiteElo"] is None and d["rated"] is False       # R3: apart from the real rating fields; unrated
    page = GL.games_page(db._conn, GL.GamesQuery.from_params({"source": "friends"}))
    assert page["total"] == 1 and page["games"][0]["startRatings"]["black"]["estimated"] is True
    db.close()


def test_blank_ratings_store_null(tmp_path):
    db = Database(tmp_path / "z.db")
    fake = _fake_server(db)
    st = state(status="over", result="1-0", termination="resign", pgn=PGN, you="black")
    gid = sidecar.Server._save_friend_game(fake, "n" * 16, st,
                                           {"white": {"rating": None, "estimated": False}, "black": None})
    rec = db.get_game(gid)
    assert (rec.start_white_rating, rec.start_black_rating, rec.termination, rec.player_color) == (None, None, "resignation", "black")
    assert sidecar._game_dict(rec)["startRatings"] is None
    db.close()


def test_the_ratings_preview_is_cached_ten_minutes(sites, monkeypatch):
    """The banner's and popover's ratings line (FRIENDS-2 D): both players, asked of the sites once."""
    sites.chesscom_stats["maxk_cc"] = {"chess_blitz": {"last": {"rating": 1446}}}
    sites.lichess_perfs["me_li"] = {"blitz": {"rating": 1700}}
    lk = L.LiveLink(lambda: None, lambda *_: None, lambda *_: None)
    lk._rating_cache = {}
    mine, theirs = [{"site": "lichess", "username": "me_li"}], [{"site": "chesscom", "username": "maxk_cc"}]
    out = lk.preview_ratings(mine, theirs, "5+0")
    assert out["them"]["rating"] == 1446 and out["you"]["estimated"] is True
    n = len(sites.requests)
    assert lk.preview_ratings(mine, theirs, "5+0") == out
    assert len(sites.requests) == n, "a second ask within ten minutes asks no site"
