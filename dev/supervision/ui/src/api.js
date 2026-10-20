// Préfixe réglable à la construction ; par défaut même origine que la page (le service sert aussi le site).
const BASE = import.meta.env.VITE_SUPERVISION_API || '/api'

async function get(path) {
  // Délai court : un tableau de bord qui reste figé sans le dire serait pire qu'un état « inconnu ».
  const res = await fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(4000) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const getStatus = () => get('/status')
export const getAlerts = () => get('/alerts')
export const getRemediationLog = () => get('/remediation-log')
export const getHistory = (minutes) => get(`/history?minutes=${minutes}`)
