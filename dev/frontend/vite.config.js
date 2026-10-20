import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// En dev (npm run dev), ce proxy joue le rôle du WAF : il route /api et /auth comme le fera l'entrée
// de la plateforme, ce qui permet de tester le parcours sans WAF. En production (image Docker),
// il n'est pas utilisé : c'est le WAF qui route.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const api = env.DEV_API_URL || 'http://localhost:8000'
  const auth = env.DEV_AUTH_URL || 'http://localhost:8001'

  // xfwd : pose X-Forwarded-For, comme le WAF, pour que l'API journalise l'IP du client.
  const route = (prefix, target) => ({
    target,
    changeOrigin: true,
    xfwd: true,
    rewrite: (path) => path.replace(new RegExp(`^${prefix}`), ''),
  })

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: { '/api': route('/api', api), '/auth': route('/auth', auth) },
    },
  }
})
