#!/usr/bin/env python3
"""Games against friends, end to end and headless (FRIENDS-2 E): two app identities (two real sidecars,
each with its own temp database, data folder and file keystore) against the Friends Worker run locally by
`wrangler dev --local` (its Durable Objects in Miniflare), with the local Chess.com/Lichess stand-in for
the ratings at a game's start. The rules' times are shortened by the Worker's variables (first move 2.5 s,
disconnect 2 s, a 1+0 game's clocks 3 s: FLAG_TEST_MS, local only). Nothing touches the network, a real
keychain, a real database or the owner's screen.

Covered: a challenge reaching the other app (timed, under 3 s), a full game to checkmate saved to both
libraries with the "Friends" source, the ratings at its start ("≈" for the Lichess-only player) and its
analysis queued at depth 14; chat on, muted, off; a rematch with the colours swapped, then resign; a draw
offer declined and one accepted; a flag; a disconnect (the app quits) then the claim, and the game saved
when that app comes back; an abort (no first move); no shared games (BETA-6 SG1: no table); chat
blocked mid-game; the test opponent (sidecar/friends_bot.py: it befriends A, accepts A's challenge, answers
chat, offers a draw once, deletes its account when it stops, and on Ctrl-C); deleting both accounts, every
server table empty after.

    .venv/bin/python sidecar/friends_play_e2e.py [--out review/scratch/friends/play_e2e.out]

Needs server/node_modules (cd server && npm ci) and stockfish/ (the analysis). Exit 0 when every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "sidecar"))

import friends_e2e as E  # noqa: E402
from friends_e2e import App, check, d1, free_port  # noqa: E402
from tests.friends_servers import PlatformServer  # noqa: E402

SERVER = REPO / "server"
SCHOLAR = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]


def game_event(app: App, gid: str, kind: str, pred=lambda d: True, timeout: float = 20) -> dict:
    return app.wait_event("friend_game", lambda d: d.get("id") == gid and d.get("kind") == kind and pred(d), timeout)


def state_where(app: App, gid: str, pred, timeout: float = 20) -> dict:
    return game_event(app, gid, "state", lambda d: pred(d["state"]), timeout)["state"]


def start_game(a: App, b: App, hb: str, tc: str, colour: str) -> tuple[str, float]:
    """a challenges b; b accepts; both open the game. Returns the game id and the challenge's travel time."""
    t0 = time.monotonic()
    c = a.call("friends_challenge", {"handle": hb, "tc": tc, "colour": colour})
    if "error" in c:
        raise RuntimeError(f"challenge refused: {c['error']}")
    cid = c["challenge"]["id"]
    b.wait_event("friends_live", lambda d: d.get("kind") == "challenge" and d["challenge"]["id"] == cid, 10)
    travel = time.monotonic() - t0
    acc = b.call("friends_challenge_answer", {"id": cid, "accept": True})
    if "error" in acc:
        raise RuntimeError(f"accept refused: {acc['error']}")
    gid = acc["game"]["id"]
    for x in (a, b):
        x.wait_event("friends_live", lambda d: d.get("kind") == "game_start" and d["game"]["id"] == gid, 10)
        x.call("friends_live_game", {"id": gid})
        state_where(x, gid, lambda s: s["status"] == "waiting")
    return gid, travel


def start_game_vs_bot(a: App, bot_handle: str) -> tuple[str, float]:
    """a challenges the bot (sidecar/friends_bot.py), which accepts on its own; a opens the game."""
    t0 = time.monotonic()
    c = a.call("friends_challenge", {"handle": bot_handle, "tc": "5+0", "colour": "white"})
    if "error" in c:
        raise RuntimeError(f"challenge refused: {c['error']}")
    g = a.wait_event("friends_live", lambda d: d.get("kind") == "game_start"
                     and bot_handle in (d["game"]["white_handle"], d["game"]["black_handle"]), 20)["game"]
    a.call("friends_live_game", {"id": g["id"]})
    game_event(a, g["id"], "connection", lambda d: d.get("connected") is True, 10)
    return g["id"], time.monotonic() - t0


