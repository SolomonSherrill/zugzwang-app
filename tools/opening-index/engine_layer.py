"""
Opening data, engine layer (OPENING_DATA.md, "Engine layer: built"; FIXPLAN OPENDATA-ENGINE).

Evaluates opening-index positions in the owner's band in descending order of the band's
game count, so any prefix of the run is the most valuable prefix and it can be killed at
any moment. Per position: one unrestricted search (the best move), then one `searchmoves`
search for each of the band's most-played moves, so a popular bad move is scored however
far from the top it sits. Every search starts on a fresh hash (`ucinewgame`), so each
stored value is reproducible by one direct search of that position.

Writes to its own SQLite file; nothing in the games corpus is touched. A position is
written with all its moves in one transaction, and positions already in the table are
skipped, so a restart picks up where it stopped and a re-run changes nothing.

    .venv/bin/python tools/opening-index/engine_layer.py run    DB TARGETS FENS [--engines N] [--limit N]
    .venv/bin/python tools/opening-index/engine_layer.py verify DB [--sample N] [--seed S]
    .venv/bin/python tools/opening-index/engine_layer.py known

Scores are from the side to move at the position: `cp`, or `mate` (moves, signed). `wpl` is
`classification.wpl(best, move)` — the same win-probability loss the game analysis uses.
"""
import argparse
import hashlib
import os
import queue
import random
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from zugzwang.core.classification import wpl  # noqa: E402
from zugzwang.core.engine_locator import find_stockfish  # noqa: E402

