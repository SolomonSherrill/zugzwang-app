<script lang="ts">
  /**
   * The approved style for empty, loading and error states (design/README.md, "Not designed
   * yet" 1; owner, 2026-11-20: the build drafts them and lists them for review): a panel with
   * one sentence and one action. An optional muted second line and a progress bar.
   */
  import Button from './Button.svelte'

  interface Props {
    sentence: string
    sub?: string | null
    action?: { label: string; run: () => void; primary?: boolean; kbd?: string } | null
    /** 0..1 for a determinate bar; null for none */
    progress?: number | null
    tone?: 'quiet' | 'error'
  }
  let { sentence, sub = null, action = null, progress = null, tone = 'quiet' }: Props = $props()
</script>

<div class="empty" class:error={tone === 'error'} role={tone === 'error' ? 'alert' : 'status'}>
  <p class="s">{sentence}</p>
  {#if sub}<p class="sub">{sub}</p>{/if}
  {#if progress !== null}
    <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress * 100)}>
      <span style:width="{Math.round(progress * 100)}%"></span>
    </div>
  {/if}
  {#if action}
    <div class="act">
      <Button variant={action.primary ? 'primary' : 'ghost'} kbd={action.kbd} onclick={action.run}>{action.label}</Button>
    </div>
  {/if}
</div>

<style>
  .empty {
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    padding: var(--space-5);
  }
  .s {
    margin: 0;
    font-weight: 500;
  }
  .error .s::before {
    content: '';
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 4px;
    background: var(--loss);
    margin-right: 8px;
    vertical-align: 1px;
  }
  .sub {
    margin: 4px 0 0;
    color: var(--text-3);
    font: var(--secondary);
  }
  .bar {
    margin-top: 12px;
    height: 4px;
    border-radius: 2px;
    background: var(--raised);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--text);
    transition: width 120ms linear;
  }
  .act {
    margin-top: 14px;
  }
</style>
