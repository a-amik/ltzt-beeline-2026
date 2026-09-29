/**
 * Шторка деталей — заявка или бригада, по образцу карточки места в картах:
 * шапка со значком вида и метками состояния, ряд круглых действий, строки
 * со значками и дальше одной лентой — приоритет, передача, обоснование.
 *
 * На широком экране шторка стоит справа поверх карты (`placement="map"`),
 * на телефоне — нижней шторкой поверх всего экрана (`placement="phone"`):
 * из списка в заявку «проваливаются», стрелка возвращает назад. Заявка
 * главнее бригады: из маршрута бригады открывают визит, и «назад» ведёт
 * обратно к бригаде.
 *
 * Действия те же, что были у прежней карточки поверх карты, и идут
 * теми же путями: передача и назначение — одной ручкой сервера новым планом,
 * события заявки — в пачку через окна событий.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, HelpMark, Label, SegmentedRadioGroup, TextInput } from '@gravity-ui/uikit'
import { ApiError, api } from '../api'
import { runAssign } from '../data'
import { activePlan, useStore, type RequestPriority } from '../store'
import { assignmentIndex, knownRequests, unassignedIndex } from '../lib/plan'
import { colorIndex, colorVar } from '../lib/colors'
import { num } from '../lib/ui'
import {
  IconAlert, IconArrowRight, IconBox, IconCalendar, IconCancel, IconCheck, IconChevron, IconClock, IconClose, IconPin,
  IconUserOff, IconUsers, IconWrench,
} from '../lib/icons'
import { KIND_LABEL, kindOf } from '../lib/kinds'
import { KIND_ICON } from './RequestCard'
import CrewCard from '../dispatch/CrewCard'
import { SKILL_NAME } from '../fixtures/planner'
import './DetailSheet.css'

const MODE: Record<string, string> = { car: 'на машине', foot: 'пешком', bike: 'на велосипеде', transit: 'на транспорте' }
const EQUIPMENT: Record<string, string> = { router: 'роутер', tv_box: 'ТВ-приставка', speaker: 'умная колонка' }
const RISK_THRESHOLD = 0.2
const PRIORITY: { value: string; content: string }[] = [
  { value: 'low', content: 'Ниже' },
  { value: 'normal', content: 'Обычный' },
  { value: 'high', content: 'Выше' },
  { value: 'urgent', content: 'Срочно' },
]

export default function DetailSheet({ placement }: { placement: 'map' | 'phone' }) {
  const requestId = useStore((s) => s.selectedRequestId)
  const crewView = useStore((s) => s.crewView)
  const crewSheet = useStore((s) => s.crewSheet)
  const dataset = useStore((s) => s.dataset)
  // Бригада, открытая из заявки: смотрят её здесь же и возвращаются стрелкой,
  // левая колонка при этом не переключается на «Инженеров».
  const [peek, setPeek] = useState<string | null>(null)
  useEffect(() => setPeek(null), [requestId])
  // На телефоне бригада открывается шторкой, только пока её не свернули к маршруту в списке.
  const crew = crewView && (placement === 'map' || crewSheet) ? crewView : null
  if (!dataset || (!requestId && !crew)) return null

  const body = requestId && peek ? (
    <CrewDetail id={peek} onBack={() => setPeek(null)} />
  ) : requestId ? (
    <RequestDetail id={requestId} back={Boolean(crewView)} onCrew={setPeek} />
  ) : (
    <CrewDetail id={crew!} />
  )
  if (placement === 'map') return <aside className="b-ds b-ds-map" aria-label="Детали">{body}</aside>
  const close = () => {
    const s = useStore.getState()
    if (s.selectedRequestId) s.selectRequest(null)
    else s.setCrewSheet(false)
  }
  return (
    <div className="b-ds-scrim" onClick={close}>
      <aside className="b-ds b-ds-phone" role="dialog" aria-label="Детали" onClick={(e) => e.stopPropagation()}>
        <div className="b-grab" />
        {body}
      </aside>
    </div>
  )
}

function CrewDetail({ id, onBack }: { id: string; onBack?: () => void }) {
  const store = useStore()
  const dataset = store.dataset!
  const engineer = dataset.engineers.find((e) => e.id === id)
  const order = dataset.engineers.map((e) => e.id)
  if (!engineer) return null
  return (
    <>
      <header className="b-ds-head" style={{ ['--c' as string]: colorVar(colorIndex(id, order)) }}>
        {onBack ? (
          <Button view="flat" size="m" onClick={onBack} title="Назад к заявке" aria-label="Назад к заявке" className="b-ds-back">
            <IconChevron />
          </Button>
        ) : null}
        <div className="b-ds-title">
          <h2>
            <span className="b-ds-crewdot" aria-hidden="true" />
            {engineer.name}
          </h2>
          <p>Бригада · {engineer.skills.map((k) => SKILL_NAME[k] ?? k).join(', ')}</p>
        </div>
        <Button view="flat" size="m" onClick={() => (onBack ? store.selectRequest(null) : store.openCrew(null))} title="Закрыть" aria-label="Закрыть">
          <IconClose />
        </Button>
      </header>
      <div className="b-ds-body b-scroll">
        <CrewCard engineerId={id} embedded />
      </div>
    </>
  )
}

function RequestDetail({ id, back, onCrew }: { id: string; back: boolean; onCrew: (engineerId: string) => void }) {
  const store = useStore()
  const plan = activePlan(store)
  const dataset = store.dataset!
  // Кому передать: поле с подсказками — набирают фамилию, выбирают из списка под полем.
  const [target, setTarget] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef<HTMLInputElement>(null)
  // Итог передачи — здесь же, под полем: уведомление карты стоит под шторкой.
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const transferRef = useRef<HTMLElement>(null)

  const assigned = useMemo(() => assignmentIndex(plan), [plan])
  const missing = useMemo(() => unassignedIndex(plan), [plan])

  const assign = useMutation({
    mutationFn: ({ engineer, after }: { engineer: string; after: string | null }) => {
      const state = useStore.getState()
      if (!state.plan) throw new Error('Нет плана')
      return runAssign(state.plan, id, engineer, after)
    },
    onSuccess: (next, variables) => {
      const state = useStore.getState()
      state.applyReplan(next)
      setTarget(null)
      setQuery('')
      const who = dataset.engineers.find((e) => e.id === variables.engineer)
      const text = `Заявка передана${who ? ` бригаде ${who.name}` : ''}`
      setResult({ ok: true, text })
      state.notify(`${text}: ${id}`)
    },
    onError: (error) => {
      setResult({ ok: false, text: error instanceof ApiError ? error.message : 'Сервер не ответил — передать нельзя' })
    },
  })
  const defer = useMutation({
    mutationFn: () => {
      const state = useStore.getState()
      if (!state.plan) throw new Error('Нет плана')
      return api.defer(state.plan.id, id, undefined, state.plan.diff?.event.time)
    },
    onSuccess: (next) => {
      const state = useStore.getState()
      state.applyReplan(next)
      state.notify(`Заявка ${id} перенесена на следующий день`)
    },
    onError: (error) => useStore.getState().notify(error instanceof ApiError ? error.message : 'Сервер не ответил'),
  })

  const request = knownRequests(dataset, store.plan).find((item) => item.id === id) ?? null
  if (!request) return null

  const order = dataset.engineers.map((e) => e.id)
  const names = new Map(dataset.engineers.map((e) => [e.id, e.name]))
  const assignment = assigned.get(id) ?? null
  const unassigned = missing.get(id) ?? null
  const deferred = plan?.deferred?.find((d) => d.request_id === id) ?? null
  const explanation = plan?.explanations?.[id] ?? null
  const alternative = explanation?.alternatives?.find((a) => a.feasible) ?? explanation?.alternatives?.[0] ?? null
  const offer = plan?.offers?.find((o) => o.request_id === id) ?? null
  const canEdit = Boolean(store.plan) && !store.offline && store.view === 'after'
  const kind = kindOf(request)
  const stop = assignment?.stop ?? null
  const late = stop && stop.late_min > 0 ? stop.late_min : 0
  const risk = stop?.late_risk ?? 0
  const frozen = Boolean(stop && plan?.diff?.frozen_requests?.includes(id))
  const manual = (store.settings.requests as Record<string, { priority: string }> | undefined)?.[id]?.priority ?? 'normal'
  const kit = (request.equipment ?? []).map((item) => EQUIPMENT[item] ?? item)

  // Кому передать: сначала те, у кого заявка встаёт в маршрут (предложение или
  // выполнимая альтернатива), с приездом и дорогой; остальные — по имени.
  const candidates = new Map((offer?.candidates ?? []).map((c) => [c.engineer_id, c]))
  const alts = new Map((explanation?.alternatives ?? []).map((a) => [a.engineer_id, a]))
  const skilled = dataset.engineers
    .filter((e) => e.skills.includes(request.skill) && e.id !== assignment?.engineerId)
    .map((e) => {
      const c = candidates.get(e.id)
      const a = alts.get(e.id)
      const meta = c
        ? `приезд ${c.arrive} · +${c.delta_travel_min} мин дороги${c.bonus_rub ? ` · бонус ${num(c.bonus_rub)} ₽` : ''}`
        : a
          ? (a.text.startsWith(e.name) ? a.text.slice(e.name.length).replace(/^[:,]?\s*/, '') : a.text)
          : 'без расчёта'
      return { id: e.id, name: e.name, meta, rank: c ? 0 : a?.feasible ? 1 : a ? 2 : 3, after: c?.insert_after ?? null }
    })
    .sort((x, y) => x.rank - y.rank || x.name.localeCompare(y.name, 'ru'))
  const chosen = skilled.find((s) => s.id === target) ?? null
  const needle = query.trim().toLowerCase()
  const hints = (needle ? skilled.filter((s) => s.name.toLowerCase().includes(needle)) : skilled).slice(0, 8)
  const pick = (s: (typeof skilled)[number]) => {
    setTarget(s.id)
    setQuery(s.name)
    setResult(null)
    setPickerOpen(false)
  }

  const close = () => store.selectRequest(null)
  const toTransfer = () => {
    transferRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    pickerRef.current?.focus()
    setPickerOpen(true)
  }
  // Комментарии диспетчера к заявке: из истории плана и из пачки, что ещё не пересчитана.
  const comments = [...(plan?.history ?? []), ...store.drafts]
    .filter((e, i, all) => 'request_id' in e && e.request_id === id && e.comment && all.findIndex((x) => x.id === e.id) === i)
    .map((e) => ({ id: e.id, time: e.time, type: e.type, text: e.comment as string }))

  return (
    <>
      <header className="b-ds-head">
        {back ? (
          <Button view="flat" size="m" onClick={close} title="Назад к бригаде" aria-label="Назад к бригаде" className="b-ds-back">
            <IconChevron />
          </Button>
        ) : null}
        <div className="b-ds-title">
          <span className={`b-kind ${kind}`}>
            {KIND_ICON[kind]}
            {KIND_LABEL[kind]}
          </span>
          <h2>{request.type_hd && request.type_hd !== KIND_LABEL[kind] ? request.type_hd : request.type_bk}</h2>
          <p>№&nbsp;{request.id}</p>
        </div>
        <Button view="flat" size="m" onClick={close} title="Закрыть" aria-label="Закрыть">
          <IconClose />
        </Button>
      </header>

      <div className="b-ds-body b-scroll">
        <div className="b-ds-chips">
          {deferred ? (
            <Label theme="normal">на завтра</Label>
          ) : assignment ? (
            <Label theme="success">назначена</Label>
          ) : (
            <Label theme="danger">не назначена</Label>
          )}
          {frozen ? <Label theme="info">начата</Label> : null}
          {late ? <Label theme="danger">опоздание {late} мин</Label> : risk >= RISK_THRESHOLD ? <Label theme="warning">риск {Math.round(risk * 100)} %</Label> : null}
          {manual !== 'normal' ? (
            <Label theme={manual === 'urgent' ? 'danger' : manual === 'high' ? 'info' : 'normal'}>
              приоритет: {PRIORITY.find((p) => p.value === manual)?.content.toLowerCase()}
            </Label>
          ) : null}
        </div>

        {canEdit ? (
          <div className="b-ds-acts" role="group" aria-label="Действия с заявкой">
            {skilled.length ? (
              <button type="button" className="main" onClick={toTransfer}>
                <i><IconUsers /></i>
                <span>{assignment ? 'Передать' : 'Назначить'}</span>
              </button>
            ) : null}
            <button type="button" onClick={() => store.openDialog('reschedule')}>
              <i><IconCalendar /></i>
              <span>Другое окно</span>
            </button>
            {unassigned ? (
              <button type="button" disabled={defer.isPending} onClick={() => defer.mutate()}>
                <i><IconArrowRight /></i>
                <span>На завтра</span>
              </button>
            ) : (
              <button type="button" onClick={() => store.openDialog('no_show')}>
                <i><IconUserOff /></i>
                <span>Клиента нет</span>
              </button>
            )}
            <button type="button" className="danger" onClick={() => store.openDialog('cancel')}>
              <i><IconCancel /></i>
              <span>Отменить</span>
            </button>
          </div>
        ) : null}

        <ul className="b-ds-rows">
          {assignment ? (
            <li>
              <button
                type="button"
                className="b-ds-row link"
                style={{ ['--c' as string]: colorVar(colorIndex(assignment.engineerId, order)) }}
                onClick={() => onCrew(assignment.engineerId)}
                title="Открыть бригаду"
              >
                <span className="b-ds-crewdot" aria-hidden="true" />
                <span className="b-ds-rt">
                  <b>{names.get(assignment.engineerId) ?? assignment.engineerId}</b>
                  <small>
                    {stop!.seq}-й визит · приезд {stop!.arrive}
                    {stop!.mode ? ` ${MODE[stop!.mode] ?? ''}` : ''}
                  </small>
                </span>
                <IconChevron className="b-ds-go" />
              </button>
            </li>
          ) : null}
          <li className={`b-ds-row${late || risk >= RISK_THRESHOLD ? ' warn' : ''}`}>
            <IconClock />
            <span className="b-ds-rt">
              <b>
                Окно {request.window_start}–{request.window_end}
              </b>
              <small>
                {late
                  ? `Опоздание на ${late} мин`
                  : risk >= RISK_THRESHOLD && stop?.arrive_p90
                    ? `Риск срыва ${Math.round(risk * 100)} % · приезд до ${stop.arrive_p90} в 9 случаях из 10`
                    : stop
                      ? `Приезд ${stop.arrive}, работа ${stop.start}–${stop.end}`
                      : `Работа ${request.duration_min} мин`}
              </small>
            </span>
          </li>
          <li className="b-ds-row">
            <IconPin />
            <span className="b-ds-rt">
              <b>{request.address}</b>
              {request.district ? <small>{request.district}</small> : null}
            </span>
          </li>
          {kit.length ? (
            <li className="b-ds-row">
              <IconBox />
              <span className="b-ds-rt">
                <b>Взять: {kit.join(', ')}</b>
              </span>
            </li>
          ) : null}
          <li className="b-ds-row">
            <IconWrench />
            <span className="b-ds-rt">
              <b>
                {request.type_bk} · {request.duration_min} мин
              </b>
              <small>Навык: {SKILL_NAME[request.skill] ?? request.skill}</small>
            </span>
          </li>
          {plan?.weights?.[id] ? (
            <li className="b-ds-row">
              <IconAlert />
              <span className="b-ds-rt">
                <b>{plan.weights[id]}</b>
              </span>
            </li>
          ) : null}
          {deferred ? (
            <li className="b-ds-row warn">
              <IconCalendar />
              <span className="b-ds-rt">
                <b>{deferred.reason}</b>
              </span>
            </li>
          ) : unassigned ? (
            <li className="b-ds-row warn">
              <IconAlert />
              <span className="b-ds-rt">
                <b>{unassigned.reason}</b>
              </span>
            </li>
          ) : null}
        </ul>

        {canEdit ? (
          <section className="b-ds-sec">
            <h3>
              Приоритет
              <HelpMark aria-label="Что значит приоритет" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
                Ниже — заявка встаёт последней. Выше — раньше обычных. Срочно — наравне с аварией. Пересчёт плана — после изменения.
              </HelpMark>
            </h3>
            <SegmentedRadioGroup
              size="m"
              width="max"
              value={manual}
              onUpdate={(value) => store.setRequestPriority(id, value === 'normal' ? null : (value as RequestPriority))}
              options={PRIORITY}
            />
          </section>
        ) : null}

        {canEdit && skilled.length ? (
          <section className="b-ds-sec" ref={transferRef}>
            <h3>{assignment ? 'Передать бригаде' : 'Назначить бригаде'}</h3>
            <div className="b-ds-transfer">
              <div className="b-ds-combo">
                <TextInput
                  size="m"
                  controlRef={pickerRef}
                  value={query}
                  placeholder="Фамилия бригады"
                  hasClear
                  onUpdate={(value) => {
                    setQuery(value)
                    setTarget(null)
                    setResult(null)
                    setPickerOpen(true)
                  }}
                  onFocus={() => setPickerOpen(true)}
                  onBlur={() => window.setTimeout(() => setPickerOpen(false), 150)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && hints[0]) pick(hints[0])
                    if (event.key === 'Escape') setPickerOpen(false)
                  }}
                  controlProps={{ role: 'combobox', 'aria-expanded': pickerOpen, 'aria-autocomplete': 'list' }}
                />
                {pickerOpen && !chosen ? (
                  <ul className="b-ds-hints" role="listbox">
                    {hints.map((s) => (
                      <li key={s.id} role="option" aria-selected={false} className={s.rank <= 1 ? '' : 'muted'} onMouseDown={() => pick(s)}>
                        <b>{s.name}</b>
                        <small>{s.meta}</small>
                      </li>
                    ))}
                    {!hints.length ? <li className="empty">Такой бригады нет</li> : null}
                  </ul>
                ) : null}
              </div>
              <Button
                view="action"
                size="m"
                disabled={!chosen || assign.isPending}
                onClick={() => chosen && assign.mutate({ engineer: chosen.id, after: chosen.after })}
              >
                {assign.isPending ? 'Передаём…' : assignment ? 'Передать' : 'Назначить'}
              </Button>
            </div>
            {result ? (
              <p className={`b-ds-result${result.ok ? ' ok' : ''}`} role="status">
                {result.ok ? <IconCheck /> : <IconAlert />}
                <span>{result.text}</span>
              </p>
            ) : chosen ? (
              <p className="b-ds-note">{chosen.meta}</p>
            ) : null}
          </section>
        ) : null}

        {offer && offer.candidates.length && !assignment ? (
          <section className="b-ds-sec">
            <h3>
              Предложить сверх нормы
              {offer.coef > 1 ? <span className="b-ds-h-note"> · дефицит окна ×{num(offer.coef, 2)}</span> : null}
            </h3>
            <ul className="b-ds-offers">
              {offer.candidates.map((c) => (
                <li key={c.engineer_id}>
                  <span className="b-ds-rt">
                    <b>{names.get(c.engineer_id) ?? c.engineer_id}</b>
                    <small>
                      приезд {c.arrive} · +{c.delta_travel_min} мин дороги
                      {c.bonus_rub ? ` · бонус ${num(c.bonus_rub)} ₽` : ' · в норме дня'}
                    </small>
                  </span>
                  <Button
                    view="outlined"
                    size="s"
                    disabled={!canEdit || assign.isPending}
                    onClick={() => assign.mutate({ engineer: c.engineer_id, after: c.insert_after })}
                  >
                    Назначить
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {comments.length ? (
          <section className="b-ds-sec">
            <h3>Комментарии</h3>
            <ul className="b-ds-notes">
              {comments.map((c) => (
                <li key={c.id}>
                  <time>{c.time}</time>
                  <span>{c.text}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {explanation ? (
          <section className="b-ds-sec">
            <h3>Почему {assignment ? names.get(assignment.engineerId) ?? 'эта бригада' : 'так'}</h3>
            <ul className="b-why-ok">
              {explanation.checks.map((check, index) => (
                <li key={index} className={check.ok ? undefined : 'no'}>
                  {check.ok ? <IconCheck /> : <IconAlert />}
                  <span>{check.text}</span>
                </li>
              ))}
            </ul>
            {alternative ? <p className="b-ds-note">{alternative.text}</p> : null}
          </section>
        ) : null}
      </div>
    </>
  )
}
