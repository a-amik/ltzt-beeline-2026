/**
 * Сводка дня поверх карты — вместо нижней полосы метрик.
 *
 * Полоса стояла на экране всю смену и отнимала у карты и списков высоту
 * ради чисел, на которые смотрят в двух случаях: после пересчёта — что
 * изменилось — и когда спрашивают итог. Поэтому в покое видна одна строка:
 * итог дня, бригады, не назначено, опоздания. Нажатие раскрывает все метрики
 * с базовым вариантом рядом. После нового плана сводка раскрывается сама
 * на несколько секунд — ровно чтобы увидеть, куда поехали числа, — и сворачивается,
 * если её не держат открытой. При «меньше движения» сама не раскрывается.
 */

import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { activePlan, useStore } from '../store'
import { num } from '../lib/ui'
import { IconChart, IconChevron } from '../lib/icons'
import MetricsBar from '../components/MetricsBar'
import './dispatch.css'

const PEEK_MS = 5000

export default function SummaryChip({ phone = false }: { phone?: boolean }) {
  const store = useStore()
  const plan = activePlan(store)
  const reduced = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [peek, setPeek] = useState(false)
  const lastPlan = useRef<string | null>(null)

  useEffect(() => {
    if (!plan) return
    const first = lastPlan.current === null
    if (lastPlan.current === plan.id) return
    lastPlan.current = plan.id
    if (first || reduced || phone) return
    setPeek(true)
    const timer = window.setTimeout(() => setPeek(false), PEEK_MS)
    return () => window.clearTimeout(timer)
  }, [plan, reduced, phone])

  if (!plan) return null
  const shown = open || peek
  const net = plan.economy?.net_rub ?? 0
  const m = plan.metrics
  return (
    <div className={`b-daysum${shown ? ' open' : ''}${phone ? ' phone' : ''}`}>
      {shown ? (
        <div className="b-daysum-full" onMouseEnter={() => peek && setOpen(true)}>
          <MetricsBar bare />
        </div>
      ) : null}
      <button type="button" className="b-daysum-line" aria-expanded={shown} onClick={() => { setPeek(false); setOpen(!shown) }}>
        <IconChart />
        <span>
          <b>{num(net)} ₽</b> итог
        </span>
        <span>
          <b>{m.engineers_used}</b> бригад
        </span>
        <span className={m.unassigned ? 'bad' : ''}>
          <b>{m.unassigned}</b> не назначено
        </span>
        {m.late ? (
          <span className="bad">
            <b>{m.late}</b> опозданий
          </span>
        ) : null}
        {m.changed_requests ? (
          <span className="info">
            <b>{m.changed_requests}</b> изменено
          </span>
        ) : null}
        <IconChevron className={shown ? 'up' : ''} />
      </button>
    </div>
  )
}
