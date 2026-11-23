"""FRIENDS.md ruling Z4 (owner, 2026-11-22, given with FRIENDS-2): Check now runs at most once every 30 s.
A second press within 30 s of the last sends no request, and the state says when it can be pressed again
(`checkNowAt`); a fake clock and the fake Chess.com of test_friends_chesscom_link."""
from tests.test_friends_chesscom_link import Clock, FakeChesscom, MIN  # noqa: F401
from zugzwang.core.friends import chesscom_link as CL


def test_check_now_at_most_once_every_30_seconds():
    clock = Clock(1_800_000_000_000 + 25 * MIN)
    cc = FakeChesscom(clock)
    link = CL.ChesscomLink(lambda: cc, clock)
    link.start("Slow_Profile")
    first = link.check(force=True)
    assert first["state"] == "waiting" and len(cc.verifies) == 1
    assert first["checkNowAt"] == clock.t + CL.CHECK_NOW_GAP_MS == clock.t + 30_000
    clock.t += 29_999
    again = link.check(force=True)
    assert len(cc.verifies) == 1, "a press within 30 s sends no request"
    assert again["checkNowAt"] == clock.t + 1
    clock.t += 1
    third = link.check(force=True)
    assert len(cc.verifies) == 2 and third["checkNowAt"] == clock.t + 30_000
    clock.t += 30_000
    assert link.state()["checkNowAt"] is None


def test_the_checks_on_their_own_are_not_held_by_the_30_seconds():
    clock = Clock(1_800_000_000_000 + 25 * MIN)
    cc = FakeChesscom(clock)
    link = CL.ChesscomLink(lambda: cc, clock)
    link.start("Slow_Profile")
    link.check(force=True)
    clock.t += CL.CHECK_EVERY_MS
    assert link.due()
    link.check(force=False)
    assert len(cc.verifies) == 2
