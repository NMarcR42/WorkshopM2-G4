import { labelOf } from './labels.js'

const money = (amount, currency) => `${Number(amount).toFixed(2)} ${currency}`
const date = (iso) => new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })

// Historique lisible : date, libellé, montant, statut. Le libellé vient du navigateur (voir labels.js) ;
// sans lui (autre navigateur, virement libre), on affiche le sens du virement.
export default function History({ transactions }) {
  return (
    <section className="rounded bg-white p-4 shadow">
      <h2 className="mb-3 font-semibold">Historique des transactions</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-normal">Date</th>
              <th className="py-1 pr-3 font-normal">Libellé</th>
              <th className="py-1 pr-3 text-right font-normal">Montant</th>
              <th className="py-1 font-normal">Statut</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {transactions.map((t) => (
              <tr key={t.id}>
                <td className="py-2 pr-3 whitespace-nowrap">{date(t.created_at)}</td>
                <td className="py-2 pr-3">{labelOf(t.id) ?? `Virement ${t.from_account} → ${t.to_account}`}</td>
                <td className="py-2 pr-3 text-right whitespace-nowrap">{money(t.amount, t.currency)}</td>
                <td className="py-2">
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-800">{t.status}</span>
                </td>
              </tr>
            ))}
            {transactions.length === 0 && (
              <tr><td colSpan="4" className="py-3 text-slate-500">Aucune transaction.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
