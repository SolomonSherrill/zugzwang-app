"""FRIENDS-1 C: friends' public games (G1, G3, G5), their tables, and the engine-free figures (S3)."""
from datetime import datetime, timedelta, timezone

import pytest

from tests import friends_fixtures as FX
from tests.friends_servers import PlatformServer
from zugzwang.core.database import Database
from zugzwang.core.friends import platform_games as PG
from zugzwang.core.friends import scouting
from zugzwang.core.friends.runner import list_payload, profile_payload

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def sites(monkeypatch):
    s = PlatformServer()
    monkeypatch.setenv("ZUGZWANG_CHESSCOM_API", s.base)
    monkeypatch.setenv("ZUGZWANG_LICHESS_API", s.base)
    monkeypatch.setattr(PG, "GAP_S", 0.0)
    yield s
    s.close()


@pytest.fixture
def eco():
    return PG.eco_only_book()


def test_chesscom_fetches_the_last_12_months_first_then_older_on_request(sites, eco):
    sites.chesscom["friend_a"] = FX.chesscom_archives("friend_a", NOW, n=150, days=720, base=sites.base)
    months = sorted(sites.chesscom["friend_a"])
    first = PG.fetch_chesscom("friend_a", now=NOW, eco_book=eco)
    assert first["oldest"] == (2025, 12)
    assert not first["complete"]
    fetched_months = [r for r in sites.requests if "/games/20" in r]
    assert len(fetched_months) == sum(1 for m in months if m.split("/")[-2:] >= ["2025", "12"])
    assert all(r["ended_at"] >= "2025-12-01" for r in first["rows"])
    older = PG.fetch_chesscom("friend_a", now=NOW, older_than=first["oldest"], eco_book=eco)
    assert older["rows"] and all(r["ended_at"] < "2025-12-01" for r in older["rows"])
    assert older["oldest"] == (2024, 12) and not older["complete"]      # 25 months of archives
    last = PG.fetch_chesscom("friend_a", now=NOW, older_than=older["oldest"], eco_book=eco)
    assert last["oldest"] == (2024, 11) and last["complete"]


def test_rows_carry_headers_and_moves_only(sites, eco):
    sites.chesscom["friend_a"] = FX.chesscom_archives("friend_a", NOW, n=40, base=sites.base)
    rows = PG.fetch_chesscom("friend_a", now=NOW, eco_book=eco)["rows"]
    r = next(x for x in rows if x["opening"])
    assert r["site"] == "chesscom" and r["player"] == "friend_a"
    assert r["eco"] and r["first_move"] in ("e2e4", "d2d4", "f2f3")
    assert r["termination"] in ("checkmate", "resignation", "timeout", "agreement", "draw")
    assert set(r) >= {"white", "black", "white_elo", "black_elo", "result", "speed", "ended_at", "pgn"}
    assert len(r["platform_id"]) < 9


def test_lichess_window_and_statuses(sites, eco):
    sites.lichess["friend_l"] = FX.lichess_games("friend_l", NOW, n=50, days=500)
    rows = PG.fetch_lichess("friend_l", since=PG.window_start(NOW), eco_book=eco)
    assert rows and all(r["ended_at"] >= "2025-11-20" for r in rows)
    assert {r["termination"] for r in rows} <= {"checkmate", "resignation", "timeout", "draw"}
    assert all(r["site"] == "lichess" for r in rows)


def test_one_request_at_a_time_and_the_site_is_waited_for(sites, eco, monkeypatch):
    sites.chesscom["friend_a"] = FX.chesscom_archives("friend_a", NOW, n=10, base=sites.base)
    waits = []
    monkeypatch.setattr(PG.time, "sleep", lambda s: waits.append(s))
    sites.fail_next_429 = 2
    PG.fetch_chesscom("friend_a", now=NOW, eco_book=eco)
    assert waits[:2] == [1.0, 1.0]          # the server's Retry-After, twice
    assert PG._LOCK.acquire(blocking=False)
    PG._LOCK.release()


def test_unknown_player_is_no_games(sites, eco):
    assert PG.fetch_chesscom("nobody_here", now=NOW, eco_book=eco)["rows"] == []
    assert PG.fetch_lichess("nobody_here", since=PG.window_start(NOW), eco_book=eco) == []


def _stored(tmp_path, eco, sites):
    sites.chesscom["friend_a"] = FX.chesscom_archives(
        "friend_a", NOW, n=120, base=sites.base,
        opponents=["me_on_chesscom", "rook_lift_demo", "gambit_goblin_demo"])
    db = Database(tmp_path / "z.db")
    rows = PG.fetch_chesscom("friend_a", now=NOW, eco_book=eco)["rows"]
    assert db.save_friend_games(rows) == len(rows)
    assert db.save_friend_games(rows) == 0          # stored once
    return db, rows


def test_friend_games_never_reach_your_games_or_insights(tmp_path, sites, eco):
    db, rows = _stored(tmp_path, eco, sites)
    assert db._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
    assert db._conn.execute("SELECT COUNT(*) FROM friend_games").fetchone()[0] == len(rows)
    assert db.delete_friend_data(None) == len(rows)