def play(white: App, black: App, gid: str, ucis: list[str], start: int = 0) -> None:
    for i, uci in enumerate(ucis, start):
        side = white if i % 2 == 0 else black
        r = side.call("friends_game_send", {"id": gid, "msg": {"t": "move", "uci": uci, "ply": i}})
        if "error" in r:
            raise RuntimeError(f"move {uci}: {r['error']}")
        state_where(side, gid, lambda s, n=i + 1: len(s["moves"]) == n)


def send(app: App, gid: str, msg: dict) -> None:
    r = app.call("friends_game_send", {"id": gid, "msg": msg})
    if "error" in r:
        raise RuntimeError(f"{msg}: {r['error']}")


def no_chat(app: App, gid: str, secs: float = 1.0) -> bool:
    try:
        game_event(app, gid, "chat", timeout=secs)
        return False
    except TimeoutError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    t0 = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="zz-friends-play-"))
    sites = PlatformServer()
    sites.lichess_perfs["b_lichess_demo"] = {"blitz": {"rating": 1700}, "rapid": {"rating": 1750}}
    sites.oauth_user = "b_lichess_demo"
    persist = root / "d1"
    env_w = dict(os.environ, WRANGLER_SEND_METRICS="false")
    subprocess.run(["npx", "wrangler", "d1", "migrations", "apply", "zugzwang-friends", "--local",
                    "--persist-to", str(persist)], cwd=SERVER, check=True, capture_output=True, env=env_w)
    port = free_port()
    worker = subprocess.Popen(["npx", "wrangler", "dev", "--local", "--port", str(port), "--ip", "127.0.0.1",
                               "--persist-to", str(persist), "--var", f"LICHESS_API:{sites.base}",
                               "--var", f"CHESSCOM_API:{sites.base}", "--var", "LINK_SECRET:e2e-secret",
                               "--var", "FIRST_MOVE_MS:2500", "--var", "DISCONNECT_MS:2000",
                               "--var", "FLAG_TEST_MS:3000", "--var", "STALE_MS:60000"],
                              cwd=SERVER, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env_w)
    url = f"http://127.0.0.1:{port}"
    apps: list[App] = []
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(url + "/v1/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.5)
        extra = {"ZUGZWANG_FRIENDS_URL": url, "ZUGZWANG_CHESSCOM_API": sites.base,
                 "ZUGZWANG_LICHESS_API": sites.base, "ZUGZWANG_OAUTH_OPENER": "fetch"}
        A, B = App("a", root, extra), App("b", root, extra)
        apps += [A, B]
        for x in (A, B):
            x.wait_event("ready", timeout=60)
        ha, hb = "play_alpha", "play_bravo"
        A.call("friends_signup", {"handle": ha, "ageConfirmed": True, "termsAccepted": True})
        B.call("friends_signup", {"handle": hb, "ageConfirmed": True, "termsAccepted": True})
        r = A.call("friends_request", {"handle": hb})
        inc = B.call("friends_list", {"mine": {}})["incoming"]
        B.call("friends_answer", {"id": inc[0]["id"], "accept": True})
        li = B.call("friends_link_lichess")
        check("setup: two friends; B Lichess-only (linked by its sign-in)", r.get("status") == "sent" and li.get("verified") is True)
        for x in (A, B):
            x.call("friends_list", {"mine": {}})        # starts the heartbeat and the live connection
            x.call("friends_live")
            x.wait_event("friends_live", lambda d: d.get("kind") == "hello", 20)
        check("both apps hold a live connection (the lobby's hello)", True)

        # ── a full game ────────────────────────────────────────────────────────────
        gid, travel = start_game(A, B, hb, "5+0", "white")
        check("a challenge reaches the other app within 3 s", travel < 3.0, f"{travel * 1000:.0f} ms")
        send(A, gid, {"t": "chat", "text": "good luck"})
        line = game_event(B, gid, "chat")["line"]
        check("chat on: A's message reaches B", line["text"] == "good luck" and line["handle"] == ha)
        send(B, gid, {"t": "mute", "on": True})
        state_where(B, gid, lambda s: s["muted"] is True)
        send(A, gid, {"t": "chat", "text": "can you hear me"})
        check("muted: B no longer receives A's messages", no_chat(B, gid))
        send(B, gid, {"t": "mute", "on": False})
        state_where(B, gid, lambda s: s["muted"] is False)
        B.call("friends_set_settings", {"chatEnabled": False})
        state_where(A, gid, lambda s: s["opponent"]["chat_on"] is False)
        send(A, gid, {"t": "chat", "text": "hello?"})
        err = game_event(A, gid, "error")
        check("chat off (B's switch, sent to the server): A sees it off and cannot send", err["error"] == "opponent_chat_off")
        B.call("friends_set_settings", {"chatEnabled": True})
        state_where(A, gid, lambda s: s["opponent"]["chat_on"] is True)
        play(A, B, gid, SCHOLAR)
        over = state_where(B, gid, lambda s: s["status"] == "over")
        check("a full game: checkmate decided on the server", over["result"] == "1-0" and over["termination"] == "checkmate")
        sa = game_event(A, gid, "saved")
        sb = game_event(B, gid, "saved")
        ga = [g for g in A.call("list_games", {})["games"] if g["id"] == sa["gameId"]][0]
        gb = [g for g in B.call("list_games", {})["games"] if g["id"] == sb["gameId"]][0]
        check("saved to both libraries with the Friends source", ga["source"] == gb["source"] == "friends"
              and ga["playerColor"] == "white" and gb["playerColor"] == "black")
        sr = ga["startRatings"]
        check("ratings at the start: B's \"≈\" from Lichess, A's blank (no linked account)",
              sr is not None and sr["white"] is None and sr["black"]["estimated"] is True and sr["black"]["rating"] > 0,
              json.dumps(sr))
        A.wait_event("sync_finished", timeout=120)
        ga2 = [g for g in A.call("list_games", {})["games"] if g["id"] == sa["gameId"]][0]
        check("analysed after saving (depth 14)", ga2["analyzed"] is True)
        tables_now = {r["name"] for r in d1(persist, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        check("no shared games (BETA-6 SG1): the server has no shared_games table", "shared_games" not in tables_now)

        # ── rematch with colours swapped, then resign ────────────────────────────────
        rm = A.call("friends_rematch", {"id": gid})
        rid = rm["challenge"]["id"]
        rc = B.wait_event("friends_live", lambda d: d.get("kind") == "challenge" and d["challenge"]["id"] == rid, 10)
        check("rematch: offered with the colours swapped and the same time control",
              rc["challenge"]["colour"] == "black" and rc["challenge"]["tc"] == "5+0" and rc["challenge"]["rematch_of"] == gid)
        acc = B.call("friends_challenge_answer", {"id": rid, "accept": True})
        g2 = acc["game"]["id"]
        check("rematch: B plays White now", acc["game"]["white_handle"] == hb)
        for x in (A, B):
            x.call("friends_game_close", {"id": gid})
            x.call("friends_live_game", {"id": g2})
            state_where(x, g2, lambda s: s["status"] == "waiting")
        play(B, A, g2, ["d2d4", "d7d5"])
        send(B, g2, {"t": "resign"})
        o2 = state_where(A, g2, lambda s: s["status"] == "over")
        check("resign: A wins", o2["termination"] == "resign" and o2["winner"] == "black")

        # ── draw offer: declined, then accepted ─────────────────────────────────────
        g3, _ = start_game(A, B, hb, "10+0", "white")
        play(A, B, g3, ["e2e4", "e7e5"])
        send(A, g3, {"t": "draw_offer"})
        state_where(B, g3, lambda s: s["draw_offer"] == "white")
        send(B, g3, {"t": "draw_decline"})
        state_where(A, g3, lambda s: s["draw_offer"] is None and s["can_offer_draw"] is False)
        send(A, g3, {"t": "draw_offer"})
        check("draw offer: declined, and A must wait before offering again", game_event(A, g3, "error")["error"] == "too_soon")
        send(B, g3, {"t": "draw_offer"})
        state_where(A, g3, lambda s: s["draw_offer"] == "black")
        send(A, g3, {"t": "draw_accept"})
        o3 = state_where(B, g3, lambda s: s["status"] == "over")
        check("draw offer accepted: a draw by agreement", o3["termination"] == "agreed" and o3["result"] == "1/2-1/2")
        game_event(A, g3, "saved")

        # ── a flag (a 1+0 game with 3 s clocks, FLAG_TEST_MS) ────────────────────────
        g4, _ = start_game(A, B, hb, "1+0", "white")
        play(A, B, g4, ["g1f3", "g8f6"])
        o4 = state_where(B, g4, lambda s: s["status"] == "over", timeout=15)
        check("flag: White's clock runs out, Black wins on time", o4["termination"] == "timeout" and o4["winner"] == "black")

        # ── disconnect (B's app quits), claim, and B's library catches up ──────────────
        g5, _ = start_game(A, B, hb, "10+0", "black")
        play(B, A, g5, ["e2e4", "e7e5", "g1f3"])
        B.close()
        left = state_where(A, g5, lambda s: s["opponent"]["connected"] is False and s["claim_at"] is not None)
        send(A, g5, {"t": "claim_win"})
        check("disconnect: no claim before 2 s", game_event(A, g5, "error")["error"] == "too_soon")
        time.sleep(max(0.0, (left["claim_at"] - left["server_time"]) / 1000) + 0.3)
        send(A, g5, {"t": "claim_win"})
        o5 = state_where(A, g5, lambda s: s["status"] == "over")
        check("disconnect then claim: A wins", o5["termination"] == "abandoned" and o5["winner"] == "black")
        B = App("b", root, extra)
        apps.append(B)
        B.wait_event("ready", timeout=60)
        B.call("friends_list", {"mine": {}})
        B.call("friends_live")
        sb5 = B.wait_event("friend_game", lambda d: d.get("id") == g5 and d.get("kind") == "saved", 30)
        check("B's app, restarted, saves the game it missed", sb5.get("gameId") is not None)

        # ── abort: no first move ──────────────────────────────────────────────────────
        g6, _ = start_game(A, B, hb, "5+0", "white")
        o6 = state_where(A, g6, lambda s: s["status"] == "over", timeout=10)
        n_before = len(A.call("list_games", {})["games"])
        time.sleep(0.5)
        check("abort: no first move in time, nothing saved", o6["termination"] == "aborted" and o6["pgn"] is None
              and len(A.call("list_games", {})["games"]) == n_before)

        # ── blocked mid-game: no chat either way ───────────────────────────────────────
        g7, _ = start_game(A, B, hb, "5+0", "white")
        play(A, B, g7, ["e2e4", "e7e5"])
        A.call("friends_block", {"handle": hb})
        state_where(B, g7, lambda s: s["chat_blocked"] is True)
        send(B, g7, {"t": "chat", "text": "hey"})
        check("blocked: chat stops, the game goes on", game_event(B, g7, "error")["error"] == "chat_unavailable")
        send(A, g7, {"t": "resign"})
        state_where(B, g7, lambda s: s["status"] == "over")

        # ── the test opponent (FRIENDS-2 F): sidecar/friends_bot.py against this server ─────
        bot_lines: list[str] = []
        bot = subprocess.Popen([sys.executable, str(REPO / "sidecar" / "friends_bot.py"), url, ha, "--pace", "0.05",
                                "--games", "1", "--seed", "7"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1, env=dict(os.environ))
        threading.Thread(target=lambda: [bot_lines.append(l.rstrip()) for l in bot.stdout], daemon=True).start()
        deadline = time.monotonic() + 30
        bot_handle = None
        while time.monotonic() < deadline and bot_handle is None:
            bot_handle = next((l.split("signed up as ")[1].split()[0] for l in bot_lines if "signed up as " in l), None)
            time.sleep(0.1)
        lst = A.call("friends_list", {"mine": {}})
        req = next((r for r in lst["incoming"] if r["handle"] == bot_handle), None)
        check("the bot signs up and sends A a friend request", bot_handle is not None and req is not None, str(bot_handle))
        A.call("friends_answer", {"id": req["id"], "accept": True})
        time.sleep(0.3)
        gb_, _ = start_game_vs_bot(A, bot_handle)
        send(A, gb_, {"t": "chat", "text": "good luck"})
        got = game_event(A, gb_, "chat", lambda d: d["line"]["handle"] == bot_handle and "you too" in d["line"]["text"], 15)
        check("the bot answers chat", "you too" in got["line"]["text"], got["line"]["text"])
        import chess as _chess
        rnd = __import__("random").Random(3)
        offered = False
        st = A.call("friends_live_game", {"id": gb_})["state"]
        end = time.monotonic() + 60
        while time.monotonic() < end and st["status"] != "over":
            if st.get("draw_offer") == "black":
                offered = True
                send(A, gb_, {"t": "resign"})
                st = state_where(A, gb_, lambda s: s["status"] == "over")
                break
            if st["turn"] == "white" and st["status"] != "over":
                b_ = _chess.Board(st["fen"])
                mv = rnd.choice(list(b_.legal_moves)).uci()
                send(A, gb_, {"t": "move", "uci": mv, "ply": len(st["moves"])})
            n = len(st["moves"])
            st = state_where(A, gb_, lambda s, n=n: len(s["moves"]) != n or s["status"] == "over" or s.get("draw_offer") == "black", 20)
        check("the bot plays legal moves and offers a draw once (after move 15)", offered and st["status"] == "over",
              f"{len(st['moves'])} plies, {st['termination']}")
        bot.wait(timeout=30)
        bot_rows = d1(persist, f"SELECT COUNT(*) AS n FROM accounts WHERE handle = '{bot_handle}'")[0]["n"]
        check("the bot deletes its account when it stops", bot.returncode == 0 and bot_rows == 0 and
              any("deleted the account" in l for l in bot_lines), f"exit {bot.returncode}")
        bot2 = subprocess.Popen([sys.executable, str(REPO / "sidecar" / "friends_bot.py"), url, ha, "--pace", "0.05"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        h2 = None
        for line in bot2.stdout:
            if "signed up as " in line:
                h2 = line.split("signed up as ")[1].split()[0]
                break
        time.sleep(0.5)
        bot2.send_signal(__import__("signal").SIGINT)
        rest = bot2.communicate(timeout=30)[0]
        rows2 = d1(persist, f"SELECT COUNT(*) AS n FROM accounts WHERE handle = '{h2}'")[0]["n"]
        check("…and on Ctrl-C", h2 is not None and rows2 == 0 and "deleted the account" in rest, str(h2))

        # ── delete both: every table empty ────────────────────────────────────────────
        for x in (A, B):
            x.call("friends_delete_account")
        tables = ["accounts", "linked_accounts", "friend_requests", "friendships", "blocks", "presence"]
        counts = {t: d1(persist, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tables}
        check("both accounts deleted: every D1 table empty", all(v == 0 for v in counts.values()), json.dumps(counts))
        n_games = len([g for g in A.call("list_games", {})["games"] if g["source"] == "friends"])
        check("the friend games stay in A's library", n_games >= 4, f"{n_games} games")
    except Exception as exc:
        check("no exception", False, repr(exc))
    finally:
        for x in apps:
            x.close()
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except Exception:
            worker.kill()
        sites.close()
    secs = time.monotonic() - t0
    failed = E.failed
    results = E.results
    summary = f"{len(results) - failed} checks passed, {failed} failed, {secs:.0f} s" if results else "no checks ran"
    print(summary)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(f"# sidecar/friends_play_e2e.py, {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                         + "\n".join(results) + "\n" + summary + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
