import { useCallback, useEffect, useState } from 'react'
import { getAccounts, getTransactions } from './api.js'
import History from './History.jsx'
import Shop from './Shop.jsx'
import TransferForm from './TransferForm.jsx'

const money = (amount, currency) => `${Number(amount).toFixed(2)} ${currency}`

export default function Dashboard({ session, onExpired }) {
  const [accounts, setAccounts] = useState([])
  const [transactions, setTransactions] = useState([])
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [acc, tx] = await Promise.all([getAccounts(session.token), getTransactions(session.token, 50)])
      setAccounts(acc)
      setTransactions(tx)
      setError('')
    } catch (err) {
      if (err.kind === 'auth') onExpired() // jeton expiré ou refusé : retour au login
      else setError(err.message)
    }
  }, [session.token, onExpired])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <div className="space-y-6">
      {error && (
        <p className="rounded bg-red-100 p-3 text-sm text-red-800">
          {error} <button onClick={refresh} className="ml-2 underline">Réessayer</button>
        </p>
      )}

      <section className="rounded-lg bg-slate-800 p-5 text-white shadow">
        <p className="text-sm text-slate-300">Solde total</p>
        <p className="text-3xl font-semibold">{money(accounts.reduce((s, a) => s + Number(a.balance), 0), 'EUR')}</p>
        <p className="mt-1 text-xs text-slate-400">{accounts.length} compte(s)</p>
      </section>

      <section className="rounded bg-white p-4 shadow">
        <h2 className="mb-3 font-semibold">Mes comptes</h2>
        <ul className="divide-y">
          {accounts.map((a) => (
            <li key={a.id} className="flex justify-between py-2">
              <span className="font-mono text-sm">{a.id}</span>
              <span className="font-semibold">{money(a.balance, a.currency)}</span>
            </li>
          ))}
          {accounts.length === 0 && !error && <li className="py-2 text-sm text-slate-500">Aucun compte.</li>}
        </ul>
      </section>

      <Shop token={session.token} accounts={accounts} onExpired={onExpired} onDone={refresh} />

      <History transactions={transactions} />

      {/* Virement libre conservé : même endpoint que la boutique, utile aux tests et à la démo technique. */}
      <details className="rounded bg-white p-4 shadow">
        <summary className="cursor-pointer font-semibold">Virement libre</summary>
        <div className="mt-3">
          <TransferForm token={session.token} accounts={accounts} onExpired={onExpired} onDone={refresh} />
        </div>
      </details>
    </div>
  )
}
