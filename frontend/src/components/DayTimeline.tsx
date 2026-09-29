/**
 * Лента дня одной бригады: полоса с долями от 10:00 до 22:00. Сторонний
 * Gantt сюда не берётся — колонка одна, и правила у неё свои: полоска визита
 * краской инженера, тонкая полоска дороги, обводка у переставленного визита,
 * отвес по времени события.
 */

import { DAY_END, DAY_SPAN, DAY_START, toMin } from '../lib/time'
import { colorVar } from '../lib/colors'
import type { RequestItem, Route } from '../types'

interface Props {
  route: Route | null
  requests: Map<string, RequestItem>
  colorIndex: number
  frozen: Set<string>
  changedRequests: Set<string>
  /** Время события: отвес, левее которого ничего не переставляли. */
  eventMin: number | null
  dimmed: boolean
}

const MODE_NAME: Record<string, string> = {
  car: 'машина',
  foot: 'пешком',
  bike: 'велосипед',
  transit: 'общественный транспорт',
}

/** Доля ленты по минуте дня; за края не выходим. */
function share(min: number): number {
  return Math.min(100, Math.max(0, ((min - DAY_START) / DAY_SPAN) * 100))
}

/** С какой доли прогонов визит считается рискованным — тот же порог, что у сервера (`risk.threshold`). */
const RISKY = 0.2

export default function DayTimeline({
  route,
  requests,
  colorIndex,
  frozen,
  changedRequests,
  eventMin,
  dimmed,
}: Props) {
  const color = colorVar(colorIndex)
  const stops = route?.stops ?? []

  return (
    <div
      className={`lane${stops.length === 0 ? ' idle' : ''}`}
      style={{ ['--c' as string]: color, opacity: dimmed ? 0.35 : 1 }}
    >
      {stops.map((stop) => {
        const request = requests.get(stop.request_id)
        if (!request) return null
        const drive = [share(toMin(stop.depart_prev)), share(toMin(stop.arrive))]
        const work = [share(toMin(stop.start)), share(toMin(stop.end))]
        const isChanged = changedRequests.has(stop.request_id)
        const isFrozen = frozen.has(stop.request_id)
        return (
          <span key={stop.request_id} className="contents">
            <span
              className="drv"
              style={{ left: `${drive[0]}%`, width: `${Math.max(0.4, drive[1] - drive[0])}%` }}
              title={`Дорога${stop.mode ? ` — ${MODE_NAME[stop.mode]}` : ''}, ${stop.travel_min} мин, ${stop.travel_km} км`}
            />
            <span
              className={isChanged ? 'chg' : undefined}
              style={{ left: `${work[0]}%`, width: `${Math.max(0.8, work[1] - work[0])}%` }}
              title={`${request.id} · ${request.type_bk} · ${stop.start}–${stop.end}${
                isFrozen ? ' · визит начат до события' : ''
              }${stop.late_min > 0 ? ` · опоздание ${stop.late_min} мин` : ''}${
                (stop.late_risk ?? 0) >= RISKY ? ` · риск срыва окна ${Math.round((stop.late_risk ?? 0) * 100)} %` : ''
              }`}
            />
            {(stop.late_risk ?? 0) >= RISKY && stop.late_min === 0 ? (
              <span
                className="risk"
                style={{ left: `${work[0]}%` }}
                title={`Риск срыва окна ${Math.round((stop.late_risk ?? 0) * 100)} %${
                  stop.arrive_p90 ? `: в 9 случаях из 10 приезд до ${stop.arrive_p90}` : ''
                }`}
              />
            ) : null}
            {stop.late_min > 0 ? (
              <span
                className="late"
                style={{ left: `${work[1]}%`, width: '1.5%' }}
                title={`Опоздание ${stop.late_min} мин`}
              />
            ) : null}
          </span>
        )
      })}

      {route?.break_start && route.break_end ? (
        <span
          className="brk"
          style={{
            left: `${share(toMin(route.break_start))}%`,
            width: `${Math.max(0.8, share(toMin(route.break_end)) - share(toMin(route.break_start)))}%`,
          }}
          title={`Обед ${route.break_start}–${route.break_end}`}
        />
      ) : null}

      {eventMin !== null && eventMin > DAY_START && eventMin < DAY_END ? (
        <span className="now" style={{ left: `${share(eventMin)}%` }} aria-hidden="true" />
      ) : null}
    </div>
  )
}
