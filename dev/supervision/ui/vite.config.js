import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// En dev, /api est relayé vers le service de supervision (lancé par docker ou uvicorn).
// En production le site est servi par ce même service : même origine, aucun proxy.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5175,
      proxy: { '/api': env.DEV_SUPERVISION_URL || 'http://localhost:8090' },
    },
  }
})
