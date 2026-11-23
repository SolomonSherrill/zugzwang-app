"""BETA-5 B (ruling K3): Chess.com linking waits for Chess.com, on a fake clock and a fake Chess.com.

The fake client stands in for the Friends server and Chess.com together, as the server behaves: a code made
at hour H is accepted until the end of hour H + 23 (LINK_CODE_HOURS = 24), found when the fake profile's
Location holds it. Also the recovery code saved to a file (BETA-5 B, "Save as a file")."""
import os
import stat
import sys

import pytest

from zugzwang.core.friends import chesscom_link as CL
from zugzwang.core.friends import settings as fsettings
from zugzwang.core.friends.client import FriendsError
from zugzwang.core.friends.identity import Identity
from zugzwang.core.friends.keystore import FileKeystore
from zugzwang.core.friends.runner import FriendsRunner
from zugzwang.core.friends.service import FriendsService

HOUR = 3_600_000
MIN = 60_000


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeChesscom:
    """The Friends server's two link endpoints over a fake Chess.com profile; counts the checks."""

    def __init__(self, clock):
        self.clock = clock
        self.location = "Nowhere"
        self.verifies = []
        self.unlinked = []
        self.linked = []
        self.down = False

    def chesscom_start(self, username):
        hour = self.clock() // HOUR
        self.linked = [{"site": "chesscom", "username": username, "verified": False}]
        return {"site": "chesscom", "username": username, "code": f"ZZ-{hour % 10**8:08d}",
                "field": "location", "expires": (hour + 24) * HOUR}

    def chesscom_verify(self, username):
        self.verifies.append(self.clock())
        if self.down:
            raise FriendsError("chesscom_unreachable", "Chess.com could not be reached. Try again.", 502)
        hour = self.clock() // HOUR
        for h in range(hour, hour - 24, -1):
            if f"ZZ-{h % 10**8:08d}" in self.location:
                self.linked = [{"site": "chesscom", "username": username.lower(), "verified": True}]
                return {"site": "chesscom", "username": username.lower(), "verified": True}
        raise FriendsError("code_not_found", "The code is not in that profile's Location yet. "
                           "Chess.com's public profile can take up to 12 hours to update.", 409)

    def me(self):
        return {"handle": "me", "linked": self.linked}

    def unlink(self, site):
        self.unlinked.append(site)
        self.linked = []
        return {"status": "unlinked", "site": site}


@pytest.fixture
def world():
    clock = Clock(1_800_000_000_000 + 25 * MIN)        # 25 minutes into an hour
    cc = FakeChesscom(clock)
    return clock, cc, CL.ChesscomLink(lambda: cc, clock)


