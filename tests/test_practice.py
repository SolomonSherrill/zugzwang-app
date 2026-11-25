"""COACH-2 C: Practice (COACH.md "COACH-2: the spec", ruling CP1), with a fake clock. Constructed positions only (no
owner game)."""
import sqlite3
import types
from datetime import datetime, timedelta, timezone

import pytest

import sidecar.main as sidecar
from zugzwang.core import coach as CO
from zugzwang.core import practice as P
from zugzwang.core.database import Database

FORK_FEN = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"          # Nc7+ forks the king and the rook on a8
T0 = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)


def _item(i, *, grp="chance:knightFork", kind="find", played_at="2026-11-01", source="game", theme="knightFork"):
    return P.Item(id=i, source=source, kind=kind, theme=theme, grp=grp, fen=FORK_FEN, answer_uci="b5c7",
                  line_uci=["b5c7", "e8d7", "c7a8"], played_uci="e1e2", game_key=f"g{i}", ply=10, played_at=played_at)


def test_the_schedule_is_the_log_replayed():
    ats = [P.Attempt(1, T0, True), P.Attempt(1, T0 + timedelta(days=3), True)]
    a = P.card_for(1, ats)
    b = P.card_for(1, list(reversed(ats)))
    assert a.due == b.due and a.stability == b.stability           # the same log, the same card
    assert P.card_for(1, []) is None                                # never attempted: new
    assert P.rating_of(P.Attempt(1, T0, True)).name == "Good"
    assert P.rating_of(P.Attempt(1, T0, True, hint=True)).name == "Hard"
    assert P.rating_of(P.Attempt(1, T0, False)).name == "Again"
    assert P.rating_of(P.Attempt(1, T0, True, revealed=True)).name == "Again"
    first_right = P.card_for(1, [P.Attempt(1, T0, True)])
    first_wrong = P.card_for(1, [P.Attempt(1, T0, False)])
    assert first_wrong.due < first_right.due                        # a miss comes back sooner
    assert first_wrong.due.date() > T0.date()                       # but on a later day: no same-day steps


def test_comes_back_in_words():
    assert P.comes_back(T0 + timedelta(days=1), T0) == "Comes back tomorrow."
    assert P.comes_back(T0 + timedelta(days=4), T0) == "Comes back in 4 days."
    assert P.comes_back(T0 + timedelta(days=21), T0) == "Comes back in 3 weeks."
    assert P.short_when(T0 + timedelta(days=9), T0) == "In 9 days"
    assert P.short_when(T0 + timedelta(days=1), T0) == "Tomorrow"


def test_the_daily_cap_and_the_feed_order():
    """New items: at most NEW_PER_DAY a day; focus groups first, then the newest game."""
    items = [_item(i, grp="threat:pin" if i % 2 else "chance:knightFork", kind="threat" if i % 2 else "find",
                   played_at=f"2026-10-{10 + i:02d}") for i in range(1, 15)]
    q = P.build_queue(items, {}, T0, focus_keys=["threat:pin"])
    assert len(q.new) == P.NEW_PER_DAY and q.due == []
    pins = [it.id for it in q.new if it.grp == "threat:pin"]
    assert [it.id for it in q.new][:len(pins)] == pins                 # focus first
    assert pins == sorted(pins, reverse=True)                          # then newest first
    # ten answered today: no new one left today; tomorrow ten more
    log = {it.id: [P.Attempt(it.id, T0 - timedelta(hours=1), True)] for it in q.new}
    assert P.build_queue(items, log, T0).new == []
    tomorrow = P.build_queue(items, log, T0 + timedelta(days=1))
    assert len(tomorrow.new) == len(items) - P.NEW_PER_DAY
    # a focus card's Practise narrows to its group
    assert {it.grp for it in P.build_queue(items, {}, T0, grp="threat:pin").new} == {"threat:pin"}


def test_a_due_item_comes_back_on_its_day():
    items = [_item(1)]
    log = {1: [P.Attempt(1, T0, True)]}
    due = P.card_for(1, log[1]).due
    assert P.build_queue(items, log, T0 + timedelta(hours=1)).due == []
    assert [it.id for it in P.build_queue(items, log, due).due] == [1]


