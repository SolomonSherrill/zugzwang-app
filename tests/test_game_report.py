"""The game report: what it selects, what it withholds, and what it says."""

import chess
import pytest

from zugzwang.core import game_report as R
from zugzwang.core.database import MoveAnalysis


def _game(sans, evals, *, best=None, after=None, unscored=(), start=chess.STARTING_FEN):
    """MoveAnalysis rows for a line of SAN moves, consistent by construction.

    *evals* is White's eval in cp for every position, len(sans) + 1 of them. Each
    ply's before-score is its position's eval and its after-score the next
    position's, both from the mover's side, as the analysis stores them. *after*
    overrides one ply's after-search (mover's POV) to make the two searches of a
    position disagree. *best* maps ply -> SAN of the engine's best move; by default
    it is some other legal move.
    """
    board = chess.Board(start)
    rows = []
    for ply, san in enumerate(sans):
        move = board.parse_san(san)
        sign = 1 if board.turn == chess.WHITE else -1
        if best and ply in best:
            best_uci = board.parse_san(best[ply]).uci()
        else:
            best_uci = next(m for m in board.legal_moves if m != move).uci()
        before, aft = sign * evals[ply], sign * evals[ply + 1]
        if after and ply in after:
            aft = after[ply]
        if ply in unscored:
            before = aft = None
        rows.append(MoveAnalysis(
            ply=ply, fen_before=board.fen(), played_uci=move.uci(), best_uci=best_uci,
            pv_uci="", score_before_cp=before, score_before_mate=None,
            score_after_cp=aft, score_after_mate=None, second_best_uci=None,
            second_best_cp=None, second_best_mate=None, classification="good",
            is_book=ply in unscored,
        ))
        board.push(move)
    return rows


LINE = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "Ng5", "d5", "exd5", "Nxd5"]


def _report(rows, **kw):
    args = dict(game_plies=len(rows), result="1-0", termination="resignation",
                player_color="white", depth=10)
    args.update(kw)
    return R.build_report(rows, **args)


def test_thresholds_are_the_measured_ones():
    # Owner ruling 2026-10-21: these rest on GAME_REPORT.md §1.1, §1.3 and §1.5.
    # Changing them means re-running the noise-floor and re-analysis probes and
    # recording the result there first — and then this test.
    assert R.SWING == 0.20
    assert R.DECIDED == 0.80


FLAT = [30] * 11


def test_swing_uses_the_kinder_of_the_two_searches():
    # Bc4's after-search says -400, but the next ply's search of the same
    # position still has White at +30: one search alone is not a swing.
    r = _report(_game(LINE, FLAT, after={4: -400}), result="*")
    assert r["moments"]["total"] == 0


def test_a_swing_both_searches_agree_on_is_a_moment():
    r = _report(_game(LINE, [30] * 5 + [-500] * 6), result="0-1")
    assert [m["ply"] for m in r["moments"]["shown"]] == [4]
    m = r["moments"]["shown"][0]
    assert m["label"] == "3.Bc4" and m["yours"] is True
    assert m["bandBefore"] == "balanced" and m["bandAfter"] == "losing"


def test_the_last_move_needs_a_finished_board_to_be_a_moment():
    # Only one search of the position after the last move exists.
    r = _report(_game(LINE, FLAT, after={9: -900}), result="*")
    assert r["moments"]["total"] == 0


def test_the_engines_own_best_move_is_never_a_moment():
    r = _report(_game(LINE, [30] * 5 + [-500] * 6, best={4: "Bc4"}), result="0-1")
    assert r["moments"]["total"] == 0


def test_the_cap_says_how_many_moments_there_were():
    # Plies 1-5 each throw the game to the other side.
    r = _report(_game(LINE, [30, 30, 600, -600, 600, -600, 30, 30, 30, 30, 30]), result="*")
    assert r["moments"]["total"] == 5
    assert len(r["moments"]["shown"]) == R.SHOWN


def test_an_error_and_its_unpunished_reply_are_one_card():
    # White blunders at ply 4, Black fails to take advantage at ply 5.
    r = _report(_game(LINE, [30] * 5 + [-500] + [30] * 5), result="*")
    assert [m["ply"] for m in r["moments"]["shown"]] == [4, 5]
    assert r["moments"]["groups"] == [[4, 5]]


