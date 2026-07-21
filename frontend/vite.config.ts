import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  server: {
    // dev only: talk to a locally running heartbeat-proxy
    proxy: { '/api': 'http://127.0.0.1:8100' },
  },
})