def test_start_keeps_the_code_and_a_restart_finds_it(world):
    clock, cc, link = world
    out = link.start("Slow_Profile")
    assert out["state"] == "code" and out["code"].startswith("ZZ-")
    assert out["expires"] == (clock() // HOUR + 24) * HOUR
    again = CL.ChesscomLink(lambda: cc, clock)          # a restart: a new object over the same settings
    assert again.state() == {**link.state()} and again.state()["code"] == out["code"]
    assert fsettings.load()["chesscom_link"]["code"] == out["code"]


def test_no_code_waits_then_checks_on_its_own_at_most_every_15_minutes(world):
    clock, cc, link = world
    code = link.start("slow_profile")["code"]
    first = link.check()                                   # the user's Check: not there yet
    assert first["state"] == "waiting" and first["nextCheck"] == clock() + 15 * MIN
    assert len(cc.verifies) == 1
    for _ in range(14):                                    # the heartbeat, every minute: nothing due
        clock.t += MIN
        assert not link.due()
        assert link.check(force=False)["state"] == "waiting"
    assert len(cc.verifies) == 1
    clock.t += MIN                                         # 15 minutes after the last check
    assert link.due()
    assert link.check(force=False)["state"] == "waiting"
    assert len(cc.verifies) == 2
    # a restart in the middle keeps the schedule
    clock.t += 7 * MIN
    assert not CL.ChesscomLink(lambda: cc, clock).due()
    clock.t += 8 * MIN
    assert CL.ChesscomLink(lambda: cc, clock).due()
    # 12 hours later Chess.com shows the code: the next check on its own links it
    clock.t += 12 * HOUR
    cc.location = "Leeds " + code
    done = link.check(force=False)
    assert done["state"] == "linked" and done["verified"] is True and done["username"] == "slow_profile"
    assert not link.due()
    n = len(cc.verifies)
    clock.t += HOUR
    assert link.check(force=False)["state"] == "linked" and len(cc.verifies) == n   # no more checks


def test_check_now_checks_at_once_and_restarts_the_wait(world):
    clock, cc, link = world
    link.start("slow_profile")
    link.check()
    clock.t += 2 * MIN
    assert link.check(force=True)["state"] == "waiting"     # Check now
    assert len(cc.verifies) == 2
    clock.t += 14 * MIN
    assert not link.due()                                   # 15 minutes from Check now, not from the first
    clock.t += MIN
    assert link.due()


def test_checks_stop_when_the_code_expires_and_the_app_says_so(world):
    clock, cc, link = world
    start = link.start("never_updates")
    link.check()
    n = 1
    while clock() < start["expires"] - 15 * MIN:
        clock.t += 15 * MIN
        link.check(force=False)
        n += 1
    assert len(cc.verifies) == n
    clock.t = start["expires"]
    assert link.state()["state"] == "expired"
    assert not link.due()
    assert link.check(force=False)["state"] == "expired" and link.check(force=True)["state"] == "expired"
    assert len(cc.verifies) == n                            # no request after it expired
    assert CL.ChesscomLink(lambda: cc, clock).state()["state"] == "expired"   # and after a restart
    # the code made at the start is refused from this moment on by the server's own rule
    cc.location = start["code"]
    with pytest.raises(FriendsError):
        cc.chesscom_verify("never_updates")


def test_unreachable_keeps_waiting_and_says_why(world):
    clock, cc, link = world
    link.start("slow_profile")
    link.check()
    clock.t += 15 * MIN
    cc.down = True
    st = link.check(force=False)
    assert st["state"] == "waiting" and "could not be reached" in st["error"]
    assert st["nextCheck"] == clock() + 15 * MIN
    cc.down = False
    clock.t += 15 * MIN
    assert link.check(force=False)["error"] is None


def test_one_check_at_a_time(world):
    clock, cc, link = world
    link.start("slow_profile")
    assert link._lock.acquire(blocking=False)
    try:
        assert link.check()["checking"] is True
        assert cc.verifies == []
    finally:
        link._lock.release()


def test_cancel_forgets_it_and_unlinks_the_unproven_name(world):
    clock, cc, link = world
    link.start("slow_profile")
    link.check()
    assert link.cancel() == {"state": "none"}
    assert link.state() == {"state": "none"} and cc.unlinked == ["chesscom"]
    assert fsettings.load()["chesscom_link"] is None


def test_dismissing_linked_never_unlinks(world):
    clock, cc, link = world
    code = link.start("slow_profile")["code"]
    cc.location = code
    assert link.check()["state"] == "linked"
    link.cancel()
    assert cc.unlinked == [] and link.state() == {"state": "none"}


def test_the_heartbeat_checks_when_due_and_announces_it(world):
    clock, cc, link = world
    events = []
    svc = FriendsService(keystore=FileKeystore(__import__("pathlib").Path(os.environ["ZUGZWANG_KEYSTORE"][5:])), base="")
    svc.chesscom = link
    runner = FriendsRunner(lambda fn: fn(), lambda e, d: events.append((e, d)), lambda: None, service=svc)
    assert runner.tick_chesscom() is None                 # nothing pending
    link.start("slow_profile")
    assert runner.tick_chesscom() is None and cc.verifies == []   # a code not yet checked by the user
    link.check()
    clock.t += 10 * MIN
    assert runner.tick_chesscom() is None and len(cc.verifies) == 1
    clock.t += 5 * MIN
    assert runner.tick_chesscom()["state"] == "waiting" and len(cc.verifies) == 2
    assert events[-1][0] == "friends_link" and events[-1][1]["lastCheck"] == clock()
    clock.t = link.state()["expires"]
    assert runner.tick_chesscom()["state"] == "expired"
    assert events[-1][1]["state"] == "expired" and len(cc.verifies) == 2


def test_delete_account_forgets_the_pending_link(world, tmp_path):
    clock, cc, link = world
    link.start("slow_profile")
    svc = FriendsService(keystore=FileKeystore(tmp_path / "k.json"), base="")
    svc.forget_local()
    assert link.state() == {"state": "none"}


# ── the recovery code saved as a file (BETA-5 B) ─────────────────────────────

def _signed_in(tmp_path):
    ks = FileKeystore(tmp_path / "keys.json")
    ident = Identity.new()
    ks.set(ident.secret.hex())
    return FriendsService(keystore=ks, base=""), ident


def test_save_recovery_code_writes_it_owner_only(tmp_path):
    svc, ident = _signed_in(tmp_path)
    path = tmp_path / "zugzwang-recovery-code.txt"
    path.write_text("old")
    if sys.platform != "win32":
        os.chmod(path, 0o644)
    assert svc.save_recovery_code(str(path)) == {"path": str(path)}
    text = path.read_text()
    assert ident.recovery_code in text and "old" not in text
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_recovery_code_says_what_failed(tmp_path):
    svc, _ = _signed_in(tmp_path)
    with pytest.raises(FriendsError) as e:
        svc.save_recovery_code(str(tmp_path / "no_such_folder" / "code.txt"))
    assert e.value.code == "save_failed" and "could not be saved to" in e.value.message
    with pytest.raises(FriendsError) as e:
        svc.save_recovery_code("relative.txt")
    assert e.value.code == "bad_path"
    with pytest.raises(FriendsError) as e:
        FriendsService(keystore=FileKeystore(tmp_path / "none.json"), base="").save_recovery_code(str(tmp_path / "x.txt"))
    assert e.value.code == "no_identity"
