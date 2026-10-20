const STATUS = {
  IN_PROGRESS: ['En cours', 'text-amber-300'],
  RESOLVED: ['Résolu', 'text-emerald-300'],
  UNRESOLVED: ['Non résolu', 'text-red-300'],
}

const ACTIONS = {
  block_ip: 'Blocage de l’IP source',
  restart: 'Redémarrage du service',
  recreate: 'Recréation du service',
  isolate: 'Isolement du service',
  restore_db: 'Restauration de la base',
  rollback_vm: 'Retour arrière de la VM',
  none: 'Aucune (faux positif écarté)',
}

const time = (iso) => (iso ? new Date(iso).toLocaleTimeString('fr-FR') : '—')

// Phrase lisible pour une ligne de la chronologie du moteur.
function describe(e) {
  switch (e.event) {
    case 'action_started': return [`Action : ${ACTIONS[e.action] ?? e.action}`, 'text-slate-200']
    case 'action_failed': return [`Action en échec : ${ACTIONS[e.action] ?? e.action}`, 'text-red-300']
    case 'verify':
      return e.ok
        ? ['Preuve canary : paiement rejoué avec succès', 'text-emerald-300']
        : [`Canary : paiement en échec${e.detail ? ` (${e.detail})` : ''}`, 'text-slate-400']
    case 'escalated': return ['Actions épuisées : intervention humaine requise', 'text-red-300']
    case 'interrupted': return ['Moteur redémarré en cours d’incident', 'text-red-300']
    default: return [e.event, 'text-slate-400']
  }
}

export function IncidentDetail({ incident }) {
  if (!incident) return <p className="text-sm text-slate-500">Aucun incident enregistré.</p>
  const ips = (incident.suspects ?? []).map((s) => `${s.value} (${Math.round(s.share * 100)} %)`).join(', ')
  return (
    <div>
      <p className="text-sm text-slate-400">
        Service visé : <b className="text-slate-200">{incident.target_service}</b>
        {ips && <> · Source suspecte : <b className="font-mono text-slate-200">{ips}</b></>}
        {incident.score != null && <> · Score d’anomalie : <b className="text-slate-200">{incident.score}</b></>}
      </p>
      <ol className="mt-3 max-h-64 space-y-1 overflow-y-auto border-l border-slate-700 pl-4">
        {incident.timeline.map((e, i) => {
          const [text, cls] = describe(e)
          return (
            <li key={i} className="text-sm">
              <span className="mr-2 font-mono text-xs text-slate-500">{time(e.ts)}</span>
              <span className={cls}>{text}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export function IncidentTable({ incidents, selected, onSelect }) {
  if (incidents.length === 0) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr><th className="py-1 pr-3">Heure</th><th className="pr-3">Statut</th><th className="pr-3">Résolu par</th><th>Durée</th></tr>
        </thead>
        <tbody>
          {incidents.map((i) => {
            const [label, cls] = STATUS[i.status] ?? [i.status, '']
            return (
              <tr key={i.id} onClick={() => onSelect(i.id)}
                className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/50 ${selected === i.id ? 'bg-slate-800/70' : ''}`}>
                <td className="py-1 pr-3 font-mono">{time(i.created_at)}</td>
                <td className={`pr-3 ${cls}`}>{label}</td>
                <td className="pr-3">{i.resolved_by ? ACTIONS[i.resolved_by] ?? i.resolved_by : '—'}</td>
                <td className="font-mono">{i.duration_s != null ? `${i.duration_s} s` : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export { ACTIONS }
