// Courbe SVG sans dépendance. Les bandes ambrées marquent les incidents : on lit « avant / pendant / après » d'un coup d'œil.
const W = 640
const H = 130
const PAD = { l: 44, r: 8, t: 8, b: 18 }

export const clock = (t) => new Date(t * 1000).toLocaleTimeString('fr-FR')

export default function Chart({ title, points, from, to, color, format, stepped = false, fixedMax, bands = [] }) {
  const x = (t) => PAD.l + ((t - from) / (to - from)) * (W - PAD.l - PAD.r)
  const max = fixedMax ?? Math.max(1e-9, ...points.map((p) => p[1])) * 1.15
  const y = (v) => H - PAD.b - (Math.min(v, max) / max) * (H - PAD.t - PAD.b)

  // Courbe « en marches » pour l'état du paiement (0/1) : une valeur reste vraie jusqu'à la mesure suivante.
  let d = ''
  points.forEach(([t, v], i) => {
    if (i === 0) d += `M${x(t)},${y(v)}`
    else d += stepped ? ` H${x(t)} V${y(v)}` : ` L${x(t)},${y(v)}`
  })
  const last = points.length ? points[points.length - 1][1] : null

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-slate-300">{title}</h3>
        <span className="font-mono text-sm" style={{ color }}>{last === null ? '—' : format(last)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={title}>
        {bands.map((b, i) => (
          <rect key={i} x={x(Math.max(b.from, from))} y={PAD.t} width={Math.max(2, x(Math.min(b.to, to)) - x(Math.max(b.from, from)))}
            height={H - PAD.t - PAD.b} fill="#f59e0b" opacity="0.15" />
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke="#334155" />
        <text x={PAD.l - 6} y={PAD.t + 8} textAnchor="end" fontSize="10" fill="#94a3b8">{format(max / 1.15)}</text>
        <text x={PAD.l - 6} y={H - PAD.b} textAnchor="end" fontSize="10" fill="#94a3b8">0</text>
        <text x={PAD.l} y={H - 4} fontSize="10" fill="#94a3b8">{clock(from)}</text>
        <text x={W - PAD.r} y={H - 4} textAnchor="end" fontSize="10" fill="#94a3b8">{clock(to)}</text>
        {points.length > 0 ? (
          <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        ) : (
          <text x={W / 2} y={H / 2} textAnchor="middle" fontSize="12" fill="#64748b">Pas de données</text>
        )}
      </svg>
    </div>
  )
}
