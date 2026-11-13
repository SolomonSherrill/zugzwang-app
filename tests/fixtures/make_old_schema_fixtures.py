"""Build the old-schema fixtures for the migration walk-forward test (BETA item 6).

    git archive ca20aa7 zugzwang | tar -x -C <dir>
    python tests/fixtures/make_old_schema_fixtures.py <dir>

`ca20aa7` is the repository's first commit (2026-09-18, "Zugzwang at review baseline").
Two databases, both written by that commit's own code:

- `schema_base_ca20aa7.db` — its `_SCHEMA` alone, no migrations: the shape a database
  had before migration v3 (no accuracy, source, external id, speed, rated, classifier
  version, completion, … columns; the old `puzzles` table). Rows inserted with SQL.
- `schema_v9_ca20aa7.db` — its `Database()` (schema + migrations v3–v9), rows written
  through its own API: what the oldest build in the repo left on disk.

Each holds one played game (Scholar's mate, 7 plies) with a run and its plies, and one
puzzle with a rating row.
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
PGN = ('[Event "Zugzwang"]\n[White "Player"]\n[Black "Stockfish"]\n[Result "1-0"]\n\n'
       '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n')
MOVES = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]


def plies():
    import chess
    b = chess.Board()
    out = []
    for i, u in enumerate(MOVES):
        out.append((i, b.fen(), u))
        b.push_uci(u)
    return out, b.fen()


def main(old_tree: str) -> None:
    sys.path.insert(0, old_tree)
    import zugzwang.core.database as old  # the first commit's module
    rows, final = plies()

    base = HERE / "schema_base_ca20aa7.db"
    base.unlink(missing_ok=True)
    con = sqlite3.connect(base)
    con.executescript(old._SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    con.execute("INSERT INTO games (played_at, player_color, skill_level, result, termination,"
                " move_count, opening_eco, opening_name, pgn, final_fen) VALUES "
                "('2026-09-01T12:00:00+00:00','white',5,'1-0','checkmate',7,'C23',"
                "'Bishop''s Opening',?,?)", (PGN, final))
    con.execute("INSERT INTO analysis_runs (game_id, engine_name, depth, created_at, payload_json)"
                " VALUES (1,'Stockfish',10,'2026-09-01T12:05:00+00:00','{}')")
    for ply, fen, u in rows:
        con.execute("INSERT INTO move_analyses (run_id, ply, fen_before, played_uci, best_uci,"
                    " pv_uci, score_before_cp, score_after_cp, classification, is_book)"
                    " VALUES (1,?,?,?,?,?,?,?,?,0)", (ply, fen, u, u, u, 30, 30, "best"))
    con.execute("INSERT INTO puzzles VALUES ('00008','r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24',"
                "'f2g3 e6e7 b2b1 b3c1 b1c1 h6c1',1913,'crushing hangingPiece long middlegame',"
                "'2026-09-01T12:00:00+00:00')")
    con.execute("INSERT INTO puzzle_rating (id, rating, rd, volatility, updated_at) VALUES "
                "(1, 1234.5, 120.0, 0.06, '2026-09-01T12:00:00+00:00')")
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()

    v9 = HERE / "schema_v9_ca20aa7.db"
    v9.unlink(missing_ok=True)
    db = old.Database(v9)
    gid = db.save_game(played_at="2026-09-01T12:00:00+00:00", player_color="white",
                       skill_level=5, result="1-0", termination="checkmate", move_count=7,
                       pgn=PGN, final_fen=final, opening_eco="C23",
                       opening_name="Bishop's Opening")
    rid = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=10)
    for ply, fen, u in rows:
        db.save_move_analysis(rid, old.MoveAnalysis(
            ply=ply, fen_before=fen, played_uci=u, best_uci=u, pv_uci=u, score_before_cp=30,
            score_before_mate=None, score_after_cp=30, score_after_mate=None,
            second_best_uci=None, second_best_cp=None, second_best_mate=None,
            classification="best", is_book=False))
    db._conn.execute(
        "INSERT INTO puzzles (id, fen, moves_uci, rating, rating_deviation, popularity, "
        "nb_plays, themes, game_url, opening_tags, imported_at) VALUES ('00008', "
        "'r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24', "
        "'f2g3 e6e7 b2b1 b3c1 b1c1 h6c1', 1913, 75, 95, 7000, "
        "'crushing hangingPiece long middlegame', '', '', '2026-09-01T12:00:00+00:00')")
    db._conn.commit()
    db._conn.execute("PRAGMA journal_mode=DELETE")
    db.close()
    for p in (base, v9):
        v = sqlite3.connect(p).execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        print(p.name, p.stat().st_size, "bytes, meta.schema_version", v)


if __name__ == "__main__":
    main(sys.argv[1])
