/**
 * Шторки карточки визита: как ехать, звонок клиенту, отчёт, проблема.
 * Шторка снизу — обычный приём курьерских приложений: палец уже там,
 * а маршрут и заявка остаются видны над ней.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Checkbox, TextArea } from '@gravity-ui/uikit'
import { num } from '../lib/ui'
import { IconBike, IconCall, IconCar, IconCarShare, IconClose, IconScooter, IconTransit, IconWalk } from '../lib/icons'
import type { RequestItem } from '../types'
import { crewApi, navLinks, type CallOut, type Report, type Way } from './crewApi'

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', key)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', key)
      document.body.style.overflow = overflow
    }
  }, [onClose])
  return (
    <div className="b-sheet-scrim" onClick={onClose}>
      <section className="b-sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header>
          <span className="b-sheet-grip" aria-hidden="true" />
          <h3>{title}</h3>
          <button type="button" className="b-sheet-x" onClick={onClose} aria-label="Закрыть">
            <IconClose />
          </button>
        </header>
        <div className="b-sheet-body">{children}</div>
      </section>
    </div>
  )
}

const WAY_ICON: Record<Way['kind'], (p: { className?: string }) => React.ReactNode> = {
  car: IconCar, carsharing: IconCarShare, transit: IconTransit, scooter: IconScooter, ebike: IconBike, foot: IconWalk,
}

export function WaysSheet({
  planId, engineerId, requestId, chosen, onChoose, onClose,
}: {
  planId: string
  engineerId: string
  requestId: string
  chosen: Way['kind'] | null
  onChoose: (kind: Way['kind']) => void
  onClose: () => void
}) {
  const ways = useQuery({
    queryKey: ['crew-ways', planId, engineerId, requestId],
    queryFn: () => crewApi.ways(planId, engineerId, requestId),
    staleTime: 60_000,
  })
  const data = ways.data
  const pick = data?.ways.find((w) => w.kind === chosen) ?? data?.ways[0]
  const links = data && pick ? navLinks(data.origin, data.target, pick.kind) : null
  return (
    <Sheet title="Как поеду" onClose={onClose}>
      {ways.isLoading ? <p className="b-crew-muted">Считаем способы…</p> : null}
      {ways.isError ? <p className="b-crew-muted">Не посчиталось: {String(ways.error)}</p> : null}
      {data ? (
        <>
          <p className="b-crew-muted">
            Выезд {data.depart}, по плану на месте в {data.plan_arrive}. Выбор остаётся у вас: план диспетчера от него не
            меняется.
          </p>
          <ul className="b-ways" role="radiogroup" aria-label="Способ поездки">
            {data.ways.map((way) => (
              <li key={way.kind}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={pick?.kind === way.kind}
                  className={`${pick?.kind === way.kind ? 'on' : ''}${way.late_min ? ' late' : ''}`}
                  onClick={() => onChoose(way.kind)}
                >
                  {WAY_ICON[way.kind]({})}
                  <span>
                    <b>{way.label}</b>
                    <em>
                      {way.walk_min ? `${way.walk_min} мин пешком до ${way.kind === 'carsharing' ? 'машины' : 'проката'} · ` : ''}
                      {way.note}
                    </em>
                  </span>
                  <span className="t">
                    <b>{way.minutes} мин</b>
                    <em>{way.late_min ? `опоздание ${way.late_min} мин` : `в ${way.arrive}`}</em>
                    <em>{way.price_rub ? `≈ ${num(way.price_rub)} ₽` : 'бесплатно'}</em>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {links ? (
            <div className="b-nav-links">
              <a href={links.yandex} target="_blank" rel="noreferrer">
                Открыть в Яндекс Картах
              </a>
              <a href={links.dgis} target="_blank" rel="noreferrer">
                Открыть в 2ГИС
              </a>
            </div>
          ) : null}
          <p className="b-crew-muted">
            Каршеринг, самокаты и велосипеды на карте — демо: у операторов нет открытых данных о расположении. Цены —
            оценка по публичным тарифам.
          </p>
        </>
      ) : null}
    </Sheet>
  )
}

export function CallSheet({ planId, engineerId, request, onClose }: {
  planId: string
  engineerId: string
  request: RequestItem
  onClose: () => void
}) {
  const [line, setLine] = useState<CallOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [seconds, setSeconds] = useState(0)
  const [ended, setEnded] = useState(false)
  useEffect(() => {
    crewApi.call(planId, engineerId, request.id).then(setLine, (e) => setError(String(e)))
  }, [planId, engineerId, request.id])
  useEffect(() => {
    if (!line || ended) return
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(timer)
  }, [line, ended])
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
  return (
    <Sheet title="Звонок клиенту" onClose={onClose}>
      <div className="b-call">
        <div className="b-call-face" aria-hidden="true">
          <IconCall />
        </div>
        <b>{request.address}</b>
        {error ? <p className="b-crew-muted">Номер не выдан: {error}</p> : null}
        {line ? (
          <>
            <p className="b-call-num">{line.proxy}</p>
            <p className="b-crew-muted">
              Клиент {line.client_masked} · номер действует до {line.valid_until}
            </p>
            <p className={ended ? 'b-crew-muted' : 'b-call-timer'} aria-live="polite">
              {ended ? `Звонок завершён, ${clock}` : `Идёт звонок · ${clock}`}
            </p>
            <p className="b-crew-muted">{line.note}. Это имитация: настоящего звонка нет.</p>
            {ended ? (
              <Button view="normal" size="xl" width="max" onClick={onClose}>
                Закрыть
              </Button>
            ) : (
              <Button view="outlined-danger" size="xl" width="max" onClick={() => setEnded(true)}>
                Завершить звонок
              </Button>
            )}
          </>
        ) : !error ? (
          <p className="b-crew-muted">Получаем подменный номер…</p>
        ) : null}
      </div>
    </Sheet>
  )
}

/** Чек-лист по типу заявки: что инженер подтверждает перед «Завершил». */
export const CHECKLIST: Record<string, string[]> = {
  Подключение: ['Кабель заведён и закреплён', 'Роутер настроен, Wi-Fi работает', 'Скорость замерена при клиенте', 'Клиент вошёл в личный кабинет'],
  'Локальная заявка': ['Неисправность найдена', 'Устранена, связь проверена', 'Клиенту объяснена причина'],
  'Глобальная проблема': ['Узел осмотрен', 'Авария устранена или передана дальше', 'Абоненты на узле проверены'],
  Дозаказ: ['Устройство выдано', 'Подключено и проверено', 'Клиент расписался за устройство'],
}

