/**
 * «Как доехать» — путь общественным транспортом до ближайшей заявки
 * по расписанию 2ГИС. Показывается бригаде, которая едет на транспорте:
 * пешком до остановки, на чём, с какой остановки, сколько ждать,
 * где пересадка, и ближайшие отправления.
 *
 * Путь строится по нажатию, а не заранее: каждый построенный маршрут
 * 2ГИС оплачивается. Ответ сервер держит в памяти, и повторное открытие
 * бесплатно. Расписание берётся на ближайший такой же день недели, что
 * и день плана, — об этом сказано под вариантами.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { api } from '../api'
import type { TransitLeg, TransitOption } from './transitTypes'
import './CrewTransit.css'

const WEEKDAY = ['воскресенье', 'понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу']

function transfers(n: number): string {
  if (!n) return 'без пересадок'
  const tail = n % 10 === 1 && n % 100 !== 11 ? 'пересадка' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'пересадки' : 'пересадок'
  return `${n} ${tail}`
}

function legText(leg: TransitLeg): { head: string; sub: string } {
  // Место у пешего участка — остановка, где из транспорта вышли, а не куда идут.
  if (leg.kind === 'walk') return { head: `Пешком ${leg.minutes} мин`, sub: leg.place ? `от «${leg.place}»` : '' }
  if (leg.kind === 'transfer') return { head: `Пересадка, ${leg.minutes} мин`, sub: leg.place }
  const lines = leg.lines.length ? ` ${leg.lines.join(', ')}` : ''
  const wait = leg.wait_min ? ` · ждать ${leg.wait_min} мин` : ''
  const where = leg.place ? `от «${leg.place}»` : ''
  const hint = leg.hint ? ` · ${leg.hint}` : ''
  return {
    head: `${leg.vehicle[0]?.toUpperCase() ?? ''}${leg.vehicle.slice(1)}${lines}`,
    sub: `${where}${hint}${wait} · в пути ${leg.minutes} мин`.replace(/^ · /, ''),
  }
}

function Option({ option, open }: { option: TransitOption; open: boolean }) {
  return (
    <details className="b-transit-option" open={open}>
      <summary>
        <b>{option.total_min} мин</b>
        <span>
          прибытие {option.arrive} · {transfers(option.transfers)}
          {option.walk ? ` · ${option.walk}` : ''}
        </span>
      </summary>
      {option.departures.length ? (
        <p className="b-transit-deps">
          Отправления: {option.departures.map((time) => <time key={time}>{time}</time>)}
        </p>
      ) : null}
      <ol className="b-transit-legs">
        {option.legs.map((leg, i) => {
          const text = legText(leg)
          return (
            <li key={i} className={leg.kind}>
              <b>{text.head}</b>
              {text.sub ? <span>{text.sub}</span> : null}
            </li>
          )
        })}
      </ol>
    </details>
  )
}

export default function CrewTransit({ planId, engineerId, requestId }: { planId: string; engineerId: string; requestId: string }) {
  const [asked, setAsked] = useState(false)
  const trip = useQuery({
    queryKey: ['crew-transit', planId, engineerId, requestId],
    queryFn: () => api.crewTransit(planId, engineerId, requestId),
    enabled: asked,
    staleTime: Infinity,
    retry: false,
  })

  if (!asked) {
    return (
      <Button view="outlined" size="l" width="max" onClick={() => setAsked(true)}>
        Как доехать на транспорте
      </Button>
    )
  }
  if (trip.isLoading) return <p className="b-crew-muted">Спрашиваем расписание у 2ГИС…</p>
  if (trip.isError) return <p className="b-crew-muted">Путь не построился: {String(trip.error)}</p>
  const data = trip.data
  if (!data) return null
  const day = new Date(`${data.date}T12:00:00`)
  const best = data.options.length ? data.options.reduce((a, b) => (b.total_min < a.total_min ? b : a)) : null
  const toMin = (clock: string) => Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3, 5))
  const late = best && data.plan_arrive ? toMin(best.arrive) - toMin(data.plan_arrive) : 0
  return (
    <div className="b-transit">
      <h4>
        Как доехать · выезд {data.depart}, {data.origin === 'офис' || data.origin === 'дом' ? `из ${data.origin === 'дом' ? 'дома' : 'офиса'}` : `от ${data.origin}`}
      </h4>
      {data.note ? <p className="b-crew-muted">{data.note}</p> : null}
      {late > 5 ? (
        <p className="b-transit-late">
          По расписанию приезд {best!.arrive}, а по плану {data.plan_arrive}: позже на {late} мин. Скажите диспетчеру
          до выезда.
        </p>
      ) : null}
      {data.options.map((option, i) => (
        <Option key={i} option={option} open={i === 0} />
      ))}
      {data.options.length ? (
        <p className="b-crew-muted">
          Расписание 2ГИС на {WEEKDAY[day.getDay()]} {day.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}: тот же день недели, что и день плана.
        </p>
      ) : null}
    </div>
  )
}
