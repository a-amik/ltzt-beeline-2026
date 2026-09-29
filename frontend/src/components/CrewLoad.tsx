/**
 * «Загрузка бригад» над лентами инженеров — у кого есть время, а кто перегружен.
 * Одна полоса на всех: доли бригад свободных, в норме и сверх нормы, а под
 * ней три числа. Число — и отбор: щелчок оставляет в списке только эту
 * часть бригад, повторный снимает отбор.
 *
 * Свободна — без маршрута или занята работой и дорогой меньше половины
 * смены; сверх нормы — план вышел за её норму (`over_norm_min` маршрута);
 * остальные — в норме. Порог в половину смены — порог показа, а не правило
 * расчёта: план от него не меняется.
 */

import type { Engineer, Route } from '../types'
import { toMin } from '../lib/time'

export type LoadKind = 'free' | 'norm' | 'over'

const FREE_SHARE = 0.5

const TEXT: Record<LoadKind, string> = { free: 'Свободны', norm: 'В норме', over: 'Сверх нормы' }
const TIP: Record<LoadKind, string> = {
  free: 'Без маршрута или в работе и дороге меньше половины смены',
  norm: 'Загружены в пределах нормы',
  over: 'План вышел за норму бригады: сверхурочные и бонус',
}

/** Доля смены, занятая работой и дорогой. */
export function loadShare(engineer: Engineer, route: Route | null): number {
  if (!route) return 0
  const shift = toMin(engineer.shift_end) - toMin(engineer.shift_start)
  return shift > 0 ? (route.work_min + route.travel_min) / shift : 0
}

export function loadKind(engineer: Engineer, route: Route | null): LoadKind {
  if ((route?.over_norm_min ?? 0) > 0) return 'over'
  return loadShare(engineer, route) < FREE_SHARE ? 'free' : 'norm'
}

interface Props {
  engineers: Engineer[]
  routes: Map<string, Route>
  value: LoadKind | null
  onChange: (kind: LoadKind | null) => void
}

export default function CrewLoad({ engineers, routes, value, onChange }: Props) {
  const counts: Record<LoadKind, number> = { free: 0, norm: 0, over: 0 }
  let busy = 0
  let shift = 0
  for (const engineer of engineers) {
    const route = routes.get(engineer.id) ?? null
    counts[loadKind(engineer, route)] += 1
    busy += route ? route.work_min + route.travel_min : 0
    shift += toMin(engineer.shift_end) - toMin(engineer.shift_start)
  }
  const avg = shift ? Math.round((busy / shift) * 100) : 0
  const kinds: LoadKind[] = ['free', 'norm', 'over']

  return (
    <div className="b-cl">
      <div className="b-dw-h">
        <span>Загрузка бригад</span>
        <b title="Работа и дорога всех бригад от суммы их смен">{avg} %</b>
      </div>
      <span className="b-cl-bar" aria-hidden="true">
        {kinds.map((k) => (counts[k] ? <i key={k} className={k} style={{ flexGrow: counts[k] }} /> : null))}
      </span>
      <div className="b-cl-keys" role="radiogroup" aria-label="Загрузка">
        {kinds.map((k) => (
          <button
            type="button"
            role="radio"
            aria-checked={value === k}
            key={k}
            className={`${k}${value === k ? ' on' : value ? ' off' : ''}`}
            disabled={!counts[k]}
            onClick={() => onChange(value === k ? null : k)}
            title={TIP[k]}
          >
            <i />
            <span>{TEXT[k]}</span>
            <b>{counts[k]}</b>
          </button>
        ))}
      </div>
    </div>
  )
}
