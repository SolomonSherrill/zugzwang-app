"""FRIENDS-1 D (ruling L4), BETA-5 (rulings L7, L8): the app shows the same Privacy policy and Terms of use as
the repository publishes, both approved as version 1 (no longer DRAFT), and the policy names every server
table."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_app_ships_the_published_texts():
    """L7: desktop/src/assets/legal/ is legal/ (README aside), byte for byte, with no file missing or extra."""
    app = ROOT / "desktop/src/assets/legal"
    published = {p.name for p in (ROOT / "legal").glob("*.md")} - {"README.md"}
    assert published == {"PRIVACY.md", "TERMS.md"}
    assert {p.name for p in app.iterdir()} == published
    for name in sorted(published):
        assert (app / name).read_bytes() == (ROOT / "legal" / name).read_bytes(), name


def test_both_are_version_1_and_not_drafts():
    """L7 (owner, 2026-11-22): approved as draft 2; version 1, effective the day beta.5 is published."""
    for name in ("PRIVACY.md", "TERMS.md"):
        text = (ROOT / "legal" / name).read_text()
        assert "DRAFT" not in text and "draft 2" not in text
        assert "Version 1, effective the day Zugzwang 0.1.0-beta.5 is published" in text


def test_the_terms_name_the_venue():
    """L8 (owner, 2026-11-22): TERMS §8's venue."""
    text = " ".join((ROOT / "legal/TERMS.md").read_text().split())
    assert "the state and federal courts located in Kings County, New York" in text


def test_the_blanks_are_filled_in():
    """FRIENDS-1B rulings L5, L6 (2026-11-22): the contact address and the governing law."""
    for name in ("PRIVACY.md", "TERMS.md"):
        text = (ROOT / "legal" / name).read_text()
        assert "to be set before approval" not in text
        assert "privacy@zugzwangapp.com" in text
    assert "laws of the State of New York" in (ROOT / "legal/TERMS.md").read_text()


def test_the_policy_covers_every_server_table():
    sql = (ROOT / "server/migrations/0001_init.sql").read_text()
    import re
    tables = re.findall(r"CREATE TABLE (\w+)", sql)
    assert tables == ["accounts", "linked_accounts", "friend_requests", "friendships", "blocks", "presence"]
    policy = (ROOT / "legal/PRIVACY.md").read_text().lower()
    for words in ("handle", "public key", "signed up", "linked accounts", "friend requests", "friendships",
                  "blocks", "presence"):
        assert words in policy, words
    for never in ("email", "password", "ip address", "chat messages"):
        assert never in policy
