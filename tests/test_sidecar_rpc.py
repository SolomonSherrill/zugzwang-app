"""Sidecar NDJSON-RPC boundary tests (Phase 2, priority 6 — R5).

The sidecar module spawns daemon worker threads at import and in Server.__init__,
so these tests build a *bare* Server via object.__new__ (no boot, no Stockfish)
and drive _handle_request directly, capturing the protocol output by patching the
module-level _send. The main() stdin loop is exercised with a recording fake
Server so the real JSONDecodeError tolerance path runs.
"""

import importlib.util
import io
import queue
import sqlite3
import threading

import chess
import time
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "zugzwang_sidecar_main", _REPO / "sidecar" / "main.py"
)
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

import zugzwang.config as C
from zugzwang.core.database import Database
from zugzwang.core.openings import OpeningsBook


TWO_GAMES = """[Event "Game One"]
[White "alice"]
[Black "bob"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0

[Event "Game Two"]
[White "carol"]
[Black "alice"]
[Result "0-1"]

1. d4 d5 2. c4 e6 0-1
"""


@pytest.fixture
def server():
    """A Server with no threads/boot — only the attributes a handler touches."""
    return object.__new__(sidecar.Server)


@pytest.fixture
def sent(monkeypatch):
    """Capture every protocol frame the sidecar would write to stdout."""
    frames = []
    monkeypatch.setattr(sidecar, "_send", lambda obj: frames.append(obj))
    return frames


# ── dispatch: unknown method ─────────────────────────────────────────────────

def test_unknown_method_replies_error(server, sent):
    server._handle_request({"id": 1, "method": "does_not_exist", "params": {}})
    assert sent == [{"id": 1, "error": {"message": "unknown method: does_not_exist"}}]


def test_unknown_method_echoes_request_id(server, sent):
    server._handle_request({"id": 99, "method": "bogus"})
    assert sent[0]["id"] == 99


def test_missing_id_tolerated(server, sent):
    # No "id" key at all -> req_id is None, still a well-formed error frame.
    server._handle_request({"method": "bogus"})
    assert sent == [{"id": None, "error": {"message": "unknown method: bogus"}}]


# ── dispatch: handler raising becomes an error reply ─────────────────────────

def test_handler_exception_becomes_error_reply(server, sent):
    # user_move with no active session -> _require_session raises RuntimeError.
    server._session = None
    server._handle_request({"id": 7, "method": "user_move", "params": {"uci": "e2e4"}})
    assert sent == [{"id": 7, "error": {"message": "no active game"}}]


def test_handler_bad_params_becomes_error_reply(server, sent):
    # ping takes no params; an unexpected kwarg raises TypeError, surfaced as error.
    server._handle_request({"id": 8, "method": "ping", "params": {"unexpected": 1}})
    assert sent[0]["id"] == 8
    assert "error" in sent[0]


def test_successful_dispatch_replies_result(server, sent):
    server._handle_request({"id": 2, "method": "ping", "params": {}})
    assert sent[0]["id"] == 2
    assert sent[0]["result"]["pong"] is True


# ── rpc_import_pgn: no dedup at the sidecar layer (R5) ────────────────────────

def _migrated(path):
    """A database that has run the attribution migration (FIXPLAN O5), so a game with
    no configured username can be stored with its side unknown. These tests are about
    import mechanics, not colour; before the migration such a game is refused."""
    db = Database(path)
    db.migrate_attribution()
    return db

