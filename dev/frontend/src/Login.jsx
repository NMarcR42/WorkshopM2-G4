import { useState } from 'react'
import { login } from './api.js'

export default function Login({ onLogin, notice }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await login(username.trim(), password))
    } catch (err) {
      // 401 = identifiants faux ; sinon le message dit déjà si le service est injoignable.
      setError(err.kind === 'auth' || err.kind === 'rejected' ? 'Identifiants invalides.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-sm space-y-4 rounded bg-white p-6 shadow">
      <h1 className="text-xl font-semibold">Connexion</h1>
      {notice && <p className="rounded bg-amber-100 p-2 text-sm text-amber-800">{notice}</p>}
      <label className="block text-sm">
        Identifiant
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required
          className="mt-1 w-full rounded border border-slate-300 p-2" />
      </label>
      <label className="block text-sm">
        Mot de passe
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
          className="mt-1 w-full rounded border border-slate-300 p-2" />
      </label>
      {error && <p className="rounded bg-red-100 p-2 text-sm text-red-800">{error}</p>}
      <button disabled={busy} className="w-full rounded bg-slate-800 p-2 text-white disabled:opacity-50">
        {busy ? 'Connexion…' : 'Se connecter'}
      </button>
      <p className="text-xs text-slate-500">Démo fictive : alice / alice-demo ou bob / bob-demo.</p>
    </form>
  )
}