const KIT: Record<string, string> = { router: 'роутер', tv_box: 'ТВ-приставка', speaker: 'умная колонка' }

export function ReportSheet({ request, initial, onSave, onClose }: {
  request: RequestItem
  initial: Report | null
  onSave: (report: Report) => void
  onClose: () => void
}) {
  const items = CHECKLIST[request.type_bk] ?? ['Работа выполнена', 'Результат проверен при клиенте']
  const [done, setDone] = useState<string[]>(initial?.checklist ?? [])
  const [before, setBefore] = useState(initial?.photos_before ?? 0)
  const [after, setAfter] = useState(initial?.photos_after ?? 0)
  const [kit, setKit] = useState<string[]>(initial?.equipment ?? [])
  const [comment, setComment] = useState(initial?.comment ?? '')
  const [signed, setSigned] = useState(initial?.signed ?? false)
  const [thumbs, setThumbs] = useState<string[]>([])
  const complete = done.length === items.length && after > 0 && signed
  const toggle = (list: string[], item: string) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])
  const photo = (which: 'before' | 'after') => (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    if (!files.length) return
    if (which === 'before') setBefore((n) => n + files.length)
    else setAfter((n) => n + files.length)
    // Фото остаются в телефоне: для показа хватает счёта и миниатюр.
    setThumbs((t) => [...t, ...files.slice(0, 4).map((f) => URL.createObjectURL(f))])
  }
  return (
    <Sheet title="Отчёт по заявке" onClose={onClose}>
      <p className="b-crew-muted">
        {request.type_bk} · {request.address}
      </p>
      <fieldset className="b-report-block">
        <legend>Что сделано</legend>
        {items.map((item) => (
          <Checkbox key={item} size="l" checked={done.includes(item)} onUpdate={() => setDone((d) => toggle(d, item))} content={item} />
        ))}
      </fieldset>
      <fieldset className="b-report-block">
        <legend>Фото</legend>
        <div className="b-report-photos">
          <label className="b-photo-btn">
            <input type="file" accept="image/*" capture="environment" multiple onChange={photo('before')} />
            До работы{before ? ` · ${before}` : ''}
          </label>
          <label className="b-photo-btn">
            <input type="file" accept="image/*" capture="environment" multiple onChange={photo('after')} />
            После работы{after ? ` · ${after}` : ''}
          </label>
        </div>
        {thumbs.length ? (
          <div className="b-thumbs">
            {thumbs.map((src) => (
              <img key={src} src={src} alt="" />
            ))}
          </div>
        ) : null}
      </fieldset>
      {request.equipment?.length ? (
        <fieldset className="b-report-block">
          <legend>Выдано клиенту</legend>
          {request.equipment.map((item) => (
            <Checkbox key={item} size="l" checked={kit.includes(item)} onUpdate={() => setKit((k) => toggle(k, item))} content={KIT[item] ?? item} />
          ))}
        </fieldset>
      ) : null}
      <fieldset className="b-report-block">
        <legend>Подпись клиента</legend>
        <Signature signed={signed} onSign={setSigned} />
      </fieldset>
      <TextArea size="l" value={comment} onUpdate={setComment} placeholder="Комментарий для диспетчера, если нужно" minRows={2} />
      <p className="b-crew-muted">
        {complete ? 'Отчёт полный: можно завершать.' : 'Для завершения нужны все пункты, фото после работы и подпись клиента.'}
      </p>
      <Button
        view="action"
        size="xl"
        width="max"
        onClick={() =>
          onSave({ request_id: request.id, checklist: done, photos_before: before, photos_after: after, equipment: kit, signed, comment })
        }
      >
        Сохранить отчёт
      </Button>
    </Sheet>
  )
}

