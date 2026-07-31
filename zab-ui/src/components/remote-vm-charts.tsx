import { useId, useMemo, useState } from 'react'

export type CostDay = {
  day: string
  cost: number
  net_cost: number
  compute: number
  storage: number
  network: number
  other: number
  hours: number
}

const CATEGORY_META = [
  { key: 'compute', label: 'Calcul', fill: 'fill-sky-500', chip: 'bg-sky-500' },
  { key: 'storage', label: 'Stockage', fill: 'fill-violet-500', chip: 'bg-violet-500' },
  { key: 'network', label: 'Réseau', fill: 'fill-teal-500', chip: 'bg-teal-500' },
  { key: 'other', label: 'Autre', fill: 'fill-zinc-400', chip: 'bg-zinc-400' },
] as const

const W = 720
const H = 210
const PAD_L = 44
const PAD_R = 38
const PAD_T = 12
const PAD_B = 26

function niceMax(value: number): number {
  if (value <= 0) return 1
  const exp = Math.floor(Math.log10(value))
  const base = 10 ** exp
  const step = [1, 2, 2.5, 5, 10].find((s) => value <= s * base) ?? 10
  return step * base
}

/** Barres empilées du coût quotidien + courbe des heures d'exécution. */
export function CostChart({ days, currency }: { days: CostDay[]; currency: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const clipId = useId()

  const money = useMemo(
    () => new Intl.NumberFormat('fr-FR', { style: 'currency', currency, maximumFractionDigits: 2 }),
    [currency],
  )

  if (days.length === 0) {
    return <p className="text-muted-foreground py-8 text-center text-xs">Aucune donnée de facturation sur la fenêtre.</p>
  }

  const plotW = W - PAD_L - PAD_R
  const plotH = H - PAD_T - PAD_B
  const slot = plotW / days.length
  const barW = Math.max(3, Math.min(26, slot * 0.62))

  const maxCost = niceMax(Math.max(...days.map((d) => d.net_cost), 0.0001))
  // Arrondi au multiple de 4 : les quarts de l'axe des heures tombent juste.
  const maxHours = Math.ceil(niceMax(Math.max(...days.map((d) => d.hours), 1)) / 4) * 4

  const x = (i: number) => PAD_L + slot * i + slot / 2
  const yCost = (v: number) => PAD_T + plotH - (v / maxCost) * plotH
  const yHours = (v: number) => PAD_T + plotH - (v / maxHours) * plotH

  const hoursPath = days
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${yHours(d.hours).toFixed(1)}`)
    .join(' ')

  const active = hover != null ? days[hover] : null
  const gridSteps = [0, 0.25, 0.5, 0.75, 1]

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          {CATEGORY_META.map((c) => (
            <span key={c.key} className="text-muted-foreground flex items-center gap-1.5">
              <span className={`size-2 rounded-full ${c.chip}`} aria-hidden />
              {c.label}
            </span>
          ))}
          <span className="text-muted-foreground flex items-center gap-1.5">
            <span className="bg-amber-500 h-0.5 w-4 rounded-full" aria-hidden />
            Heures allumée
          </span>
        </div>
        <p className="tabular-nums">
          {active ? (
            <>
              <span className="font-medium">{active.day}</span>
              <span className="text-muted-foreground"> · </span>
              {money.format(active.net_cost)}
              <span className="text-muted-foreground"> · </span>
              <span className="text-amber-600 dark:text-amber-400">{active.hours.toFixed(2)} h</span>
            </>
          ) : (
            <span className="text-muted-foreground">Survole une journée pour le détail</span>
          )}
        </p>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label="Coût quotidien de la VM et heures d'exécution"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={PAD_L} y={PAD_T} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {gridSteps.map((step) => {
          const y = PAD_T + plotH - step * plotH
          return (
            <g key={step}>
              <line
                x1={PAD_L}
                x2={W - PAD_R}
                y1={y}
                y2={y}
                className="stroke-border"
                strokeWidth={1}
                strokeDasharray={step === 0 ? undefined : '3 4'}
              />
              <text x={PAD_L - 6} y={y + 3} textAnchor="end" className="fill-muted-foreground text-[9px] tabular-nums">
                {(maxCost * step).toFixed(maxCost < 2 ? 2 : 1)}
              </text>
              <text x={W - PAD_R + 6} y={y + 3} className="fill-amber-600/80 dark:fill-amber-400/80 text-[9px] tabular-nums">
                {Math.round(maxHours * step)}h
              </text>
            </g>
          )
        })}

        <g clipPath={`url(#${clipId})`}>
          {days.map((d, i) => {
            let cursor = yCost(0)
            return (
              <g key={d.day} opacity={hover == null || hover === i ? 1 : 0.45}>
                {CATEGORY_META.map((c) => {
                  const value = Math.max(0, Number(d[c.key as keyof CostDay] ?? 0))
                  if (value <= 0) return null
                  const h = (value / maxCost) * plotH
                  cursor -= h
                  return (
                    <rect
                      key={c.key}
                      x={x(i) - barW / 2}
                      y={cursor}
                      width={barW}
                      height={Math.max(h, 0.6)}
                      rx={1.5}
                      className={c.fill}
                    />
                  )
                })}
              </g>
            )
          })}

          <path d={hoursPath} fill="none" className="stroke-amber-500" strokeWidth={1.75} strokeLinejoin="round" />
          {days.map((d, i) =>
            d.hours > 0 ? (
              <circle key={d.day} cx={x(i)} cy={yHours(d.hours)} r={hover === i ? 3.5 : 2} className="fill-amber-500" />
            ) : null,
          )}
        </g>

        {days.map((d, i) => (
          <rect
            key={`hit-${d.day}`}
            x={PAD_L + slot * i}
            y={PAD_T}
            width={slot}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          >
            <title>{`${d.day} — ${d.net_cost.toFixed(3)} ${currency} — ${d.hours.toFixed(2)} h`}</title>
          </rect>
        ))}

        {days.map((d, i) => {
          const every = Math.max(1, Math.round(days.length / 8))
          if (i % every !== 0 && i !== days.length - 1) return null
          return (
            <text
              key={`lbl-${d.day}`}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              className="fill-muted-foreground text-[9px] tabular-nums"
            >
              {d.day.slice(5)}
            </text>
          )
        })}
      </svg>
    </div>
  )
}

/** Sparkline compacte pour les tuiles de KPI. */
export function Sparkline({ values, tone = 'sky' }: { values: number[]; tone?: 'sky' | 'amber' | 'emerald' }) {
  if (values.length === 0) return null
  const w = 120
  const h = 28
  const max = Math.max(...values, 0.0001)
  const step = values.length > 1 ? w / (values.length - 1) : w
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`)
  const stroke = { sky: 'stroke-sky-500', amber: 'stroke-amber-500', emerald: 'stroke-emerald-500' }[tone]
  const fill = { sky: 'fill-sky-500/15', amber: 'fill-amber-500/15', emerald: 'fill-emerald-500/15' }[tone]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-7 w-full" aria-hidden preserveAspectRatio="none">
      <polygon points={`0,${h} ${points.join(' ')} ${w},${h}`} className={fill} />
      <polyline points={points.join(' ')} fill="none" className={stroke} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Jauge circulaire : part de sessions saines sur le total. */
export function Ring({
  value,
  total,
  tone,
  label,
}: {
  value: number
  total: number
  tone: 'emerald' | 'amber' | 'zinc'
  label: string
}) {
  const r = 26
  const c = 2 * Math.PI * r
  const ratio = total > 0 ? Math.min(1, value / total) : 0
  const stroke = { emerald: 'stroke-emerald-500', amber: 'stroke-amber-500', zinc: 'stroke-zinc-400' }[tone]
  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 64 64" className="size-16 -rotate-90" aria-label={label}>
        <circle cx="32" cy="32" r={r} fill="none" className="stroke-muted" strokeWidth={7} />
        {ratio > 0 ? (
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            className={stroke}
            strokeWidth={7}
            strokeLinecap="round"
            strokeDasharray={`${(c * ratio).toFixed(2)} ${c.toFixed(2)}`}
          />
        ) : null}
      </svg>
      <div className="min-w-0">
        <p className="text-xl font-semibold tabular-nums">
          {value}
          <span className="text-muted-foreground text-sm font-normal">/{total}</span>
        </p>
        <p className="text-muted-foreground text-xs">{label}</p>
      </div>
    </div>
  )
}
