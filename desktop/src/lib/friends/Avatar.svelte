<script lang="ts">
  import { initial } from './friendsModel'
  interface Props {
    handle: string
    size?: number
    /** null: no presence dot */
    online?: boolean | null
  }
  let { handle, size = 28, online = null }: Props = $props()
  const dot = $derived(size >= 40 ? 11 : 9)
</script>

<span class="av" aria-hidden="true" style:width="{size}px" style:height="{size}px" style:font-size="{size >= 40 ? 16 : size >= 28 ? 12 : 11}px"
  >{initial(handle)}{#if online !== null}<span class="dot" class:on={online} style:width="{dot}px" style:height="{dot}px"></span>{/if}</span
>

<style>
  .av {
    position: relative;
    flex: none;
    border-radius: var(--radius-round);
    background: var(--selected);
    color: var(--text);
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .dot {
    position: absolute;
    right: -1px;
    bottom: -1px;
    border-radius: var(--radius-round);
    background: var(--disabled);
    box-shadow: 0 0 0 2px var(--bg);
  }
  .dot.on {
    background: var(--win);
  }
</style>
