-- The Zugzwang Friends server's tables (FRIENDS.md ruling V1): these six, nothing else.
-- Every row that names an account is removed when the account is deleted (src/index.ts deleteAccount).

CREATE TABLE accounts (
  id         INTEGER PRIMARY KEY,
  handle     TEXT    NOT NULL UNIQUE COLLATE NOCASE,   -- 3-20 of [A-Za-z0-9_-], unique ignoring case
  public_key TEXT    NOT NULL UNIQUE,                  -- Ed25519, 32 bytes, base64url
  created    INTEGER NOT NULL                          -- Unix ms
);

CREATE TABLE linked_accounts (
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  site       TEXT    NOT NULL CHECK (site IN ('chesscom', 'lichess')),
  username   TEXT    NOT NULL COLLATE NOCASE,
  verified   INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
  PRIMARY KEY (account_id, site)
);
CREATE INDEX linked_accounts_site_username ON linked_accounts (site, username);

CREATE TABLE friend_requests (
  id      INTEGER PRIMARY KEY,
  from_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  to_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created INTEGER NOT NULL,
  UNIQUE (from_id, to_id),
  CHECK (from_id <> to_id)
);
CREATE INDEX friend_requests_to ON friend_requests (to_id);

CREATE TABLE friendships (
  a_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,   -- the smaller id
  b_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created INTEGER NOT NULL,
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)
);
CREATE INDEX friendships_b ON friendships (b_id);

CREATE TABLE blocks (
  blocker_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  blocked_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created    INTEGER NOT NULL,
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id)
);
CREATE INDEX blocks_blocked ON blocks (blocked_id);

CREATE TABLE presence (
  account_id     INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  last_seen      INTEGER,                                   -- Unix ms of the last heartbeat
  appear_offline INTEGER NOT NULL DEFAULT 0 CHECK (appear_offline IN (0, 1))
);
