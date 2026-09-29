/**
 * Живой день: контроль и наш план рядом и в движении. Слева день так, как его
 * разослали диспетчеры заказчика 17 августа, справа наш план; часы одни,
 * камеры связаны. Под каждой картой счётчики, между ними — разница, которая
 * растёт по ходу дня: сколько заявок вовремя, сколько опозданий и простоя.
 *
 * Сценарий тот же, что в «Имитации», и настраивается тем же сайд-шитом
 * (`ScenarioForm`): какой день (без событий, обычный, тяжёлый, свои события) и откуда стартуют бригады — у обоих планов одинаково. Для случайного дня добавлен
 * номер набора: набор № N здесь — день № N участка в «Имитации». День
 * считает сервер (`POST /race/day`): контроль отвечает на события правилом
 * п. 2.3 — первый подходящий свободный инженер, наш план — перепланированием.
 *
 * Контрольный план восстановлен по окнам и считается нашей моделью дороги —
 * это сказано подписью, чтобы жюри не приняло реконструкцию за факт.
 *
 * Свой файл диспетчера здесь не участвует: контрольного распределения у него
 * нет, и сервер считает день только на наборах заказчика. Открыт файл — день
 * идёт на наборе «Вся Москва», о чём сказано в ⓘ.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { HelpMark } from '@gravity-ui/uikit'
import { api } from '../../api'
import { activePlan, useStore } from '../../store'
import { buildDay, statsAt, type DayStats } from '../../lib/playback'
import { readRouteColors } from '../../lib/colors'
import { num, plural } from '../../lib/ui'
import type { DatasetSummary, ScenarioSpec } from '../../types'
import { loadDataset } from '../../data'
import DemoShell, { DemoBusy, useFirstRun } from './DemoShell'
import { DAY_START } from '../../lib/time'
import { ScenarioButton, ScenarioFooter, ScenarioForm, ScenarioSheet } from '../scenario/ScenarioSheet'
import {
  DAY_TYPES, DEFAULT_SCENARIO, STARTS, isRandom, scenarioLabel, type LiveKind, type ScenarioDraft,
} from '../scenario/scenario'
import PlaybackMap, { type MapSync } from './PlaybackMap'
import { useClock } from './useClock'

/** Набор заказчика, на котором идёт день, когда на экране открыт свой файл. */
const HOME_SET = 'moskva'

const NO_EVENTS = { new_requests: 0, cancels: 0, no_shows: 0, reschedules: 0, delays: 0, engineer_off: 0 }

/** Счётчики событий сценария — те же, что у дня «Имитации» (`race.spec_for`). */
function counts(kind: LiveKind, base: number) {
  if (!isRandom(kind)) return NO_EVENTS
  const t = DAY_TYPES[kind]
  return { ...t.counts, new_requests: t.newShare === 1 ? null : Math.round(base * t.newShare) }
}

