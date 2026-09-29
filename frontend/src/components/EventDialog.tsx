/**
 * События дня. Форма одна на семь случаев, потому что и событие одно:
 * что-то произошло в такой-то час, и план надо пересчитать с этой минуты.
 * Координаты новой заявки берутся тычком по карте или адресом из набора —
 * подсказчика адресов у прототипа нет и не требуется.
 *
 * У новой заявки дня есть правило назначения: предложить бригадам или отдать
 * лучшей директивно. Авария по умолчанию идёт директивно, остальное —
 * предложением: так у бригады остаётся право выбора там, где сервис
 * не горит, и не остаётся там, где горит.
 *
 * Диалог ничего не пересчитывает: событие сохраняется в пачку и встаёт
 * на карту, а варианты ответа на пачку сервер считает в фоне (`DraftPanel`).
 * Новых заявок можно набрать несколько подряд — «Сохранить и ещё» оставляет
 * диалог открытым с тем же временем звонка.
 *
 * Сценарий набора подставляется начальным состоянием: диалог заводится
 * заново на каждое открытие (`key` у вызывающего), и досылать значения
 * эффектом не приходится. Поля и кнопки — Gravity UI: своих полей ввода
 * и своих выпадающих списков в приложении нет.
 */

import { useState } from 'react'
import { Button, SegmentedRadioGroup, Select, TextArea, TextInput } from '@gravity-ui/uikit'
import { activePlan, useStore, type DialogKind } from '../store'
import { assignmentIndex, knownRequests } from '../lib/plan'
import { nextRequestId } from '../lib/drafts'
import type { EventPolicy, NoShowNote, PlanEvent, RequestItem, Skill } from '../types'

export const TITLE: Record<DialogKind, string> = {
  urgent: 'Срочная заявка',
  new_request: 'Новая заявка в течение дня',
  cancel: 'Отмена заявки',
  no_show: 'Клиента нет на месте',
  reschedule: 'Перенос окна клиента',
  delay: 'Бригада задерживается',
  engineer_off: 'Инженер недоступен',
}

const HINT: Record<DialogKind, string> = {
  urgent: 'Авария встаёт как можно раньше; визиты, начатые до её времени, не переставляются.',
  new_request:
    'Заявка либо встаёт сегодня, либо явно уходит на завтра с причиной. Обещанные визиты в горизонте блокировки не двигаются.',
  cancel: 'Освободившееся время получают неназначенные и новые заявки; обещанные визиты остаются на своих местах.',
  no_show: 'Бригада ждёт положенное время и едет дальше; заявка уходит на завтра, клиентская служба перезванивает.',
  reschedule: 'Заявка примеряется в новое окно у той же бригады, потом у других; не встаёт — остаётся не назначенной.',
  delay: 'Хвост маршрута бригады сдвигается; визит, который перестал помещаться, уходит другой бригаде или в предложения.',
  engineer_off: 'Начатый визит бригада доводит до конца; остальные её заявки перераспределяются.',
}

const SKILLS: { value: Skill; content: string }[] = [
  { value: 'emergency', content: 'Аварийные работы' },
  { value: 'connect', content: 'Подключение и дозаказы' },
  { value: 'local', content: 'Локальные работы' },
]

export const NO_SHOW_NOTES: { value: NoShowNote; content: string }[] = [
  { value: 'absent', content: 'Клиента нет дома' },
  { value: 'unreachable', content: 'Не отвечает на звонки' },
  { value: 'waiting', content: 'Ждали положенное время' },
  { value: 'partial', content: 'Работа выполнена частично' },
  { value: 'cancelled_on_site', content: 'Отказ от работ на месте' },
  { value: 'client_moved', content: 'Перенос по просьбе клиента' },
  { value: 'we_moved', content: 'Перенос по решению диспетчера' },
]

interface Props {
  kind: DialogKind
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[12px] text-[var(--b-text-2)]">
      {label}
      {children}
    </label>
  )
}

