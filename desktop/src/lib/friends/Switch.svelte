<script lang="ts">
  /** A switch as the Settings mockup draws it (28 x 16, the knob right and light when on). */
  interface Props {
    checked: boolean
    label: string
    sub?: string
    disabled?: boolean
    onchange: (v: boolean) => void
  }
  let { checked, label, sub, disabled = false, onchange }: Props = $props()
</script>

<button type="button" class="sw" role="switch" aria-checked={checked} {disabled} onclick={() => onchange(!checked)}>
  <span class="text"><span class="label">{label}</span>{#if sub}<span class="sub">{sub}</span>{/if}</span>
  <span class="track" class:on={checked} aria-hidden="true"><span class="knob"></span></span>
</button>

<style>
  .sw {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    width: 100%;
    padding: 0;
    background: none;
    border: 0;
    color: var(--text);
    font: var(--body);
    text-align: left;
    cursor: pointer;
  }
  .sw:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .sw:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
    border-radius: 4px;
  }
  .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .sub {
    color: var(--text-3);
    font: var(--secondary);
  }
  .track {
    flex: none;
    width: 28px;
    height: 16px;
    border-radius: 8px;
    background: var(--selected);
    position: relative;
  }
  .knob {
    position: absolute;
    left: 2px;
    top: 2px;
    width: 12px;
    height: 12px;
    border-radius: 6px;
    background: var(--text-3);
  }
  .track.on {
    background: var(--text);
  }
  .track.on .knob {
    left: auto;
    right: 2px;
    background: var(--bg);
  }
</style>
