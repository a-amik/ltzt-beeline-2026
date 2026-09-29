/**
 * Узлы рисунков «Отчётов»: тонкие линии, подписи набором, цвет — только
 * у метки ряда. Каждый рисунок подписан «Рис. N» и отвечает на наведение
 * подсказкой у метки. Своих формул здесь нет: страницы отдают готовые ряды.
 */

import { useState, type ReactNode } from 'react'
import { num } from '../../lib/ui'

export interface Legend { label: string; color: string; dashed?: boolean }

export function Figure({ n, title, legend, children, note }: {
  n: number; title: ReactNode; legend?: Legend[]; children: ReactNode; note?: ReactNode
}) {
  return (
    <figure className="b-an-fig">
      <div className="h"><b>Рис. {n}.</b> {title}</div>
      {legend ? (
        <div className="lg">
          {legend.map((l) => <span key={l.label}><i className={l.dashed ? 'd' : undefined} style={{ background: l.color, borderColor: l.color }} />{l.label}</span>)}
        </div>
      ) : null}
      {children}
      {note ? <figcaption>{note}</figcaption> : null}
    </figure>
  )
}

/** Плитки с числом; у плитки — плоская пиктограмма из общего набора значков (`lib/icons`). */
export function Tiles({ items }: { items: { value: string; label: string; note?: string; icon?: ReactNode }[] }) {
  return (
    <div className="b-an-tiles">
      {items.map((t) => (
        <div key={t.label}>
          {t.icon ? <i className="ic">{t.icon}</i> : null}
          <b>{t.value}</b>
          <span>{t.label}</span>
          {t.note ? <small>{t.note}</small> : null}
        </div>
      ))}
    </div>
  )
}

/** Сгруппированные полосы: группа — участок, полоса — план. Длина — от нуля. */
export function GroupBars({ groups, series, fmt, max }: {
  groups: { label: string; values: (number | null)[] }[]
  series: Legend[]
  fmt: (v: number) => string
  max?: number
}) {
  const [hover, setHover] = useState<string | null>(null)
  const top = max ?? Math.max(1, ...groups.flatMap((g) => g.values.filter((v): v is number => v !== null)))
  return (
    <div className="b-an-gbars">
      {groups.map((g) => (
        <div key={g.label} className="g">
          <div className="gl">{g.label}</div>
          <div className="gb">
            {g.values.map((v, i) => {
              const id = `${g.label}-${i}`
              return (
                <div key={i} className={`bar${hover === id ? ' on' : ''}`} onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)}>
                  <span className="name">{series[i].label}</span>
                  <span className="track">
                    <span className="fill" style={{ width: v === null ? 0 : `${Math.max(0.5, (100 * v) / top)}%`, background: series[i].color }} />
                  </span>
                  <span className="val">{v === null ? '—' : fmt(v)}</span>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

export interface Series { key: string; label: string; color: string; values: (number | null)[]; dashed?: boolean; dots?: boolean }

/** Линии по общей оси X с перекрестием и подсказкой. Значения вне [lo, hi] прижаты к краю. */
export function LineChart({ x, series, lo, hi, fmt = (v) => num(v, 1), height = 240, ticks, bands, width = 720 }: {
  x: string[]; series: Series[]; lo: number; hi: number; fmt?: (v: number) => string; height?: number; ticks?: number[]; width?: number
  bands?: { from: number; label: string }[]
}) {
  const [at, setAt] = useState<number | null>(null)
  const W = width
  const H = height
  const R = 16
  const T = 12
  const B = 28
  const tk = ticks ?? [lo, (lo + hi) / 2, hi]
  const L = Math.max(44, Math.max(...tk.map((v) => fmt(v).length)) * 6.6 + 12)
  const px = (i: number) => L + ((W - L - R) * (x.length === 1 ? 0.5 : i / (x.length - 1)))
  const py = (v: number) => H - B - ((H - T - B) * (Math.max(lo, Math.min(hi, v)) - lo)) / (hi - lo || 1)
  const step = Math.max(1, Math.ceil(x.length / 10))
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const vx = ((e.clientX - r.left) / r.width) * W
    let best = 0
    x.forEach((_, i) => { if (Math.abs(px(i) - vx) < Math.abs(px(best) - vx)) best = i })
    setAt(best)
  }
  return (
    <div className="b-an-plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" onMouseMove={onMove} onMouseLeave={() => setAt(null)}>
        {bands?.map((b) => (
          <g key={b.label} className="band">
            <line x1={px(b.from)} x2={px(b.from)} y1={T} y2={H - B} />
            <text x={px(b.from) + 4} y={T + 10}>{b.label}</text>
          </g>
        ))}
        {tk.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={py(v)} y2={py(v)} className="grid" />
            <text x={L - 6} y={py(v) + 4} textAnchor="end">{fmt(v)}</text>
          </g>
        ))}
        {x.map((label, i) => (i % step === 0 || i === x.length - 1 ? <text key={i} x={px(i)} y={H - 8} textAnchor="middle">{label}</text> : null))}
        {series.map((s) => {
          const d = s.values.map((v, i) => (v === null ? '' : `${i && s.values[i - 1] !== null ? 'L' : 'M'}${px(i).toFixed(1)},${py(v).toFixed(1)}`)).join('')
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={2.2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" />
              {s.dots ? s.values.map((v, i) => (v === null ? null : <circle key={i} cx={px(i)} cy={py(v)} r={2.6} fill={s.color} />)) : null}
            </g>
          )
        })}
        {at !== null ? (
          <g className="cross">
            <line x1={px(at)} x2={px(at)} y1={T} y2={H - B} />
            {series.map((s) => (s.values[at] === null ? null : <circle key={s.key} cx={px(at)} cy={py(s.values[at] as number)} r={4} fill={s.color} />))}
          </g>
        ) : null}
      </svg>
      {at !== null ? (
        <div className="tip" style={{ left: `${(px(at) / W) * 100}%` }}>
          <b>{x[at]}</b>
          {series.map((s) => (s.values[at] === null ? null : <span key={s.key}><i style={{ background: s.color }} />{s.label}: {fmt(s.values[at] as number)}</span>))}
        </div>
      ) : null}
    </div>
  )
}

/** Цепочка: колонки слева направо со стрелками между ними. */
export function Chain({ cols }: { cols: { title: string; items: { b: string; s: string }[] }[] }) {
  return (
    <div className="b-an-chain">
      {cols.map((c, i) => (
        <div key={c.title} className="cwrap">
          <div className="c">
            <h4>{c.title}</h4>
            {c.items.map((it) => <div key={it.b} className="box"><b>{it.b}</b><span>{it.s}</span></div>)}
          </div>
          {i < cols.length - 1 ? <span className="ar" aria-hidden="true" /> : null}
        </div>
      ))}
    </div>
  )
}