def test_about_one_new_item_in_five_is_a_probe_and_none_without_puzzles():
    items = [_item(i) for i in range(1, 30)]
    q = P.build_queue(items, {}, T0, probes=True)
    assert q.probe_slots == [4, 9]                                     # the 5th and 10th new items
    assert sum(1 for it in q.new if it is not None) == P.NEW_PER_DAY - 2
    assert P.build_queue(items, {}, T0, probes=False).probe_slots == []
    # an unattempted probe is reused before a new one is drawn
    probe = _item(99, source="probe", grp="probe:fork", theme="fork")
    q2 = P.build_queue(items + [probe], {}, T0, probes=True)
    assert q2.new[4] is probe and q2.probe_slots == [9]


def test_items_from_a_game_are_its_missed_moments_with_a_theme():
    after = "r3k3/8/8/1N6/8/8/4K3/8 b - - 1 1"
    moments = [
        CO.Moment(ply=0, kind="chance", outcome="missed", themes=["knightFork", "fork"], fen=FORK_FEN,
                  line=["b5c7", "e8d7", "c7a8"], played="e1e2", key_move="b5c7", move_type="check", mate=False, gain=5),
        CO.Moment(ply=0, kind="chance", outcome="caught", themes=["pin"], fen=FORK_FEN, line=["b5c7"],
                  played="b5c7", key_move="b5c7", move_type="check", mate=False, gain=5),
        CO.Moment(ply=0, kind="threat", outcome="missed", themes=[], fen=after, line=["a8a2"], played="e1e2",
                  key_move="a8a2", move_type="other", mate=False, gain=5),
        CO.Moment(ply=0, kind="threat", outcome="missed", themes=["hangingPiece"], fen=after, line=["a8a2"],
                  played="e1e2", key_move="a8a2", move_type="other", mate=False, gain=3),
    ]
    g = CO.GameMoments(game_id=5, key="x1", played_at="2026-11-01", colour="white", opponent="Someone",
                       fens={0: FORK_FEN}, moments=moments, run_id=8)
    got = P.items_from_game(g, {0: "b5c7"})
    assert [(i.kind, i.theme, i.fen, i.answer_uci) for i in got] == [
        ("find", "knightFork", FORK_FEN, "b5c7"), ("threat", "hangingPiece", FORK_FEN, "b5c7")]
    v = P.view(got[0])
    assert "theme" not in v and v["hintSquare"] == "b5" and v["played"] == "1. Ke2"


def test_the_reveal_names_the_theme_and_when_it_comes_back():
    it = _item(1)
    r = P.reveal(it, "b5c7", True, False, ["chance:knightFork"], T0 + timedelta(days=4), T0)
    assert r["verdict"] == "right" and r["sentence"] == "You found it: 1. Nc7+ starts a knight fork."
    assert r["theme"] == "Knight fork" and r["focus"] is True and r["comesBack"] == "Comes back in 4 days."
    no = P.reveal(it, "e1e2", False, False, [], T0 + timedelta(days=1), T0)
    assert no["verdict"] == "notQuite" and no["sentence"] == "Not 1. Ke2: 1. Nc7+ starts a knight fork."
    assert no["focus"] is False


