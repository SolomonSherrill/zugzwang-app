"""UI-BUILD-3 E: the Games screen's list (core/games_list.py, `rpc_games_page`): filters, the
game-id search, sorts, each month's record over every game the filters keep (not only the page),
both accuracies from the standard run (no error counts: the stacked list has no "Your errors"
column, UI-BUILD-4 B), and Import PGN's games queued for depth-14 analysis
(`rpc_analyze_pending(game_ids=...)`). Constructed games, players "alice" and "bob"."""
from datetime import timezone

import pytest

from zugzwang.core import games_list as GL
from zugzwang.core.database import Database, MoveAnalysis
from tests.test_sidecar_rpc import sidecar

UTC = timezone.utc
FEN0 = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _pgn(white="alice", black="bob", tc="180+2", result="1-0", extra=""):
    return (f'[Event "Live Chess"]\n[White "{white}"]\n[Black "{black}"]\n[WhiteElo "1500"]\n'
            f'[BlackElo "1400"]\n[TimeControl "{tc}"]\n[Result "{result}"]\n{extra}\n'
            f'1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 {result}\n')


def _save(db, *, at, color="white", result="1-0", source="chesscom", ext=None,
          tc="180+2", white="alice", black="bob", eco=None, name=None, extra=""):
    return db.save_game(played_at=at, player_color=color, skill_level=0, result=result,
                        termination="resignation", move_count=6,
                        pgn=_pgn(white, black, tc, result, extra), final_fen=FEN0,
                        opening_eco=eco, opening_name=name, source=source, external_id=ext)


def _plies(classes):
    classes = list(classes) + ["best"] * (6 - len(classes))     # every game here is 6 plies
    return [MoveAnalysis(ply=i, fen_before=FEN0, played_uci="e2e4", best_uci="e2e4",
                         pv_uci="e2e4", score_before_cp=0, score_before_mate=None,
                         score_after_cp=0, score_after_mate=None, second_best_uci=None,
                         second_best_cp=None, second_best_mate=None, classification=c,
                         is_book=False) for i, c in enumerate(classes)]


def _run(db, gid, classes, depth=14, acc=(80.0, 70.0)):
    rid = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=depth)
    db.complete_analysis_run(rid, {}, white_accuracy=acc[0], black_accuracy=acc[1],
                             plies=_plies(classes))
    return rid


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "g.db")
    yield d
    d.close()


def page(db, **params):
    return GL.games_page(db._conn, GL.GamesQuery.from_params(params), tz=UTC)


def ids(res):
    return [g["id"] for g in res["games"]]


def test_month_records_count_every_game_the_filters_keep_not_only_the_page(db):
    nov = [_save(db, at=f"2026-11-{d:02d}T10:00:00+00:00", result=r, ext=f"n{d}")
           for d, r in ((1, "1-0"), (2, "0-1"), (3, "1-0"), (4, "1/2-1/2"), (5, "*"))]
    _save(db, at="2026-10-30T10:00:00+00:00", result="0-1", ext="o1")
    res = page(db, limit=2)
    assert ids(res) == [nov[4], nov[3]]                     # newest first, one page of two
    assert (res["total"], res["all"]) == (6, 6)
    assert res["months"] == [
        {"month": "2026-11", "games": 5, "won": 2, "lost": 1, "drawn": 1},
        {"month": "2026-10", "games": 1, "won": 0, "lost": 1, "drawn": 0},
    ]
    # under a filter, the record is the filter's
    won = page(db, result="win", limit=1)
    assert won["total"] == 2 and won["months"] == [{"month": "2026-11", "games": 2, "won": 2, "lost": 0, "drawn": 0}]


def test_months_are_local_calendar_months(db):
    _save(db, at="2026-11-01T02:00:00+00:00", ext="a")
    q = GL.GamesQuery()
    from datetime import timedelta, timezone as tzm
    west = tzm(timedelta(hours=-5))                         # 21:00 on 31 October there
    assert [m["month"] for m in GL.games_page(db._conn, q, tz=west)["months"]] == ["2026-10"]


def test_result_is_the_users_side_and_unknown_or_unfinished_match_none(db):
    w = _save(db, at="2026-11-01T10:00:00+00:00", color="white", result="1-0", ext="w")
    l = _save(db, at="2026-11-02T10:00:00+00:00", color="black", result="1-0", ext="l")
    d = _save(db, at="2026-11-03T10:00:00+00:00", result="1/2-1/2", ext="d")
    _save(db, at="2026-11-04T10:00:00+00:00", result="*", ext="u")
    assert ids(page(db, result="win")) == [w]
    assert ids(page(db, result="loss")) == [l]
    assert ids(page(db, result="draw")) == [d]
    assert [g["outcome"] for g in page(db)["games"]] == [None, "draw", "loss", "win"]