def _games_in(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    finally:
        conn.close()


def test_import_pgn_imports_every_game(server, sent, tmp_path):
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    server._handle_request({"id": 1, "method": "import_pgn", "params": {"pgn": TWO_GAMES}})
    result = sent[0]["result"]
    assert result["count"] == 2
    assert len(result["gameIds"]) == 2
    assert _games_in(db_path) == 2


def test_import_pgn_reimport_duplicates_no_dedup(server, sent, tmp_path):
    # These games carry no platform id (no Site/Link URL), so there is nothing to
    # match on and re-importing duplicates them. A game *with* an id is
    # de-duplicated — see the IMPORT-EXTID tests below.
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    req = {"id": 1, "method": "import_pgn", "params": {"pgn": TWO_GAMES}}
    server._handle_request(req)
    server._handle_request(req)
    assert _games_in(db_path) == 4


# ── IMPORT-EXTID: imports store the platform id (owner ruling 2026-10-22) ──────

def _chesscom_pgn(link, white="some_opponent", black="old_handle"):
    return (f'[Event "Live Chess"]\n[Site "Chess.com"]\n[White "{white}"]\n'
            f'[Black "{black}"]\n[Link "{link}"]\n[Result "1-0"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 1-0\n')


# The two Link shapes chess.com exports (ids synthetic).
LINK_32 = "https://www.chess.com/game/live/900000000032?move=0"
LINK_42 = "https://www.chess.com/analysis/game/live/900000000042/analysis"


@pytest.mark.parametrize("link, ext", [(LINK_32, "900000000032"), (LINK_42, "900000000042")])
def test_an_import_stores_the_platform_game_id(server, sent, tmp_path, link, ext):
    server._db = _migrated(tmp_path / "s.db")
    server._openings = None
    server._handle_request({"id": 1, "method": "import_pgn",
                            "params": {"pgn": _chesscom_pgn(link), "usernames": ["old_handle"]}})
    gid = sent[0]["result"]["gameId"]
    assert server._db.get_game(gid).external_id == ext


def test_an_import_of_a_game_sync_already_stored_is_skipped_and_reported(server, sent, tmp_path):
    """The case that made games 32, 42 and 278 duplicates of synced games."""
    server._db = _migrated(tmp_path / "s.db")
    server._openings = None
    server._db.save_game(played_at="2026-05-29", player_color="black", skill_level=0,
                         result="1-0", termination="", move_count=4,
                         pgn=_chesscom_pgn(LINK_32), final_fen="x", source="chesscom",
                         external_id="900000000032")
    second = _chesscom_pgn(LINK_42)
    server._handle_request({"id": 1, "method": "import_pgn", "params": {
        "pgn": _chesscom_pgn(LINK_32) + "\n" + second, "usernames": ["old_handle"]}})
    result = sent[0]["result"]
    assert result["count"] == 1                       # only the game not yet stored
    skipped = [i for i in result["issues"] if not i["imported"]]
    assert len(skipped) == 1 and "already in your library" in skipped[0]["reason"]
    assert _games_in(tmp_path / "s.db") == 2


def test_reimporting_a_file_with_ids_does_not_duplicate(server, sent, tmp_path):
    server._db = _migrated(tmp_path / "s.db")
    server._openings = None
    req = {"id": 1, "method": "import_pgn",
           "params": {"pgn": _chesscom_pgn(LINK_42), "usernames": ["old_handle"]}}
    server._handle_request(req)
    server._handle_request(req)
    assert "already in your library" in sent[1]["error"]["message"]
    assert _games_in(tmp_path / "s.db") == 1


def test_sync_does_not_duplicate_a_game_a_file_import_already_stored(tmp_path):
    db = _migrated(tmp_path / "s.db")
    db.save_game(played_at="2026-05-29", player_color="black", skill_level=0, result="1-0",
                 termination="", move_count=4, pgn=_chesscom_pgn(LINK_32), final_fen="x",
                 source="imported", external_id="900000000032")
    assert "900000000032" in db.existing_external_ids("chesscom")


@pytest.mark.parametrize("pgn,want", [
    ("", "empty"),
    ("   \n\n", "empty"),
    # Prose and a file of aborted games are the *same parse* — python-chess
    # returns a default-header, zero-move game for any non-empty text — so they
    # share the one message that covers both causes, rather than getting a
    # confident guess between them.
    ("not a pgn at all []", "none had any moves"),
    ('[White "a"]\n[Black "b"]\n[Result "*"]\n\n*\n', "none had any moves"),
])
def test_import_pgn_says_why_nothing_was_imported(server, sent, tmp_path, pgn, want):
    server._db = _migrated(tmp_path / "s.db")
    server._openings = None
    server._handle_request({"id": 5, "method": "import_pgn", "params": {"pgn": pgn}})
    assert "error" in sent[0]
    assert want in sent[0]["error"]["message"].lower()


def test_import_pgn_reports_a_truncated_game_rather_than_counting_it_clean(
    server, sent, tmp_path
):
    # The case the single catch-all never fired on: parsing stops at `Qh9`, two of
    # five plies are stored, and the old response was indistinguishable from a
    # clean import of a two-move game.
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    server._handle_request({"id": 6, "method": "import_pgn", "params": {"pgn": (
        '[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh9 Nf6 3. Nf3 1-0'
    )}})
    result = sent[0]["result"]
    assert result["count"] == 1
    (issue,) = result["issues"]
    assert issue["imported"] is True
    assert "stopped after 2 plies" in issue["reason"]
    assert _games_in(db_path) == 1


# ── Q1: the file-picker route reads the PGN sidecar-side ─────────────────────

def test_import_pgn_from_a_path_imports_the_same_games(server, sent, tmp_path):
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    pgn_file = tmp_path / "archive.pgn"
    pgn_file.write_text(TWO_GAMES)
    server._handle_request(
        {"id": 1, "method": "import_pgn", "params": {"path": str(pgn_file)}}
    )
    result = sent[0]["result"]
    assert result["count"] == 2
    assert _games_in(db_path) == 2


def test_import_pgn_path_wins_over_pgn_text(server, sent, tmp_path):
    # Not a preference so much as a guard: the picker route sends `path` with no
    # `pgn`, and the paste route the reverse. If a caller ever sent both, silently
    # importing the textarea's stale contents instead of the chosen file would be
    # the worst of the two outcomes.
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    pgn_file = tmp_path / "one.pgn"
    pgn_file.write_text(TWO_GAMES)
    server._handle_request({"id": 1, "method": "import_pgn", "params": {
        "path": str(pgn_file),
        "pgn": '[White "x"]\n[Black "y"]\n[Result "1-0"]\n\n1. e4 1-0',
    }})
    assert sent[0]["result"]["count"] == 2


def test_import_pgn_missing_file_names_the_file(server, sent, tmp_path):
    server._db = _migrated(tmp_path / "s.db")
    server._openings = None
    server._handle_request(
        {"id": 1, "method": "import_pgn", "params": {"path": str(tmp_path / "gone.pgn")}}
    )
    assert "error" in sent[0]
    assert "gone.pgn" in sent[0]["error"]["message"]


def test_import_pgn_tolerates_undecodable_bytes(server, sent, tmp_path):
    """A PGN exported in a non-UTF-8 encoding must not abort the whole import.

    Games are read with errors='replace', so a bad byte in a player name costs a
    replacement character in that one header rather than the entire file.
    """
    db_path = tmp_path / "s.db"
    server._db = _migrated(db_path)
    server._openings = None
    pgn_file = tmp_path / "latin1.pgn"
    pgn_file.write_bytes(TWO_GAMES.replace("alice", "ali\xe7e").encode("latin-1"))
    server._handle_request(
        {"id": 1, "method": "import_pgn", "params": {"path": str(pgn_file)}}
    )
    assert sent[0]["result"]["count"] == 2


# ── Q2: the puzzle CSV picker rejects bad choices on the request ─────────────

def test_an_unattributable_game_is_refused_per_game_before_the_migration(server, sent, tmp_path):
    """Unmigrated database, a username that matches only game two's player: game one
    cannot be attributed and is reported as an issue, not stored as White, and game
    two still imports (FIXPLAN O5)."""
    db_path = tmp_path / "s.db"
    server._db = Database(db_path)
    server._openings = None
    server._handle_request({"id": 1, "method": "import_pgn",
                            "params": {"pgn": TWO_GAMES, "usernames": ["carol"]}})
    result = sent[0]["result"]
    assert result["count"] == 1
    refused = [i for i in result["issues"] if not i["imported"]]
    assert [i["label"] for i in refused] == ["alice vs bob"]
    assert _games_in(db_path) == 1


def test_import_puzzles_rejects_a_still_compressed_csv(server, sent, tmp_path):
    # Lichess only publishes the .zst. Reaching the import thread with one means
    # a UnicodeDecodeError arriving as an error *event* long after the click.
    zst = tmp_path / "lichess_db_puzzle.csv.zst"
    zst.write_bytes(b"\x28\xb5\x2f\xfd")
    server._handle_request(
        {"id": 1, "method": "import_puzzles", "params": {"csv_path": str(zst)}}
    )
    assert "error" in sent[0]
    msg = sent[0]["error"]["message"]
    assert "compressed" in msg and "zstd -d" in msg


def test_import_puzzles_rejects_a_missing_csv(server, sent, tmp_path):
    server._handle_request(
        {"id": 1, "method": "import_puzzles", "params": {"csv_path": str(tmp_path / "no.csv")}}
    )
    assert "error" in sent[0]
    assert "No such file" in sent[0]["error"]["message"]


def test_import_puzzles_starts_for_a_plausible_csv(server, sent, tmp_path, monkeypatch):
    csv = tmp_path / "puzzles.csv"
    csv.write_text("PuzzleId,FEN\n")
    started: list = []
    server._importer = type("Fake", (), {"start": lambda self, *a: started.append(a)})()
    server._db_path = tmp_path / "s.db"
    server._handle_request(
        {"id": 1, "method": "import_puzzles", "params": {"csv_path": str(csv)}}
    )
    assert sent[0]["result"] == {"started": True}
    assert started[0][0] == csv


# ── P2: adopting a user-picked Stockfish binary ──────────────────────────────

def test_set_stockfish_path_rejects_a_non_engine(server, sent, tmp_path, monkeypatch):
    """The check is a UCI handshake, not an executable-bit test.

    The mistake worth catching is picking the wrong *program* — an executable that
    is not an engine passes every cheaper check there is.
    """
    monkeypatch.setattr(
        sidecar.chess.engine.SimpleEngine, "popen_uci",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("not an engine"))),
    )
    persisted: list = []
    monkeypatch.setattr(sidecar, "persist_path", lambda p: persisted.append(p))
    server._handle_request(
        {"id": 1, "method": "set_stockfish_path", "params": {"path": str(tmp_path / "vim")}}
    )
    assert "error" in sent[0]
    assert "not a usable uci engine" in sent[0]["error"]["message"].lower()
    # A rejected pick must not be remembered, or the next launch inherits it.
    assert persisted == []