@pytest.fixture
def server(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(sidecar, "_emit", lambda e, d: sent.append((e, d)))
    clock = {"now": T0}
    monkeypatch.setattr(sidecar, "_utcnow", lambda: clock["now"])
    srv = object.__new__(sidecar.Server)
    srv._db = Database(tmp_path / "p.db")
    srv._coach = types.SimpleNamespace(latest={"overview": {"focus": [{"key": "chance:knightFork"}]}})
    srv.clock = clock
    srv.sent = sent
    return srv


def test_the_attempt_log_is_append_only(server):
    server._db.add_practice_items([_item(0)])
    iid = server._db.practice_items()[0]["id"]
    server.rpc_practice_answer(iid, "b5c7", True, 4200)
    with pytest.raises(sqlite3.IntegrityError):
        server._db._conn.execute("UPDATE practice_attempts SET correct = 0")
    with pytest.raises(sqlite3.IntegrityError):
        server._db._conn.execute("DELETE FROM practice_attempts")
    row = server._db.practice_attempt_rows()[0]
    assert (row["item_id"], row["kind"], row["source"], row["answer_uci"], row["correct"], row["time_ms"],
            row["hint"], row["revealed"]) == (iid, "find", "game", "b5c7", 1, 4200, 0, 0)
    assert row["at"] == T0.isoformat()


def test_a_session_day_by_day(server):
    server._db.add_practice_items([_item(i, played_at=f"2026-10-{i + 1:02d}") for i in range(12)])
    st = server.rpc_practice_status()
    assert st["due"] == P.NEW_PER_DAY and st["new"] == P.NEW_PER_DAY and st["probes"] is False
    s = server.rpc_practice_session()
    assert len(s["items"]) == P.NEW_PER_DAY and all("theme" not in v for v in s["items"])
    first = s["items"][0]["id"]
    out = server.rpc_practice_answer(first, "b5c7", True, 3000, session=s["session"])
    assert out["verdict"] == "right" and out["focus"] is True and out["comesBack"].startswith("Comes back")
    assert server.sent[-1][0] == "practice_updated" and server.sent[-1][1]["due"] == P.NEW_PER_DAY - 1
    # the answer shown counts as wrong, whatever is sent
    out = server.rpc_practice_answer(s["items"][1]["id"], None, True, 9000, revealed=True)
    assert out["verdict"] == "notQuite"
    # the next day: the item answered wrong is due, and new ones within the cap
    server.clock["now"] = T0 + timedelta(days=3)
    s2 = server.rpc_practice_session()
    assert s["items"][1]["id"] in [v["id"] for v in s2["items"]]
    with pytest.raises(RuntimeError):
        server.rpc_practice_answer(first, "a1a8", True)                 # not a legal move there


def test_probes_come_from_unseen_puzzles_near_the_rating(server):
    db = server._db
    server._db.add_practice_items([_item(i) for i in range(12)])
    for k, rating in enumerate((1500, 1520, 2400)):
        db._conn.execute("INSERT INTO puzzles (id, fen, moves_uci, rating, rating_deviation, popularity, nb_plays,"
                         " themes, game_url, opening_tags, imported_at) VALUES (?, ?, ?, ?, 80, 90, 100, ?, '', '', ?)",
                         (f"pz{k}", "r3k3/8/8/8/8/8/1N6/4K3 b - - 0 1", "e8d8 b2c4", rating, "fork short",
                          T0.isoformat()))
    db._conn.execute("INSERT INTO pz.puzzle_themes_fts(puzzle_themes_fts) VALUES('rebuild')")
    db.mark_puzzles_imported(3)
    db.save_puzzle_rating(1510, 80, 0.06)
    db._conn.execute("INSERT INTO puzzle_attempts (puzzle_id, mode, attempted_at) VALUES ('pz1', 'rated', ?)",
                     (T0.isoformat(),))
    db._conn.commit()
    s = server.rpc_practice_session()
    probes = [v for v in s["items"] if v["source"] == "probe"]
    assert len(probes) == 1                         # one fork puzzle is unseen near 1500 (pz1 was tried, pz2 is far)
    assert probes[0]["puzzleRating"] == 1500 and probes[0]["side"] == "white"
    assert probes[0]["oppMove"] == "1... Kd8"
    pid = probes[0]["id"]
    out = server.rpc_practice_answer(pid, "b2c4", True, 5000)
    assert out["verdict"] == "right" and out["sentence"] == "You found it: 2. Nc4."
    row = [r for r in db.practice_attempt_rows() if r["item_id"] == pid][0]
    assert row["source"] == "probe"                 # its first attempt is the transfer measurement


def test_the_report_says_added_to_practice(server):
    srv = server
    srv._db.add_practice_items([P.Item(id=0, source="game", kind="find", theme="knightFork", grp="chance:knightFork",
                                       fen=FORK_FEN, answer_uci="b5c7", game_key="local-1", ply=10)])
    assert srv._db.practice_keys_for_game("local-1") == {(10, "find")}