def test_colour_source_rated_speed_daily_opening_and_analysis_filters(db):
    a = _save(db, at="2026-11-01T10:00:00+00:00", color="black", ext="a", extra='[Rated "true"]',
              eco="B01", name="Scandinavian Defense: Valencian Variation")
    b = _save(db, at="2026-11-02T10:00:00+00:00", ext="b", tc="60",
              extra='[Rated "false"]', eco="C55", name="Italian Game: Two Knights Defense")
    c = _save(db, at="2026-11-03T10:00:00+00:00", ext="c", tc="1/86400")
    loc = _save(db, at="2026-11-04T10:00:00+00:00", source="local", tc="-",
                white="You", black="Stockfish")
    imp = _save(db, at="2026-11-05T10:00:00+00:00", source="imported", ext="i", tc="?")
    _run(db, a, ["best", "best"])
    assert ids(page(db, color="black")) == [a]
    assert ids(page(db, source="local")) == [loc]
    assert ids(page(db, source="imported")) == [imp]
    assert ids(page(db, rated="rated")) == [a]
    assert ids(page(db, rated="casual")) == [b]
    assert ids(page(db, speeds=["daily"])) == [c]
    assert ids(page(db, speeds=["bullet", "blitz"])) == [b, a]
    assert ids(page(db, speeds=["nonsense"])) == [imp, loc, c, b, a]   # unknown speeds ignored
    assert ids(page(db, opening="valencian")) == [a]
    assert ids(page(db, opening="c55")) == [b]
    assert ids(page(db, analysis="analyzed")) == [a]
    assert set(ids(page(db, analysis="unanalyzed"))) == {b, c, loc, imp}
    item = {g["id"]: g for g in page(db)["games"]}
    assert item[c]["speedBucket"] == "daily" and item[c]["timeControl"] == "1/86400"
    assert item[imp]["timeControl"] is None and item[loc]["timeControl"] is None
    assert item[a]["blackElo"] == 1400 and item[a]["black"] == "bob"


def test_since_is_inclusive_and_until_exclusive(db):
    a = _save(db, at="2026-11-01T00:00:00+00:00", ext="a")
    b = _save(db, at="2026-11-02T00:00:00+00:00", ext="b")
    _save(db, at="2026-11-03T00:00:00+00:00", ext="c")
    assert ids(page(db, since="2026-11-01T00:00:00Z", until="2026-11-03T00:00:00Z")) == [b, a]


def test_search_finds_a_game_by_id_exactly_or_text_as_a_substring(db):
    a = _save(db, at="2026-11-01T10:00:00+00:00", ext="4417",
              name="Sicilian Defense 483", eco="B22")
    b = _save(db, at="2026-11-18T10:00:00+00:00", ext="AbCdEfGh", source="lichess")
    assert ids(page(db, search="4417")) == [a]
    assert ids(page(db, search="abcdefgh")) == [b]          # a Lichess id, any case
    assert ids(page(db, search=f"#{b}")) == [b]             # the app's id
    assert ids(page(db, search="#483")) == []               # "#" names an id only, never text
    assert ids(page(db, search="483")) == [a]               # a bare number still finds text
    assert ids(page(db, search="90000000")) == []           # an id is never a substring
    assert ids(page(db, search="sicilian")) == [a]
    assert ids(page(db, search="b22")) == [a]
    assert ids(page(db, search="18 nov 2026")) == [b]       # the date as the list shows it
    assert GL.matches_id("#12", 12, None) and not GL.matches_id("#12", 120, None)


def test_the_opponent_is_the_other_side_and_stockfish_for_games_played_here(db):
    _save(db, at="2026-11-01T10:00:00+00:00", color="black", white="bob", black="alice", ext="x")
    _save(db, at="2026-11-02T10:00:00+00:00", source="local", white="You", black="Stockfish")
    assert ids(page(db, search="bob")) and not ids(page(db, search="alice"))
    assert len(ids(page(db, search="stockfish"))) == 1


def test_both_accuracies_come_from_the_standard_run_and_no_error_counts_are_sent(db):
    white = _save(db, at="2026-11-01T10:00:00+00:00", color="white", ext="w")
    black = _save(db, at="2026-11-02T10:00:00+00:00", color="black", ext="b")
    none = _save(db, at="2026-11-04T10:00:00+00:00", ext="n")
    _run(db, white, ["blunder", "mistake"], acc=(80.0, 70.0))
    _run(db, black, ["best"], acc=(61.5, 88.25))
    _run(db, white, ["best"] * 6, depth=24, acc=(99.0, 99.0))   # a deeper Analyse again run: not read
    games = {g["id"]: g for g in page(db)["games"]}
    acc = {i: (g["whiteAccuracy"], g["blackAccuracy"], g["analyzed"]) for i, g in games.items()}
    assert acc[white] == (80.0, 70.0, True)
    assert acc[black] == (61.5, 88.25, True)
    assert acc[none] == (None, None, False)
    assert all("errors" not in g for g in games.values())   # the "Your errors" column is gone
    # both ratings and both names, for the two lines of each row
    assert (games[black]["white"], games[black]["whiteElo"]) == ("alice", 1500)
    assert (games[black]["black"], games[black]["blackElo"]) == ("bob", 1400)


