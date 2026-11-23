-- BETA-6 (FRIENDS.md ruling SG1, owner 2026-11-23): shared games wait for a screen that shows them. The server
-- stops keeping them and deletes any it has: the table goes, and with it the "Share the games you play in
-- Zugzwang" switch the server held (the app keeps its own copy of the switch, unused). The Privacy policy,
-- version 2, names neither (FRIENDS.md "What is stored, field by field"; legal/PRIVACY.md).
DROP TABLE shared_games;
ALTER TABLE presence DROP COLUMN share_games;