DECIDED_AT_6 = [30] * 6 + [600] * 5   # Black's 3…Nf6 throws it


def test_point_of_no_return_names_the_move_only_when_it_is_a_moment():
    r = _report(_game(LINE, DECIDED_AT_6), result="1-0")
    assert r["decided"] == {"position": 6, "side": "white", "byPly": 5}
    assert r["lines"][0] == "The game was decided at 3…Nf6: from there you were winning to the end."


def test_a_draw_has_no_point_of_no_return():
    r = _report(_game(LINE, DECIDED_AT_6), result="1/2-1/2", termination="agreement")
    assert r["decided"] is None


def test_lost_on_time_while_winning_is_said_plainly():
    r = _report(_game(LINE, DECIDED_AT_6), result="0-1", termination="timeout")
    assert r["decided"] is None
    assert any(line.startswith("You lost on time in a position the engine rated at")
               for line in r["lines"])
    assert any(line.startswith("You were winning from move 4 to move 6") for line in r["lines"])


def test_a_run_short_of_the_game_withholds_the_verdict():
    r = _report(_game(LINE, FLAT), game_plies=40)
    assert r["basis"]["complete"] is False
    assert r["decided"] is None and r["ending"] is None and r["fortune"] == []
    assert any("Analysis stops after 10 of 40 half-moves" in line for line in r["lines"])


def test_an_unscored_opening_leaves_a_gap_in_the_series():
    r = _report(_game(LINE, FLAT, unscored={0, 1, 2, 3}), result="*")
    assert r["series"][:4] == [None, None, None, None]
    assert all(x is not None for x in r["series"][4:])


def test_moves_are_numbered_from_the_starting_fen():
    # Game 162: a set-up position with Black to move on move 30.
    start = "8/8/8/4k3/8/8/4K3/4Q3 b - - 0 30"
    rows = _game(["Kd5", "Qa5+", "Ke4"], [900] * 4, start=start)
    assert R._move_label(rows[0].fen_before, "Kd5") == "30…Kd5"
    assert R._move_label(rows[1].fen_before, "Qa5+") == "31.Qa5+"


def test_a_moment_the_story_names_always_gets_a_card():
    # Game 1797: the move that threw the win away was the 4th-largest swing, and the
    # top three were later swings. The sentence naming it must have a card to click.
    # White is decided-winning (+600) through position 4 and throws it with 3.Bc4?
    # (to 0: a 0.40 swing). Three larger swings follow (~0.69 each) that never put
    # White back above the 0.80 band, so they do not change who lost the lead.
    evals = [30, 30, 600, 600, 600, 0, 250, -990, 250, -990, -990]
    r = _report(_game(LINE, evals), result="0-1", termination="resignation")
    went = [f for f in r["fortune"] if f["kind"] == "lead_lost"][0]["byPly"]
    shown = [m["ply"] for m in r["moments"]["shown"]]
    assert r["moments"]["total"] > R.SHOWN
    assert went == 4
    assert sorted(m["ply"] for m in r["moments"]["shown"])[:1] == [4]
    assert 4 in shown and len(shown) == R.SHOWN + 1


# ── slice 2: the clock on the moments ────────────────────────────────────────

def test_time_control_parsing():
    assert R.parse_time_control("600") == (600, 0)
    assert R.parse_time_control("180+2") == (180, 2)
    assert R.parse_time_control("1/86400") is None   # daily
    assert R.parse_time_control("-") is None
    assert R.parse_time_control(None) is None


def test_time_spent_counts_the_increment():
    # 180+2: White 178+2 -> spent 4; Black 175+2 -> spent 7.
    assert R.time_spent([178.0, 175.0, 170.0], 180, 2) == [4.0, 7.0, 10.0]


def test_time_added_mid_game_is_unknown_not_negative():
    # Game 330: a clock rose in a no-increment game (time given by the opponent).
    assert R.time_spent([590.0, 595.0, 700.0], 600, 0) == [10.0, 5.0, None]


def test_time_spent_when_black_moves_first():
    assert R.time_spent([170.0, 175.0], 180, 0, white_first=False) == [10.0, 5.0]


