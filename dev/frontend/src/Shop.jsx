import { useRef, useState } from 'react'
import { createTransaction } from './api.js'
import { saveLabel } from './labels.js'

// Compte du commerçant fictif : configurable à la construction.
const MERCHANT = import.meta.env.VITE_MERCHANT_ACCOUNT ?? 'ACC-MERCHANT'

// Vitrine fictive : quelques livres. Les prix sont des chaînes pour rester exacts (l'API attend 2 décimales).
const ARTICLES = [
  { id: 'livre-1', name: 'Résilience des systèmes', author: 'A. Martin', price: '24.90' },
  { id: 'livre-2', name: 'Pare-feu pour tous', author: 'C. Bernard', price: '18.50' },
  { id: 'livre-3', name: 'Comprendre le chiffrement', author: 'S. Leroy', price: '32.00' },
  { id: 'livre-4', name: "Détecter l'anomalie", author: 'M. Dubois', price: '27.90' },
]

export default function Shop({ token, accounts, onExpired, onDone }) {
  const [busyId, setBusyId] = useState(null)
  const [result, setResult] = useState(null) // { ok, message }

  // Une clé d'idempotence par article, GARDÉE si la réponse s'est perdue (timeout, 503) :
  // recliquer sur « Payer » ne débite alors pas deux fois. Jetée dès que le résultat est définitif.
  const keys = useRef({})
  const source = accounts[0]?.id

  const pay = async (article) => {
    setBusyId(article.id)
    setResult(null)
    keys.current[article.id] ??= crypto.randomUUID()
    try {
      const { transaction, replayed } = await createTransaction(
        token,
        { from_account: source, to_account: MERCHANT, amount: article.price, currency: 'EUR' },
        keys.current[article.id],
      )
      delete keys.current[article.id]
      saveLabel(transaction.id, article.name)
      const note = replayed ? ' (déjà enregistré, non débité deux fois)' : ''
      setResult({ ok: true, message: `« ${article.name} » acheté pour ${transaction.amount} ${transaction.currency}${note}.` })
      onDone()
    } catch (err) {
      if (err.kind === 'auth') return onExpired()
      if (!err.retryable) delete keys.current[article.id] // refus définitif (solde...) : nouvelle tentative = nouvelle clé
      const hint = err.retryable ? ' Vous pouvez réessayer : le paiement ne sera pas débité deux fois.' : ''
      setResult({ ok: false, message: `Paiement échoué : ${err.message}${hint}` })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="space-y-3 rounded bg-white p-4 shadow">
      <h2 className="font-semibold">Boutique</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {ARTICLES.map((a) => (
          <article key={a.id} className="flex flex-col justify-between rounded border border-slate-200 p-3">
            <div>
              <h3 className="font-medium">{a.name}</h3>
              <p className="text-sm text-slate-500">{a.author}</p>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <span className="font-semibold">{a.price} EUR</span>
              <button onClick={() => pay(a)} disabled={busyId !== null || !source}
                className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                {busyId === a.id ? 'Envoi…' : 'Payer'}
              </button>
            </div>
          </article>
        ))}
      </div>
      {result && (
        <p className={`rounded p-2 text-sm ${result.ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
          {result.message}
        </p>
      )}
    </section>
  )
}
