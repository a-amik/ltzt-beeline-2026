/**
 * Сайд-шит «Сценарий» справа: что случится за день и откуда стартуют
 * бригады. Один и тот же для «Живого дня» и «Имитации», чтобы сценарий
 * назывался и настраивался одинаково. Закрывается крестиком, Esc и щелчком
 * мимо; экран под ним остаётся виден.
 */

import { useEffect, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { Button, HelpMark, Select } from '@gravity-ui/uikit'
import type { CustomEvent, CustomEventType, Dataset, Engineer, EventSet, RequestItem, SetEvent, Settings } from '../../types'
import { IconClose, IconPlus, IconSliders } from '../../lib/icons'
import {
  DAY_LABELS, LIVE_KINDS, SCENARIO_NOTE, SEEDS, STARTS, dayKindInfo, isRandom, startInfo,
  type ScenarioDraft, type StartKind,
} from './scenario'
import './scenario.css'

export function ScenarioSheet({ open, onClose, children, footer }: {
  open: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="b-scn" role="dialog" aria-label="Сценарий">
      <div className="b-scn-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="b-scn-sheet">
        <header>
          <b>Сценарий</b>
          <Button view="flat" size="m" onClick={onClose} title="Закрыть — Esc" aria-label="Закрыть"><IconClose /></Button>
        </header>
        <div className="b-scn-body b-scroll">{children}</div>
        {footer ? <footer>{footer}</footer> : null}
      </aside>
    </div>
  )
}

/** Выбор из нескольких вариантов строками: подпись и ⓘ с пояснением. */
export function Choice<T extends string>({ title, value, options, onChange }: {
  title: string
  value: T
  options: { value: T; label: string; info: string }[]
  onChange: (value: T) => void
}) {
  return (
    <fieldset className="b-scn-choice">
      <legend>{title}</legend>
      <div className="b-scn-list">
        {options.map((o) => (
          <label key={o.value} className={o.value === value ? 'on' : undefined}>
            <input type="radio" name={title} value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
            <HelpMark aria-label={`Что такое «${o.label}»`} popoverProps={{ placement: ['left', 'bottom-end'] }}>
              <div className="b-demo-info">{o.info}</div>
            </HelpMark>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/**
 * Кнопка сценария в шапке экрана показа — одна и та же в «Живом дне» и
 * «Имитации», на одном месте: подпись говорит, какой сценарий сейчас
 * прогоняется, нажатие открывает сайд-шит.
 */
export function ScenarioButton({ label, open, onClick }: { label: string; open: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`b-scn-btn${open ? ' on' : ''}`} onClick={onClick} aria-expanded={open} title="Какой день и откуда стартуют бригады">
      <IconSliders />
      <span>Сценарий</span>
      <b>{label}</b>
    </button>
  )
}


/** Виды событий в том порядке, в каком их перечисляет состав набора. */
const KINDS: { type: string; label: string }[] = [
  { type: 'new_request', label: 'Новые заявки' },
  { type: 'urgent', label: 'Срочная авария' },
  { type: 'cancel', label: 'Отмены' },
  { type: 'no_show', label: 'Клиента нет' },
  { type: 'reschedule', label: 'Переносы окна' },
  { type: 'delay', label: 'Задержки бригад' },
  { type: 'engineer_off', label: 'Выбывает бригада' },
]

const byTime = (a: SetEvent, b: SetEvent) => a.time.localeCompare(b.time)

/** Одна строка о наборе: сколько событий и в какие часы. */
export function setLine(events: SetEvent[]): string {
  if (!events.length) return 'событий нет'
  const t = [...events].sort(byTime)
  return `${events.length} ${plural(events.length, 'событие', 'события', 'событий')}, ${t[0].time}—${t[t.length - 1].time}`
}

function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10
  const h = n % 100
  if (d === 1 && h !== 11) return one
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return few
  return many
}

/** Времена событий одного вида; одинаковые — один раз с множителем: «14:00 ×3». */
function times(list: SetEvent[]): string {
  const out: { text: string; n: number }[] = []
  for (const e of list) {
    const text = e.delay_min ? `${e.time} (+${e.delay_min} мин)` : e.time
    const last = out[out.length - 1]
    if (last && last.text === text) last.n += 1
    else out.push({ text, n: 1 })
  }
  return out.map((x) => (x.n > 1 ? `${x.text} ×${x.n}` : x.text)).join(', ')
}

/** Состав набора по видам: что и во сколько случится. */
export function EventsSummary({ events }: { events: SetEvent[] }) {
  const rows = KINDS.map((k) => ({ ...k, list: events.filter((e) => e.type === k.type).sort(byTime) })).filter((r) => r.list.length)
  if (!rows.length) return <p className="b-scn-note">В этом наборе событий нет.</p>
  return (
    <dl className="b-scn-set">
      {rows.map((r) => (
        <div key={r.type}>
          <dt>{r.label}<b>{r.list.length}</b></dt>
          <dd>
            {r.type === 'new_request' && r.list.length > 3
              ? `${r.list[0].time}—${r.list[r.list.length - 1].time}`
              : times(r.list)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * Номер случайного набора событий и его состав. Тот же номер — те же
 * события; наборов столько же, сколько дней обычного и тяжёлого типа
 * в «Имитации», и набор № N здесь — день № N того же участка там.
 */
export function SeedPicker({ value, sets, failed, onChange }: {
  value: number
  sets: EventSet[] | undefined
  failed?: boolean
  onChange: (seed: number) => void
}) {
  const chosen = sets?.find((x) => x.seed === value)
  return (
    <fieldset className="b-scn-choice">
      <legend>
        Набор событий
        <HelpMark aria-label="Что такое набор событий" popoverProps={{ placement: ['left', 'bottom-end'] }}>
          <div className="b-demo-info">
            Число событий задаёт тип дня, а&nbsp;набор&nbsp;— какие именно заявки придут и&nbsp;отменятся и&nbsp;в&nbsp;какую минуту.
            Тот&nbsp;же номер&nbsp;— тот&nbsp;же день. Набор №&nbsp;N здесь&nbsp;— день №&nbsp;N этого участка в&nbsp;«Имитации».
          </div>
        </HelpMark>
      </legend>
      <Select size="l" width="max" value={[String(value)]} onUpdate={([v]) => onChange(Number(v))}
        options={Array.from({ length: SEEDS }, (_, i) => {
          const set = sets?.find((x) => x.seed === i + 1)
          return { value: String(i + 1), content: set ? `Набор № ${i + 1} · ${setLine(set.events)}` : `Набор № ${i + 1}` }
        })} />
      {chosen ? <EventsSummary events={chosen.events} />
        : <p className="b-scn-note">{failed ? 'Состав набора не пришёл с сервера.' : 'Состав набора загружается…'}</p>}
    </fieldset>
  )
}

const CUSTOM_TYPES: { value: CustomEventType; label: string; target: 'request' | 'engineer' | 'address' }[] = [
  { value: 'engineer_off', label: 'Бригада выбыла', target: 'engineer' },
  { value: 'delay', label: 'Бригада задержалась', target: 'engineer' },
  { value: 'new_request', label: 'Новая заявка', target: 'address' },
  { value: 'cancel', label: 'Клиент отменил', target: 'request' },
  { value: 'no_show', label: 'Клиента нет', target: 'request' },
  { value: 'reschedule', label: 'Перенос окна', target: 'request' },
]

const TIMES = Array.from({ length: 37 }, (_, i) => {
  const m = 9 * 60 + i * 15
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
})

const DELAYS = [15, 30, 45, 60, 90, 120]

/** Событие по умолчанию нового вида: цель — первая бригада или заявка набора. */
export function customDefault(type: CustomEventType, engineers: Engineer[], requests: RequestItem[], time = '13:00'): CustomEvent {
  const kind = CUSTOM_TYPES.find((t) => t.value === type)!
  return {
    type, time,
    engineer_id: kind.target === 'engineer' ? engineers[0]?.id ?? null : null,
    request_id: kind.target === 'engineer' ? null : requests[0]?.id ?? null,
    delay_min: type === 'delay' ? 30 : undefined,
  }
}

/**
 * Свои события: что, во сколько и с кем — без случайности. Новая заявка
 * звонит с адреса известной заявки и ждёт визита через час, на три часа;
 * перенос сдвигает окно на два часа — как у случайных наборов.
 */
export function CustomEvents({ value, engineers, requests, onChange }: {
  value: CustomEvent[]
  engineers: Engineer[]
  requests: RequestItem[]
  onChange: (events: CustomEvent[]) => void
}) {
  const set = (i: number, patch: Partial<CustomEvent>) => onChange(value.map((e, k) => (k === i ? { ...e, ...patch } : e)))
  const reqOptions = requests.map((r) => ({ value: r.id, content: r.address || r.id }))
  const engOptions = engineers.map((e) => ({ value: e.id, content: e.name || e.id }))
  return (
    <fieldset className="b-scn-choice">
      <legend>
        Свои события
        <HelpMark aria-label="Как задаются свои события" popoverProps={{ placement: ['left', 'bottom-end'] }}>
          <div className="b-demo-info">
            Событие случится ровно так, как задано, в&nbsp;обоих планах в&nbsp;одну минуту. Новая заявка звонит с&nbsp;адреса выбранной заявки
            и&nbsp;ждёт визита через час, окно&nbsp;— три часа. Перенос сдвигает окно на&nbsp;два часа. «Клиента нет» случается, когда бригада приезжает.
          </div>
        </HelpMark>
      </legend>
      <div className="b-scn-custom">
        {value.map((e, i) => {
          const kind = CUSTOM_TYPES.find((t) => t.value === e.type)!
          return (
            <div key={i} className="b-scn-ev">
              <div className="top">
                <Select size="m" width="max" value={[e.type]}
                  onUpdate={([v]) => set(i, customDefault(v as CustomEventType, engineers, requests, e.time))}
                  options={CUSTOM_TYPES.map((t) => ({ value: t.value, content: t.label }))} />
                {e.type === 'no_show' ? null : (
                  <Select size="m" width={96} value={[e.time]} onUpdate={([v]) => set(i, { time: v })}
                    options={TIMES.map((t) => ({ value: t, content: t }))} />
                )}
                <Button view="flat" size="m" onClick={() => onChange(value.filter((_, k) => k !== i))} title="Убрать событие" aria-label="Убрать событие">
                  <IconClose />
                </Button>
              </div>
              <div className="top">
                {kind.target === 'engineer' ? (
                  <Select size="m" width="max" filterable value={e.engineer_id ? [e.engineer_id] : []} onUpdate={([v]) => set(i, { engineer_id: v })} options={engOptions} placeholder="Бригада" />
                ) : (
                  <Select size="m" width="max" filterable value={e.request_id ? [e.request_id] : []} onUpdate={([v]) => set(i, { request_id: v })} options={reqOptions}
                    placeholder={kind.target === 'address' ? 'С какого адреса' : 'Какая заявка'} />
                )}
                {e.type === 'delay' ? (
                  <Select size="m" width={96} value={[String(e.delay_min ?? 30)]} onUpdate={([v]) => set(i, { delay_min: Number(v) })}
                    options={DELAYS.map((d) => ({ value: String(d), content: `+${d} мин` }))} />
                ) : null}
              </div>
            </div>
          )
        })}
        {value.length < 12 ? (
          <Button view="outlined" size="m" onClick={() => onChange([...value, customDefault('engineer_off', engineers.slice(value.length % Math.max(engineers.length, 1)), requests)])}>
            <span className="flex items-center gap-1.5"><IconPlus />Добавить событие</span>
          </Button>
        ) : null}
      </div>
    </fieldset>
  )
}

/**
 * Содержимое сайд-шита «Сценарий» — одно на «Живой день» и «Имитацию»:
 * какой день, откуда стартуют бригады, затем свои события, номер набора
 * с составом или состав событий набора участка, и общая строка внизу.
 * Экраны отличаются только тем, как проживают выбранное.
 */
export function ScenarioForm({ draft, onChange, datasetId, dataset, settings, sharePct, hybridKm, offline }: {
  draft: ScenarioDraft
  onChange: (draft: ScenarioDraft) => void
  /** Участок, для которого показывать состав наборов и списки бригад и заявок. */
  datasetId: string
  dataset: Dataset | undefined
  settings: Settings | null
  sharePct: number
  hybridKm: number
  offline?: boolean
}) {
  const sets = useQuery({
    queryKey: ['race-sets', datasetId, draft.kind, draft.start, sharePct, settings],
    queryFn: () => api.raceSets({ dataset_id: datasetId, kind: draft.kind as 'normal' | 'hard', start: draft.start, settings }),
    staleTime: Infinity,
    retry: 2,
    enabled: isRandom(draft.kind) && !offline,
  })
  const set = (patch: Partial<ScenarioDraft>) => onChange({ ...draft, ...patch })
  return (
    <>
      <Choice title="Какой день" value={draft.kind}
        options={LIVE_KINDS.map((k) => ({ value: k, label: DAY_LABELS[k], info: dayKindInfo(k, sharePct) }))}
        onChange={(kind) => set({
          kind,
          custom: kind === 'custom' && !draft.custom.length && dataset ? [customDefault('engineer_off', dataset.engineers, dataset.requests)] : draft.custom,
        })} />
      <Choice title="Откуда стартуют бригады" value={draft.start}
        options={(Object.keys(STARTS) as StartKind[]).map((k) => ({ value: k, label: STARTS[k].label, info: startInfo(k, hybridKm) }))}
        onChange={(start) => set({ start })} />
      {draft.kind === 'custom' ? (
        dataset
          ? <CustomEvents value={draft.custom} engineers={dataset.engineers} requests={dataset.requests} onChange={(custom) => set({ custom })} />
          : <p className="b-scn-note">Загружаем бригады и заявки участка…</p>
      ) : null}
      {isRandom(draft.kind) ? <SeedPicker value={draft.seed} sets={sets.data} failed={sets.isError} onChange={(seed) => set({ seed })} /> : null}
      {draft.kind === 'data' && dataset ? (
        <fieldset className="b-scn-choice">
          <legend>Что в наборе участка</legend>
          <EventsSummary events={(dataset.events ?? []).map((e) => ({ time: e.time, type: e.type, delay_min: 'delay_min' in e ? e.delay_min : null }))} />
        </fieldset>
      ) : null}
      <p className="b-scn-note">{SCENARIO_NOTE}</p>
    </>
  )
}

/** Кнопки сайд-шита — одни на оба экрана. */
export function ScenarioFooter({ draft, onApply, onReset }: { draft: ScenarioDraft; onApply: () => void; onReset: () => void }) {
  return (
    <>
      <Button view="action" size="l" disabled={draft.kind === 'custom' && !draft.custom.length} onClick={onApply}>Прожить день</Button>
      <Button view="flat" size="l" onClick={onReset}>По умолчанию</Button>
    </>
  )
}
