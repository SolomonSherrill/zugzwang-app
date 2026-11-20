#!/usr/bin/env python3
"""End-to-end smoke test: spawn the sidecar, play moves, exercise every
game-end path, and verify games persist. Uses a temp DB via ZUGZWANG_DB so the
real ~/.zugzwang database is never touched.

Run:  .venv/bin/python sidecar/smoke_test.py
      .venv/bin/python sidecar/smoke_test.py --sidecar <packaged executable> --skip-trainer

`--sidecar` drives a packaged (PyInstaller) sidecar instead of the checkout's script —
CI runs it on every target (BETA item 7). `--skip-trainer` skips the opening-trainer
section, which needs the book (W20) and is hidden in beta builds; without it the run
stops there, as before. The data folder (`ZUGZWANG_DATA_DIR`) is a temp directory too, so
the user's settings are never touched.
"""

import argparse

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SIDECAR = REPO_ROOT / "sidecar" / "main.py"


class Client:
    def __init__(self, db_path: Path, cmd: list[str] | None = None) -> None:
        env = dict(os.environ, ZUGZWANG_DB=str(db_path), ZUGZWANG_DATA_DIR=str(db_path.parent))
        self.proc = subprocess.Popen(
            cmd or [sys.executable, str(SIDECAR)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self.responses: dict = {}
        self.events: list = []
        self._cond = threading.Condition()
        self._next_id = 0
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            msg = json.loads(line)
            with self._cond:
                if "event" in msg:
                    self.events.append(msg)
                else:
                    self.responses[msg["id"]] = msg
                self._cond.notify_all()

    def _stderr_loop(self) -> None:
        for line in self.proc.stderr:
            print("  " + line.rstrip())

    def request(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self.proc.stdin.write(json.dumps({"id": req_id, "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        with self._cond:
            ok = self._cond.wait_for(lambda: req_id in self.responses, timeout)
            if not ok:
                raise TimeoutError(f"no response to {method}")
            msg = self.responses.pop(req_id)
        if "error" in msg:
            raise RuntimeError(f"{method} failed: {msg['error']['message']}")
        return msg["result"]

    def wait_event(self, name: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for i, ev in enumerate(self.events):
                    if ev["event"] == name:
                        return self.events.pop(i)["data"]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no {name} event")
                self._cond.wait(remaining)

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def chess_start_fen() -> str:
    return "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", help="a packaged sidecar executable to drive instead")
    ap.add_argument("--skip-trainer", action="store_true",
                    help="skip the opening-trainer section (no book, W20; hidden in beta)")
    ap.add_argument("--book", type=Path,
                    help="an opening book file of the manifest (BOOK-DL) to install into the temp "
                         "data folder and switch to through book_use before the trainer; default "
                         "$ZUGZWANG_TEST_BOOK, else the dev run's book in use (read only)")
    args = ap.parse_args()
    t0 = time.monotonic()
    tmp = Path(tempfile.mkdtemp()) / "smoke.db"
    c = Client(tmp, [args.sidecar] if args.sidecar else None)

    ready = c.wait_event("ready", timeout=30)
    assert ready["ok"], f"sidecar not ready: {ready}"
    print(f"✓ ready in {time.monotonic() - t0:.1f}s")

    # engine_status only. `set_stockfish_path` persists into ~/.zugzwang/settings.json,
    # and ZUGZWANG_DB isolates the database but not USER_DIR — so exercising it here
    # would edit the real user's settings. It is covered by unit tests instead.
    eng = c.request("engine_status")
    assert eng["ok"] and eng["path"], eng
    print(f"✓ engine_status → {eng['path']}")

    info = c.request("app_info")
    assert info["dataDir"] == str(tmp.parent), info
    print(f"✓ app_info → version {info['version']} (beta {info['beta']}, frozen "
          f"{info['frozen']}), log {info['logPath']}")

    # ── live play: ack latency, engine reply, opening detection ──────────────
    res = c.request("new_game", {"color": "white", "skill": 5})
    assert res["engineToMove"] is False
    t1 = time.monotonic()
    res = c.request("user_move", {"uci": "e2e4"})
    assert res["ok"] and res["san"] == "e4" and res["end"] is None
    ack_ms = (time.monotonic() - t1) * 1000
    ev = c.wait_event("engine_move")
    print(f"✓ play: ack {ack_ms:.0f}ms, engine {ev['san']} after "
          f"{(time.monotonic() - t1) * 1000:.0f}ms")

    res = c.request("user_move", {"uci": "e4e6"})
    assert res["ok"] is False
    print("✓ illegal move rejected")

    # ── resign → saved ────────────────────────────────────────────────────────
    res = c.request("resign")
    assert res["end"]["termination"] == "resignation"
    assert res["end"]["result"] == "0-1"
    resign_id = res["end"]["gameId"]
    print(f"✓ resign saved as game {resign_id}")

    # ── draw → saved ──────────────────────────────────────────────────────────
    c.request("new_game", {"color": "white", "skill": 0})
    res = c.request("draw")
    assert res["end"]["termination"] == "draw_agreed"
    assert res["end"]["result"] == "1/2-1/2"
    print("✓ draw agreed saved")

    # ── flag (timeout) → saved ────────────────────────────────────────────────
    c.request("new_game", {"color": "white", "skill": 0})
    res = c.request("flag", {"loser": "white"})
    assert res["end"]["termination"] == "timeout"
    assert res["end"]["result"] == "0-1"
    print("✓ flag fall saved as timeout")

    # ── checkmate by user (fool's mate as black) → end in user_move ──────────
    c.request("new_game", {"color": "black", "skill": 0,
                           "fen": "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"})
    res = c.request("user_move", {"uci": "d8h4"})
    assert res["ok"] and res["end"] is not None
    assert res["end"]["termination"] == "checkmate" and res["end"]["result"] == "0-1"
    print("✓ checkmate detected and saved")

    # ── playing black: engine moves first ─────────────────────────────────────
    res = c.request("new_game", {"color": "black", "skill": 1})
    assert res["engineToMove"] is True
    ev = c.wait_event("engine_move")
    print(f"✓ as black, engine opened with {ev['san']}")
    opening = [e for e in c.events if e["event"] == "opening"]
    if opening:
        d = opening[-1]["data"]
        print(f"✓ opening event: {d['eco']} {d['name']}")

    # ── review API: list / detail ─────────────────────────────────────────────
    res = c.request("list_games")
    assert len(res["games"]) == 4, f"expected 4 games, got {len(res['games'])}"
    assert all(g["analyzed"] is False for g in res["games"])
    mate_game = next(g for g in res["games"] if g["termination"] == "checkmate")
    print(f"✓ list_games → {len(res['games'])} games")

    detail = c.request("get_game", {"game_id": mate_game["id"]})
    assert detail["plies"][-1]["san"].endswith("#")
    assert detail["plies"][-1]["check"] is True
    assert detail["analysis"] is None
    print(f"✓ get_game → {len(detail['plies'])} plies, final {detail['plies'][-1]['san']}")

    # ── PGN import ────────────────────────────────────────────────────────────
    pgn = (
        '[Event "Test"]\n[Date "2024.01.15"]\n[White "Alice"]\n[Black "Bob"]\n'
        '[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O 1-0'
    )
    # With the user's handle, as a real import has: since O5 a game no configured
    # handle attributes is refused, not stored as White (checked further down).
    res = c.request("import_pgn", {"pgn": pgn, "usernames": ["alice"]})
    imported_id = res["gameId"]
    assert res["issues"] == []
    detail = c.request("get_game", {"game_id": imported_id})
    assert detail["source"] == "imported" and detail["white"] == "Alice"
    assert detail["openingName"] is not None
    print(f"✓ import_pgn → game {imported_id} ({detail['openingEco']} {detail['openingName']})")

    # A game python-chess gives up on partway is still stored — truncated — and
    # the response has to say so, or the user is told it imported cleanly.
    res = c.request("import_pgn", {"pgn": (
        '[Event "Broken"]\n[White "Carol"]\n[Black "Dan"]\n[Result "1-0"]\n\n'
        '1. e4 e5 2. Qh9 Nf6 3. Nf3 1-0'
    ), "usernames": ["carol"]})
    (issue,) = res["issues"]
    assert res["count"] == 1 and issue["imported"] is True, res
    assert c.request("get_game", {"game_id": res["gameId"]})["moveCount"] == 2
    print(f"✓ truncated PGN imported and reported ({issue['reason'][:44]}…)")

    # Prose and a file of aborted games produce the identical parse — python-chess
    # hands back a default-header, zero-move game for any non-empty text — so both
    # get the message that covers both causes. Only truly empty input differs.
    for bad, want in (
        ("not a pgn at all []", "none had any moves"),
        ('[White "a"]\n[Black "b"]\n[Result "*"]\n\n*\n', "none had any moves"),
        ("   \n", "the PGN is empty"),
    ):
        try:
            c.request("import_pgn", {"pgn": bad})
            raise AssertionError(f"{bad!r} should be rejected")
        except RuntimeError as exc:
            assert want in str(exc), exc
    print("✓ unparsable, moveless and empty PGNs each rejected with a reason")

    # The file-picker route: the sidecar opens the file itself, so an archive
    # export never has to travel through the NDJSON pipe.
    pgn_file = tmp.parent / "smoke_archive.pgn"
    pgn_file.write_text(pgn)
    res = c.request("import_pgn", {"path": str(pgn_file), "usernames": ["alice"]})
    assert res["count"] == 1 and res["issues"] == [], res
    assert c.request("get_game", {"game_id": res["gameId"]})["white"] == "Alice"
    try:
        c.request("import_pgn", {"path": str(tmp.parent / "not_there.pgn")})
        raise AssertionError("a missing file should be rejected")
    except RuntimeError as exc:
        assert "not_there.pgn" in str(exc), exc
    print("✓ import_pgn from a file path, and a missing file named in the error")

    # O5: no configured handle, on a database that has not run the attribution
    # migration — refused with the reason, never stored under a guessed colour.
    try:
        c.request("import_pgn", {"pgn": pgn})
        raise AssertionError("an unattributable game should be refused before the migration")
    except RuntimeError as exc:
        assert "cannot be attributed" in str(exc), exc
    print("✓ an import no handle attributes is refused, not stored as White")

    # ── streaming analysis (low depth for speed) ──────────────────────────────
    t2 = time.monotonic()
    res = c.request("analyze_game", {"game_id": imported_id, "depth": 8})
    assert res["runId"] > 0
    plies_seen = 0
    while True:
        try:
            # The first ply waits for the analysis engine to start: on a slow runner that
            # took over a second, and a 1 s wait counted 0 plies (v0.1.0-beta.1's first CI
            # run, macOS x86_64). Later plies come in milliseconds at depth 8.
            ev = c.wait_event("analysis_ply", timeout=60.0 if plies_seen == 0 else 5.0)
            assert ev["gameId"] == imported_id
            plies_seen += 1
        except TimeoutError:
            break
    done = c.wait_event("analysis_done", timeout=30)
    assert plies_seen == 9, f"expected 9 ply events, got {plies_seen}"
    assert done["whiteAccuracy"] is None or done["whiteAccuracy"] > 0
    print(f"✓ analysis streamed {plies_seen} plies in {time.monotonic() - t2:.1f}s "
          f"(accuracies: W {done['whiteAccuracy']} / B {done['blackAccuracy']})")

    detail = c.request("get_game", {"game_id": imported_id})
    assert detail["analysis"] is not None
    assert len(detail["analysis"]["moves"]) == 9
    classifications = {m["classification"] for m in detail["analysis"]["moves"]}
    print(f"✓ analysis persisted & reloadable (classes seen: {sorted(classifications)})")

    res = c.request("list_games")
    row = next(g for g in res["games"] if g["id"] == imported_id)
    assert row["analyzed"] is True
    print("✓ list_games shows accuracy after analysis")

    # ── move explanations ─────────────────────────────────────────────────────
    #
    # Most plies have nothing provable to say, which is the designed outcome, so
    # this cannot assert that a sentence came back. What it does assert is that the
    # protocol is intact: the handler runs, the shapes are right, and every sentence
    # is backed by a finding rather than appearing on its own.
    said = 0
    for ma in detail["analysis"]["moves"]:
        got = c.request("explain_move", {"game_id": imported_id, "ply": ma["ply"]})
        assert got["analysed"] is True, f"ply {ma['ply']} has an analysis row"
        assert got["ply"] == ma["ply"]
        assert isinstance(got["findings"], list) and isinstance(got["sentences"], list)
        assert got["ruleVersion"] > 0
        if got["sentences"]:
            assert got["findings"], "a sentence with no finding behind it"
            said += 1
        # Layer 5: claims and descriptions in separate, typed arrays; the rule
        # sentences appear among the claims unchanged.
        rules_shown = [x["text"] for x in got["claims"] if x["source"] == "rules"]
        engine_shown = [x for x in got["claims"] if x["source"] == "engine_line"]
        # Reversed precedence: an engine-line claim replaces the rule sentences.
        assert rules_shown == ([] if engine_shown else got["sentences"])
        assert all(x["type"] == "claim" for x in got["claims"])
        assert all(x["type"] == "description" for x in got["descriptions"])
        assert len(got["descriptions"]) <= 2
        for f in got["findings"]:
            assert f["kind"] and f["subject"] in ("played", "best")
            for p in f["pieces"]:
                assert p["color"] in ("white", "black"), "PieceOn must carry a colour"
    explained = c.request("explain_move", {"game_id": imported_id, "ply": 999})
    assert explained["analysed"] is False and explained["sentences"] == []
    print(f"✓ explain_move → {said}/{len(detail['analysis']['moves'])} plies said "
          f"something; an unknown ply reports analysed=false")

    # ── "flag this" (BETA): a local file, keyed by platform game id + ply ─────
    flag = c.request("flag_item", {"kind": "label", "shown": "smoke", "note": "smoke test",
                                   "game_id": imported_id, "ply": 0, "label": "best"})
    flagged = [json.loads(x) for x in Path(flag["path"]).read_text(encoding="utf-8").splitlines()]
    assert flag["count"] == 1 and flagged[0]["ply"] == 0 and flagged[0]["fen_before"], flagged
    assert Path(flag["path"]).parent.parent == tmp.parent, flag
    print(f"✓ flag_item → {flag['path']} (classifier {flagged[0]['run_classifier_version']}, "
          f"rules {flagged[0]['rule_version']})")

    # ── probe_move: positions for review-screen exploration ──────────────────
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    probed = c.request("probe_move", {"fen": start, "uci": "e2e4"})
    assert probed["legal"] and probed["san"] == "e4"
    assert c.request("probe_move", {"fen": probed["fen"], "uci": "e2e4"}) == {"legal": False}
    print(f"✓ probe_move → {probed['san']} lands on {probed['fen'].split(' ')[0]}; "
          "the same move from the other side is refused")

    # ── single-FEN analysis ───────────────────────────────────────────────────
    c.request("analyze_fen", {"fen": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"})
    ev = c.wait_event("fen_analyzed", timeout=30)
    assert ev["bestUci"]
    print(f"✓ analyze_fen → best {ev['bestUci']} (cp {ev['cp']})")

    # ── puzzles: import a small synthetic CSV through the real pipeline ──────
    status = c.request("puzzle_status")
    assert status["imported"] is False and status["count"] == 0
    print(f"✓ puzzle_status: not imported (rating {status['rating']:.0f})")

    csv_path = tmp.parent / "mini_puzzles.csv"
    header = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags"
    # Real Lichess-format rows (mate-in-1 after a setup move) + one row that
    # must be filtered out (NbPlays < 50).
    rows = [
        "t1,r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3,"
        "g8f6 h5f7,820,80,95,1000,mate mateIn1 short,,",
        "t2,rnbqkbnr/ppppp1pp/8/5p2/4P3/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 2,"
        "e4f5 d8h4,840,85,90,800,advantage short,,",
        "skip,8/8/8/8/8/8/8/K6k w - - 0 1,a1a2 h1h2,900,90,90,10,endgame,,",
    ]
    csv_path.write_text(header + "\n" + "\n".join(rows) + "\n")

    # Picker mistakes are rejected on the request, not by an error event minutes
    # later. The .zst is the likely one: Lichess publishes only the compressed file.
    zst_path = tmp.parent / "lichess_db_puzzle.csv.zst"
    zst_path.write_bytes(b"\x28\xb5\x2f\xfd")
    for bad, want in ((zst_path, "compressed"), (tmp.parent / "absent.csv", "No such file")):
        try:
            c.request("import_puzzles", {"csv_path": str(bad)})
            raise AssertionError(f"{bad.name} should be rejected")
        except RuntimeError as exc:
            assert want in str(exc), exc
    print("✓ compressed and missing puzzle CSVs rejected before the import starts")

    c.request("import_puzzles", {"csv_path": str(csv_path)})
    done = c.wait_event("puzzle_import_done", timeout=30)
    assert done["count"] == 2, f"expected 2 imported (1 filtered), got {done['count']}"
    status = c.request("puzzle_status")
    assert status["imported"] is True and status["count"] == 2
    print("✓ puzzle import: 2 rows imported, low-play row filtered, meta marked")

    res = c.request("next_puzzles", {"target_rating": 830, "rating_range": 100})
    assert len(res["puzzles"]) == 2
    pz = res["puzzles"][0]
    assert len(pz["movesUci"]) >= 2
    print(f"✓ next_puzzles → {len(res['puzzles'])} in range (first: {pz['id']} @{pz['rating']})")

    res = c.request("count_theme_puzzles", {"themes": ["mateIn1"], "rating_range": 300})
    assert res["count"] == 1
    print("✓ theme FTS query works (mateIn1 → 1)")

    # rated flow: session-less, rating updated on outcome
    before = c.request("get_puzzle_rating")
    res = c.request("rate_puzzle", {"puzzle_rating": pz["rating"], "puzzle_rd": pz["ratingDeviation"], "outcome": 1.0})
    assert res["rating"] > res["before"]
    c.request("save_puzzle_attempt", {
        "puzzle_id": pz["id"], "session_id": None, "mode": "rated",
        "solved": True, "failed": False, "used_hint": False, "gave_up": False,
        "solve_time_s": 4.2, "rating_before": before["rating"], "rating_after": res["rating"],
    })
    print(f"✓ rated solve: {res['before']:.0f} → {res['rating']:.0f} (Glicko-2 in Python core)")

    # rush session + leaderboard
    sess = c.request("start_puzzle_session", {"mode": "rush", "time_limit_s": 180})
    c.request("update_puzzle_session", {"session_id": sess["sessionId"], "score": 7})
    lb = c.request("puzzle_leaderboard", {"mode": "rush", "time_limit_s": 180})
    assert lb["entries"][0]["score"] == 7 and lb["newRank"] == 0
    print("✓ rush session saved; leaderboard shows new entry at rank 0")

    # ── opening trainer ───────────────────────────────────────────────────────
    # W26: a missing book fails the book checks without hiding the ones after them.
    failed: list[str] = []
    if args.skip_trainer:
        print("- opening trainer SKIPPED (--skip-trainer: no book, W20; hidden in beta)")
        trainer(c, skip=True)
    else:
        for name, step in (("opening book", lambda: install_book(c, tmp, args.book)),
                           ("opening trainer", lambda: trainer(c, skip=False))):
            try:
                step()
            except Exception as exc:
                failed.append(f"{name}: {exc!r}")
                print(f"✗ {name} FAILED: {exc!r}")
                break
    finish(c, tmp, t0, failed)


def install_book(c: "Client", tmp: Path, book: Path | None) -> None:
    """BOOK-DL: put a manifest book in the temp data folder (a symlink, as if downloaded) and
    switch to it through the app's own path: book_use → verified backup → book relabel →
    book_done, then the facts refill."""
    sys.path.insert(0, str(REPO_ROOT))
    from tests.bookfile import real_book_path
    from zugzwang.core import books
    book = book or real_book_path()
    if book is None:
        raise AssertionError("no opening book: pass --book, set ZUGZWANG_TEST_BOOK, or install "
                             "one in the dev run (Settings → Opening book)")
    size = book.stat().st_size
    spec = next((b for b in books.MANIFEST if b.bytes == size), None)
    assert spec is not None, f"{book} is not a manifest book ({size} bytes)"
    st = c.request("books_status")
    assert st["active"] is None and not any(b["installed"] for b in st["books"]), st
    dest = tmp.parent / "books" / spec.file
    dest.parent.mkdir(exist_ok=True)
    dest.symlink_to(book.resolve())
    lobby = c.request("trainer_lobby")
    assert lobby["bookAvailable"] is False
    t = time.monotonic()
    assert c.request("book_use", {"id": spec.id})["started"] is True
    done = c.wait_event("book_done", timeout=300)
    assert done["id"] == spec.id and done["integrity"] == "ok", done
    assert Path(done["backup"]).exists(), done
    st = c.request("books_status")
    assert st["active"] == spec.id and st["job"] is None, st
    if done["labelsChanged"]:
        c.wait_event("pattern_facts_refilled", timeout=60)
    print(f"✓ book_use {spec.id}: backup, relabel of {done['runs']} runs "
          f"({done['labelsChanged']} labels → book) in {time.monotonic() - t:.1f}s")


def trainer(c: "Client", skip: bool) -> None:
    if skip:
        return
    lobby = c.request("trainer_lobby")
    # full encyclopedia: dozens of name-grouped families, available + gated
    assert len(lobby["families"]) > 50 and lobby["indexed"] is False
    assert any(f["available"] for f in lobby["families"])
    assert any(not f["available"] for f in lobby["families"])
    # default sort is popularity (total book weight) descending
    pops = [f["popularity"] for f in lobby["families"]]
    assert pops == sorted(pops, reverse=True)
    print(f"✓ trainer_lobby → {len(lobby['families'])} families "
          f"({sum(f['available'] for f in lobby['families'])} trainable), coverage not yet indexed")

    t3 = time.monotonic()
    c.request("trainer_index_coverage")
    c.wait_event("trainer_index_done", timeout=120)
    lobby = c.request("trainer_lobby")
    assert lobby["indexed"] is True
    print(f"✓ coverage indexed in {time.monotonic() - t3:.1f}s")

    fam = c.request("trainer_family", {"name": "Italian Game"})
    assert len(fam["lines"]) > 0
    line = fam["lines"][0]
    assert line["uci"] and line["fen"]
    print(f"✓ trainer_family → {len(fam['lines'])} curated Italian lines "
          f"(first: {line['eco']} {line['name']}, {len(line['uci'])} steering plies)")

    res = c.request("book_moves", {"fen": chess_start_fen()})
    assert "e2e4" in res["accepted"]
    res = c.request("book_reply", {"fen": chess_start_fen(), "mode": "pinned"})
    assert res["uci"] is not None
    print(f"✓ book queries work (pinned reply from start: {res['uci']})")

    res = c.request("opening_at", {"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"})
    assert res["opening"] is not None
    print(f"✓ opening_at → {res['opening']['eco']} {res['opening']['name']}")

    # mastery flow: 3 distinct terminal positions at 100% accuracy → mastered
    c.request("trainer_attempt", {"eco": line["eco"], "name": line["name"], "color": "white"})
    terminal_fens = [
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq - 0 1",
    ]
    prog = None
    for tf in terminal_fens:
        prog = c.request("trainer_complete", {
            "eco": line["eco"], "name": line["name"], "color": "white", "mode": "varied",
            "terminal_fen": tf, "moves_played": 6, "errors_made": 0, "accuracy": 1.0,
        })["progress"]
    assert prog["distinctLines"] == 3 and prog["mastered"] is True
    fam = c.request("trainer_family", {"name": "Italian Game"})
    assert fam["mastered"] == 1 and fam["drilled"] == 1
    lobby = c.request("trainer_lobby")
    italian = next(f for f in lobby["families"] if f["name"] == "Italian Game")
    assert italian["mastered"] == 1
    print("✓ mastery: 3 distinct completions @100% → line mastered, counts roll up")


def finish(c: "Client", tmp: Path, t0: float, failed: list[str] | None = None) -> None:
    c.close()

    # ── verify persistence with the real Database schema ─────────────────────
    conn = sqlite3.connect(tmp)
    rows = conn.execute(
        "SELECT id, result, termination, opening_name FROM games ORDER BY id"
    ).fetchall()
    n_runs = conn.execute("SELECT count(*) FROM analysis_runs").fetchone()[0]
    n_moves = conn.execute("SELECT count(*) FROM move_analyses").fetchone()[0]
    # R6: the completed run's pattern facts are written when it completes.
    n_facts = conn.execute(
        "SELECT count(*) FROM pattern_facts f JOIN analysis_runs r ON r.id = f.run_id"
        " WHERE r.completed_at IS NOT NULL").fetchone()[0]
    conn.close()
    # 4 played + 1 imported from text + 1 imported-but-truncated + 1 imported from
    # a file path. The truncated one is the point of counting here at all: a game
    # the parser gave up on is stored, so it has to show up.
    assert len(rows) == 7, f"expected 7 saved games, got {len(rows)}"
    terms = [r[2] for r in rows[:4]]
    assert terms == ["resignation", "draw_agreed", "timeout", "checkmate"], terms
    assert rows[0][3] is not None, "opening name not populated on save"
    assert n_runs == 1 and n_moves == 9, (n_runs, n_moves)
    assert n_facts == 1, f"expected the run's pattern facts, got {n_facts} rows"
    print(f"✓ 7 games + 1 analysis run ({n_moves} move rows) persisted to DB "
          f"(game 1 opening: {rows[0][3]})")

    if failed:
        print(f"\nFAILED ({len(failed)}): " + "; ".join(failed))
        sys.exit(1)
    print(f"\nAll checks passed in {time.monotonic() - t0:.1f}s total.")


if __name__ == "__main__":
    main()
