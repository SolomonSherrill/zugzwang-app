"""Write desktop/harness/friends_fixtures.json: the Friends screens' data for the browser harness, made
by the sidecar's own code (platform_games' parsers, scouting, list_payload/profile_payload) from the
synthetic games of tests/friends_fixtures.py. Every name is made up. Re-run after changing either:

    .venv/bin/python -m tests.make_friends_harness_fixtures
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from tests import friends_fixtures as FX
from zugzwang.core.database import Database
from zugzwang.core.friends import platform_games as PG
from zugzwang.core.friends import rating_compare
from zugzwang.core.friends.runner import list_payload, profile_payload

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
OUT = Path(__file__).resolve().parents[1] / "desktop" / "harness" / "friends_fixtures.json"
ME = {"chesscom": "you_demo", "lichess": "you_demo_li"}
H = 3600_000

FRIENDS = [
    # handle, online, last seen ago (ms), linked, seed, n
    ("maxk", True, 0, [("chesscom", "maxk_chess")], 11, 220),
    ("benji", True, 0, [("lichess", "benji_lc")], 12, 90),
    ("noa_p", False, 2 * H, [("chesscom", "noa_p_cc"), ("lichess", "noa_p_lc")], 13, 140),
    ("dvorak77", False, 3 * 24 * H, [("chesscom", "dvorak77_cc")], 14, 70),
    ("hannah_k", False, 15 * 24 * H, [], 15, 0),
]


def main() -> None:
    eco = PG.eco_only_book()
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "h.db")
        friends = []
        for i, (handle, online, ago, linked, seed, n) in enumerate(FRIENDS):
            for site, user in linked:
                opp = [ME[site], "rook_lift_demo", "gambit_goblin_demo", "pawnstar_demo", "h_ortega_demo"]
                if site == "chesscom":
                    arch = FX.chesscom_archives(user, NOW, opponents=opp, n=n, seed=seed)
                    rows = [r for a in arch.values() for r in PG.chesscom_rows(user, a["games"], eco)]
                else:
                    rows = PG.lichess_rows(user, FX.lichess_games(user, NOW, opponents=opp, n=n, seed=seed), eco)
                db.save_friend_games(rows)
                db.set_friend_player(site, user.lower(), fetched_at=(datetime.fromtimestamp((NOW_MS - 12 * 60_000) / 1000, timezone.utc)
                                     .strftime("%Y-%m-%dT%H:%M:%SZ")), oldest="2025-12-01T00:00:00Z", complete=False)
            friends.append({"handle": handle, "since": NOW_MS - (50 + 9 * i) * 24 * H, "online": online,
                            "last_seen": NOW_MS - ago if not online else NOW_MS - 30_000,
                            "linked": [{"site": s, "username": u} for s, u in linked]})
        lst = {"server_time": NOW_MS, "friends": friends,
               "incoming": [{"id": 31, "handle": "ri_tan", "created": NOW_MS - 2 * H},
                            {"id": 32, "handle": "elena_v", "created": NOW_MS - 26 * H}],
               "outgoing": [{"id": 33, "handle": "jdaw", "created": NOW_MS - 50 * H}], "blocked": []}
        out_list = list_payload(db, lst, ME)
        profiles = {f["handle"]: profile_payload(db, f, ME, recent_limit=60) for f in friends}
        games = {}
        for p in profiles.values():
            for g in p["recent"][:3]:
                row = db.friend_game(g["id"])
                import chess.pgn, io
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                games[str(g["id"])] = {"id": row["id"], "site": row["site"], "white": row["white"], "black": row["black"],
                                       "whiteElo": row["white_elo"], "blackElo": row["black_elo"], "result": row["result"],
                                       "opening": row["opening"], "eco": row["eco"], "endedAt": row["ended_at"],
                                       "timeControl": row["time_control"], "startFen": game.board().fen(),
                                       "moves": [m.uci() for m in game.mainline_moves()]}
        db.close()
    data = {"now": NOW_MS, "me": ME, "handle": "you_demo", "list": out_list, "profiles": profiles,
            "games": games, "ratingSource": rating_compare.credit(),
            "recoveryCode": "7K2Q-M9DX-W4P8-RTA6-HVN3-C5JF-0BGE-1YZS-Q8KD",
            "me_linked": [{"site": "chesscom", "username": "you_demo", "verified": True}]}
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
