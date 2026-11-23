"""Synthetic friends' games for the Friends tests, the headless end-to-end run and the harness
(FRIENDS-1 E). Every player is made up; every game id is short (the public scan reads 9-12 digits as a
game id). Deterministic: the same call gives the same games.

`chesscom_archives(user, now)` → {archive url: {"games": [...]}} as api.chess.com serves them;
`lichess_games(user, now)` → the ndjson objects lichess.org's /api/games/user serves.
"""
from __future__ import annotations

import io
import random
from datetime import datetime, timedelta, timezone

import chess
import chess.pgn

#: opening lines (SAN), each a plausible start
LINES = {
    "italian": "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6",
    "ruy": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7",
    "scotch": "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nc3 Bb4",
    "qgd": "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O",
    "london": "d4 d5 Bf4 Nf6 e3 c5 c3 Nc6 Nd2 e6",
    "sicilian": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
    "french": "e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6",
    "caro": "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5",
    "kid": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O",
    "slav": "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5",
}
#: a mating finish from the start position (fool's mate pattern, for a checkmate ending)
MATE_BLACK = "f3 e5 g4 Qh4#"
TCS = [("180+2", "blitz", 180, 2), ("300", "blitz", 300, 0), ("600", "rapid", 600, 0),
       ("60", "bullet", 60, 0)]


def _pgn(white: str, black: str, line: str, result: str, termination: str, when: datetime,
         site: str, tc: str, extra: dict | None = None) -> str:
    g = chess.pgn.Game()
    g.headers.update({"Event": "Live Chess" if site == "chesscom" else "Rated game",
                      "Site": "Chess.com" if site == "chesscom" else "lichess.org",
                      "Date": when.strftime("%Y.%m.%d"), "White": white, "Black": black,
                      "Result": result, "TimeControl": tc, "Termination": termination})
    for k, v in (extra or {}).items():
        g.headers[k] = v
    node = g
    board = chess.Board()
    for san in line.split():
        mv = board.parse_san(san)
        board.push(mv)
        node = node.add_variation(mv)
    return str(g)


def _games(user: str, opponents: list[str], now: datetime, n: int, seed: int, site: str,
           days: int = 360) -> list[dict]:
    rnd = random.Random(seed)
    out = []
    rating = {"blitz": 1440, "rapid": 1510, "bullet": 1370}
    for i in range(n):
        when = now - timedelta(days=days * (n - i) / n, hours=rnd.randint(0, 20))
        opp = opponents[i % len(opponents)]
        as_white = rnd.random() < 0.5
        tc, speed, base, inc = TCS[rnd.randrange(len(TCS))]
        key = rnd.choice(["italian", "ruy", "scotch", "qgd", "london"] if as_white else
                         ["sicilian", "french", "caro", "kid", "slav", "italian", "qgd"])
        r = rnd.random()
        mate = r < 0.08
        if mate:
            line, res, term, as_white = MATE_BLACK, "0-1", f"{user} won by checkmate", False
        else:
            line = LINES[key]
            outcome = "won" if r < 0.55 else "drawn" if r < 0.62 else "lost"
            winner_white = (outcome == "won") == as_white
            res = "1/2-1/2" if outcome == "drawn" else ("1-0" if winner_white else "0-1")
            how = rnd.choice(["resignation", "resignation", "time", "checkmate"])
            wname = (user if as_white else opp) if winner_white else (opp if as_white else user)
            term = ("Game drawn by agreement" if outcome == "drawn" else
                    f"{wname} won on time" if how == "time" else f"{wname} won by {how}")
        rating[speed] += rnd.randint(-12, 14)
        white, black = (user, opp) if as_white else (opp, user)
        welo = rating[speed] if as_white else rating[speed] + rnd.randint(-40, 40)
        belo = rating[speed] if not as_white else rating[speed] + rnd.randint(-40, 40)
        out.append({"i": i, "when": when, "white": white, "black": black, "line": line, "res": res,
                    "term": term, "tc": tc, "speed": speed, "base": base, "inc": inc,
                    "welo": welo, "belo": belo, "rated": rnd.random() < 0.9})
    return out


def chesscom_archives(user: str, now: datetime, *, opponents: list[str] | None = None,
                      n: int = 120, seed: int = 1, days: int = 360, base: str = "https://api.chess.com") -> dict:
    opponents = opponents or ["rook_lift_demo", "gambit_goblin_demo", "pawnstar_demo", "h_ortega_demo"]
    months: dict[str, list] = {}
    for g in _games(user, opponents, now, n, seed, "chesscom", days):
        w = g["when"]
        url = f"{base}/pub/player/{user.lower()}/games/{w.year:04d}/{w.month:02d}"
        gid = 70000000 + seed * 10000 + g["i"]
        months.setdefault(url, []).append({
            "url": f"https://www.chess.com/game/live/{gid}",
            "pgn": _pgn(g["white"], g["black"], g["line"], g["res"], g["term"], w, "chesscom", g["tc"]),
            "time_control": g["tc"], "end_time": int(w.timestamp()), "rated": g["rated"],
            "time_class": g["speed"], "rules": "chess",
            "white": {"username": g["white"], "rating": g["welo"],
                      "result": "win" if g["res"] == "1-0" else "agreed" if g["res"] == "1/2-1/2" else "resigned"},
            "black": {"username": g["black"], "rating": g["belo"],
                      "result": "win" if g["res"] == "0-1" else "agreed" if g["res"] == "1/2-1/2" else "resigned"},
        })
    return {u: {"games": gs} for u, gs in sorted(months.items())}


def lichess_games(user: str, now: datetime, *, opponents: list[str] | None = None, n: int = 60,
                  seed: int = 2, days: int = 360) -> list[dict]:
    opponents = opponents or ["knightly_demo", "bishop_pair_demo"]
    out = []
    for g in _games(user, opponents, now, n, seed, "lichess", days):
        status = ("mate" if "checkmate" in g["term"] else "draw" if g["res"] == "1/2-1/2" else
                  "outoftime" if "time" in g["term"] else "resign")
        winner = "white" if g["res"] == "1-0" else "black" if g["res"] == "0-1" else None
        o = {"id": f"lc{seed}{g['i']:04d}x", "rated": g["rated"], "variant": "standard",
             "speed": g["speed"], "perf": g["speed"], "createdAt": int(g["when"].timestamp() * 1000) - 600000,
             "lastMoveAt": int(g["when"].timestamp() * 1000), "status": status,
             "players": {"white": {"user": {"name": g["white"], "id": g["white"].lower()}, "rating": g["welo"] + 300},
                         "black": {"user": {"name": g["black"], "id": g["black"].lower()}, "rating": g["belo"] + 300}},
             "clock": {"initial": g["base"], "increment": g["inc"], "totalTime": g["base"] + 40 * g["inc"]},
             "pgn": _pgn(g["white"], g["black"], g["line"], g["res"], "Normal", g["when"], "lichess",
                         f"{g['base']}+{g['inc']}")}
        if winner:
            o["winner"] = winner
        out.append(o)
    return out
