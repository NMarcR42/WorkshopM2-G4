import { useCallback, useEffect, useState } from 'react'
import { getAccounts, getTransactions } from './api.js'
import TransferForm from './TransferForm.jsx'

const money = (amount, currency) => `${Number(amount).toFixed(2)} ${currency}`

export default function Dashboard({ session, onExpired }) {
  const [accounts, setAccounts] = useState([])
  const [transactions, setTransactions] = useState([])
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [acc, tx] = await Promise.all([getAccounts(session.token), getTransactions(session.token)])
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

      <TransferForm token={session.token} accounts={accounts} onExpired={onExpired} onDone={refresh} />

      <section className="rounded bg-white p-4 shadow">
        <h2 className="mb-3 font-semibold">Dernières transactions</h2>
        <ul className="divide-y text-sm">
          {transactions.map((t) => (
            <li key={t.id} className="flex justify-between py-2">
              <span>
                {t.from_account} → {t.to_account}
              </span>
              <span>
                {money(t.amount, t.currency)} <span className="text-green-700">{t.status}</span>
              </span>
            </li>
          ))}
          {transactions.length === 0 && <li className="py-2 text-slate-500">Aucune transaction.</li>}
        </ul>
      </section>
    </div>
  )
}
