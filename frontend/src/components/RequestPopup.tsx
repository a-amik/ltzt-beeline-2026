/**
 * Карточка выбранной заявки поверх карты: кто едет, когда приедет и почему
 * именно он. Объяснение приходит готовым — клиент его не собирает,
 * а показывает по пунктам, вместе с тем, кто ещё мог поехать.
 *
 * Здесь же два действия диспетчера. У назначенной заявки — «Передать»:
 * ручная замена исполнителя, её эксперты заказчика назвали обязательной.
 * У неназначенной — предложения: кому и за какой бонус её можно отдать
 * сверх нормы дня, как агрегатор предлагает заказ водителю. Оба действия
 * идут одной ручкой сервера и приходят новым планом с разницей; отказ
 * приходит словами и показывается как есть.
 *
 * У аварии под адресом — её масштаб: сколько квартир задето и во сколько раз
 * от этого выросла цена её пропуска. Все аварии стоят выше подключений; масштаб
 * решает, какую из них брать первой, когда бригад на все не хватает.
 *
 * И здесь же события, которые случаются с этой заявкой: отмена, перенос окна,
 * клиента нет на месте. Их держит карточка, а не меню в шапке: заявку уже
 * выбрали, и искать её второй раз в выпадающем списке незачем. Событие
 * уходит в пачку, как и всякое другое (`DraftPanel`).
 */

import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, Select } from '@gravity-ui/uikit'
import { ApiError } from '../api'
import { runAssign } from '../data'
import { api } from '../api'
import { activePlan, useStore, type RequestPriority } from '../store'
import { assignmentIndex, knownRequests, unassignedIndex } from '../lib/plan'
import { num } from '../lib/ui'
import { IconAlert, IconCheck, IconClose } from '../lib/icons'

const MODE: Record<string, string> = {
  car: 'на машине',
  foot: 'пешком',
  bike: 'на велосипеде',
  transit: 'на общественном транспорте',
}