/** Подпись пальцем на холсте. Сама линия никуда не уходит: для показа хватает факта подписи. */
function Signature({ signed, onSign }: { signed: boolean; onSign: (value: boolean) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const strokes = useRef(0)
  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const scale = event.currentTarget.width / (box.width || 1)
    return [(event.clientX - box.left) * scale, (event.clientY - box.top) * scale] as const
  }
  const ink = useMemo(() => getComputedStyle(document.documentElement).getPropertyValue('--b-text').trim() || '#13171b', [])
  return (
    <div className="b-sign">
      <canvas
        ref={canvas}
        width={640}
        height={200}
        aria-label="Поле подписи клиента"
        onPointerDown={(event) => {
          const ctx = canvas.current?.getContext('2d')
          if (!ctx) return
          drawing.current = true
          event.currentTarget.setPointerCapture?.(event.pointerId)
          const [x, y] = point(event)
          ctx.strokeStyle = ink
          ctx.lineWidth = 4
          ctx.lineCap = 'round'
          ctx.beginPath()
          ctx.moveTo(x, y)
        }}
        onPointerMove={(event) => {
          if (!drawing.current) return
          const ctx = canvas.current?.getContext('2d')
          if (!ctx) return
          const [x, y] = point(event)
          ctx.lineTo(x, y)
          ctx.stroke()
        }}
        onPointerUp={() => {
          if (!drawing.current) return
          drawing.current = false
          strokes.current += 1
          onSign(true)
        }}
      />
      <div className="b-sign-row">
        <span className="b-crew-muted">{signed ? 'Подписано' : 'Клиент расписывается пальцем'}</span>
        <Button
          view="flat"
          size="s"
          onClick={() => {
            const ctx = canvas.current?.getContext('2d')
            ctx?.clearRect(0, 0, 640, 200)
            strokes.current = 0
            onSign(false)
          }}
        >
          Стереть
        </Button>
        <Button view="flat" size="s" onClick={() => onSign(true)}>
          Подписано на бумаге
        </Button>
      </div>
    </div>
  )
}

/** «Задерживаюсь»: четыре шага из настройки `delay_step_min`; от порога день пересчитывается сам. */
export function DelaySheet({ step, autoFrom, onSend, onClose }: {
  step: number
  autoFrom: number | null
  onSend: (minutes: number) => void
  onClose: () => void
}) {
  return (
    <Sheet title="Задерживаюсь" onClose={onClose}>
      <p className="b-crew-muted">
        {autoFrom === null
          ? 'Диспетчер получит сигнал и решит, что делать с вашими визитами.'
          : `От ${autoFrom} мин хвост вашего дня пересчитается сам: следующие клиенты получат новое время, а что не успеваете — уйдёт другим бригадам.`}
      </p>
      <div className="b-delay">
        {[1, 2, 3, 4].map((n) => (
          <button key={n} type="button" onClick={() => onSend(step * n)}>
            <b>{step * n}</b> мин
          </button>
        ))}
      </div>
    </Sheet>
  )
}

export const PROBLEMS = [
  'Клиента нет на месте',
  'Не пускают: охрана, домофон',
  'Нет доступа к щитку',
  'Не хватает оборудования',
  'Нужна вторая бригада',
  'Опасно работать',
]

export function ProblemSheet({ onSend, onClose }: { onSend: (text: string, sos: boolean) => void; onClose: () => void }) {
  const [other, setOther] = useState('')
  return (
    <Sheet title="Проблема на заявке" onClose={onClose}>
      <ul className="b-problems">
        {PROBLEMS.map((text) => (
          <li key={text}>
            <button type="button" onClick={() => onSend(text, false)}>
              {text}
            </button>
          </li>
        ))}
      </ul>
      <TextArea size="l" value={other} onUpdate={setOther} placeholder="Другое — опишите словами" minRows={2} />
      <Button view="normal" size="l" width="max" disabled={!other.trim()} onClick={() => onSend(other.trim(), false)}>
        Отправить диспетчеру
      </Button>
      <Button view="outlined-danger" size="xl" width="max" onClick={() => onSend('SOS: нужна срочная помощь', true)}>
        SOS — угроза жизни или здоровью
      </Button>
    </Sheet>
  )
}
