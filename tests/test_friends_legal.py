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


def test_the_versions_and_no_drafts():
    """L7 (owner, 2026-11-22): approved as draft 2; version 1, effective the day beta.5 is published. FRIENDS-2 B
    (2026-11-22): the policy's version 2 adds what games against friends store, effective with beta.6 (decided,
    for the owner to confirm: review/reports/FRIENDS-2.md); the Terms stay version 1."""
    for name in ("PRIVACY.md", "TERMS.md"):
        text = (ROOT / "legal" / name).read_text()
        assert "DRAFT" not in text and "draft 2" not in text
    assert "Version 2, effective the day Zugzwang 0.1.0-beta.6 is published" in (ROOT / "legal/PRIVACY.md").read_text()
    # BETA-6 ruling L10 (owner, 2026-11-23): Terms version 2, "(when they arrive)" removed in both places
    terms = (ROOT / "legal/TERMS.md").read_text()
    assert "Version 2, effective the day Zugzwang 0.1.0-beta.6 is published" in terms
    assert "when they arrive" not in terms


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
    import re
    sql = "".join(p.read_text() for p in sorted((ROOT / "server/migrations").glob("*.sql")))
    dropped = re.findall(r"DROP TABLE (\w+)", sql)
    tables = [t for t in re.findall(r"CREATE TABLE (\w+)", sql) if t not in dropped]
    assert tables == ["accounts", "linked_accounts", "friend_requests", "friendships", "blocks", "presence"]
    columns = [c for c in re.findall(r"ADD COLUMN (\w+)", sql) if c not in re.findall(r"DROP COLUMN (\w+)", sql)]
    assert columns == ["chat_on"]
    policy = " ".join((ROOT / "legal/PRIVACY.md").read_text().lower().split())
    for words in ("handle", "public key", "signed up", "linked accounts", "friend requests", "friendships",
                  "blocks", "presence", "chat in friend games", "challenges", "live games"):
        assert words in policy, words
    # BETA-6 ruling SG1: the server keeps no shared games, and the policy names none
    assert dropped == ["shared_games"]
    for words in ("shared games", "share the games you play in zugzwang", "games you share"):
        assert words not in policy, words
    # the Durable Objects' own storage (FRIENDS-2): each table they create is named in the policy
    for src, names in (("lobby.ts", ["challenges", "games"]),):
        made = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", (ROOT / "server/src" / src).read_text())
        assert made == names, src
    for never in ("email", "password", "ip address", "chat messages"):
        assert never in policy