def test_sorts_keep_unanalysed_games_last_and_pages_follow_the_order(db):
    a = _save(db, at="2026-11-01T10:00:00+00:00", ext="a", name="Ruy Lopez")
    b = _save(db, at="2026-11-02T10:00:00+00:00", ext="b", name="Caro-Kann Defense")
    c = _save(db, at="2026-11-03T10:00:00+00:00", ext="c", name="Ruy Lopez")
    _run(db, a, ["best"], acc=(60.0, 50.0))
    _run(db, b, ["best"], acc=(90.0, 50.0))
    assert ids(page(db, sort="accuracy_low")) == [a, b, c]
    assert ids(page(db, sort="accuracy_high")) == [b, a, c]
    assert ids(page(db, sort="oldest")) == [a, b, c]
    assert ids(page(db, sort="opening")) == [b, c, a]       # by name, newest first within one
    assert ids(page(db, sort="nonsense")) == [c, b, a]
    assert ids(page(db, sort="accuracy_low", offset=1, limit=1)) == [b]


def test_the_rpc_reads_its_params(db):
    _save(db, at="2026-11-01T10:00:00+00:00", ext="a")
    server = object.__new__(sidecar.Server)
    server._db = db
    res = server.rpc_games_page(result="win", speeds=["blitz"], offset=0, limit=10)
    assert res["total"] == 1 and res["games"][0]["externalId"] == "a"


# ── Import PGN: the imported games analysed at depth 14 ─────────────────────

def test_games_with_standard_run_is_the_pending_test_for_a_set(db):
    a = _save(db, at="2026-11-01T10:00:00+00:00", source="imported", ext="a")
    b = _save(db, at="2026-11-02T10:00:00+00:00", source="imported", ext="b")
    c = _save(db, at="2026-11-03T10:00:00+00:00", source="imported", ext="c")
    _run(db, a, ["best"])
    _run(db, b, ["best"], depth=24)                        # deeper only: still pending
    assert db.games_with_standard_run([a, b, c], 14) == {a}
    assert db.games_with_standard_run([], 14) == set()


def test_analyse_pending_with_game_ids_queues_exactly_those_games(db, tmp_path):
    a = _save(db, at="2026-11-01T10:00:00+00:00", source="imported", ext="a")
    b = _save(db, at="2026-11-02T10:00:00+00:00", source="imported", ext="b")
    c = _save(db, at="2026-11-03T10:00:00+00:00", source="chesscom", ext="c")
    _save(db, at="2026-11-04T10:00:00+00:00", source="imported", ext="other")
    _run(db, a, ["best"])
    seen = {}

    class FakeSync:
        def running(self):
            return False

        def start_analyze(self, **kw):
            seen.update(kw)
    server = object.__new__(sidecar.Server)
    server._sync = FakeSync()
    server._db = db
    server._db_path = tmp_path / "g.db"
    out = server.rpc_analyze_pending(game_ids=[a, b, c])
    assert out["count"] == 2
    assert {s: [r.id for r in recs] for s, recs in seen["chosen"].items()} == {
        "chesscom": [c], "imported": [b]}
    assert seen["depth"] == 14


def test_the_runner_takes_a_chosen_queue_of_any_source(tmp_path, monkeypatch):
    d = Database(tmp_path / "q.db")
    b = _save(d, at="2026-11-02T10:00:00+00:00", source="imported", ext="b")
    recs = {"imported": [d.get_game(b)]}
    d.close()
    monkeypatch.setattr(sidecar, "_emit", lambda *a, **k: None)
    r = sidecar.SyncRunner(lambda fn: fn(), sidecar.EngineBudget(cores=1, idle_ceiling=1))
    taken = []

    def fake(db_, openings, rec):
        taken.append(rec.id)
        _run(db_, rec.id, ["best"])
        return True
    r._analyze_from_evals = fake
    try:
        r._run_analyze(["imported"], tmp_path / "q.db", 14, None, recs)
    finally:
        r._quit_engine()
    assert taken == [b]
    d = Database(tmp_path / "q.db")
    assert d.games_with_standard_run([b], 14) == {b}
    d.close()
