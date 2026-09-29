/**
 * Строка заявки. Ни рамки, ни фона: разделитель волосяной, выбранная залита
 * жёлтым. Состояние, общее для всей группы («не назначена», «изменилась»),
 * в строку не пишется — его несёт подпись группы; в строке остаётся то,
 * что у неё своё: причина отказа, замок начатого визита, опоздание.
 */

import { Label } from '@gravity-ui/uikit'
import type { Assignment } from '../lib/plan'
import type { Deferred, RequestItem, Unassigned } from '../types'
import { colorVar } from '../lib/colors'
import { IconAlert, IconBolt, IconBox, IconCalendar, IconPlug, IconWrench } from '../lib/icons'
import { KIND_LABEL, kindOf, type Kind } from '../lib/kinds'

// Вид заявки читается значком раньше слов: авария — молния, ремонт — ключ,
// подключение — вилка, дозаказ — коробка. Подтип заказчика — серым рядом.
const KIND_ICON: Record<Kind, React.ReactNode> = {
  accident: <IconBolt />,
  repair: <IconWrench />,
  connect: <IconPlug />,
  upsell: <IconBox />,
}

const EQUIPMENT: Record<string, string> = { router: 'роутер', tv_box: 'ТВ-приставка', speaker: 'умная колонка' }
/** Порог, с которого риск срыва окна выносится на карточку; тот же, что в допущениях. */
const RISK_THRESHOLD = 0.2

interface Props {
  request: RequestItem
  assignment: Assignment | null
  unassigned: Unassigned | null
  deferred?: Deferred | null
  engineerName: string | null
  colorIndex: number
  selected: boolean
  frozen: boolean
  /** Ручной приоритет диспетчера: срочно, выше, ниже. */
  manual?: string | null
  onSelect: () => void
}

const MANUAL: Record<string, { text: string; theme: 'danger' | 'info' | 'normal' }> = {
  urgent: { text: 'срочно', theme: 'danger' },
  high: { text: 'выше', theme: 'info' },
  low: { text: 'ниже', theme: 'normal' },
}

export default function RequestCard({
  request,
  assignment,
  unassigned,
  deferred = null,
  engineerName,
  colorIndex,
  selected,
  frozen,
  manual = null,
  onSelect,
}: Props) {
  const late = assignment && assignment.stop.late_min > 0 ? assignment.stop.late_min : 0
  const risk = assignment?.stop.late_risk ?? 0
  const kit = (request.equipment ?? []).map((item) => EQUIPMENT[item] ?? item)
  const kind = kindOf(request)

  return (
    <div
      className="b-list-i"
      role="option"
      tabIndex={0}
      aria-selected={selected}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="t">
        <s>{request.id}</s>
        <span className={`b-kind ${kind}`} title={`${request.type_bk} · ${request.type_hd}`}>
          {KIND_ICON[kind]}
          {KIND_LABEL[kind]}
        </span>
        {request.type_hd && request.type_hd !== KIND_LABEL[kind] ? <em className="b-kind-sub">{request.type_hd}</em> : null}
        {manual && MANUAL[manual] ? (
          <Label size="xs" theme={MANUAL[manual].theme}>
            {MANUAL[manual].text}
          </Label>
        ) : null}
      </div>
      <div className="w">
        {request.window_start}–{request.window_end}
      </div>
      <div className="a">{request.address}</div>
      {kit.length ? <div className="a muted">взять: {kit.join(', ')}</div> : null}

      {assignment ? (
        <>
          <div className="e" style={{ ['--c' as string]: colorVar(colorIndex) }}>
            <i />
            {engineerName ?? assignment.engineerId}
            {request.priority === 'urgent' ? (
              <Label size="xs" theme="warning">
                срочная
              </Label>
            ) : null}
          </div>
          <div className="x">
            {frozen ? (
              <Label size="xs">начата</Label>
            ) : (
              `${assignment.stop.seq}-й визит · ${assignment.stop.arrive}`
            )}
          </div>
        </>
      ) : null}

      {deferred ? (
        <div className="r muted">
          <IconCalendar />
          <span>
            {deferred.reason}
            {deferred.since !== '00:00' ? ` · решено в ${deferred.since}` : ''}
          </span>
        </div>
      ) : unassigned ? (
        <div className="r">
          <IconAlert />
          <span>{unassigned.reason}</span>
        </div>
      ) : null}

      {late > 0 ? (
        <div className="r">
          <IconAlert />
          <span>Опоздание на {late} мин</span>
        </div>
      ) : risk >= RISK_THRESHOLD ? (
        <div className="r">
          <IconAlert />
          <span>
            Риск срыва окна {Math.round(risk * 100)} %
            {assignment?.stop.arrive_p90 ? ` · приезд до ${assignment.stop.arrive_p90} в 9 случаях из 10` : ''}
          </span>
        </div>
      ) : null}
    </div>
  )
}