def test_set_stockfish_path_persists_and_restarts(server, sent, tmp_path, monkeypatch):
    class FakeEngine:
        id = {"name": "Stockfish 17"}
        quit_calls = 0

        def quit(self):
            FakeEngine.quit_calls += 1

    monkeypatch.setattr(
        sidecar.chess.engine.SimpleEngine, "popen_uci",
        staticmethod(lambda *a, **k: FakeEngine()),
    )
    persisted: list = []
    monkeypatch.setattr(sidecar, "persist_path", lambda p: persisted.append(p))
    started: list = []
    monkeypatch.setattr(server, "_start_engine", lambda p: started.append(p) or True)

    binary = tmp_path / "stockfish"
    binary.write_text("")
    server._handle_request(
        {"id": 1, "method": "set_stockfish_path", "params": {"path": str(binary)}}
    )
    result = sent[0]["result"]
    assert result == {"ok": True, "path": str(binary), "name": "Stockfish 17"}
    assert persisted == [binary]
    assert started == [binary]
    # The probe process must be closed; otherwise every pick leaks an engine.
    assert FakeEngine.quit_calls == 1


def test_a_second_engine_start_does_not_inherit_the_first_failure(monkeypatch):
    """`start()` must clear the previous outcome.

    The whole point of the picker is the second attempt. If `ready` were still set
    and `error` still populated from the failed boot, `_start_engine` would read
    the old failure as the new result and the user's good pick would be rejected.
    """
    worker = object.__new__(sidecar.EngineWorker)
    worker._jobs = queue.Queue()
    worker.ready = threading.Event()
    worker.ready.set()
    worker.error = "Stockfish init failed"

    worker.start("/opt/stockfish")

    assert worker.error is None
    assert not worker.ready.is_set()
    assert worker._jobs.get_nowait() == ("init", "/opt/stockfish")


