import { useEffect, useState } from 'react'
import { getHistory, getStatus } from './api.js'
import Chart from './Chart.jsx'
import { ACTIONS, IncidentDetail, IncidentTable } from './Incidents.jsx'

const HISTORY_MIN = 15

// Un état = un bandeau : le jury doit comprendre la situation en un coup d'œil.
const BANNER = {
  HEALTHY: { title: 'Service de paiement sain', color: 'border-emerald-500 bg-emerald-950/60 text-emerald-200' },
  DEGRADED: { title: 'Service dégradé', color: 'border-red-500 bg-red-950/60 text-red-200' },
  REMEDIATING: { title: 'Remédiation en cours', color: 'border-amber-500 bg-amber-950/60 text-amber-200' },
  RECOVERED: { title: 'Reprise vérifiée', color: 'border-emerald-400 bg-emerald-900/50 text-emerald-100' },
  UNKNOWN: { title: 'État inconnu', color: 'border-slate-500 bg-slate-900 text-slate-300' },
}

function subtitle(state, status, active, last) {
  if (state === 'HEALTHY') return 'Un paiement fictif complet passe via le WAF, comptes cohérents.'
  if (state === 'DEGRADED') return 'Le paiement de contrôle échoue ; le détecteur et le moteur de remédiation prennent le relais.'
  if (state === 'REMEDIATING') {
    const step = [...active.timeline].reverse().find((e) => e.event === 'action_started')
    return step ? `Action en cours : ${ACTIONS[step.action] ?? step.action}. En attente de la preuve du canary.` : 'Analyse du signal.'
  }
  if (state === 'RECOVERED') {
    return `Paiement rejoué avec succès après « ${ACTIONS[last.resolved_by] ?? last.resolved_by} » en ${last.duration_s} s, sans intervention humaine.`
  }
  return status.probe.reachable ? 'La sonde ne répond plus de façon fraîche.' : 'Sonde canary injoignable : aucune preuve d’état.'
}

export default function App() {
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState(null)
  const [offline, setOffline] = useState(false)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async (fn, set) => {
      try {
        const data = await fn()
        if (alive) { set(data); setOffline(false) }
      } catch {
        if (alive) setOffline(true)   // la supervision elle-même est injoignable : on l'affiche, on ne fige pas l'écran
      }
    }
    const tick = () => load(getStatus, setStatus)
    const tickH = () => load(() => getHistory(HISTORY_MIN), setHistory)
    tick(); tickH()
    const a = setInterval(tick, 2000)
    const b = setInterval(tickH, 5000)
    return () => { alive = false; clearInterval(a); clearInterval(b) }
  }, [])

  if (!status) {
    return <p className="p-8 text-slate-400">{offline ? 'Service de supervision injoignable.' : 'Chargement…'}</p>
  }

  const incidents = status.incidents
  const active = incidents.find((i) => i.status === 'IN_PROGRESS')
  const last = incidents[0]
  const state = offline ? 'UNKNOWN' : status.state
  const banner = BANNER[state]
  const detail = incidents.find((i) => i.id === selected) ?? active ?? last

  const to = history ? Date.now() / 1000 : 0
  const from = to - HISTORY_MIN * 60
  const bands = incidents.map((i) => ({
    from: new Date(i.created_at).getTime() / 1000,
    to: i.ended_at ? new Date(i.ended_at).getTime() / 1000 : to,
  }))
  const s = history?.series ?? { probe: [], rps: [], p95_ms: [] }

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <header className="mb-4 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Supervision · RESILIENCE-ALPHA</h1>
        <span className="text-xs text-slate-500">{offline ? 'liaison perdue' : 'mise à jour toutes les 2 s'}</span>
      </header>

      <section className={`rounded-xl border-2 p-5 ${banner.color}`} aria-live="polite">
        <p className="text-2xl font-bold">{banner.title}</p>
        <p className="mt-1 text-sm opacity-90">{subtitle(state, status, active, last)}</p>
      </section>

      <section className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Paiement de contrôle" value={!status.probe.reachable ? '—' : status.probe.ok ? 'OK' : 'ÉCHEC'} />
        <Stat label="Dernière vérification" value={status.probe.age_s != null ? `il y a ${Math.round(status.probe.age_s)} s` : '—'} />
        <Stat label="Moteur de remédiation" value={status.engine_reachable ? 'joignable' : 'injoignable'} />
        <Stat label="Incidents enregistrés" value={incidents.length} />
      </section>

      <section className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2">
          <Chart title="État du paiement (1 = sain, 0 = échec)" points={s.probe} from={from} to={to} color="#34d399" stepped fixedMax={1.15}
            format={(v) => (v >= 0.5 ? 'sain' : 'échec')} bands={bands} />
        </div>
        <Chart title="Trafic de l’API (req/s)" points={s.rps} from={from} to={to} color="#60a5fa" format={(v) => v.toFixed(1)} bands={bands} />
        <Chart title="Latence p95 de l’API (ms)" points={s.p95_ms} from={from} to={to} color="#f472b6" format={(v) => Math.round(v)} bands={bands} />
      </section>
      <p className="mt-1 text-xs text-slate-500">Les bandes ambrées marquent les incidents.</p>

      <section className="mt-5 grid gap-5 md:grid-cols-2">
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase text-slate-400">Incidents</h2>
          {incidents.length === 0 ? <p className="text-sm text-slate-500">Aucun incident.</p>
            : <IncidentTable incidents={incidents} selected={detail?.id} onSelect={setSelected} />}
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase text-slate-400">Chronologie de l’incident</h2>
          <IncidentDetail incident={detail} />
        </div>
      </section>
    </main>
  )
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  )
}