export default function EventDialog({ kind }: Props) {
  const store = useStore()
  const dataset = store.dataset
  const plan = activePlan(store)
  const scenario = dataset?.events.find((item) => item.type === kind) ?? null
  const preset = scenario && (scenario.type === 'urgent' || scenario.type === 'new_request') ? scenario.request : null
  const isNew = kind === 'urgent' || kind === 'new_request'

  const [time, setTime] = useState(scenario?.time ?? store.clock)
  const [saved, setSaved] = useState(0)
  const [address, setAddress] = useState(preset?.address ?? '')
  const [latInput, setLatInput] = useState<string | null>(null)
  const [lonInput, setLonInput] = useState<string | null>(null)
  const [duration, setDuration] = useState(String(preset?.duration_min ?? (kind === 'new_request' ? 90 : 60)))
  const [windowStart, setWindowStart] = useState(preset?.window_start ?? (kind === 'new_request' ? '14:00' : '15:00'))
  const [windowEnd, setWindowEnd] = useState(preset?.window_end ?? (kind === 'new_request' ? '18:00' : '17:00'))
  const [skill, setSkill] = useState<Skill>(preset?.skill ?? (kind === 'new_request' ? 'connect' : 'emergency'))
  const [policy, setPolicy] = useState<EventPolicy>(kind === 'urgent' ? 'direct' : 'offer')
  const [note, setNote] = useState<NoShowNote>('absent')
  const [delay, setDelay] = useState('30')
  // Комментарий диспетчера едет с событием: его видно в шторке заявки и в истории плана.
  const [comment, setComment] = useState('')
  const memo = comment.trim() || undefined
  const [requestId, setRequestId] = useState(
    store.selectedRequestId ??
      (scenario && 'request_id' in scenario ? scenario.request_id : (plan?.routes[0]?.stops[0]?.request_id ?? '')),
  )
  const [engineerId, setEngineerId] = useState(
    store.selectedEngineerId ??
      (scenario?.type === 'engineer_off' ? scenario.engineer_id : (plan?.routes[0]?.engineer_id ?? '')),
  )

  if (!dataset) return null

  // Тычок по карте побеждает сценарий, но не набранное руками.
  const lat = latInput ?? (store.pickedPoint?.lat.toFixed(4) ?? String(preset?.lat ?? ''))
  const lon = lonInput ?? (store.pickedPoint?.lon.toFixed(4) ?? String(preset?.lon ?? ''))

  const assigned = assignmentIndex(plan)
  const known = knownRequests(dataset, plan)
  const hidden = store.picking
  const picked = known.find((item) => item.id === requestId) ?? null
  const pickedStop = assigned.get(requestId)?.stop ?? null

  const stamp = () => `e-${Date.now()}`

  const onSubmit = (event: PlanEvent) => store.addDraft(event)

  const submit = (more = false) => {
    if (!more) store.openDialog(null)
    if (isNew) {
      const request: RequestItem = {
        id: nextRequestId(kind === 'urgent' ? 'u' : 'n'),
        type_bk: kind === 'urgent' ? 'Авария' : SKILLS.find((item) => item.value === skill)?.content ?? 'Заявка',
        type_hd: kind === 'urgent' ? 'Срочный выезд' : 'Заявка день в день',
        address: address || 'Точка на карте',
        district: '—',
        lat: Number(lat),
        lon: Number(lon),
        geo_quality: 'house',
        duration_min: Number(duration),
        window_start: windowStart,
        window_end: windowEnd,
        priority: kind === 'urgent' ? 'urgent' : 'normal',
        skill,
        transport: null,
      }
      onSubmit({ id: stamp(), type: kind, time, request, policy, comment: memo })
      if (more) {
        setSaved((n) => n + 1)
        setAddress('')
        setLatInput(null)
        setLonInput(null)
        store.setPickedPoint(null)
      }
      return
    }
    if (kind === 'cancel') {
      onSubmit({ id: stamp(), type: 'cancel', time, request_id: requestId, comment: memo })
      return
    }
    if (kind === 'no_show') {
      onSubmit({ id: stamp(), type: 'no_show', time: pickedStop?.arrive ?? time, request_id: requestId, note, comment: memo })
      return
    }
    if (kind === 'reschedule') {
      onSubmit({ id: stamp(), type: 'reschedule', time, request_id: requestId, window_start: windowStart, window_end: windowEnd, comment: memo })
      return
    }
    if (kind === 'delay') {
      onSubmit({ id: stamp(), type: 'delay', time, engineer_id: engineerId, delay_min: Number(delay), comment: memo })
      return
    }
    onSubmit({ id: stamp(), type: 'engineer_off', time, engineer_id: engineerId, comment: memo })
  }

  const valid = isNew
    ? Boolean(lat && lon && Number(duration) > 0)
    : kind === 'cancel' || kind === 'no_show' || kind === 'reschedule'
      ? Boolean(requestId)
      : kind === 'delay'
        ? Boolean(engineerId && Number(delay) > 0)
        : Boolean(engineerId)

  const requestOptions = [...assigned.keys()].map((id) => ({
    value: id,
    content: `${id} · ${known.find((item) => item.id === id)?.address ?? 'заявка'}`,
  }))

  return (
    <div
      className={`b-dialog-wrap fixed inset-0 z-50 flex items-center justify-center p-4 transition-opacity ${
        hidden ? 'pointer-events-none opacity-0' : ''
      }`}
    >
      <div className="absolute inset-0 bg-black/30" onClick={() => store.openDialog(null)} aria-hidden="true" />
      <div
        role="dialog"
        aria-label={TITLE[kind]}
        className="b-dialog relative w-[440px] max-w-[94vw] rounded-[var(--b-r-l)] bg-[var(--b-float)] p-4"
        style={{ boxShadow: 'var(--b-shadow-float)' }}
      >
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-[16px] font-semibold leading-6">{TITLE[kind]}</h2>
          <Button view="flat" size="s" onClick={() => store.openDialog(null)} title="Закрыть">
            ✕
          </Button>
        </div>

        <div className="mt-3 flex flex-col gap-2.5">
          {kind !== 'no_show' ? (
            <Field label={kind === 'new_request' ? 'Когда позвонил клиент' : 'Время события'}>
              <TextInput size="l" controlProps={{ type: 'time' }} value={time} onUpdate={setTime} />
            </Field>
          ) : null}

          {isNew ? (
            <>
              <Field label="Адрес">
                <Select
                  size="l"
                  width="max"
                  filterable
                  value={address ? [address] : []}
                  placeholder="Выберите адрес"
                  onUpdate={([value]) => {
                    const chosen = dataset.requests.find((item) => item.address === value)
                    setAddress(value ?? '')
                    if (chosen) {
                      setLatInput(String(chosen.lat))
                      setLonInput(String(chosen.lon))
                    }
                  }}
                  options={dataset.requests.map((item) => ({ value: item.address, content: item.address }))}
                />
              </Field>

              <div className="flex items-end gap-2">
                <span className="flex-1">
                  <Field label="Широта">
                    <TextInput size="l" value={lat} onUpdate={setLatInput} />
                  </Field>
                </span>
                <span className="flex-1">
                  <Field label="Долгота">
                    <TextInput size="l" value={lon} onUpdate={setLonInput} />
                  </Field>
                </span>
                <Button view="outlined" size="l" onClick={() => store.setPicking(true)}>
                  На карте
                </Button>
              </div>

              <div className="flex gap-2">
                <span className="flex-1">
                  <Field label="Длительность, мин">
                    <TextInput size="l" type="number" value={duration} onUpdate={setDuration} />
                  </Field>
                </span>
                <span className="flex-1">
                  <Field label="Навык">
                    <Select
                      size="l"
                      width="max"
                      value={[skill]}
                      onUpdate={([value]) => setSkill(value as Skill)}
                      options={SKILLS}
                    />
                  </Field>
                </span>
              </div>
            </>
          ) : null}

          {isNew || kind === 'reschedule' ? (
            <div className="flex gap-2">
              <span className="flex-1">
                <Field label={kind === 'reschedule' ? 'Новое окно с' : 'Окно с'}>
                  <TextInput size="l" controlProps={{ type: 'time' }} value={windowStart} onUpdate={setWindowStart} />
                </Field>
              </span>
              <span className="flex-1">
                <Field label={kind === 'reschedule' ? 'Новое окно до' : 'Окно до'}>
                  <TextInput size="l" controlProps={{ type: 'time' }} value={windowEnd} onUpdate={setWindowEnd} />
                </Field>
              </span>
            </div>
          ) : null}

          {isNew ? (
            <Field label="Как назначать">
              <SegmentedRadioGroup
                size="l"
                width="max"
                value={policy}
                onUpdate={(value) => setPolicy(value as EventPolicy)}
                options={[
                  { value: 'offer', content: 'Предложить бригадам' },
                  { value: 'direct', content: 'Отдать лучшей' },
                ]}
              />
            </Field>
          ) : null}

          {kind === 'cancel' || kind === 'no_show' || kind === 'reschedule' ? (
            <Field
              label={
                kind === 'cancel' ? 'Какую заявку снять' : kind === 'no_show' ? 'К какой заявке приехали' : 'Какую заявку перенести'
              }
            >
              <Select
                size="l"
                width="max"
                filterable
                value={requestId ? [requestId] : []}
                onUpdate={([value]) => setRequestId(value ?? '')}
                options={requestOptions}
              />
            </Field>
          ) : null}

          {kind === 'no_show' ? (
            <>
              <Field label="Что случилось">
                <Select
                  size="l"
                  width="max"
                  value={[note]}
                  onUpdate={([value]) => setNote(value as NoShowNote)}
                  options={NO_SHOW_NOTES}
                />
              </Field>
              {pickedStop ? (
                <p className="text-[12px] leading-snug text-[var(--b-text-3)]">
                  Бригада приехала в {pickedStop.arrive}, окно клиента {picked?.window_start}–{picked?.window_end}.
                </p>
              ) : null}
            </>
          ) : null}

          {kind === 'delay' || kind === 'engineer_off' ? (
            <Field label={kind === 'delay' ? 'Кто задерживается' : 'Кто выбыл'}>
              <Select
                size="l"
                width="max"
                filterable
                value={engineerId ? [engineerId] : []}
                onUpdate={([value]) => setEngineerId(value ?? '')}
                options={dataset.engineers.map((engineer) => ({ value: engineer.id, content: engineer.name }))}
              />
            </Field>
          ) : null}

          {kind === 'delay' ? (
            <Field label="На сколько минут">
              <TextInput size="l" type="number" value={delay} onUpdate={setDelay} />
            </Field>
          ) : null}
        </div>

        <div className="mt-2.5">
          <Field label="Комментарий">
            <TextArea size="l" minRows={2} maxRows={5} value={comment} onUpdate={setComment} placeholder="Что важно знать бригаде и диспетчеру" />
          </Field>
        </div>

        <p className="mt-3 text-[12px] leading-snug text-[var(--b-text-3)]">
          {HINT[kind]} Событие встанет в пачку, варианты пересчёта посчитаются сами.
        </p>
        {saved ? (
          <p className="mt-1 text-[12px] leading-snug text-[var(--b-text-2)]">Сохранено заявок: {saved}. Следующая — новый адрес.</p>
        ) : null}

        <div className="mt-3 flex justify-end gap-2">
          <Button view="flat" size="l" onClick={() => store.openDialog(null)}>
            Отмена
          </Button>
          {isNew ? (
            <Button view="outlined" size="l" onClick={() => submit(true)} disabled={!valid}>
              Сохранить и ещё
            </Button>
          ) : null}
          <Button view="action" size="l" onClick={() => submit()} disabled={!valid}>
            Сохранить
          </Button>
        </div>
      </div>
    </div>
  )
}
