import { useEffect, useState } from 'react'
import { FACE_MODE, identifyFace } from './api.js'

// Étape 2 du login : reconnaissance faciale. La caméra est lue par le serveur du PC hôte (service IA) :
// le navigateur n'a ni caméra ni image à gérer, il déclenche juste l'identification et attend le verdict.
// onVerified(faceToken) : visage validé. onFallback(raison) : plan B (mot de passe seul).
//
// Plan B automatique uniquement pour une PANNE (caméra introuvable, serveur IA injoignable ou en erreur).
// Un visage refusé ou un compte bloqué n'ouvre PAS le plan B tout seul : ce serait contourner le contrôle.
// Le bouton manuel reste là pour que l'opérateur décide le jour J.
export default function FaceStep({ username, onVerified, onFallback }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [wait, setWait] = useState(0) // secondes avant de pouvoir réessayer (LED rouge côté poste)

  useEffect(() => {
    if (wait <= 0) return
    const t = setTimeout(() => setWait(wait - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const r = await identifyFace(username)
      if (r.verified) return onVerified(r.faceToken)
      setError(r.message)
      setWait(r.pauseS)
    } catch (err) {
      if (err.kind === 'rejected') setError(err.message) // 429 compte bloqué, 409 poste occupé
      else onFallback(`Service de reconnaissance indisponible (${err.message})`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Placez-vous face à la caméra du poste, puis lancez la reconnaissance. L'analyse dure quelques secondes.
      </p>
      <div className="grid aspect-video place-items-center rounded-lg bg-slate-900 text-sm text-slate-300">
        {busy ? 'Analyse en cours… regardez la caméra' : 'Caméra du poste en attente'}
      </div>
      {FACE_MODE === 'mock' && (
        <p className="rounded bg-amber-100 p-2 text-xs text-amber-800">Mode simulation : aucune reconnaissance réelle.</p>
      )}
      {error && <p className="rounded bg-red-100 p-2 text-sm text-red-800">{error}</p>}
      <button type="button" onClick={start} disabled={busy || wait > 0}
        className="w-full rounded bg-slate-800 p-2 text-white disabled:opacity-50">
        {busy ? 'Vérification…' : wait > 0 ? `Réessayer dans ${wait} s` : 'Lancer la reconnaissance'}
      </button>
      <button type="button" onClick={() => onFallback('Plan B choisi manuellement.')}
        className="w-full text-sm text-slate-500 underline">
        Caméra ou reconnaissance en panne ? Continuer avec le mot de passe seul
      </button>
    </div>
  )
}