DEPTH = 14
THREADS = 1
HASH_MB = 16
BANDS = "1-3"  # 600-799, 800-999, 1000-1199: the mover's rating
PLY_CAP = 24
TOP_MOVES = 3
INDEX = "index24-2026-08-09.bin"
INDEX_MONTHS = "2026-08,2026-09"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opening_engine_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opening_engine_positions (
    key         TEXT PRIMARY KEY,   -- Polyglot key, 16 hex digits
    fen         TEXT NOT NULL,
    min_ply     INTEGER NOT NULL,   -- shallowest ply the index saw it at
    band_games  INTEGER NOT NULL,   -- games by movers in the band reaching it
    queue_rank  INTEGER NOT NULL,   -- 0 = most games
    status      TEXT NOT NULL,      -- 'ok', or 'no_moves' (mate / stalemate)
    best_uci    TEXT,
    best_cp     INTEGER,
    best_mate   INTEGER,
    best_pv     TEXT,
    seconds     REAL NOT NULL,      -- wall time of all its searches on one engine
    evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opening_engine_moves (
    key         TEXT NOT NULL,
    rank        INTEGER NOT NULL,   -- 1 = most played in the band
    move_uci    TEXT NOT NULL,
    polyglot    INTEGER NOT NULL,
    band_games  INTEGER NOT NULL,
    cp          INTEGER,
    mate        INTEGER,
    pv          TEXT,
    wpl         REAL,               -- loss against the unrestricted best, >= 0
    is_best     INTEGER NOT NULL,   -- the unrestricted search chose this move
    PRIMARY KEY (key, move_uci)
);
"""


def decode(board, raw):
    """A Polyglot move as python-chess's reader decodes it (castling king-takes-rook)."""
    to, frm, promo = raw & 0x3F, (raw >> 6) & 0x3F, (raw >> 12) & 0x7
    move = chess.Move(frm, to, promotion=[None, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN][promo])
    if board.piece_type_at(frm) == chess.KING and board.color_at(to) == board.turn:
        move = chess.Move(frm, {chess.H1: chess.G1, chess.A1: chess.C1, chess.H8: chess.G8, chess.A8: chess.C8}[to])
    return move


def open_engine():
    eng = chess.engine.SimpleEngine.popen_uci(str(find_stockfish()))
    eng.configure({"Threads": THREADS, "Hash": HASH_MB})
    return eng


def search(eng, board, move=None):
    """One depth-DEPTH search on a fresh hash, optionally restricted to `move`."""
    info = eng.analyse(board, chess.engine.Limit(depth=DEPTH), root_moves=[move] if move else None,
                       game=object())  # a new game object sends ucinewgame: fresh hash
    s = info["score"].relative
    pv = info.get("pv", [])
    return s.score(), s.mate(), pv


def evaluate(eng, fen, tops):
    """(best, moves) for one position; tops = [(polyglot move, band games)]."""
    board = chess.Board(fen)
    if not any(board.legal_moves):
        return None, []
    cp, mate, pv = search(eng, board)
    best = (pv[0].uci() if pv else None, cp, mate, " ".join(m.uci() for m in pv))
    moves = []
    for rank, (raw, n) in enumerate(tops, 1):
        m = decode(board, raw)
        if m not in board.legal_moves:
            raise ValueError(f"{fen}: polyglot move {raw} decodes to illegal {m}")
        mcp, mmate, mpv = search(eng, board, m)
        if mpv and mpv[0] != m:
            raise RuntimeError(f"{fen}: searchmoves {m} returned a PV starting {mpv[0]}")
        moves.append((rank, m.uci(), raw, n, mcp, mmate, " ".join(x.uci() for x in mpv),
                      wpl(cp, mate, mcp, mmate), int(m.uci() == best[0])))
    return best, moves


def engine_id():
    out = subprocess.run([str(find_stockfish())], input="uci\nquit\n", capture_output=True, text=True).stdout
    return next(line[len("id name "):] for line in out.splitlines() if line.startswith("id name "))


def provenance(targets, fens, engines):
    sf = find_stockfish()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    return {
        "engine": engine_id(),
        "engine_path": str(sf),
        "engine_sha256": hashlib.sha256(sf.read_bytes()).hexdigest(),
        "depth": str(DEPTH), "threads": str(THREADS), "hash_mb": str(HASH_MB),
        "search": "unrestricted best + one searchmoves search per popular move; ucinewgame before every search",
        "bands": f"{BANDS} (mover's rating 600-1199)", "ply_cap": str(PLY_CAP), "top_moves": str(TOP_MOVES),
        "order": "band_games descending, then key",
        "index": INDEX, "index_months": INDEX_MONTHS,
        "targets": str(targets), "fens": str(fens),
        "engines": str(engines),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit + ("-dirty" if dirty else ""),
    }


def connect(path):
    db = sqlite3.connect(path, timeout=60, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def load_queue(targets, fens):
    fen_of = {}
    for line in open(fens):
        k, f = line.rstrip("\n").split("\t")
        fen_of[k] = f
    q = []
    for line in open(targets):
        k, minply, n, tops = line.rstrip("\n").split("\t")
        q.append((-int(n), k, int(minply),
                  [(int(a), int(b)) for a, b in (t.split(":") for t in tops.split(",") if t)]))
    q.sort()
    missing = sum(1 for x in q if x[1] not in fen_of)
    return [(r, k, fen_of[k], minply, -negn, tops) for r, (negn, k, minply, tops) in enumerate(q) if k in fen_of], missing


def run(a):
    db = connect(a.db)
    meta = dict(db.execute("SELECT key, value FROM opening_engine_meta"))
    prov = provenance(a.targets, a.fens, a.engines)
    if meta:
        for k in ("engine", "engine_sha256", "depth", "threads", "hash_mb", "bands", "ply_cap", "top_moves", "index"):
            if meta[k] != prov[k]:
                sys.exit(f"refusing to resume: {k} is {prov[k]!r}, the table was written with {meta[k]!r}")
        # Each start appends its own line, so a run split over restarts records every commit.
        db.execute("INSERT INTO opening_engine_meta VALUES (?, ?)",
                   (f"resumed_{prov['started']}", f"commit {prov['commit']}, engines {a.engines}"))
    else:
        db.executemany("INSERT INTO opening_engine_meta VALUES (?, ?)", prov.items())
    db.commit()
    done = {k for (k,) in db.execute("SELECT key FROM opening_engine_positions")}
    work, missing = load_queue(a.targets, a.fens)
    todo = [w for w in work if w[1] not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"queue {len(work):,} (targets without a FEN: {missing}); already evaluated {len(done):,}; "
          f"this run {len(todo):,} on {a.engines} engines, {prov['engine']}, depth {DEPTH}", flush=True)

    jobs: queue.Queue = queue.Queue(maxsize=a.engines * 4)
    results: queue.Queue = queue.Queue()
    stop = threading.Event()

    def worker():
        eng = open_engine()
        try:
            while True:
                job = jobs.get()
                if job is None:
                    return
                rank, k, fen, minply, n, tops = job
                t = time.perf_counter()
                best, moves = evaluate(eng, fen, tops)
                results.put((job, best, moves, time.perf_counter() - t))
        except Exception as e:  # noqa: BLE001 - reported and the run stops; nothing half-written
            results.put(("error", repr(e), None, None))
        finally:
            eng.quit()

    def feeder():
        for job in todo:
            if stop.is_set():
                break
            jobs.put(job)
        for _ in range(a.engines):
            jobs.put(None)

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(a.engines)]
    for th in threads:
        th.start()
    threading.Thread(target=feeder, daemon=True).start()

    t0, written, last_commit, last_report, errors = time.time(), 0, time.time(), time.time(), 0
    try:
        while any(th.is_alive() for th in threads) or not results.empty():
            try:
                job, best, moves, secs = results.get(timeout=1)
            except queue.Empty:
                continue
            if job == "error":
                print(f"worker error: {best}", flush=True)
                errors += 1
                stop.set()
                continue
            rank, k, fen, minply, n, tops = job
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db:
                db.execute("DELETE FROM opening_engine_moves WHERE key = ?", (k,))
                if best is None:
                    db.execute("INSERT OR REPLACE INTO opening_engine_positions VALUES (?,?,?,?,?,'no_moves',NULL,NULL,NULL,NULL,?,?)",
                               (k, fen, minply, n, rank, secs, now))
                else:
                    db.execute("INSERT OR REPLACE INTO opening_engine_positions VALUES (?,?,?,?,?,'ok',?,?,?,?,?,?)",
                               (k, fen, minply, n, rank, *best, secs, now))
                    db.executemany("INSERT INTO opening_engine_moves VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   [(k, *m) for m in moves])
            written += 1
            if time.time() - last_report > 600:
                el = time.time() - t0
                print(f"{written:,} positions in {el / 3600:.2f} h ({written / el * 3600:,.0f}/h); "
                      f"last rank {rank:,}, {n} games", flush=True)
                last_report = time.time()
    except KeyboardInterrupt:
        stop.set()
    el = time.time() - t0
    print(f"stopped: {written:,} positions written in {el:.0f} s, errors {errors}", flush=True)


def uci_search(sf, fen, move=None):
    """A direct search through a raw UCI pipe, independent of python-chess's engine layer."""
    p = subprocess.Popen([sf], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    cmd = f"uci\nsetoption name Threads value {THREADS}\nsetoption name Hash value {HASH_MB}\nucinewgame\nisready\n"
    cmd += f"position fen {fen}\ngo depth {DEPTH}" + (f" searchmoves {move}" if move else "") + "\n"
    p.stdin.write(cmd)
    p.stdin.flush()
    last = None
    for line in p.stdout:
        if line.startswith("info") and " depth " in line and " score " in line and " multipv " in line:
            last = line.split()
        if line.startswith("bestmove"):
            bm = line.split()[1]
            break
    p.stdin.write("quit\n")
    p.stdin.flush()
    p.wait()
    i = last.index("score")
    cp = int(last[i + 2]) if last[i + 1] == "cp" else None
    mate = int(last[i + 2]) if last[i + 1] == "mate" else None
    return bm, cp, mate


def verify(a):
    db = sqlite3.connect(a.db)
    sf = str(find_stockfish())
    rows = db.execute("SELECT key, fen, best_uci, best_cp, best_mate FROM opening_engine_positions "
                      "WHERE status = 'ok' ORDER BY queue_rank").fetchall()
    rng = random.Random(a.seed)
    pick = rows[:2] + rng.sample(rows[2:], min(a.sample, len(rows) - 2))
    bad = 0
    for key, fen, best_uci, best_cp, best_mate in pick:
        top = db.execute("SELECT move_uci, cp, mate, band_games FROM opening_engine_moves "
                         "WHERE key = ? AND rank = 1", (key,)).fetchone()
        db_best = (best_uci, best_cp, best_mate)
        fresh_best = uci_search(sf, fen)
        fresh_top = uci_search(sf, fen, top[0])
        ok = fresh_best == db_best and fresh_top == (top[0], top[1], top[2])
        bad += not ok
        print(f"{'OK  ' if ok else 'DIFF'} {key} {fen}\n"
              f"     best   stored {db_best}  fresh {fresh_best}\n"
              f"     played stored {(top[0], top[1], top[2])} ({top[3]} games)  fresh {fresh_top}")
    print(f"{len(pick) - bad} of {len(pick)} match exactly, {bad} differ")


KNOWN = [
    # (name, moves to the position, the move to score, what to expect)
    ("Ruy Lopez mainline, 3...a6", "e4 e5 Nf3 Nc6 Bb5", "a7a6", "sound: small loss"),
    ("Italian, 3...Bc5", "e4 e5 Nf3 Nc6 Bc4", "f8c5", "sound: small loss"),
    ("Queen's Gambit Declined, 2...e6", "d4 d5 c4", "e7e6", "sound: small loss"),
    ("Stafford Gambit, 3...Nc6", "e4 e5 Nf3 Nf6 Nxe5", "b8c6", "dubious: Black worse than after 3...d6"),
    ("Stafford trap, 6.Bg5??", "e4 e5 Nf3 Nf6 Nxe5 Nc6 Nxc6 dxc6 d3 Bc5", "c1g5", "blunder: 6...Nxe4"),
    ("Englund Gambit, 1...e5", "d4", "e7e5", "dubious: Black worse"),
    ("Englund trap, 6.Bc3??", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2", "d2c3", "blunder: 6...Bb4, ...Qc1#"),
    ("Englund, 6.Nc3 (the right move)", "d4 e5 dxe5 Nc6 Nf3 Qe7 Bf4 Qb4+ Bd2 Qxb2", "b1c3", "best or near it"),
]


def known(_a):
    eng = open_engine()
    sf = str(find_stockfish())
    print(engine_id(), f"depth {DEPTH}, {THREADS} thread, hash {HASH_MB} MB")
    for name, line, uci, expect in KNOWN:
        b = chess.Board()
        for san in line.split():
            b.push_san(san)
        m = chess.Move.from_uci(uci)
        cp, mate, pv = search(eng, b)
        mcp, mmate, mpv = search(eng, b, m)
        loss = wpl(cp, mate, mcp, mmate)
        raw_best, raw_move = uci_search(sf, b.fen()), uci_search(sf, b.fen(), uci)
        same = raw_best == (pv[0].uci(), cp, mate) and raw_move == (mpv[0].uci(), mcp, mmate)
        print(f"{name:34} best {pv[0].uci()} {cp if mate is None else f'#{mate}'}; "
              f"{uci} {mcp if mmate is None else f'#{mmate}'} pv {' '.join(x.uci() for x in mpv[:4])}; "
              f"wpl {loss:.3f}  [{expect}]  raw-UCI {'same' if same else f'DIFF {raw_best} {raw_move}'}")
    eng.quit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("db")
    r.add_argument("targets")
    r.add_argument("fens")
    r.add_argument("--engines", type=int, default=(os.cpu_count() or 2) - 1)
    r.add_argument("--limit", type=int, default=0)
    v = sub.add_parser("verify")
    v.add_argument("db")
    v.add_argument("--sample", type=int, default=6)
    v.add_argument("--seed", type=int, default=20261023)
    sub.add_parser("known")
    args = ap.parse_args()
    {"run": run, "verify": verify, "known": known}[args.cmd](args)