export default function RequestPopup() {
  const store = useStore()
  const plan = activePlan(store)
  const dataset = store.dataset
  const id = store.selectedRequestId
  const [target, setTarget] = useState<string | null>(null)

  const assigned = useMemo(() => assignmentIndex(plan), [plan])
  const missing = useMemo(() => unassignedIndex(plan), [plan])

  const assign = useMutation({
    mutationFn: ({ engineer, after }: { engineer: string; after: string | null }) => {
      const state = useStore.getState()
      if (!state.plan || !id) throw new Error('Нет плана')
      return runAssign(state.plan, id, engineer, after)
    },
    onSuccess: (next, variables) => {
      const state = useStore.getState()
      state.applyReplan(next)
      setTarget(null)
      const who = dataset?.engineers.find((e) => e.id === variables.engineer)
      state.notify(`Заявка ${id} передана${who ? ` бригаде ${who.name}` : ''}`)
    },
    onError: (error) => {
      const text = error instanceof ApiError ? error.message : 'Сервер не ответил — передать нельзя'
      useStore.getState().notify(text)
    },
  })

  const defer = useMutation({
    mutationFn: () => {
      const state = useStore.getState()
      if (!state.plan || !id) throw new Error('Нет плана')
      return api.defer(state.plan.id, id, undefined, state.plan.diff?.event.time)
    },
    onSuccess: (next) => {
      const state = useStore.getState()
      state.applyReplan(next)
      state.notify(`Заявка ${id} перенесена на следующий день`)
    },
    onError: (error) => {
      useStore.getState().notify(error instanceof ApiError ? error.message : 'Сервер не ответил')
    },
  })

  if (!id || !dataset) return null

  const request = knownRequests(dataset, store.plan).find((item) => item.id === id) ?? null
  if (!request) return null

  const names = new Map(dataset.engineers.map((engineer) => [engineer.id, engineer.name]))
  const assignment = assigned.get(id) ?? null
  const unassigned = missing.get(id) ?? null
  const explanation = plan?.explanations?.[id] ?? null
  const alternative = explanation?.alternatives?.find((item) => item.feasible) ?? explanation?.alternatives?.[0] ?? null
  const offer = plan?.offers?.find((item) => item.request_id === id) ?? null
  const canEdit = Boolean(store.plan) && !store.offline && store.view === 'after'
  const skilled = dataset.engineers.filter(
    (engineer) => engineer.skills.includes(request.skill) && engineer.id !== assignment?.engineerId,
  )

  return (
    <aside className="b-popcard absolute bottom-3 left-3 z-10 max-h-[70%] overflow-y-auto">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="b-pt truncate">
            {request.id} · {request.type_bk}
          </div>
          <div className={`b-pm truncate${assignment ? '' : ' bad'}`}>
            {assignment
              ? `${names.get(assignment.engineerId) ?? assignment.engineerId} · прибытие ${
                  assignment.stop.arrive
                }${assignment.stop.mode ? ` ${MODE[assignment.stop.mode]}` : ''} · окно ${
                  request.window_start
                }–${request.window_end}`
              : `Не назначена · окно ${request.window_start}–${request.window_end}`}
          </div>
        </div>
        <Button
          view="flat"
          size="s"
          onClick={() => store.selectRequest(null)}
          title="Закрыть карточку"
        >
          <IconClose />
        </Button>
      </div>

      <div className="b-pm -mt-2 truncate">{request.address}</div>
      {/* Масштаб аварии и её вес внутри ступени: строка приходит с сервера готовой (`Plan.weights`). */}
      {plan?.weights?.[request.id] ? <div className="b-weight">{plan.weights[request.id]}</div> : null}

      {unassigned ? (
        <ul className="b-why-ok">
          <li className="no">
            <IconAlert />
            <span>{unassigned.reason}</span>
          </li>
        </ul>
      ) : null}
      {canEdit ? (
        <div className="b-prio">
          <span>Приоритет</span>
          <Select
            size="s"
            value={[String((store.settings.requests as Record<string, { priority: string }> | undefined)?.[request.id]?.priority ?? 'normal')]}
            onUpdate={([value]) => store.setRequestPriority(request.id, value === 'normal' ? null : (value as RequestPriority))}
            options={[
              { value: 'normal', content: 'обычный' },
              { value: 'high', content: 'выше — раньше обычных' },
              { value: 'urgent', content: 'срочно — как авария' },
              { value: 'low', content: 'ниже — последней' },
            ]}
          />
        </div>
      ) : null}
      {canEdit ? (
        <div className="b-acts-row">
          <Button view="outlined" size="s" onClick={() => store.openDialog('reschedule')}>
            Другое окно
          </Button>
          {unassigned ? (
            <Button view="outlined" size="s" disabled={defer.isPending} onClick={() => defer.mutate()}>
              На завтра
            </Button>
          ) : (
            <Button view="outlined" size="s" onClick={() => store.openDialog('no_show')}>
              Клиента нет
            </Button>
          )}
          <Button view="flat-danger" size="s" onClick={() => store.openDialog('cancel')}>
            Отменить
          </Button>
        </div>
      ) : null}

      {offer && offer.candidates.length ? (
        <div className="b-offer">
          <div className="b-offer-h">
            Предложить сверх нормы
            {offer.coef > 1 ? <span> · дефицит окна ×{num(offer.coef, 2)}</span> : null}
          </div>
          {offer.candidates.map((candidate) => (
            <div key={candidate.engineer_id} className="b-offer-i">
              <span className="min-w-0 flex-1">
                <b>{names.get(candidate.engineer_id) ?? candidate.engineer_id}</b>
                <small>
                  приезд {candidate.arrive} · +{candidate.delta_travel_min} мин дороги
                  {candidate.bonus_rub ? ` · бонус ${num(candidate.bonus_rub)} ₽` : ' · в норме дня'}
                </small>
              </span>
              <Button
                view="outlined"
                size="s"
                disabled={!canEdit || assign.isPending}
                onClick={() => assign.mutate({ engineer: candidate.engineer_id, after: candidate.insert_after })}
              >
                Назначить
              </Button>
            </div>
          ))}
        </div>
      ) : unassigned && offer ? (
        <div className="b-alt">Взять сверх нормы некому: у готовых бригад заявка не встаёт в маршрут.</div>
      ) : null}

      {explanation ? (
        <ul className="b-why-ok">
          {explanation.checks.map((check, index) => (
            <li key={index} className={check.ok ? undefined : 'no'}>
              {check.ok ? <IconCheck /> : <IconAlert />}
              <span>{check.text}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {alternative ? <div className="b-alt">{alternative.text}</div> : null}

      {canEdit && skilled.length ? (
        <div className="b-reassign">
          <Select
            size="s"
            width="max"
            placeholder={assignment ? 'Передать бригаде…' : 'Назначить бригаде…'}
            value={target ? [target] : []}
            onUpdate={([value]) => setTarget(value ?? null)}
            options={skilled.map((engineer) => ({ value: engineer.id, content: engineer.name }))}
          />
          <Button
            view="action"
            size="s"
            disabled={!target || assign.isPending}
            onClick={() => target && assign.mutate({ engineer: target, after: null })}
          >
            {assign.isPending ? 'Передаём…' : assignment ? 'Передать' : 'Назначить'}
          </Button>
        </div>
      ) : null}
    </aside>
  )
}