def test_the_profile_figures(tmp_path, sites, eco):
    db, rows = _stored(tmp_path, eco, sites)
    entry = {"handle": "friend-a", "linked": [{"site": "chesscom", "username": "friend_a"}]}
    p = profile_payload(db, entry, {"chesscom": "me_on_chesscom"})
    # head to head: only the games against your linked account, from your side
    vs_me = [r for r in rows if "me_on_chesscom" in (r["white"], r["black"])]
    assert p["record"]["games"] == len(vs_me) > 0
    assert p["record"]["won"] == sum(1 for r in vs_me if scouting.outcome_for(
        r, scouting.side_of(r, "me_on_chesscom")) == "won")
    assert all(g["where"] == "Chess.com" for g in p["together"])
    # FRIENDS-1B D: each game together carries your colour, for its square
    stored = {r["id"]: r for r in db.friend_games_of([("chesscom", "friend_a")])}
    assert all(g["color"] == scouting.side_of(stored[g["id"]], "me_on_chesscom") for g in p["together"]) and {g["color"] for g in p["together"]} <= {"white", "black"}
    # scouting: As White counts only their White games, grouped by family
    white_games = [r for r in rows if r["white"] == "friend_a" and r["opening"]]
    assert sum(x["games"] for x in p["scouting"]["asWhite"]) <= len(white_games)
    assert p["scouting"]["asWhite"][0]["games"] >= p["scouting"]["asWhite"][-1]["games"]
    assert all(x["opening"] and ":" not in x["opening"] for x in p["scouting"]["asWhite"])
    assert p["scouting"]["vsE4"] and p["scouting"]["vsD4"]
    # endings add up
    e = p["endings"]
    assert e["games"] == len(rows)
    assert abs(e["won"]["pct"] + e["lost"]["pct"] + e["draws"]["pct"] - 100) <= 1
    assert sum(x["games"] for x in p["bySpeed"]) == len(rows)
    assert p["ratings"] and p["ratings"][0]["site"] == "chesscom"
    assert p["recentTotal"] == len(rows) and len(p["recent"]) == 10
    assert p["data"]["stale"] is True          # never marked fetched


def test_ratings_and_the_lichess_estimate():
    rows = [{"id": i, "site": "lichess", "platform_id": str(i), "player": "x", "white": "x", "black": "y",
             "white_elo": 1700 + i, "black_elo": 1500, "result": "1-0", "speed": "blitz", "rated": 1,
             "ended_at": (NOW - timedelta(days=40 - i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "termination": "resignation"}
            for i in range(20)]
    r = scouting.ratings(rows, NOW)
    assert r[0]["rating"] == 1719 and r[0]["delta30"] == 1719 - 1710
    # FRIENDS-1B D: the sparkline starts where the 30-day change counts from and ends at the rating shown
    assert r[0]["spark"] == list(range(1710, 1720))
    li = scouting.list_ratings(r)
    assert li[0]["approx"] is True and li[0]["speed"] == "blitz" and li[0]["rating"] == 1449


def test_the_sparkline_series():
    assert scouting.spark_series([1500]) == [] and scouting.spark_series([]) == []
    assert scouting.spark_series([1500, 1510]) == [1500, 1510]
    long = list(range(100))
    s = scouting.spark_series(long)
    assert len(s) == scouting.SPARK_POINTS and s[0] == 0 and s[-1] == 99 and s == sorted(s)
    # no games in the last 30 days: no line (and no 30-day change)
    old = [{"id": 1, "site": "chesscom", "platform_id": "1", "player": "x", "white": "x", "black": "y",
            "white_elo": 1600, "black_elo": 1500, "result": "1-0", "speed": "rapid", "rated": 1,
            "ended_at": (NOW - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"), "termination": "resignation"}]
    r = scouting.ratings(old, NOW)
    assert r[0]["spark"] == [] and r[0]["delta30"] is None


def test_endings_buckets():
    def g(res, term):
        return {"player": "x", "white": "x", "black": "y", "result": res, "termination": term}
    e = scouting.endings([g("1-0", "checkmate"), g("1-0", "resignation"), g("0-1", "timeout"),
                          g("1/2-1/2", "agreement")])
    assert e["draws"]["pct"] == 25 and e["won"]["pct"] == 50 and e["lost"]["pct"] == 25
    assert e["won"]["by"] == {"mate": 50, "resigned": 50, "time": 0, "other": 0}
    assert e["lost"]["by"]["time"] == 100


def test_friends_list_payload(tmp_path, sites, eco):
    db, _ = _stored(tmp_path, eco, sites)
    lst = {"friends": [{"handle": "friend-a", "online": True, "linked": [{"site": "chesscom", "username": "friend_a"}]},
                       {"handle": "no-links", "online": False, "linked": []}], "incoming": [], "outgoing": []}
    out = list_payload(db, lst, {"chesscom": "me_on_chesscom"})
    a, b = out["friends"]
    assert a["hasData"] and a["ratings"] and a["record"]["games"] > 0 and a["lastGame"]
    assert not b["hasData"] and b["ratings"] == [] and b["lastGame"] is None