@pytest.mark.parametrize("found", [Path("/opt/stockfish"), None])
def test_boot_loads_the_openings_book_even_with_no_engine(monkeypatch, sent, tmp_path, found):
    """The book must not be gated on Stockfish.

    Nothing it feeds — opening labels, the entire trainer — uses the engine, so
    a machine with no Stockfish installed would otherwise lose the trainer too.
    Found by the fresh-install audit, where the trainer lobby returned zero
    families despite the ECO data being present.
    """
    server = object.__new__(sidecar.Server)
    monkeypatch.setenv("ZUGZWANG_DB", str(tmp_path / "zz.db"))
    monkeypatch.setattr(sidecar, "InsightsRunner", lambda p: "insights")
    monkeypatch.setattr(sidecar, "OpeningsBook", lambda: "book")
    monkeypatch.setattr(sidecar, "find_stockfish", lambda: found)

    class FakeWorker:
        error = None
        ready = threading.Event()

        def start(self, path):
            self.ready.set()

    server._engine = FakeWorker()
    server._boot()

    assert server._openings == "book"
    assert sent[-1]["event"] == "ready"
    assert sent[-1]["data"]["ok"] is (found is not None)


# ── W8: the lobby must be able to say *why* nothing is trainable ─────────────

def test_openings_book_reports_its_own_absence(tmp_path):
    """`has_book` must come off the reader, not be inferred from line weights.

    With no book every line falls back to weight 1, both curation floors reject
    everything, and the lobby renders a full family list with nothing trainable.
    That is indistinguishable from a real book that happens to be thin unless
    absence is asked about directly.
    """
    absent = OpeningsBook(book_path=tmp_path / "nope.bin", eco_dir=tmp_path)
    assert absent.has_book is False
    assert absent.reader is None

    present = OpeningsBook(book_path=C.OPENINGS_BOOK_PATH, eco_dir=tmp_path)
    if not C.OPENINGS_BOOK_PATH.exists():
        pytest.skip("book_mingame3.bin is gitignored; nothing to compare against")
    assert present.has_book is True
    present.close()


@pytest.mark.parametrize("has_book", [True, False])
def test_trainer_lobby_reports_whether_a_book_loaded(server, sent, tmp_path, has_book):
    class FakeOpenings:
        def family_index(self):
            return []

    fake = FakeOpenings()
    fake.has_book = has_book
    server._openings = fake
    server._db = Database(tmp_path / "t.db")
    server._coverage = types.SimpleNamespace(running=lambda: False)

    server._handle_request({"id": 1, "method": "trainer_lobby"})
    result = sent[0]["result"]

    assert result["bookAvailable"] is has_book
    assert result["bookPath"] == str(C.OPENINGS_BOOK_PATH)
    server._db.close()


def test_engine_status_reports_what_would_be_used(server, sent, monkeypatch):
    monkeypatch.setattr(sidecar, "find_stockfish", lambda: Path("/opt/sf"))
    server._handle_request({"id": 1, "method": "engine_status"})
    assert sent[0]["result"] == {"ok": True, "path": str(Path("/opt/sf"))}


def test_engine_status_reports_absence(server, sent, monkeypatch):
    monkeypatch.setattr(sidecar, "find_stockfish", lambda: None)
    server._handle_request({"id": 1, "method": "engine_status"})
    assert sent[0]["result"] == {"ok": False, "path": None}


# ── I1a: insights replies from a worker, not the dispatch thread ─────────────
#
# build_insights takes ~11 s on a real database. Run inline it blocks the single
# request loop, so every other RPC — including board moves — stalls behind it.

@pytest.fixture
def blocked_insights(monkeypatch):
    """Stand in for build_insights, held until the test releases it."""
    gate = threading.Event()
    entered = threading.Event()
    calls = []

    def fake(db, **kwargs):
        calls.append(kwargs)
        entered.set()
        gate.wait(timeout=5)
        return {"ok": True}

    monkeypatch.setattr(sidecar, "build_insights", fake)
    fake.gate, fake.entered, fake.calls = gate, entered, calls
    return fake


