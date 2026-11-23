# Zugzwang Friends — Privacy policy

Version 2, effective the day Zugzwang 0.1.0-beta.6 is published
(https://github.com/SolomonSherrill/zugzwang-app/releases). Version 2 adds games against friends:
challenges, live games and chat.

This policy covers **Friends**: the part of Zugzwang that lets you add friends by a handle, see when they
are online, look at their public games, and play them. Everything else in Zugzwang runs on your computer and sends
nothing to us: your games, analysis, puzzles and settings stay in the app's own files.

**Who runs it.** Zugzwang and its Friends server are published by the developer of Zugzwang
(https://github.com/SolomonSherrill/zugzwang-app). Contact: **privacy@zugzwangapp.com**.

## What the Friends server stores

The server is a Cloudflare Worker with one database, and, for games against friends, a lobby and one
object per live game (Cloudflare Durable Objects, each with its own small storage). It stores these things
and nothing else:

| What | Why | Kept until |
|---|---|---|
| Your **handle** (the name you chose, 3–20 letters, numbers, `_` and `-`) | so friends can find you | you delete your account |
| Your **public key** (a 32-byte Ed25519 key) | to check that requests come from your computer; the private key never leaves it | you delete your account |
| The **date you signed up** | a record of when the account began | you delete your account |
| **Linked accounts**: a Chess.com or Lichess username you link, and whether it was proven yours | so friends see your ratings and games | you unlink it or delete your account |
| **Friend requests** you send or receive, and when | to show and answer them | answered, cancelled, or your account deleted |
| **Friendships**: who you are friends with, and since when | the friends list | either of you removes the other, or an account is deleted |
| **Blocks**: accounts you blocked, and when | so they cannot reach you | you unblock, or an account is deleted |
| **Presence**: when the app last checked in (about once a minute while it is open) and your "Appear offline" switch | to show friends whether you are online | overwritten at each check-in; deleted with your account |
| Your **"Chat in friend games"** switch | to keep chat off when you turned it off | you change it or delete your account |
| **Challenges**: who challenged whom, the time control and colour asked for, when it was sent and when it expires | to show and answer them | answered, cancelled or expired (one minute), or an account deleted |
| **Live games**: the two handles, their proven linked usernames and chat switches, the moves, the clocks and the result | to run the game and its clocks, and so both apps can save it | both apps have saved the finished game, or 24 hours after it ended |

**Not stored:** your email (none is asked for), a password (there is none), your IP address, the
contents of any request, chat messages, the Lichess sign-in token, and the Chess.com code.

- **Lichess sign-in.** When you link Lichess, Lichess gives the app a sign-in token. The server uses it
  once to read your Lichess username, then revokes it at once. It is never saved.
- **Chess.com code.** To link Chess.com you put a short code in your public Chess.com profile's Location
  until the app finds it there; the server reads your public profile to find it. Chess.com can take up to
  12 hours to show a change to a profile, so the code lasts 24 hours and the app checks for it every 15
  minutes while it is open. The server does not save the code (it is worked out again from a server
  secret); the app keeps it on your computer until the link is made or cancelled, or the code expires.
  Remove it from your profile afterwards: Chess.com shows your profile to anyone.
- **Chat** (in games against friends): text only, at most 200 characters a message. It is passed to your
  opponent and held only in the memory of the game's server object (lost even earlier if that object
  goes idle), deleted when the game ends, and never logged or written to any storage. Messages sent
  after the game ends are passed on and held nowhere. With "Chat in friend games" off you neither see nor
  send messages, and your friends see that your chat is off; you can also mute a game, or block a friend.

**What your friends see:** your handle, whether you are online (or when you were last seen, unless you
turned on "Appear offline"), your proven linked usernames, when you became friends, and whether your chat in
friend games is on. Your opponent in a game sees your handle, your
proven linked usernames (the app uses them to show your rating at the game's start), your moves and your
messages. People who are
not your friends can learn only whether a handle is taken.

## Who else handles the data

- **Cloudflare** runs the server and its database (as our processor). Like any web host it receives the
  network address your requests come from in order to answer them and to count requests against abuse
  limits; our code does not store it. Cloudflare's own logs and retention are described in Cloudflare's
  privacy policy (https://www.cloudflare.com/privacypolicy/). Deleted rows can remain in the database's
  automatic point-in-time backups for up to 30 days before they are gone for good.
- **Chess.com and Lichess.** The app fetches your friends' public games and ratings straight from those
  sites' public APIs, from your computer, so those sites see the request as any visitor's. Their own
  privacy policies apply to what they publish and log.

## What stays on your computer

- The **recovery secret** your key is made from, in your operating system's keychain (the macOS
  Keychain or the Windows Credential Manager). It is never put in the app's database or its backups.
- Your handle and the Friends switches ("Appear offline", "Chat in friend games"), in the app's settings
  file.
- While you link Chess.com: the Chess.com username, its code, when the code expires and when the app last
  checked, in the app's settings file, until the link is made or cancelled, or the code expires.
- Your friends' **public games and ratings**, fetched from Chess.com and Lichess, kept in their own
  tables of the app's database, apart from your games. They never appear in your Games or Insights.
- Your **games against friends**, saved to your library like your other games (the "Friends" source),
  with both players' ratings at the game's start when the app could find them. The chat is not saved.

## Your choices

- **See it:** the Friends screen and Settings → Friends show everything the server holds about you.
- **Change it:** unlink or relink an account; turn "Appear offline" or "Chat in friend games" on or off;
  block or remove friends.
  A handle cannot be changed yet.
- **Delete it:** Settings → Friends → **Delete account** removes every row about you from the server
  (your handle, links, friends, requests, blocks, presence, switches and challenges) at once;
  a game you are playing is resigned, and kept only until your opponent's app has saved it. Your games stay on your computer.
- **Recovery code:** it is the only way back into your account on another computer. We cannot recover it
  or reset it for you, because we never had it.

## Children

Friends is for people **13 or older**; sign-up asks you to confirm it. If we learn that an account
belongs to someone younger, we delete it.

## Security

There are no passwords to steal: every request is signed by a key made on your computer, and the server
keeps only the public half. Requests are sent over HTTPS and are valid for one minute.

## Changes

If this policy changes, the new version will be in the app and at
https://github.com/SolomonSherrill/zugzwang-app with its date, and the app will say so before you use
Friends again.
