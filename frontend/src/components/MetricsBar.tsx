/**
 * Полоса метрик. Число не подменяется, а доезжает от прежнего значения
 * к новому: читателю важно, куда оно поехало. Разница с базовым вариантом
 * п. 2.3 задания стоит под числом сразу: базовый считается следом за нашим
 * планом, а бригады и пробег — две обязательные метрики. «Окон под риском» —
 * ожидаемое число визитов с началом позже окна при случайном шуме дороги
 * и работы (risk.py).
 * Изменённое после события набрано синим — тем же цветом, каким событие
 * помечено на ленте и в списке.
 */

import { useEffect, useRef } from 'react'
import { animate, useReducedMotion } from 'motion/react'
import { Button } from '@gravity-ui/uikit'
import { activePlan, useStore } from '../store'
import { num } from '../lib/ui'
import { IconUsers } from '../lib/icons'
import type { Metrics } from '../types'

function AnimatedNumber({ value, digits = 0 }: { value: number; digits?: number }) {
  const reduced = useReducedMotion()
  const ref = useRef<HTMLSpanElement>(null)
  const previous = useRef(value)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const from = previous.current
    previous.current = value
    if (reduced || from === value) {
      node.textContent = num(value, digits)
      return
    }
    const controls = animate(from, value, {
      duration: 0.4,
      ease: 'easeOut',
      onUpdate: (current) => {
        node.textContent = num(current, digits)
      },
    })
    return () => controls.stop()
  }, [value, digits, reduced])

  return <span ref={ref}>{num(value, digits)}</span>
}

interface Cell {
  key: keyof Metrics
  label: string
  digits?: number
  /** Изменённое после события — синим: это след события, а не оценка. */
  event?: boolean
}

const CELLS: Cell[] = [
  { key: 'engineers_used', label: 'Бригад в работе' },
  { key: 'distance_km', label: 'Пробег, км', digits: 1 },
  { key: 'unassigned', label: 'Не назначено' },
  { key: 'late', label: 'Опозданий' },
  { key: 'risk_late', label: 'Окон под риском', digits: 1 },
  { key: 'changed_requests', label: 'Изменено после события', event: true },
]

interface Props {
  /** До 1100 px правая колонка уходит панелью, и кнопка к ней — сюда. */
  showPanelButton?: boolean
  bare?: boolean
}

const MONEY = [
  { key: 'net_rub', label: 'Итог дня, ₽', hint: 'ценность выполненного минус оклады, бонусы и дорога' },
  { key: 'bonus_rub', label: 'Бонусы, ₽', hint: 'за работу сверх нормы дня' },
] as const

export default function MetricsBar({ showPanelButton = false, bare = false }: Props) {
  const store = useStore()
  const plan = activePlan(store)
  const baseline = store.baselinePlan

  // Полоса одна строкой и уезжает вбок; колесо мыши крутит её вбок же,
  // иначе без тачпада хвост полосы не достать.
  const stripRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = stripRef.current
    if (!node || bare) return
    const onWheel = (event: WheelEvent) => {
      if (node.scrollWidth <= node.clientWidth || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
      node.scrollLeft += event.deltaY
      event.preventDefault()
    }
    const mark = () => {
      const left = node.scrollLeft > 1
      const right = node.scrollLeft + node.clientWidth < node.scrollWidth - 1
      const more = left && right ? 'both' : left ? 'left' : right ? 'right' : ''
      if (more) node.dataset.more = more
      else delete node.dataset.more
    }
    mark()
    const observer = new ResizeObserver(mark)
    observer.observe(node)
    for (const child of Array.from(node.children)) observer.observe(child)
    node.addEventListener('scroll', mark, { passive: true })
    node.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      observer.disconnect()
      node.removeEventListener('scroll', mark)
      node.removeEventListener('wheel', onWheel)
    }
  }, [bare, plan])

  const body = (
    <div className="b-metrics" ref={stripRef}>
      {CELLS.map((cell) => {
        const value = plan ? (plan.metrics[cell.key] ?? 0) : 0
        const base = baseline ? (baseline.metrics[cell.key] ?? null) : null
        const blue = Boolean(cell.event) && value > 0
        return (
          <div className="b-metric" key={cell.key}>
            <small>{cell.label}</small>
            <b style={blue ? { color: 'var(--b-info)' } : undefined}>
              {plan ? <AnimatedNumber value={value} digits={cell.digits ?? 0} /> : '—'}
            </b>
            <span>
              {base === null
                ? cell.event && plan && value > 0
                  ? `маршрутов из ${plan.routes.length}`
                  : ''
                : `у базового ${num(base, cell.digits ?? 0)}`}
            </span>
          </div>
        )
      })}
      {plan?.economy
        ? MONEY.map((cell) => (
            <div className="b-metric" key={cell.key} title={cell.hint}>
              <small>{cell.label}</small>
              <b>
                <AnimatedNumber value={plan.economy?.[cell.key] ?? 0} />
              </b>
              <span>
                {cell.key === 'net_rub' && plan.economy?.value_lost_rub
                  ? `упущено ${num(plan.economy.value_lost_rub)}`
                  : cell.key === 'bonus_rub'
                    ? `${plan.routes.filter((r) => (r.over_norm_min ?? 0) > 0).length} бригад сверх нормы`
                    : ''}
              </span>
            </div>
          ))
        : null}
      {/* «Вся Москва»: выезды в чужой участок — строка затрат дня; у набора одного участка её нет. */}
      {plan?.economy && store.dataset?.sectors?.length ? (
        <div className="b-metric" title="Цена въездов бригад в чужой участок — в затратах дня. Эксперт: нерациональная логистика">
          <small>Чужой участок, ₽</small>
          <b>
            <AnimatedNumber value={plan.economy.sector_rub ?? 0} />
          </b>
          <span>въездов {plan.economy.sector_entries ?? 0}</span>
        </div>
      ) : null}
    </div>
  )

  if (bare) return <div className="p-3">{body}</div>

  return (
    <footer className="b-bot">
      {body}
      <span className="ml-auto flex flex-none items-center gap-2">
        {store.offline ? (
          <span className="text-[var(--b-text-3)]">демо-данные</span>
        ) : null}
        {showPanelButton ? (
          <Button view="outlined" size="l" onClick={() => store.setPanelOpen(!store.panelOpen)}>
            <span className="flex items-center gap-1.5">
              <IconUsers />
              Бригады
            </span>
          </Button>
        ) : null}
      </span>
    </footer>
  )
}
