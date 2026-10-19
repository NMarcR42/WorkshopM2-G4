// Client HTTP du front. Le navigateur est hors Docker : il ne connaît ni "api" ni "auth".
// Tout passe par le WAF (seul point d'entrée), sur la même origine que la page, donc pas de CORS.
// Le WAF route /api -> API et /auth -> auth en retirant le préfixe (voir doc/ARCHITECTURE.md).
// Les préfixes sont configurables à la construction de l'image : VITE_API_BASE, VITE_AUTH_BASE.
const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
const AUTH_BASE = import.meta.env.VITE_AUTH_BASE ?? '/auth'

// Délai max d'une requête. Sans lui, un service saturé laisserait l'écran bloqué ;
// avec lui, l'utilisateur voit un échec clair (et c'est ce que le jury doit voir pendant l'attaque).
const TIMEOUT_MS = Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS ?? 8000)

// kind : 'network' (rien reçu), 'unavailable' (503), 'auth' (401), 'forbidden' (403), 'rejected' (4xx métier), 'server'.
// retryable : on peut renvoyer la même demande sans risque de double paiement (même Idempotency-Key).
export class ApiError extends Error {
  constructor(kind, message, status) {
    super(message)
    this.kind = kind
    this.status = status
    this.retryable = kind === 'network' || kind === 'unavailable' || kind === 'server'
  }
}

// FastAPI renvoie soit {detail: "texte"}, soit {detail: [{loc, msg}, ...]} pour une validation.
function readDetail(data) {
  if (!data || !data.detail) return null
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join(' ; ')
  return null
}

async function request(base, path, { method = 'GET', token, body, headers = {} } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  let res
  try {
    res = await fetch(base + path, {
      method,
      signal: controller.signal,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}), // jeton de l'auth, vérifié par l'API
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    const timeout = e.name === 'AbortError'
    throw new ApiError('network', timeout ? 'Le service ne répond pas (délai dépassé).' : 'Service injoignable.')
  } finally {
    clearTimeout(timer)
  }

  const data = await res.json().catch(() => null) // une erreur du WAF peut ne pas être du JSON
  if (res.ok) return { data, status: res.status }

  const detail = readDetail(data)
  if (res.status === 401) throw new ApiError('auth', detail ?? 'Session expirée.', 401)
  if (res.status === 403) throw new ApiError('forbidden', detail ?? 'Action refusée.', 403)
  if (res.status === 503) throw new ApiError('unavailable', 'Service momentanément indisponible.', 503)
  if (res.status >= 500) throw new ApiError('server', 'Erreur du service.', res.status)
  throw new ApiError('rejected', detail ?? `Requête refusée (${res.status}).`, res.status)
}

export const login = (username, password) =>
  request(AUTH_BASE, '/login', { method: 'POST', body: { username, password } }).then((r) => r.data)

export const getAccounts = (token) => request(API_BASE, '/v1/accounts', { token }).then((r) => r.data)

export const getTransactions = (token, limit = 10) =>
  request(API_BASE, `/v1/transactions?limit=${limit}`, { token }).then((r) => r.data)

// Idempotency-Key : si la réponse se perd (timeout), renvoyer la même clé ne paie pas deux fois.
export const createTransaction = (token, payload, idempotencyKey) =>
  request(API_BASE, '/v1/transactions', {
    method: 'POST',
    token,
    body: payload,
    headers: { 'Idempotency-Key': idempotencyKey },
  }).then((r) => ({ transaction: r.data, replayed: r.status === 200 }))