@pytest.fixture
def insights_server(server, tmp_path):
    db_path = tmp_path / "s.db"
    Database(db_path).close()  # migrate once, as _boot does
    server._insights = sidecar.InsightsRunner(db_path)
    yield server
    server._insights.shutdown()


def test_insights_dispatch_returns_before_build_finishes(
    insights_server, sent, blocked_insights
):
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})

    assert blocked_insights.entered.wait(timeout=5)
    assert sent == []  # dispatch returned; the build is still running

    blocked_insights.gate.set()


def test_other_requests_answered_while_insights_runs(
    insights_server, sent, blocked_insights
):
    """The point of the fix: the app stays usable during an 11 s build."""
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)

    insights_server._handle_request({"id": 2, "method": "ping"})
    assert sent[0]["id"] == 2  # ping overtakes the in-flight insights build

    blocked_insights.gate.set()


def test_insights_reply_carries_its_own_id(insights_server, sent, blocked_insights):
    insights_server._handle_request({"id": 7, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)
    blocked_insights.gate.set()

    _wait_for(lambda: any(f.get("id") == 7 for f in sent))
    assert sent[-1] == {"id": 7, "result": {"ok": True}}


def test_insights_filters_reach_build_insights(
    insights_server, sent, blocked_insights
):
    blocked_insights.gate.set()
    insights_server._handle_request({
        "id": 1, "method": "insights",
        "params": {"color": "white", "speeds": ["blitz"], "since": "2026-01-01",
                   "rated": "rated"},
    })

    _wait_for(lambda: blocked_insights.calls)
    assert blocked_insights.calls[0] == {
        "color": "white", "speeds": ["blitz"], "since": "2026-01-01",
        "rated": "rated", "include_local": False,
    }


def test_insights_failure_replies_error_not_silence(insights_server, sent, monkeypatch):
    """A worker-thread exception must still reach the caller, or the frontend's
    pending promise never settles and the screen spins forever."""
    def boom(db, **kwargs):
        raise RuntimeError("no games")

    monkeypatch.setattr(sidecar, "build_insights", boom)
    insights_server._handle_request({"id": 3, "method": "insights", "params": {}})

    _wait_for(lambda: sent)
    assert sent[0] == {"id": 3, "error": {"message": "no games"}}


def test_worker_survives_a_failed_build(insights_server, sent, monkeypatch):
    """One bad request must not kill the thread and strand every later one."""
    calls = []

    def flaky(db, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("first fails")
        return {"ok": True}

    monkeypatch.setattr(sidecar, "build_insights", flaky)
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    _wait_for(lambda: sent)
    insights_server._handle_request({"id": 2, "method": "insights", "params": {}})

    _wait_for(lambda: len(sent) == 2)
    assert "error" in sent[0]
    assert sent[1] == {"id": 2, "result": {"ok": True}}


# ── I1a follow-ups: read-only, snapshot, shutdown, supersession ──────────────

def test_worker_connection_cannot_write(tmp_path):
    """Structural, not by convention: the worker holds a mode=ro handle, so a
    stray write in insights code fails loudly instead of racing the app thread."""
    db_path = tmp_path / "s.db"
    Database(db_path).close()
    ro = Database(db_path, read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro._conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
    finally:
        ro.close()


def test_snapshot_hides_a_concurrent_write(tmp_path):
    """The whole point of the read transaction: a build that reads the same
    table twice must not see a row appear halfway through."""
    db_path = tmp_path / "s.db"
    writer = Database(db_path)
    ro = Database(db_path, read_only=True)
    try:
        with ro.snapshot():
            before = ro._conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
            writer._conn.execute("INSERT INTO meta (key, value) VALUES ('new', '1')")
            writer._conn.commit()
            after = ro._conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        assert before == after
        # and the snapshot is released at the end of the block
        assert ro._conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == before + 1
    finally:
        ro.close()
        writer.close()


def test_shutdown_closes_the_worker_connection(insights_server, sent):
    runner = insights_server._insights
    runner.submit(1, {})  # force the lazy connection open
    _wait_for(lambda: runner._db is not None)

    runner.shutdown()

    assert runner.closed.wait(timeout=2)
    assert runner._db is None
    assert not runner._thread.is_alive()


def test_shutdown_is_idempotent(insights_server, sent):
    """Server.run() shuts the worker down, and so does anything else holding it.
    The second call races the worker's own close — it must not raise."""
    runner = insights_server._insights
    runner.submit(1, {})
    _wait_for(lambda: runner._db is not None)

    runner.shutdown()
    runner.shutdown()  # no ProgrammingError on the closed connection


def test_shutdown_is_bounded_even_if_a_build_will_not_stop(
    insights_server, sent, blocked_insights
):
    """A build takes ~11 s. Closing the app must not wait it out.

    The real escape is interrupt() (see the test below); this pins the weaker
    guarantee that holds even when the work is not interruptible at all — the
    fake build here ignores interrupts entirely.
    """
    runner = insights_server._insights
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)

    started = time.monotonic()
    runner.shutdown(timeout=0.5)
    elapsed = time.monotonic() - started

    assert elapsed < 2  # bounded by the join timeout, not by the build
    blocked_insights.gate.set()


def test_interrupt_aborts_a_query_from_another_thread(tmp_path):
    """shutdown()'s escape hatch: sqlite3.interrupt is the only way to reclaim a
    worker that is mid-scan, and it must work across threads."""
    db_path = tmp_path / "s.db"
    writer = Database(db_path)
    writer._conn.execute("CREATE TABLE big (x)")
    writer._conn.executemany("INSERT INTO big VALUES (?)", ((i,) for i in range(60000)))
    writer._conn.commit()
    writer.close()

    box, err, opened = {}, [], threading.Event()

    def scan():
        ro = Database(db_path, read_only=True)  # must be created on this thread
        box["db"] = ro
        opened.set()
        try:
            ro._conn.execute("SELECT COUNT(*) FROM big a, big b").fetchone()
        except sqlite3.OperationalError as exc:
            err.append(exc)
        ro.close()

    t = threading.Thread(target=scan, daemon=True)
    t.start()
    assert opened.wait(timeout=5)
    time.sleep(0.2)  # let the scan actually start
    box["db"].interrupt()
    t.join(timeout=5)

    assert not t.is_alive()
    assert err and "interrupted" in str(err[0])


def test_queued_request_superseded_before_it_runs(
    insights_server, sent, blocked_insights
):
    """Toggling filters during an 11 s build must not queue up 11 s each."""
    runner = insights_server._insights
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)  # id 1 is now in flight

    insights_server._handle_request({"id": 2, "method": "insights", "params": {}})
    insights_server._handle_request({"id": 3, "method": "insights", "params": {}})
    blocked_insights.gate.set()

    _wait_for(lambda: len(sent) == 3)
    by_id = {f["id"]: f for f in sent}
    assert by_id[2]["result"] == {"superseded": True}   # overtaken by id 3
    assert by_id[3]["result"] == {"ok": True}           # newest, actually built
    assert len(blocked_insights.calls) == 2             # id 1 and id 3 only


def test_superseded_reply_cannot_be_mistaken_for_an_empty_result(
    insights_server, sent, blocked_insights
):
    """The marker must carry no data keys at all.

    It arrives as a *success* frame — sidecar.ts is pure transport and resolves
    the promise with whatever `result` holds — so the frontend tells "superseded"
    from "built" purely by inspecting the payload. If this ever carried `overview`,
    even a zeroed one, InsightsScreen would assign it to `data` and the screen
    would blank on every rapid filter toggle.
    """
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)
    insights_server._handle_request({"id": 2, "method": "insights", "params": {}})
    insights_server._handle_request({"id": 3, "method": "insights", "params": {}})
    blocked_insights.gate.set()

    _wait_for(lambda: len(sent) == 3)
    superseded = {f["id"]: f for f in sent}[2]

    assert "error" not in superseded       # a success frame, not a failure
    assert superseded["result"] == {"superseded": True}
    # `overview` named explicitly: it is the key InsightsScreen dereferences
    # immediately (`data.overview.total`), so its absence is what stops a render.
    assert "overview" not in superseded["result"]


