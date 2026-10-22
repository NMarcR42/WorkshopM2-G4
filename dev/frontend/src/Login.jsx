import { useState } from 'react'
import FaceStep from './FaceStep.jsx'
import { FACE_MODE, login } from './api.js'

// Parcours de connexion en 3 étapes : identifiant -> visage -> mot de passe.
// Plan B : si le visage échoue (ou FACE_MODE=off), on passe directement au mot de passe,
// avec un avertissement ; le jeton est alors émis sans preuve faciale.
const STEPS = ['Identifiant', 'Visage', 'Mot de passe']

export default function Login({ onLogin, notice }) {
  const [step, setStep] = useState(0)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [faceToken, setFaceToken] = useState(null)
  const [fallback, setFallback] = useState('') // raison du plan B, vide si visage validé
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const next = (e) => {
    e.preventDefault()
    setError('')
    setFaceToken(null)
    setStep(FACE_MODE === 'off' ? 2 : 1)
  }

  const faceOk = (token) => {
    setFaceToken(token)
    setFallback('')
    setStep(2)
  }

  const planB = (reason) => {
    setFaceToken(null)
    setFallback(reason)
    setStep(2)
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await login(username.trim(), password, faceToken))
    } catch (err) {
      // 401 = identifiants faux ; sinon le message dit déjà si le service est injoignable.
      setError(err.kind === 'auth' || err.kind === 'rejected' ? 'Identifiants invalides.' : err.message)
      setPassword('')
      // Le token visage est à usage unique côté IA (même après un mot de passe faux) et auth peut le refuser
      // (403 : absent/expiré/FACE_ENFORCE actif). Il faut donc refaire l'étape visage, sauf si elle est désactivée.
      if (faceToken || err.kind === 'forbidden') {
        setFaceToken(null)
        if (FACE_MODE !== 'off') setStep(1)
      }
    } finally {
      setBusy(false)
    }
  }

  const input = 'mt-1 w-full rounded border border-slate-300 p-2'

  return (
    <div className="mx-auto max-w-sm space-y-4 rounded-lg bg-white p-6 shadow">
      <h1 className="text-xl font-semibold">Connexion sécurisée</h1>

      <ol className="flex gap-2 text-xs">
        {STEPS.map((label, i) => (
          <li key={label} className={`flex-1 rounded-full px-2 py-1 text-center ${
            i === step ? 'bg-slate-800 text-white' : i < step ? 'bg-green-100 text-green-800' : 'bg-slate-100 text-slate-500'}`}>
            {i + 1}. {label}
          </li>
        ))}
      </ol>

      {notice && <p className="rounded bg-amber-100 p-2 text-sm text-amber-800">{notice}</p>}

      {error && <p className="rounded bg-red-100 p-2 text-sm text-red-800">{error}</p>}

      {step === 0 && (
        <form onSubmit={next} className="space-y-4">
          <label className="block text-sm">
            Identifiant
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required
              autoComplete="username" className={input} />
          </label>
          <button className="w-full rounded bg-slate-800 p-2 text-white">Continuer</button>
        </form>
      )}

      {step === 1 && <FaceStep username={username.trim()} onVerified={faceOk} onFallback={planB} />}

      {step === 2 && (
        <form onSubmit={submit} className="space-y-4">
          {fallback && (
            <p className="rounded bg-amber-100 p-2 text-sm text-amber-800">
              Plan B : vérification faciale ignorée ({fallback}) Connexion par mot de passe uniquement.
            </p>
          )}
          <label className="block text-sm">
            Mot de passe pour {username.trim()}
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus required
              autoComplete="current-password" className={input} />
          </label>
          <button disabled={busy} className="w-full rounded bg-slate-800 p-2 text-white disabled:opacity-50">
            {busy ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      )}

      {step > 0 && (
        <button type="button" onClick={() => { setStep(0); setError(''); setPassword('') }}
          className="text-xs text-slate-500 underline">
          Changer d'identifiant
        </button>
      )}
    </div>
  )
}
