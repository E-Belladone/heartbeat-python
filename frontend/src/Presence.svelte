<script lang="ts">
  import { relativeTime, type PublicPresence } from './presence'

  let { presence, failed }: { presence: PublicPresence | null; failed: boolean } = $props()

  // one legend for every state the pastille can be in, shown on hover
  const LEGEND = [
    'active now: a device pushed a strong signal recently (unlock, sync, ...)',
    'online: a device is reachable on the tailnet, nothing more is known',
    'last seen ...: nothing reachable; time since the last heartbeat',
    'presence unavailable: this page cannot reach the heartbeat itself',
  ].join('\n')
</script>

<div
  class="presence"
  class:active={presence?.activity === 'active'}
  class:around={presence?.activity === 'around'}
  title={LEGEND}
>
  <span class="dot" aria-hidden="true"></span>
  {#if failed || presence === null}
    <span class="label">presence unavailable</span>
  {:else if presence.activity === 'active'}
    <span class="label">active now</span>
  {:else if presence.activity === 'around'}
    <span class="label">online</span>
  {:else}
    <span class="label">last seen {relativeTime(presence.last_seen_relative)}</span>
  {/if}
</div>

<style>
  .presence {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.9rem;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--highlight-med);
    color: var(--subtle);
    cursor: help;
  }

  .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: var(--muted);
  }

  /* around: reachable, no recent activity signal — steady foam */
  .around .dot {
    background: var(--foam);
  }

  /* active: a strong signal fired recently — foam with the glow */
  .active .dot {
    background: var(--foam);
    box-shadow: 0 0 6px var(--foam);
  }

  .active .label,
  .around .label {
    color: var(--text);
  }
</style>
