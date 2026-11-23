<script lang="ts">
  /** The Privacy policy or the Terms of use (FRIENDS.md ruling L4), as the app ships them
   *  (src/assets/legal/, kept identical to the repository's legal/ by tests/test_friends_legal.py).
   *  Version 1, approved 2026-11-22 (ruling L7). */
  import Button from '../ui/Button.svelte'
  import privacyText from '../../assets/legal/PRIVACY.md?raw'
  import termsText from '../../assets/legal/TERMS.md?raw'
  interface Props {
    doc: 'privacy' | 'terms'
    onclose: () => void
  }
  let { doc, onclose }: Props = $props()
  const TEXT = { privacy: privacyText, terms: termsText }
  const TITLE = { privacy: 'Privacy policy', terms: 'Terms of use' }
  const text = $derived(TEXT[doc])
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose()
  }
</script>

<svelte:window onkeydown={key} />
<div class="veil" role="presentation" onclick={onclose}>
  <div class="dialog" role="dialog" aria-modal="true" aria-label={TITLE[doc]} tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
    <header>
      <h2>{TITLE[doc]}</h2>
      <Button variant="quiet" onclick={onclose}>Close</Button>
    </header>
    <pre>{text}</pre>
  </div>
</div>

<style>
  .veil {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.55);
  }
  .dialog {
    width: min(720px, calc(100vw - 64px));
    max-height: calc(100vh - 96px);
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-panel);
    box-shadow: var(--shadow-popover);
    outline: none;
  }
  header {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 12px 0 20px;
    height: 48px;
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
    font: var(--body-strong);
  }
  pre {
    margin: 0;
    padding: 16px 20px 20px;
    overflow: auto;
    white-space: pre-wrap;
    font: var(--body);
    color: var(--text-2);
    user-select: text;
  }
</style>