export default function DemoCompare({ onClose }: { onClose: () => void }) {
  const store = useStore()
  // Свой файл — не набор заказчика: день идёт на Москве, её набор берётся из того же кэша, что у экрана.
  const summaries = useQueryClient().getQueryData<DatasetSummary[]>(['datasets']) ?? []
  const uploaded = summaries.find((item) => item.id === store.datasetId)?.source === 'upload' || store.datasetId.startsWith('upload-')
  const datasetId = uploaded ? HOME_SET : store.datasetId
  const home = useQuery({ queryKey: ['dataset', HOME_SET], queryFn: () => loadDataset(HOME_SET), staleTime: Infinity, enabled: uploaded })
  const plan = uploaded ? null : activePlan(store)
  const dataset = uploaded ? home.data ?? null : store.dataset
  const [scenario, setScenario] = useState<ScenarioDraft>(DEFAULT_SCENARIO)
  const [draft, setDraft] = useState<ScenarioDraft>(DEFAULT_SCENARIO)
  const [panel, setPanel] = useState(false)
  const options = (store.rules as { options?: { intraday_share_pct?: number; hybrid_home_km?: number } } | null)?.options
  const sharePct = Number(options?.intraday_share_pct ?? 12)
  const hybridKm = Number(options?.hybrid_home_km ?? 4.6)
  const base = Math.round(((dataset?.requests.length ?? 0) * sharePct) / 100)

  const spec: ScenarioSpec = {
    dataset_id: datasetId, seed: isRandom(scenario.kind) ? scenario.seed : 0, ...counts(scenario.kind, base),
    events_from: scenario.kind === 'data' ? 'data' : 'random',
    custom: scenario.kind === 'custom' ? scenario.custom : [],
    policy: 'direct', accept_prob: 1, time_limit_s: 3,
    settings: { ...store.settings, options: { ...((store.settings as { options?: object } | null)?.options ?? {}), ...STARTS[scenario.start].options } },
  }
  const day = useQuery({
    // Версия правил в ключе: сохранили новые — день считается заново, а не берётся из кэша.
    queryKey: ['race-day', datasetId, scenario, base, store.settings, store.rulesVersion],
    queryFn: () => api.raceDay(spec),
    staleTime: Infinity,
    retry: false,
    enabled: !store.offline && Boolean(dataset),
  })

  const colors = useMemo(() => readRouteColors(), [])
  const live = day.data
  const withEvents = scenario.kind !== 'none'
  // Без сервера показываем только рабочий план: контроль и сценарий считает сервер.
  const ours = useMemo(() => {
    const shown = live ? live.ours : store.offline ? plan : null
    return dataset && shown ? buildDay(dataset, shown, colors) : null
  }, [dataset, plan, live, colors, store.offline])
  const theirs = useMemo(() => (dataset && live ? buildDay(dataset, live.control, colors) : null), [dataset, live, colors])
  const [sync] = useState<MapSync>(() => ({ maps: [], busy: false }))
  // Часы не идут, пока день считается: запускаются, когда он пришёл.
  const clock = useClock(60, false)
  const a = theirs ? statsAt(theirs, clock.time) : null
  const b = ours ? statsAt(ours, clock.time) : null
  const waiting = day.isFetching
  // Спрашиваем вместе с расчётом дня: пока он идёт, утро ещё не готово, если его не было.
  const first = useFirstRun(datasetId, scenario.start, spec.settings ?? null, waiting)
  useEffect(() => {
    if (waiting) {
      clock.pause()
      clock.seek(DAY_START)
    } else if (live && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      clock.restart()
    }
    // Только на смену «считается — посчитан»: часы меняются каждый кадр.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting, live])
  const marks = waiting ? [] : [
    ...(theirs?.events ?? []).filter((e) => e.kind === 'late' || e.kind === 'missed').map((e) => ({ t: e.t, tone: 'bad' as const })),
    ...(withEvents ? (ours?.events ?? []).filter((e) => e.kind === 'event').map((e) => ({ t: e.t, tone: 'event' as const })) : []),
  ]
  const startText = STARTS[scenario.start].label.toLowerCase()

  const extra = <ScenarioButton label={scenarioLabel(scenario.kind, scenario.start, scenario.seed)} open={panel} onClick={() => setPanel((v) => !v)} />

  return (
    <DemoShell
      title="Живой день"
      info={
        <>
          <b>{dataset?.name ?? 'Набор'}</b>: контроль и&nbsp;наш план&nbsp;— один день, одни заявки, одни часы, один старт бригад.
          Сценарий тот&nbsp;же, что в&nbsp;«Имитации»: оба плана получают одни события в&nbsp;одну минуту, контроль отвечает правилом п.&nbsp;2.3,
          наш план&nbsp;— перепланированием. Что прогоняется, подписано на&nbsp;кнопке «Сценарий».
          {uploaded ? ' Свой файл здесь не участвует: контрольного распределения у него нет, поэтому день идёт на наборе заказчика.' : ''}
        </>
      }
      clock={clock}
      busy={waiting}
      marks={marks}
      onClose={onClose}
      inRail
      menu
      extra={extra}
    >
      <ScenarioSheet
        open={panel}
        onClose={() => setPanel(false)}
        footer={<ScenarioFooter draft={draft} onReset={() => setDraft(DEFAULT_SCENARIO)}
          onApply={() => { setScenario(draft); setPanel(false); clock.restart() }} />}
      >
        <ScenarioForm draft={draft} onChange={setDraft} datasetId={datasetId} dataset={dataset ?? undefined}
          settings={store.settings} sharePct={sharePct} hybridKm={hybridKm} offline={store.offline} />
      </ScenarioSheet>
      <div className="b-demo-duo">
        {waiting ? <DemoBusy title="Проживаем день" detail={scenarioLabel(scenario.kind, scenario.start, scenario.seed)} first={first} /> : null}
        <section className="b-demo-pane">
          <h3>
            Контрольное распределение
            <HelpMark aria-label="Откуда план" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
              <div className="b-demo-info">
                Кому отдали заявки диспетчеры 17&nbsp;августа. Порядок визитов восстановлен по&nbsp;окнам, дорога&nbsp;— нашей моделью, старт&nbsp;— {startText}.
                {withEvents ? ' Днём отвечает правилом п. 2.3: заявку получает первый подходящий свободный инженер.' : ''}
              </div>
            </HelpMark>
          </h3>
          {store.offline ? (
            <p className="b-demo-empty">Контрольный план считает сервер.</p>
          ) : (
            <PlaybackMap scene={theirs} time={clock.time} theme={store.theme} sync={sync} labels={false} />
          )}
          {waiting || !a ? null : <Strip stats={a} />}
        </section>
        <section className="b-demo-pane ours">
          <h3>
            Наш план
            <HelpMark aria-label="Откуда план" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
              <div className="b-demo-info">
                Решатель с&nbsp;текущими настройками, старт&nbsp;— {startText}.
                {withEvents ? ' Днём отвечает на события перепланированием.' : ''}
              </div>
            </HelpMark>
          </h3>
          <PlaybackMap scene={ours} time={clock.time} theme={store.theme} sync={sync} labels={false} />
          {waiting || !b ? null : <Strip stats={b} />}
        </section>
      </div>
      {day.isError ? (
        <div className="b-demo-delta"><b>День не&nbsp;посчитался:</b> <span className="bad">{String(day.error)}</span></div>
      ) : waiting ? null : (
        <Delta a={a} b={b} />
      )}
    </DemoShell>
  )
}

function Strip({ stats }: { stats: DayStats | null }) {
  if (!stats) return <div className="b-demo-strip muted">Считаем…</div>
  return (
    <div className="b-demo-strip">
      <span><small>Вовремя</small><b>{stats.onTime}</b></span>
      <span className={stats.late ? 'bad' : ''}><small>Опоздания</small><b>{stats.late}</b></span>
      <span className={stats.missed ? 'bad' : ''}><small>Сорвано</small><b>{stats.missed}</b></span>
      <span><small>Бригад</small><b>{stats.crews}</b></span>
      <span><small>Пробег</small><b>{num(stats.km, 0)} км</b></span>
      <span><small>Заработано</small><b>{num(stats.value)} ₽</b></span>
    </div>
  )
}

function Delta({ a, b }: { a: DayStats | null; b: DayStats | null }) {
  if (!a || !b) return null
  const sign = (n: number, unit = '') => `${n > 0 ? '+' : n < 0 ? '−' : ''}${num(Math.abs(n), 0)}${unit}`
  const items = [
    { forms: ['заявка вовремя', 'заявки вовремя', 'заявок вовремя'], value: b.onTime - a.onTime, good: b.onTime >= a.onTime },
    { forms: ['опоздание', 'опоздания', 'опозданий'], value: b.late - a.late, good: b.late <= a.late },
    { forms: ['сорванное окно', 'сорванных окна', 'сорванных окон'], value: b.missed - a.missed, good: b.missed <= a.missed },
    { forms: ['бригада', 'бригады', 'бригад'], value: b.crews - a.crews, good: b.crews <= a.crews },
    { forms: ['км пробега', 'км пробега', 'км пробега'], value: Math.round(b.km - a.km), good: b.km <= a.km },
    { forms: ['₽ заработано', '₽ заработано', '₽ заработано'], value: b.value - a.value, good: b.value >= a.value },
  ].map((item) => ({ ...item, label: plural(Math.abs(item.value), item.forms[0], item.forms[1], item.forms[2]) }))
  return (
    <div className="b-demo-delta" aria-live="off">
      <b>Наш план к этой минуте:</b>
      {items.map((item) => (
        // Число и подпись — раздельно: на компьютере они идут строкой, на телефоне — блоком «число над подписью».
        <span key={item.label} className={item.value === 0 ? 'zero' : item.good ? 'ok' : 'bad'}>
          <b>{sign(item.value)}</b> <small>{item.label}</small>
        </span>
      ))}
    </div>
  )
}