# White blunders at ply 4 (3.Bc4) with 0:40 left in a 10-minute game.
CLOCKS = [598.0, 597.0, 590.0, 580.0, 40.0, 500.0, 30.0, 490.0, 20.0, 480.0]


def test_a_moment_carries_its_clock():
    r = _report(_game(LINE, [30] * 5 + [-500] * 6), result="0-1",
                clocks=CLOCKS, time_control="600")
    m = r["moments"]["shown"][0]
    assert m["ply"] == 4 and m["spent"] == 550.0 and m["clockLeft"] == 40.0
    assert r["basis"]["timeControl"] == "600"


def test_no_clocks_no_time_element():
    r = _report(_game(LINE, [30] * 5 + [-500] * 6), result="0-1")
    assert r["moments"]["shown"][0]["spent"] is None
    assert r["basis"]["timeControl"] is None and r["lowClock"] is None


def test_the_low_clock_line_says_when_and_counts_moments_after_it():
    # Changed for AUDIT-10 (owner, 2026-11-11): this test used to count the moment on
    # ply 4 — the move the clock fell on — as coming "after that". It does not.
    r = _report(_game(LINE, [30] * 5 + [-500] * 6), result="0-1",
                clocks=CLOCKS, time_control="600")
    assert r["lowClock"] == {"ply": 4, "position": 5, "threshold": 60.0, "momentsAfter": 0}
    assert "Your clock fell under 1:00 at move 3." in r["lines"]
    assert not any("came after that" in line for line in r["lines"])


def test_a_moment_after_the_clock_fell_is_counted():
    """The clock falls on ply 4 (40 s), White's 4.Ng5 (ply 6) is the moment."""
    r = _report(_game(LINE, [30] * 7 + [-500] * 4), result="0-1",
                clocks=CLOCKS, time_control="600")
    assert r["lowClock"]["ply"] == 4 and r["lowClock"]["momentsAfter"] == 1
    assert "Your clock fell under 1:00 at move 3. One of your moments below came after that." \
        in r["lines"]


def test_the_report_never_says_anything_about_pace():
    # Owner ruling: moments take a median 1.56x the player's own median move time, so
    # the clock is shown and nothing is claimed about rushing.
    r = _report(_game(LINE, [30] * 5 + [-500] * 6), result="0-1",
                clocks=CLOCKS, time_control="600")
    text = " ".join(r["lines"] + [s for m in r["moments"]["shown"] for s in m["sentences"]])
    for word in ("rush", "hurr", "quick", "fast", "slow", "too long", "impuls"):
        assert word not in text.lower()


# ── slice 3: the opening line, four cases ────────────────────────────────────

class _Book:
    """A book that knows the first *depth* moves of LINE, plus one alternative."""

    has_book = True

    def __init__(self, depth, extra=None, alts_at=None):
        self.depth = depth
        self.extra = extra or {}      # ply -> extra SAN the book also knows
        self.alts_at = alts_at        # ply where the book knows ONLY the extra move

    def book_moves_by_weight(self, board):
        ply = (board.fullmove_number - 1) * 2 + (0 if board.turn == chess.WHITE else 1)
        out = []
        if ply < self.depth and ply != self.alts_at:
            out.append(board.parse_san(LINE[ply]))
        if ply in self.extra:
            out.append(board.parse_san(self.extra[ply]))
        return out


def _pgn_moves(rows):
    return [(r.fen_before, r.played_uci) for r in rows]


def _opening(book, evals=FLAT, **kw):
    rows = _game(LINE, evals)
    return _report(rows, result="*", pgn_moves=_pgn_moves(rows), book=book, **kw)


def test_left_the_book_only_when_the_book_had_a_move():
    # The book knows plies 0-3 and, at ply 4, only Bb5 — White played Bc4.
    r = _opening(_Book(4, extra={4: "Bb5"}, alts_at=4))
    assert r["opening"]["case"] == "deviated" and r["opening"]["ply"] == 4
    assert r["lines"][0] == ("You left the book at 3.Bc4 — the book has Bb5 here, "
                             "with the position balanced.")


