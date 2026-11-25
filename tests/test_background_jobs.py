"""COACH-2 D (rulings CB1, CB2): a run is over once its end is announced, and every event and status carries the run's
id, so a status check made on the end never revives it (the stuck "Syncing: fetching your games…" card)."""
import threading
import time
import types

import pytest

import sidecar.main as sidecar


@pytest.fixture
def events(monkeypatch):
    got = []
    monkeypatch.setattr(sidecar, "_emit", lambda e, d: got.append((e, d)))
    return got


def test_the_sync_is_not_running_once_sync_finished_is_emitted(events, monkeypatch, tmp_path):
    """The order that left the card stuck: sync_finished is emitted in the worker's finally while its thread is
    alive, and the coach's on_finished is posted after it; a sync_status asked on sync_finished said syncing: true."""
    seen = {}
    release = threading.Event()
    posted = []

    def post(fn):
        posted.append(fn)
        release.wait(5)          # the thread stays alive after sync_finished, as the coach's post kept it

    runner = sidecar.SyncRunner(post)
    runner.on_finished = lambda: None
    monkeypatch.setattr(runner, "_sync_source", lambda *a, **k: (0, 0))
    monkeypatch.setattr(sidecar, "OpeningsBook", lambda: types.SimpleNamespace(close=lambda: None))
    real_emit = sidecar._emit

    def spy(e, d):
        real_emit(e, d)
        if e == "sync_finished":
            seen["running_at_finished"] = runner.running()
            seen["alive"] = runner._thread.is_alive()
    monkeypatch.setattr(sidecar, "_emit", spy)
    runner.start(jobs=[("lichess", "someone")], usernames=["someone"], db_path=tmp_path / "z.db", depth=14)
    for _ in range(200):
        if "running_at_finished" in seen:
            break
        time.sleep(0.01)
    assert seen == {"running_at_finished": False, "alive": True}
    assert runner.running() is False                 # the thread still lives (posting), the run is over
    release.set()
    runner._thread.join(5)
    names = [e for e, _ in events]
    assert names[-2:] == ["sync_done", "sync_finished"]
    assert all(d.get("run") == 1 for _, d in events)
    assert len(posted) == 1


def test_every_run_has_its_own_id_on_status_and_events(events, monkeypatch, tmp_path):
    runner = sidecar.SyncRunner(lambda fn: None)
    monkeypatch.setattr(runner, "_sync_source", lambda *a, **k: (0, 0))
    monkeypatch.setattr(sidecar, "OpeningsBook", lambda: types.SimpleNamespace(close=lambda: None))
    for want in (1, 2):
        runner.start(jobs=[("lichess", "someone")], usernames=["someone"], db_path=tmp_path / "z.db", depth=14)
        runner._thread.join(5)
        assert runner.run_id == want and not runner.running()
    assert [d["run"] for e, d in events if e == "sync_finished"] == [1, 2]


def test_a_status_check_reports_the_run_id(monkeypatch, tmp_path):
    from zugzwang.core.database import Database
    server = object.__new__(sidecar.Server)
    server._db = Database(tmp_path / "z.db")
    server._sync = types.SimpleNamespace(running=lambda: False, run_id=7)
    st = server.rpc_sync_status()
    assert st["syncing"] is False and st["run"] == 7


def test_a_puzzle_import_is_over_when_its_end_is_announced(events):
    """The same race in the puzzle import: puzzle_import_done is posted to the app thread while the import's thread
    still lives; the lobby's status check on it read importing: true."""
    release = threading.Event()
    state = {}
    runner = sidecar.PuzzleImportRunner(lambda fn: fn())

    def gen(cancelled):
        yield ("progress", 10, 100, 5)
        yield ("done", {"count": 1})
        release.wait(5)          # still alive after the end was announced

    def on_done(stats):
        state["running_at_done"] = runner.running()
    runner._start("lichess", gen, on_done)
    for _ in range(200):
        if "running_at_done" in state:
            break
        time.sleep(0.01)
    assert state == {"running_at_done": False}
    assert runner._thread.is_alive() and not runner.running()
    release.set()
    runner._thread.join(5)
    assert runner.run_id == 1


def test_background_jobs_reports_a_game_analysis_until_its_end(events, monkeypatch, tmp_path):
    from zugzwang.core.database import Database
    monkeypatch.setattr(sidecar, "_ma_dict", lambda ma: {})
    server = object.__new__(sidecar.Server)
    server._db = Database(tmp_path / "z.db")
    server._sync = sidecar.SyncRunner(lambda fn: None)
    server._importer = sidecar.PuzzleImportRunner(lambda fn: fn())
    server._coach_reading = None
    server._analysis_jobs[5] = {"gameId": 3, "runId": 5, "depth": 24, "done": 0, "total": 0}
    server._analysis_jobs[6] = {"gameId": 4, "runId": 6, "depth": 14, "done": 0, "total": 0}
    server._db.save_move_analysis = lambda run_id, ma: None
    server._on_analysis_event(4, 6, ("ply", 37, 90, types.SimpleNamespace()))
    assert server.rpc_background_jobs()["analysis"] == {"gameId": 4, "runId": 6, "depth": 14, "done": 38, "total": 90}
    assert events[-1][0] == "analysis_ply" and events[-1][1]["runId"] == 6 and events[-1][1]["depth"] == 14
    server._on_analysis_event(3, 5, ("cancelled",))          # the run before, cancelled by the new one
    assert events[-1] == ("analysis_cancelled", {"gameId": 3, "runId": 5, "depth": 24})
    assert server.rpc_background_jobs()["analysis"]["runId"] == 6
    server._on_analysis_event(4, 6, ("error", "boom"))
    assert server.rpc_background_jobs()["analysis"] is None
    jobs = server.rpc_background_jobs()
    assert jobs["sync"] == {"running": False, "run": 0, "kind": None, "progress": None}
    assert jobs["puzzles"]["running"] is False and jobs["coach"] is None
