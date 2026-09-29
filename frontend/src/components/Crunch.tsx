/**
 * Ход расчёта, который видно. Решатель молчит несколько секунд, и молчание
 * читается зависанием; поэтому у ожидания есть прогноз времени, полоса,
 * идущая по нему, и подписи о том, что делается сейчас. Прогноз — не замер
 * сервера, а оценка от настроек: решатель работает ровно столько, сколько
 * ему отведено (`time_limit_s`), плюс ремонт по событию. Полоса до конца
 * не доходит, пока ответ не пришёл: обещать «готово» вправе только сервер.
 */

import { useEffect, useState } from 'react'

export interface Phase {
  at: number
  text: string
}

interface Props {
  title: string
  estimateMs: number
  phases: Phase[]
  facts?: string
}

export default function Crunch({ title, estimateMs, phases, facts }: Props) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const started = performance.now()
    const timer = window.setInterval(() => setElapsed(performance.now() - started), 100)
    return () => window.clearInterval(timer)
  }, [])

  const share = Math.min(1, elapsed / estimateMs)
  // Полоса замедляется к концу и встаёт на 96 %: остаток закрывает ответ.
  const width = Math.min(0.96, 1 - (1 - share) ** 2 * 0.96 - (share >= 1 ? 0 : 0.04)) * 100
  const left = Math.max(0, Math.ceil((estimateMs - elapsed) / 1000))
  const phase = [...phases].reverse().find((item) => item.at <= share) ?? phases[0]

  return (
    <div className="b-crunch" role="status" aria-live="polite">
      <div className="b-crunch-h">
        <b>{title}</b>
        <span>{share < 1 ? `ещё ~${left} с` : 'дольше обычного, ждём ответ'}</span>
      </div>
      <div className="b-crunch-bar">
        <i style={{ width: `${width}%` }} />
      </div>
      <small key={phase.text}>{phase.text}</small>
      {facts ? <em>{facts}</em> : null}
    </div>
  )
}
