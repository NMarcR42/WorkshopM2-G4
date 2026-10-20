import { useRef, useState } from 'react'
import { createTransaction } from './api.js'

export default function TransferForm({ token, accounts, onExpired, onDone }) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('ACC-MERCHANT')
  const [amount, setAmount] = useState('10.00')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null) // { ok, message }

  // Une clé par "intention de paiement". On la GARDE si la réponse s'est perdue (timeout, 503) :
  // le renvoi ne paiera pas deux fois. On la jette dès que le résultat est définitif ou que le formulaire change.
  const keyRef = useRef(null)
  const edit = (setter) => (e) => {
    keyRef.current = null
    setter(e.target.value)
  }

  const source = from || accounts[0]?.id || ''

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    keyRef.current ??= crypto.randomUUID()
    try {
      const { transaction, replayed } = await createTransaction(
        token,
        { from_account: source, to_account: to.trim().toUpperCase(), amount, currency: 'EUR' },
        keyRef.current,
      )
      keyRef.current = null
      const note = replayed ? ' (déjà enregistré, non débité deux fois)' : ''
      setResult({ ok: true, message: `Paiement accepté : ${transaction.amount} ${transaction.currency} vers ${transaction.to_account}${note}.` })
      onDone()
    } catch (err) {
      if (err.kind === 'auth') return onExpired()
      if (!err.retryable) keyRef.current = null // refus définitif (solde, compte...) : nouvelle tentative = nouvelle clé
      const hint = err.retryable ? ' Vous pouvez réessayer : le paiement ne sera pas débité deux fois.' : ''
      setResult({ ok: false, message: `Paiement échoué : ${err.message}${hint}` })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded bg-white p-4 shadow">
      <h2 className="font-semibold">Nouveau paiement</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          Depuis
          <select value={source} onChange={edit(setFrom)} className="mt-1 w-full rounded border border-slate-300 p-2">
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.id}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Vers (compte)
          <input value={to} onChange={edit(setTo)} required pattern="[A-Za-z0-9-]+"
            className="mt-1 w-full rounded border border-slate-300 p-2 font-mono" />
        </label>
        <label className="text-sm">
          Montant (EUR)
          <input type="number" min="0.01" step="0.01" value={amount} onChange={edit(setAmount)} required
            className="mt-1 w-full rounded border border-slate-300 p-2" />
        </label>
      </div>
      <button disabled={busy || !source} className="rounded bg-slate-800 px-4 py-2 text-white disabled:opacity-50">
        {busy ? 'Envoi…' : 'Payer'}
      </button>
      {result && (
        <p className={`rounded p-2 text-sm ${result.ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
          {result.message}
        </p>
      )}
    </form>
  )
}
