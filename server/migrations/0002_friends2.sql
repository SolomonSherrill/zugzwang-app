-- FRIENDS-2 (FRIENDS.md "FRIENDS-2: the spec", part C): the two Settings switches sent to the server, and
-- the games shared by "Share the games you play in Zugzwang". The Privacy policy lists each field
-- (FRIENDS.md "What is stored, field by field"; legal/PRIVACY.md).

-- "Chat in friend games" (H3): off, you neither see nor send messages, and friends see that your chat is off
ALTER TABLE presence ADD COLUMN chat_on INTEGER NOT NULL DEFAULT 1;
-- "Share the games you play in Zugzwang": off by default; turning it off deletes your shared games
ALTER TABLE presence ADD COLUMN share_games INTEGER NOT NULL DEFAULT 0;

-- a finished friend game, kept only when both players had sharing on as it ended; for 12 months, or until
-- either player turns sharing off or deletes the account; shown to the friends of either player
CREATE TABLE shared_games (
  id TEXT PRIMARY KEY,
  white_id INTEGER NOT NULL,
  black_id INTEGER NOT NULL,
  ended INTEGER NOT NULL,
  tc TEXT NOT NULL,
  result TEXT NOT NULL,
  termination TEXT NOT NULL,
  pgn TEXT NOT NULL
);
CREATE INDEX shared_games_white ON shared_games (white_id, ended);
CREATE INDEX shared_games_black ON shared_games (black_id, ended);