def test_book_with_nothing_here_does_not_say_anyone_left_it():
    r = _opening(_Book(4))
    assert r["opening"]["case"] == "no_book_move"
    assert r["lines"][0] == ("The book has no move after 2…Nc6: the line is past what it "
                             "covers, with the position balanced.")
    assert "left" not in r["lines"][0]


def test_book_ending_at_its_horizon_says_the_book_ends(monkeypatch):
    monkeypatch.setattr(R.C, "BOOK_HORIZON_PLY", 4)
    r = _opening(_Book(4))
    assert r["opening"]["case"] == "book_ended"
    assert r["lines"][0].startswith("The game was in book until move 3, where the book ends")
    assert "left" not in r["lines"][0]


def test_a_game_entirely_in_book():
    r = _opening(_Book(99))
    assert r["opening"]["case"] == "all_book"
    assert r["lines"][0] == "Every move of the game was a book move."


def test_no_book_no_opening_line():
    class NoBook(_Book):
        has_book = False
    r = _opening(NoBook(4))
    assert r["opening"] is None
    assert not any("book" in line for line in r["lines"])


def test_opening_standing_is_omitted_where_unscored():
    # Position 5 (after the deviation at ply 4) is scored by ply 4's after-search and
    # ply 5's before-search; unscore both and there is nothing to describe it with.
    rows = _game(LINE, FLAT, unscored={0, 1, 2, 3, 4, 5})
    r = _report(rows, result="*", pgn_moves=_pgn_moves(rows),
                book=_Book(4, extra={4: "Bb5"}, alts_at=4))
    assert r["opening"]["band"] is None
    assert r["lines"][0] == "You left the book at 3.Bc4 — the book has Bb5 here."


def test_the_book_is_read_most_played_first():
    from zugzwang.core.openings import OpeningsBook
    b = OpeningsBook()
    if not b.has_book:
        import pytest
        pytest.skip("no Polyglot book installed (W8)")
    moves = b.book_moves_by_weight(chess.Board())
    weights = {e.move: e.weight for e in b._reader.find_all(chess.Board())}
    assert [weights[m] for m in moves] == sorted(weights.values(), reverse=True)


# ── slice 4: the slow decline ────────────────────────────────────────────────

# The Breyer Ruy Lopez to move 12: 24 legal plies with nothing forcing in them.
LONG = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5",
        "Bb3", "d6", "c3", "O-O", "h3", "Nb8", "d4", "Nbd7", "Nbd2", "Bb7", "Bc2", "Re8"]


def test_a_slow_decline_names_the_stretch():
    # White slides 40 -> 400 cp by ~65 cp a move: no move swings 20 points, the game
    # is decided, and the slide is pointed at instead.
    evals = [30 + 30 * j for j in range(len(LONG) + 1)]
    evals = [min(e, 600) for e in evals]
    r = _report(_game(LONG, evals), result="1-0")
    assert r["moments"]["total"] == 0 and r["decided"] is not None
    sl = r["slide"]
    assert sl is not None and sl["side"] == "black"
    assert sl["to"] - sl["from"] <= R.SLIDE_WINDOW
    assert sl["fromWp"] - sl["toWp"] >= R.SLIDE_MIN
    assert any(line.startswith("It slid between moves") and line.endswith("for your opponent.")
               for line in r["lines"])


def test_no_slide_line_when_a_moment_decided_it():
    r = _report(_game(LINE, DECIDED_AT_6), result="1-0")
    assert r["slide"] is None
    assert not any(line.startswith("It slid") for line in r["lines"])


def test_no_slide_line_for_a_fall_under_the_threshold():
    # A 0.80 band crossed from 0.75: decided, no moment, but no 20-point window.
    v = [0.75, 0.70, 0.62, 0.58]
    assert R.slide(v, v, 3) is None


def test_the_slide_is_the_shortest_window_with_the_largest_fall():
    v = [0.6, 0.6, 0.6, 0.3, 0.3, 0.3]
    assert R.slide(v, v, 5) == (2, 3, pytest.approx(0.3))


def test_two_disagreeing_searches_cannot_make_a_slide():
    # One search says 0.50 -> 0.10; the other search of the end position says 0.45.
    # Measured from the lowest start to the highest end, that is a 0.05 fall.
    low = [0.50, 0.10]
    high = [0.50, 0.45]
    assert R.slide(low, high, 1) is None


