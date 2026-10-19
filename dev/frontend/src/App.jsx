import { useState } from 'react'
import Dashboard from './Dashboard.jsx'
import Login from './Login.jsx'

// La session (jeton + identité) vit dans sessionStorage : elle disparaît à la fermeture de l'onglet.
// Suffisant pour un POC ; en production on préférerait un cookie HttpOnly posé par le serveur.
const KEY = 'session'

function loadSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(KEY))
    return s && s.expiresAt > Date.now() ? s : null
  } catch {
    return null
  }
}

export default function App() {
  const [session, setSession] = useState(loadSession)
  const [notice, setNotice] = useState('')

  const start = (auth) => {
    // expires_in est en secondes ; on garde la date d'expiration pour ne pas réutiliser un jeton mort.
    const s = { token: auth.access_token, username: auth.username, role: auth.role, expiresAt: Date.now() + auth.expires_in * 1000 }
    sessionStorage.setItem(KEY, JSON.stringify(s))
    setNotice('')
    setSession(s)
  }

  const logout = (message = '') => {
    sessionStorage.removeItem(KEY)
    setNotice(message)
    setSession(null)
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="bg-slate-800 text-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <span className="font-semibold">Paiement — démo fictive</span>
          {session && (
            <span className="text-sm">
              {session.username}{' '}
              <button onClick={() => logout()} className="ml-3 underline">
                Déconnexion
              </button>
            </span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6">
        {session ? (
          <Dashboard session={session} onExpired={() => logout('Session expirée, reconnectez-vous.')} />
        ) : (
          <Login onLogin={start} notice={notice} />
        )}
      </main>
    </div>
  )
}
