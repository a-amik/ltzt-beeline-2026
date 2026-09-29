/**
 * Пачка событий и варианты ответа на неё. Событие диспетчер не «пересчитывает»,
 * а сохраняет: оно встаёт в пачку и на карту, и сервер тут же в фоне считает,
 * что с ним делать, — сохранить порядок визитов, перестроить день или отложить
 * новые заявки на завтра. План дня меняется только тем вариантом, который
 * приняли; до того любой можно посмотреть на карте вместо плана.
 *
 * Считается пачка целиком и заново на каждое изменение, с паузой: вбрасывают
 * обычно несколько заявок подряд, и считать варианты на каждую по отдельности
 * значило бы показывать ответы на вопрос, который уже сменился. Запросов
 * два: быстрые варианты (сохранить порядок, на завтра — доли секунды)
 * приходят и показываются сразу, решатель для «перестроить день» идёт следом.
 * Второй запрос не отправляется, пока не вернулся первый, и новый расчёт
 * не начинается, пока не кончился идущий: иначе пять тычков подряд заводили
 * пять решателей разом, и все пятеро делили один процессор.
 */

import { useEffect, useRef, useState } from 'react'
import { Button } from '@gravity-ui/uikit'
import { api, ApiError } from '../api'
import { useStore } from '../store'
import { draftLabel } from '../lib/drafts'
import { num } from '../lib/ui'
import { IconClose } from '../lib/icons'
import '../manager/manager.css'
import type { ReplanVariant } from '../types'
import Crunch, { type Phase } from './Crunch'

const PAUSE_MS = 700

const QUICK_PHASES: Phase[] = [
  { at: 0, text: 'Замораживаем начатое и обещанное: визиты в горизонте блокировки не двигаются' },
  { at: 0.35, text: 'Вставляем новое в свободное время бригад, порядок визитов прежний' },
  { at: 0.7, text: 'Считаем, что будет, если новое отложить на завтра' },
]

const FULL_PHASES: Phase[] = [
  { at: 0, text: 'Замораживаем начатое и обещанное, остаток дня отдаём решателю' },
  { at: 0.15, text: 'Четыре стратегии поиска идут параллельно по всем бригадам' },
  { at: 0.55, text: 'Ищем план лучше: больше выполненных заявок, потом выше итог дня' },
  { at: 0.85, text: 'Сравниваем с планом до событий: кого сдвинули и на сколько' },
]

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