def test_a_loss_one_search_saw_is_not_called_a_slow_decline():
    # Game 1308: the blunder's reply is an unscored book move, so only the blunder's
    # own after-search sees the loss. Not a moment — and not "no single move" either.
    evals = [30] * 5 + [-600] * 6
    rows = _game(LINE, evals, unscored={5})
    r = _report(rows, result="0-1")
    assert r["moments"]["total"] == 0
    assert r["slide"] is None
    assert not any("no single move" in line.lower() for line in r["lines"])


def test_a_slide_never_spans_an_unscored_position():
    # Game 1484: the best window first crossed an unscored book stretch.
    low = [0.60, None, 0.30]
    assert R.slide(low, low, 2) is None


# ── gated slides: moments elsewhere (owner ruling 2026-10-21) ────────────────

def test_a_slip_after_earlier_moments_is_scoped_to_the_stretch():
    # Black blunders (ply 1) and White hands it back (ply 2): two moments. Then White
    # pulls ahead 50 cp a move with no moment, and the game is decided by that drift.
    evals = [30, 30, 600, 0] + [min(600, 50 * j) for j in range(1, 22)]
    r = _report(_game(LONG, evals), result="1-0")
    assert r["moments"]["total"] == 2 and r["decided"]["byPly"] is None
    sl = r["slide"]
    assert sl is not None and sl["scope"] == "stretch" and sl["from"] >= 3
    assert any(line.startswith("Between moves") and "your opponent's position slipped from" in line
               for line in r["lines"])
    # Moments exist, so nothing may claim no single move decided it.
    assert not any("no single move" in line.lower() for line in r["lines"])


def test_a_window_holding_a_moment_emits_no_slide():
    # Black's 0.25 blunder at ply 5 is inside the best window: the moment explains it.
    evals = [0, 0, 0, 0, 0, 0, 300, 350, 400, 450, 500, 550, 600, 600,
             600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600]
    r = _report(_game(LONG, evals), result="1-0")
    assert r["decided"]["byPly"] is None and r["moments"]["total"] >= 1
    assert r["slide"] is None
    assert r["slideGated"] is not None and 5 in r["slideGated"]["blockedBy"]
    assert not any("slipped" in line or "slid" in line for line in r["lines"])


def test_no_moment_games_keep_the_game_wording():
    evals = [min(30 + 30 * j, 600) for j in range(len(LONG) + 1)]
    r = _report(_game(LONG, evals), result="1-0")
    assert r["slide"]["scope"] == "game"
    assert any("no single move decided it" in line for line in r["lines"])


# ── slice 6: the repeated-pattern line ───────────────────────────────────────

class _F:
    def __init__(self, kind, subject="played"):
        self.kind, self.subject = kind, subject


def _with_findings(monkeypatch, by_ply):
    """Stub the rendered findings per ply index (the explain layer is tested on its own)."""
    def fake(row, player_color, *, run=None):
        b = chess.Board(row["fen_before"])
        ply = (b.fullmove_number - 1) * 2 + (0 if b.turn == chess.WHITE else 1)
        return [(_F(*k) if isinstance(k, tuple) else _F(k), "A sentence.")
                for k in by_ply.get(ply, [])]
    monkeypatch.setattr(R, "rendered_pairs_stored_ply", fake)


ONE_MOMENT_AT_4 = [30] * 5 + [-500] * 6   # White's 3.Bc4 (ply 4) is the moment


def _errors(rows, *plies):
    """Label these plies `mistake`. The mistake lines count only moves the run labels an
    error (owner ruling AUDIT-6, 2026-11-11); `_game` labels every ply `good`."""
    for p in plies:
        rows[p].classification = "mistake"
    return rows


def test_a_repeat_that_includes_a_moment_gets_one_line(monkeypatch):
    _with_findings(monkeypatch, {0: ["hangs_piece"], 4: ["hangs_piece"]})
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 0, 4), result="0-1")
    assert r["pattern"]["plies"] == [0, 4] and r["pattern"]["onCards"] == [4]
    assert ("You dropped material to a capture twice in this game; 3.Bc4, one of them, "
            "is a moment below.") in r["lines"]