def test_superseded_requests_still_get_a_reply(insights_server, sent, blocked_insights):
    """Skipping the work must not skip the reply — an unanswered id leaves the
    frontend's pending promise unsettled forever."""
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)
    for i in (2, 3, 4, 5):
        insights_server._handle_request({"id": i, "method": "insights", "params": {}})
    blocked_insights.gate.set()

    _wait_for(lambda: len(sent) == 5)
    assert {f["id"] for f in sent} == {1, 2, 3, 4, 5}


def test_in_flight_build_still_returns_its_own_result(
    insights_server, sent, blocked_insights
):
    """Only never-started jobs are skipped. A build that already ran has a real
    answer, so it replies with it rather than claiming to be superseded."""
    insights_server._handle_request({"id": 1, "method": "insights", "params": {}})
    assert blocked_insights.entered.wait(timeout=5)
    insights_server._handle_request({"id": 2, "method": "insights", "params": {}})
    blocked_insights.gate.set()

    _wait_for(lambda: len(sent) == 2)
    assert sent[0] == {"id": 1, "result": {"ok": True}}


def _wait_for(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within %.1fs" % timeout)


# ── FenAnalysisRunner: newest request wins ───────────────────────────────────
#
# Built with object.__new__ so no thread starts and no engine is resolved; these
# cover the bookkeeping that decides which search is still wanted.

@pytest.fixture
def live():
    runner = object.__new__(sidecar.FenAnalysisRunner)
    runner._engine = None
    runner._lock = threading.Lock()
    runner._pending = None
    runner._generation = 0
    runner._quit = False
    runner._wake = threading.Event()
    return runner


def test_a_later_request_supersedes_an_earlier_one(live):
    first = live.analyze("fen-a")
    second = live.analyze("fen-b")
    assert live.superseded(first) and not live.superseded(second)


def test_only_the_newest_request_is_left_to_run(live):
    """Four quick steps through a line must not queue four searches — the three
    positions the user passed through are not the one they are looking at."""
    for fen in ("a", "b", "c", "d"):
        live.analyze(fen)
    assert live._pending[1] == "d"


def test_shutdown_supersedes_whatever_is_running(live):
    gen = live.analyze("fen-a")
    live.shutdown()
    assert live.superseded(gen) and live._quit


def test_a_superseded_search_emits_nothing(live, monkeypatch):
    """A stale score on screen is worse than a late one: the panel would be
    showing the evaluation of a position that is no longer on the board."""
    emitted = []
    monkeypatch.setattr(sidecar, "_emit", lambda name, data: emitted.append((name, data)))
    monkeypatch.setattr(sidecar, "analyze_position_multipv", lambda *a, **k: [])
    live._engine = object()  # never used: the analysis call is patched out

    gen = live.analyze("fen-a")
    live.analyze("fen-b")  # the user moved on before the search finished
    live._do_fen(gen, "fen-a")
    assert emitted == []


def test_the_current_search_does_emit(live, monkeypatch):
    emitted = []
    monkeypatch.setattr(sidecar, "_emit", lambda name, data: emitted.append((name, data)))
    monkeypatch.setattr(
        sidecar, "analyze_position_multipv",
        lambda *a, **k: [{"cp": 31, "mate": None, "uci": ["e2e4"], "san": ["e4"]}],
    )
    live._engine = object()

    gen = live.analyze("fen-a")
    live._do_fen(gen, "fen-a")
    (name, data), = emitted
    assert name == "fen_analyzed"
    assert data["fen"] == "fen-a" and data["bestUci"] == "e2e4" and data["cp"] == 31


def test_a_cancelled_search_publishes_nothing_at_all(live, monkeypatch):
    """`analyze_position_multipv` answers [] when cancelled mid-search. Reaching
    the emit with that would publish a null score over a good one already on
    screen, so the generation check has to come first."""
    emitted = []
    monkeypatch.setattr(sidecar, "_emit", lambda name, data: emitted.append((name, data)))

    def cancelled_mid_search(*a, **k):
        live.analyze("fen-b")  # the user steps on while the engine is searching
        assert k["is_cancelled"]()
        return []

    monkeypatch.setattr(sidecar, "analyze_position_multipv", cancelled_mid_search)
    live._engine = object()
    live._do_fen(live.analyze("fen-a"), "fen-a")
    assert emitted == []


# ── rpc_probe_move: board truth for one exploration move ─────────────────────
#
# The review screen asks for a position per variation node, so a wrong answer
# here is a node holding a position nobody can reach. No engine and no database
# is touched, which is why a bare Server can answer.

_OPENING = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _probe(server, sent, fen, uci):
    server._handle_request({"id": 1, "method": "probe_move", "params": {"fen": fen, "uci": uci}})
    return sent[-1]["result"]


def test_probe_move_reports_where_the_move_lands(server, sent):
    got = _probe(server, sent, _OPENING, "e2e4")
    assert got["legal"] is True
    assert got["san"] == "e4"
    assert got["fen"].startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b")
    assert got["check"] is False and got["gameOver"] is False


def test_probe_move_names_the_move_before_playing_it(server, sent):
    """SAN is from the position the move is made in, not the one it reaches."""
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    assert _probe(server, sent, fen, "f3g5")["san"] == "Ng5"


@pytest.mark.parametrize("uci", ["e2e5", "a1a1", "", "zzzz", "e9e4"])
def test_probe_move_rejects_a_move_that_cannot_be_played(server, sent, uci):
    """Illegal and unparseable both answer `legal: false` and carry no position:
    an invented landing square is exactly how an unreachable node gets stored."""
    assert _probe(server, sent, _OPENING, uci) == {"legal": False}


def test_probe_move_reports_check(server, sent):
    fen = "rnbqkbnr/ppp2ppp/8/3pp3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 3"
    got = _probe(server, sent, fen, "d8h4")
    assert got["legal"] is True and got["check"] is True


def test_probe_move_reports_game_over_on_mate(server, sent):
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    got = _probe(server, sent, fen, "f3f7")
    assert got["san"] == "Qxf7#"
    assert got["check"] is True and got["gameOver"] is True


def test_probe_move_carries_the_promotion_piece(server, sent):
    fen = "8/4P3/8/8/8/8/8/K6k w - - 0 1"
    assert _probe(server, sent, fen, "e7e8q")["san"] == "e8=Q"
    assert _probe(server, sent, fen, "e7e8n")["san"] == "e8=N"


def test_probe_move_rejects_a_bad_fen_as_an_error_reply(server, sent):
    """A malformed position is a caller bug, not a move that happens to be
    illegal, and must not be flattened into `legal: false`."""
    server._handle_request(
        {"id": 7, "method": "probe_move", "params": {"fen": "not a fen", "uci": "e2e4"}}
    )
    assert "error" in sent[-1] and sent[-1]["id"] == 7


# ── main() stdin loop: tolerates malformed JSON ──────────────────────────────

class _RecordingServer:
    def __init__(self):
        self.requests = []
        self._stop = threading.Event()

    def post_request(self, req):
        self.requests.append(req)

    def post_call(self, fn):
        pass

    def post_stop(self):
        self._stop.set()

    def run(self):
        self._stop.wait(timeout=5)


def test_main_skips_bad_json_and_blank_lines(monkeypatch):
    rec = _RecordingServer()
    monkeypatch.setattr(sidecar, "Server", lambda: rec)
    monkeypatch.setattr(sidecar.sys, "stdin", io.StringIO(
        '{"id": 1, "method": "ping"}\n'
        "not valid json {\n"
        "\n"
        "   \n"
        '{"id": 2, "method": "get_state"}\n'
    ))
    sidecar.main()  # returns once stdin hits EOF -> post_stop -> run() unblocks
    assert rec.requests == [
        {"id": 1, "method": "ping"},
        {"id": 2, "method": "get_state"},
    ]


# ── game_report ──────────────────────────────────────────────────────────────

def _report_server(server, tmp_path, *, analysed: bool):
    from tests.test_game_report import DECIDED_AT_6, LINE, _game

    db = Database(tmp_path / "r.db")
    pgn = '[Event "x"]\n[White "me"]\n[Black "opp"]\n[Result "1-0"]\n\n' \
          "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 1-0"
    gid = db.save_game(
        played_at="2026-10-21T12:00:00+00:00", player_color="white", skill_level=0,
        result="1-0", termination="resignation", move_count=10, pgn=pgn,
        final_fen="x", source="chesscom",
    )
    if analysed:
        run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=10)
        db.complete_analysis_run(run, {}, plies=_game(LINE, DECIDED_AT_6))
    server._db = db
    return gid