function money(value: number): string {
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${num(Math.abs(value))} ₽`
}

export default function DraftPanel() {
  const store = useStore()
  const drafts = store.drafts
  const planId = store.plan?.id ?? null
  const [error, setError] = useState<string | null>(null)
  const [adopting, setAdopting] = useState(false)
  const [slowPending, setSlowPending] = useState(false)
  const setCrunching = useStore((s) => s.setCrunching)
  const dataset = store.dataset
  const facts = dataset
    ? `${drafts.length} ${plural(drafts.length, 'событие', 'события', 'событий')} · ${dataset.engineers.length} бригад · ${dataset.requests.length} заявок`
    : undefined
  // Решатель работает ровно отведённое время; ремонт по событию — доли секунды.
  const limitS = Number((store.rules.options as { time_limit_s?: number } | undefined)?.time_limit_s ?? 4)
  // Волна заявок: граница отрезка из настройки `batch_window_min` — так же считает сервер (`wave.py`).
  const windowMin = Number((store.rules.options as { batch_window_min?: number } | undefined)?.batch_window_min ?? 15)
  const firstMin = drafts.length
    ? Math.min(...drafts.map((d) => Number(d.time.slice(0, 2)) * 60 + Number(d.time.slice(3, 5))))
    : null
  const dueMin = firstMin !== null && windowMin > 0 ? Math.ceil(firstMin / windowMin) * windowMin : null
  const waveDue =
    dueMin !== null ? `${String(Math.floor(dueMin / 60)).padStart(2, '0')}:${String(dueMin % 60).padStart(2, '0')}` : null
  const quickMs = 400 + drafts.length * 150
  const fullMs = (limitS + 0.6) * 1000 + drafts.length * 200
  const ticket = useRef(0)
  const busy = useRef<Promise<void> | null>(null)

  useEffect(() => {
    if (!drafts.length || !planId) return
    const mine = ++ticket.current
    setError(null)
    const timer = window.setTimeout(() => {
      const job = async () => {
        // Пока считался прежний запрос, пачка могла смениться ещё раз.
        if (mine !== ticket.current) return
        setCrunching(true)
        try {
          const quick = await api.variants(planId, drafts, ['keep', 'tomorrow'])
          if (mine !== ticket.current) return
          useStore.getState().setVariants(quick.variants)
          useStore.getState().setPreview(quick.variants[0]?.key ?? null)
          setSlowPending(true)
          const slow = await api.variants(planId, drafts, ['full'])
          if (mine !== ticket.current) return
          useStore.getState().setVariants([...quick.variants.slice(0, 1), ...slow.variants, ...quick.variants.slice(1)])
        } catch (failure) {
          if (mine !== ticket.current) return
          setError(failure instanceof ApiError ? failure.message : 'Сервер не ответил: варианты считает он')
        } finally {
          if (mine === ticket.current) {
            setSlowPending(false)
            setCrunching(false)
          }
        }
      }
      busy.current = (busy.current ?? Promise.resolve()).then(job, job)
    }, PAUSE_MS)
    return () => window.clearTimeout(timer)
  }, [drafts, planId, setCrunching])

  if (!drafts.length) return null

  const variants = store.variants

  const adopt = async (variant: ReplanVariant) => {
    setAdopting(true)
    try {
      const plan = await api.adopt(variant.plan.id)
      const state = useStore.getState()
      state.clearDrafts()
      state.applyReplan(plan)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : String(failure))
    } finally {
      setAdopting(false)
    }
  }

  return (
    <aside className="b-drafts" aria-label="События и варианты пересчёта">
      <div className="b-drafts-h">
        <b>События · {drafts.length}</b>
        <Button view="flat" size="s" onClick={() => store.clearDrafts()}>
          Сбросить
        </Button>
      </div>

      {waveDue ? (
        <p className="b-drafts-wave">
          Волна заявок: обычные события пересчитываются пачкой в {waveDue}; авария идёт сразу. Отрезок — в настройках.
        </p>
      ) : null}
      <ul className="b-drafts-list">
        {drafts.map((event) => (
          <li key={event.id}>
            <time>{event.time}</time>
            <span>{draftLabel(event)}</span>
            <button type="button" title="Убрать из пачки" onClick={() => store.removeDraft(event.id)}>
              <IconClose />
            </button>
          </li>
        ))}
      </ul>

      {error ? <p className="b-drafts-err">{error}</p> : null}

      {!variants && !error ? (
        <Crunch key={`q${drafts.length}`} title="Примеряем события к дню" estimateMs={quickMs} phases={QUICK_PHASES} facts={facts} />
      ) : null}

      {variants ? (
        <div className="b-variants" role="radiogroup" aria-label="Варианты пересчёта">
          {slowPending && !variants.some((item) => item.key === 'full') ? (
            <div className="b-variant wait">
              <Crunch key={`f${drafts.length}`} title="Перестроить день — считаем" estimateMs={fullMs} phases={FULL_PHASES} facts={facts} />
            </div>
          ) : null}
          {variants.map((variant) => {
            const on = variant.key === store.preview
            const twin = variant.same_as ? variants.find((item) => item.key === variant.same_as) : null
            const fresh = variant.placed + variant.offered + variant.deferred
            return (
              <div key={variant.key} className={`b-variant${on ? ' on' : ''}`}>
                <button type="button" className="b-variant-pick" role="radio" aria-checked={on} onClick={() => store.setPreview(variant.key)}>
                  <b>{variant.title}</b>
                  <small>{twin ? `Тот же план, что «${twin.title}»` : variant.hint}</small>
                  <span className="b-variant-n">
                    {fresh ? <em>сегодня {variant.placed + variant.offered} из {fresh}</em> : null}
                    <em>сдвинуто {variant.changed}</em>
                    <em className={variant.net_delta_rub < 0 ? 'bad' : undefined}>итог {money(variant.net_delta_rub)}</em>
                  </span>
                </button>
                {on ? (
                  <>
                    {variant.requests.length ? (
                      <ul className="b-variant-r">
                        {variant.requests.map((row) => (
                          <li key={row.request_id} className={row.code}>
                            <b>{row.request_id}</b> {row.outcome}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    <Button view="action" size="m" width="max" loading={adopting} onClick={() => adopt(variant)}>
                      Принять
                    </Button>
                  </>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
    </aside>
  )
}