def test_a_repeat_off_the_moments_says_nothing(monkeypatch):
    _with_findings(monkeypatch, {0: ["hangs_piece"], 2: ["hangs_piece"]})
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 0, 2), result="0-1")
    assert r["pattern"] is None


def test_a_single_occurrence_is_not_a_pattern(monkeypatch):
    _with_findings(monkeypatch, {4: ["hangs_piece"]})
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 4), result="0-1")
    assert r["pattern"] is None


def test_a_kind_without_a_checked_phrase_says_nothing(monkeypatch):
    _with_findings(monkeypatch, {0: [("trapped_piece", "best")], 4: [("trapped_piece", "best")]})
    r = _report(_game(LINE, ONE_MOMENT_AT_4), result="0-1")
    assert r["pattern"] is None


def test_no_pattern_line_without_the_users_side(monkeypatch):
    _with_findings(monkeypatch, {0: ["hangs_piece"], 4: ["hangs_piece"]})
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 0, 4), result="0-1", player_color=None)
    assert r["pattern"] is None


# ── AUDIT-6: the mistake lines count only unexcused error-labelled moves ─────

def test_the_dropped_material_line_skips_moves_not_labelled_errors(monkeypatch):
    """The same two hangs, one on a move the run calls `good`: one countable move is not
    a pattern (owner ruling AUDIT-6)."""
    _with_findings(monkeypatch, {0: ["hangs_piece"], 4: ["hangs_piece"]})
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 4), result="0-1")
    assert r["pattern"] is None


def test_the_dropped_material_line_skips_a_move_its_own_sentence_excuses(monkeypatch):
    """"…, but everything else was worse" excuses the move; it is not counted."""
    def fake(row, player_color, *, run=None):
        b = chess.Board(row["fen_before"])
        ply = (b.fullmove_number - 1) * 2 + (0 if b.turn == chess.WHITE else 1)
        line = ("This drops the knight on f3 — Qxf3 takes it, but everything else was worse."
                if ply == 0 else "This drops the bishop on c4 — Nxc4 takes it.")
        return [(_F("hangs_piece"), line)] if ply in (0, 4) else []
    monkeypatch.setattr(R, "rendered_pairs_stored_ply", fake)
    r = _report(_errors(_game(LINE, ONE_MOMENT_AT_4), 0, 4), result="0-1")
    assert r["pattern"] is None


# ── AUDIT-8: no "no single move swung it" beside a badge that says one did ───

def test_no_single_move_line_is_dropped_beside_a_twenty_point_badge():
    """The swing rule reads the kinder of two searches and finds no moment here; the
    badge on ply 2 comes from its own stored pair, which loses far more than 20 points.
    The flat sentence would contradict it, so it goes, with nothing in its place
    (owner ruling AUDIT-8)."""
    rows = _game(LINE, FLAT, after={2: -600})
    plain = _report(rows)
    assert plain["moments"]["total"] == 0
    assert "No single move swung this game by 20 points or more." in plain["lines"]
    rows[2].classification = "blunder"
    r = _report(rows)
    assert r["moments"]["total"] == 0
    assert not any(line.startswith("No single move swung") for line in r["lines"])


# ── AUDIT-Q6: nor "— no single move decided it" in the slide line ────────────

def test_the_decided_line_drops_its_no_single_move_clause_beside_a_badge():
    """The same condition as AUDIT-8: a move labelled an error whose own stored loss is 20
    points or more. The rest of the line stays (owner ruling AUDIT-Q6)."""
    evals = [min(30 + 30 * j, 600) for j in range(len(LONG) + 1)]
    plain = _report(_game(LONG, evals), result="1-0")
    told = [line for line in plain["lines"] if "never came back into doubt" in line]
    assert told and told[0].endswith(" — no single move decided it.")
    rows = _game(LONG, evals, after={3: -700})
    rows[3].classification = "blunder"
    r = _report(rows, result="1-0")
    assert r["moments"]["total"] == 0
    line = next(x for x in r["lines"] if "never came back into doubt" in x)
    assert line == told[0].replace(" — no single move decided it.", ".")
