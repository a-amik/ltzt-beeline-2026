/**
 * «Окна дня» над списком заявок — где будет плотно. Столбик на двухчасовое
 * окно: высота — сколько заявок в нём, цвет — чем они кончаются по плану:
 * в порядке, под риском срыва, без бригады или с опозданием, на завтра.
 * Суточные окна (аварии «весь день») стоят отдельным столбиком в конце.
 *
 * Столбик — и цифра, и выбор: щелчок оставляет в списке заявки этого окна,
 * повторный снимает отбор. Приём тот же, что у окон в «Нагрузке».
 */

import type { Assignment } from '../lib/plan'
import { DAY_END, DAY_START, toMin } from '../lib/time'
import type { RequestItem } from '../types'

/** Риск срыва окна, с которого визит считается «под риском»; тот же порог, что у карточки заявки. */
const RISK_THRESHOLD = 0.2
const SLOT_MIN = 120
const WHOLE_DAY = 'day'

/** Окно заявки → столбик: начало окна, округлённое до двух часов; длинные окна — «весь день». */
export function slotOf(item: RequestItem): string {
  const start = toMin(item.window_start)
  const end = toMin(item.window_end)
  if (end - start > 2 * SLOT_MIN || start < DAY_START || start >= DAY_END) return WHOLE_DAY
  return String(DAY_START + Math.floor((start - DAY_START) / SLOT_MIN) * SLOT_MIN)
}

function label(slot: string): string {
  if (slot === WHOLE_DAY) return 'день'
  const start = Number(slot) / 60
  return `${start}–${start + SLOT_MIN / 60}`
}

interface Props {
  requests: RequestItem[]
  assigned: Map<string, Assignment>
  deferred: Map<string, unknown>
  value: string | null
  onChange: (slot: string | null) => void
}

type Kind = 'ok' | 'risk' | 'bad' | 'later'

const KIND_TEXT: Record<Kind, string> = {
  ok: 'в порядке',
  risk: 'под риском',
  bad: 'без бригады или с опозданием',
  later: 'на завтра',
}

export default function DayWindows({ requests, assigned, deferred, value, onChange }: Props) {
  const slots: string[] = []
  for (let t = DAY_START; t < DAY_END; t += SLOT_MIN) slots.push(String(t))
  const counts = new Map<string, Record<Kind, number>>()
  for (const slot of [...slots, WHOLE_DAY]) counts.set(slot, { ok: 0, risk: 0, bad: 0, later: 0 })
  for (const item of requests) {
    const stop = assigned.get(item.id)?.stop
    const kind: Kind = stop
      ? stop.late_min > 0
        ? 'bad'
        : (stop.late_risk ?? 0) >= RISK_THRESHOLD
          ? 'risk'
          : 'ok'
      : deferred.has(item.id)
        ? 'later'
        : 'bad'
    counts.get(slotOf(item))![kind] += 1
  }
  const shown = counts.get(WHOLE_DAY)!.ok + counts.get(WHOLE_DAY)!.risk + counts.get(WHOLE_DAY)!.bad + counts.get(WHOLE_DAY)!.later
    ? [...slots, WHOLE_DAY]
    : slots
  const total = (c: Record<Kind, number>) => c.ok + c.risk + c.bad + c.later
  const peak = Math.max(1, ...shown.map((slot) => total(counts.get(slot)!)))

  return (
    <div className="b-dw">
      <div className="b-dw-h">
        <span>Окна дня</span>
        {value ? (
          <button type="button" onClick={() => onChange(null)}>
            Все окна
          </button>
        ) : null}
      </div>
      <div className="b-dw-cols" role="radiogroup" aria-label="Окно дня" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
        {shown.map((slot) => {
          const c = counts.get(slot)!
          const n = total(c)
          const tip = [
            `${slot === WHOLE_DAY ? 'Весь день' : label(slot)}: ${n} заявок`,
            ...(['ok', 'risk', 'bad', 'later'] as Kind[]).filter((k) => c[k]).map((k) => `${KIND_TEXT[k]} ${c[k]}`),
          ].join(' · ')
          return (
            <button
              type="button"
              role="radio"
              aria-checked={value === slot}
              key={slot}
              className={value === slot ? 'on' : value ? 'off' : undefined}
              disabled={!n}
              onClick={() => onChange(value === slot ? null : slot)}
              title={tip}
            >
              <b className={c.bad ? 'bad' : undefined}>{n}</b>
              <span className="bar" aria-hidden="true">
                <span style={{ height: `${(n / peak) * 100}%` }}>
                  {(['bad', 'risk', 'later', 'ok'] as Kind[]).map((k) =>
                    c[k] ? <i key={k} className={k} style={{ flexGrow: c[k] }} /> : null,
                  )}
                </span>
              </span>
              <small>{label(slot)}</small>
            </button>
          )
        })}
      </div>
    </div>
  )
}
