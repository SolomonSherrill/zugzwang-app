<script lang="ts">
  /**
   * COACH-2 D (ruling CB1): background work, visible outside its own screen. At the bottom of the sidebar while
   * anything runs in the background, one line per job (a game's deeper analysis, the sync, a puzzle download, the
   * coach reading your games), with a thin bar when its share is known; a click opens what it is about. In the icon
   * rail each job is an icon with the same words as its tooltip and accessible name. Fed by the one store of
   * background jobs (background/jobs.svelte.ts).
   */
  import { jobs } from '../background/jobs.svelte'
  import { jobLines, type JobTarget } from '../background/jobsModel'

  let { rail = false, onopen }: { rail?: boolean; onopen: (t: JobTarget) => void } = $props()
  const lines = $derived(jobLines(jobs.now))
</script>

{#if lines.length}
  <div class="activity" class:rail aria-label="Running in the background" role="group" data-testid="activity">
    {#each lines as l (l.key)}
      <button type="button" class="job" onclick={() => onopen(l.target)} aria-label={rail ? l.text : undefined} title={rail ? undefined : l.text} data-job={l.key}>
        {#if rail}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="9" stroke="var(--raised)" stroke-width="3" />
            <circle
              cx="12"
              cy="12"
              r="9"
              stroke="currentColor"
              stroke-width="3"
              stroke-linecap="round"
              stroke-dasharray="{Math.max(0.08, l.fraction ?? 0.25) * 56.55} 56.55"
              transform="rotate(-90 12 12)"
            />
          </svg>
          <span class="tip" aria-hidden="true">{l.text}</span>
        {:else}
          <span class="text">{l.text}</span>
          {#if l.fraction !== null}
            <span class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(l.fraction * 100)} aria-label={l.text}
              ><span style:width="{Math.round(l.fraction * 100)}%"></span></span
            >
          {/if}
        {/if}
      </button>
    {/each}
  </div>
{/if}

<style>
  .activity {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
    min-width: 0;
  }
  .job {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 6px 8px;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text-2);
    font: var(--secondary);
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }
  .job:hover {
    color: var(--text);
    background: var(--surface);
  }
  .job:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .text {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bar {
    display: block;
    height: 2px;
    border-radius: 1px;
    background: var(--raised);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--text-2);
    transition: width 120ms linear;
  }

  /* the icon rail (below 1440 wide): an icon per job, its words as the tooltip */
  .activity.rail {
    align-items: center;
    width: 100%;
    padding-top: 6px;
  }
  .rail .job {
    position: relative;
    width: 36px;
    height: 36px;
    padding: 0;
    align-items: center;
    justify-content: center;
    flex: none;
  }
  .tip {
    position: absolute;
    left: calc(100% + 10px);
    top: 50%;
    transform: translateY(-50%);
    padding: 5px 9px;
    white-space: nowrap;
    font: var(--secondary);
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--border-control);
    border-radius: var(--radius-control);
    box-shadow: var(--shadow-popover);
    pointer-events: none;
    opacity: 0;
    visibility: hidden;
    transition: opacity 80ms ease-out;
    z-index: 40;
  }
  .rail .job:hover .tip,
  .rail .job:focus-visible .tip {
    opacity: 1;
    visibility: visible;
  }
</style>