def test_game_report_rpc_reports_the_point_of_no_return(server, sent, tmp_path):
    gid = _report_server(server, tmp_path, analysed=True)
    server._handle_request({"id": 1, "method": "game_report", "params": {"game_id": gid}})
    r = sent[0]["result"]
    assert r["analysed"] is True and r["basis"]["complete"] is True
    assert r["decided"] == {"position": 6, "side": "white", "byPly": 5}
    assert r["moments"]["shown"][0]["label"] == "3…Nf6"


def test_game_report_rpc_on_an_unanalysed_game(server, sent, tmp_path):
    gid = _report_server(server, tmp_path, analysed=False)
    server._handle_request({"id": 1, "method": "game_report", "params": {"game_id": gid}})
    # No book on this bare server, so no opening line either; with one, an unanalysed
    # game still gets it, because it needs the book and not the engine.
    assert sent[0]["result"] == {"analysed": False, "opening": None, "lines": []}


# ── W15: the bulk-analysis count says which games are actually unanalysed ─────

def test_sync_status_splits_unanalysed_from_below_depth(server, sent, tmp_path):
    from tests.runs import mark_complete

    db = Database(tmp_path / "w15.db")
    pgn = '[Event "x"]\n[White "me"]\n[Black "opp"]\n\n1. e4 e5 *'

    def game(ext):
        return db.save_game(
            played_at="2026-10-21T12:00:00+00:00", player_color="white", skill_level=0,
            result="*", termination="x", move_count=2, pgn=pgn, final_fen="x",
            source="chesscom", external_id=ext,
        )

    game("never-analysed")
    shallow = game("depth-10")
    mark_complete(db, db.save_analysis_run(game_id=shallow, engine_name="Stockfish",
                                           depth=10))
    server._db = db
    server._sync = type("S", (), {"running": lambda self: False})()

    server._handle_request({"id": 1, "method": "sync_status", "params": {"depth": 14}})
    c = sent[0]["result"]["chesscom"]
    assert c == {"synced": 2, "pending": 2, "unanalysed": 1, "belowDepth": 1, "depth": 14,
                 "needsAttention": 0}


# ── slice 5: judging a Try ───────────────────────────────────────────────────

def test_a_position_request_never_supersedes_a_judgement():
    # Playing the Try move puts a new position on the board, which asks for live
    # analysis at once; that must not cancel the judgement being waited for.
    runner = object.__new__(sidecar.FenAnalysisRunner)
    runner._lock = threading.Lock()
    runner._wake = threading.Event()
    runner._quit = False
    runner._pending = None
    runner._generation = 0
    runner._judge_pending = None
    runner._judge_generation = 0
    token = runner.judge(chess.STARTING_FEN, "e2e4")
    runner.analyze(chess.STARTING_FEN)
    assert not runner._judge_superseded(token)
    newer = runner.judge(chess.STARTING_FEN, "d2d4")
    assert runner._judge_superseded(token) and not runner._judge_superseded(newer)


def test_judge_move_refuses_an_illegal_move(server, sent):
    server._live = None
    server._handle_request({"id": 1, "method": "judge_move",
                            "params": {"fen": chess.STARTING_FEN, "uci": "e2e5"}})
    assert "error" in sent[0]
