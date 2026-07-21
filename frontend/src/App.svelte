<script lang="ts">
  import { onMount } from 'svelte'

  import Presence from './Presence.svelte'
  import { type PublicPresence, watchPresence } from './presence'

  let presence = $state<PublicPresence | null>(null)
  let failed = $state(false)

  onMount(() =>
    watchPresence(
      (p) => {
        presence = p
        failed = false
      },
      () => {
        failed = true
      },
    ),
  )
</script>

<main>
  <h1>heartbeat</h1>
  <p class="tagline">a self-hosted presence beacon: aggregate signal only, never which device.</p>
  <Presence {presence} {failed} />
</main>

<style>
  main {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 2rem;
    text-align: center;
  }
  h1 {
    margin: 0;
    font-weight: 600;
    color: var(--rose);
  }
  .tagline {
    margin: 0;
    max-width: 32rem;
    color: var(--muted);
  }
</style>
