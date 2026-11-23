<script lang="ts">
  /** A challenge, shown on any screen (FRIENDS.md ruling S2; MinimalFriends-challenge.html). Built in
   *  FRIENDS-1, shown from FRIENDS-2: nothing mounts it in the app yet. Accept before Decline; no red or
   *  green on its buttons. */
  import Button from '../ui/Button.svelte'
  import Avatar from './Avatar.svelte'
  interface Props {
    from: string
    timeControl: string
    /** the colour you play */
    youPlay: 'White' | 'Black'
    /** "Unrated. Ratings shown in the game: you 1438, maxk 1446 (Chess.com blitz)." */
    note: string
    /** seconds left */
    expiresIn: number
    onaccept: () => void
    ondecline: () => void
  }
  let { from, timeControl, youPlay, note, expiresIn, onaccept, ondecline }: Props = $props()
  const left = $derived(`${Math.floor(Math.max(0, expiresIn) / 60)}:${String(Math.max(0, expiresIn) % 60).padStart(2, '0')}`)
</script>

<div class="banner" role="alertdialog" aria-label="Challenge from {from}">
  <Avatar handle={from} size={28} online={true} />
  <div class="text">
    <div><strong>{from}</strong> challenges you to a <strong>{timeControl}</strong> game. You play {youPlay}.</div>
    <div class="sub">{note} Expires in {left}.</div>
  </div>
  <div class="acts">
    <Button variant="primary" onclick={onaccept}>Accept</Button>
    <Button onclick={ondecline}>Decline</Button>
  </div>
</div>

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    font: var(--body);
    color: var(--text);
    max-width: 720px;
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  strong {
    font-weight: 500;
  }
  .sub {
    color: var(--text-3);
    font: var(--secondary);
    margin-top: 2px;
  }
  .acts {
    display: flex;
    gap: var(--space-2);
  }
</style>
