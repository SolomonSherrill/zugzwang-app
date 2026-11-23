<script lang="ts">
  /** UI-BUILD A6: every base component in each of its states, for a screenshot. */
  import MoveQualityIcon from '../src/lib/ui/MoveQualityIcon.svelte'
  import Button from '../src/lib/ui/Button.svelte'
  import SegmentedControl from '../src/lib/ui/SegmentedControl.svelte'
  import Chip from '../src/lib/ui/Chip.svelte'
  import Panel from '../src/lib/ui/Panel.svelte'
  import StatStrip from '../src/lib/ui/StatStrip.svelte'
  import PlayerStrip from '../src/lib/ui/PlayerStrip.svelte'
  import { QUALITIES } from '../src/lib/ui/moveQuality'
  import ChallengeBanner from '../src/lib/friends/ChallengeBanner.svelte'

  let chart = $state<'eval' | 'material' | 'time'>('eval')
  let colour = $state<'both' | 'white' | 'black'>('both')
</script>

<main>
  <h1>Base components</h1>
  <p class="note">Sample labels only; no figure here is data.</p>

  <Panel title="MoveQualityIcon">
    {#each [16, 18, 20] as size (size)}
      <div class="row">
        <span class="label">{size}px</span>
        {#each QUALITIES as q (q.cls)}
          <span class="icon-cell"><MoveQualityIcon cls={q.cls} size={size as 16 | 18 | 20} /><span class="cap">{q.name}</span></span>
        {/each}
      </div>
    {/each}
  </Panel>

  <Panel title="Button">
    <div class="row">
      <Button variant="primary" kbd="N">New game</Button>
      <Button kbd="F">Flip</Button>
      <Button pressed>Pressed</Button>
      <Button variant="quiet">Quiet</Button>
      <Button disabled>Disabled</Button>
      <Button variant="primary" disabled>Primary disabled</Button>
      <Button size="sm">Small</Button>
    </div>
  </Panel>

  <Panel title="SegmentedControl and Chip">
    <div class="row">
      <SegmentedControl
        label="Chart"
        bind:value={chart}
        options={[
          { value: 'eval', label: 'Eval' },
          { value: 'material', label: 'Material' },
          { value: 'time', label: 'Time' },
        ]}
      />
      <SegmentedControl
        label="Colour"
        bind:value={colour}
        options={[
          { value: 'both', label: 'Both' },
          { value: 'white', label: 'White' },
          { value: 'black', label: 'Black', disabled: true },
        ]}
      />
      <Chip selected>Blitz</Chip>
      <Chip>Rapid</Chip>
      <Chip disabled>Daily</Chip>
    </div>
  </Panel>

  <StatStrip
    stats={[
      { label: 'Label', value: '0' },
      { label: 'With a sub line', value: '0.0', sub: 'sub line' },
      { label: 'Rising', value: '0', sub: '+0 in 30 days', tone: 'win' },
      { label: 'Falling', value: '0', sub: '−0 in 30 days', tone: 'loss' },
    ]}
  />

  <Panel title="PlayerStrip">
    <div class="strips">
      <PlayerStrip name="Opponent" rating={1500} clock="1:40" />
      <PlayerStrip name="Player" rating={1500} you clock="1:12" active />
      <PlayerStrip name="Stockfish" rating="Level 10" />
      <PlayerStrip name="No rating" rating={null} />
    </div>
  </Panel>

  <Panel title="ChallengeBanner (FRIENDS-2; built in FRIENDS-1)">
    <ChallengeBanner
      from="maxk"
      timeControl="5+0"
      youPlay="Black"
      note="Unrated. Ratings shown in the game: you 1438, maxk 1446 (Chess.com blitz)."
      expiresIn={52}
      onaccept={() => {}}
      ondecline={() => {}}
    />
  </Panel>
</main>

<style>
  main {
    padding: 28px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    max-width: 1140px;
  }
  h1 {
    margin: 0;
    font: var(--heading);
  }
  .note {
    margin: -16px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    padding: 6px 0;
  }
  .label {
    width: 40px;
    color: var(--text-3);
    font: var(--secondary);
  }
  .icon-cell {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    width: 92px;
  }
  .cap {
    font: var(--secondary);
    color: var(--text-2);
  }
  .strips {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px 32px;
  }
</style>
