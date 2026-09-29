/**
 * Имитация операционного дня. Диспетчер задаёт, сколько и каких событий
 * случится, сервер проживает день дважды — по правилу «всё новое на завтра»
 * и по выбранному правилу ответа — и отдаёт ленту событий с исходами
 * и показатели рядом. Лучшее значение строки жирным, худшее красным,
 * как в сравнении с исходными данными.
 *
 * План любого прогона можно открыть на экране: карта, список и ленты бригад
 * покажут день таким, каким он кончился. Пока он открыт, экран не подхватывает
 * «последний план» с сервера — это другая ветка дня.
 *
 * Сверх событий симулятора в день можно вбросить свои заявки: адрес,
 * окно и минуту звонка. Вброшенная встаёт событием ровно в свою минуту, когда
 * к ней уже случилось всё, что случилось раньше, — и в итогах по каждой видно,
 * вписалась ли она день в день и к кому, а если нет, то почему ушла на завтра.
 * Заявки, поставленные тычком по карте, переносятся сюда одной кнопкой.
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, NumberInput, SegmentedRadioGroup, Select, TextInput } from '@gravity-ui/uikit'
import { runSimulation } from '../data'
import { useStore } from '../store'
import { num } from '../lib/ui'
import { IconClose } from '../lib/icons'
import { windowAfter } from '../lib/drafts'
import type { InjectedRequest, ScenarioSpec, SimEvent, SimPolicy, SimulationResult, SimulationRun } from '../types'

const POLICY_LABEL: Record<SimPolicy, string> = {
  static: 'Всё новое — на завтра',
  offer: 'Предлагать бригадам',
  direct: 'Отдавать лучшей',
}

const EVENT_LABEL: Record<string, string> = {
  new_request: 'Новая заявка',
  offer: 'Предложение',
  cancel: 'Отмена',
  no_show: 'Клиента нет',
  reschedule: 'Перенос окна',
  delay: 'Задержка бригады',
  engineer_off: 'Бригада выбыла',
  urgent: 'Авария',
}

const OUTCOME_TONE: Record<SimEvent['outcome_code'], string> = {
  assigned: 'ok',
  accepted: 'ok',
  offered: 'wait',
  declined: 'warn',
  deferred: 'bad',
  removed: 'muted',
  shifted: 'muted',
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="b-sim-row">
      <span>{label}</span>
      {children}
    </label>
  )
}

export default function SimulationDrawer() {
  const store = useStore()
  const open = store.simOpen
  const [seed, setSeed] = useState<number | null>(1)
  // Пусто — сервер разыграет долю региона из настройки «Доля заявок день в день».
  const [newRequests, setNewRequests] = useState<number | null>(null)
  const share = Number((store.rules as { options?: { intraday_share_pct?: number } } | null)?.options?.intraday_share_pct ?? 12)
  const autoNew = `${Math.round(((store.dataset?.requests.length ?? 0) * share) / 100)} — ${share} % региона`
  const [cancels, setCancels] = useState<number | null>(2)
  const [noShows, setNoShows] = useState<number | null>(2)
  const [reschedules, setReschedules] = useState<number | null>(1)
  const [delays, setDelays] = useState<number | null>(1)
  const [engineerOff, setEngineerOff] = useState<number | null>(0)
  const [policy, setPolicy] = useState<SimPolicy>('offer')
  const [accept, setAccept] = useState<string>('70')
  const [shown, setShown] = useState<string>('')
  const [injected, setInjected] = useState<InjectedRequest[]>([])
  const [injTime, setInjTime] = useState('13:00')
  const [injAddress, setInjAddress] = useState('')
  const [injStart, setInjStart] = useState(windowAfter('13:00').start)
  const [injEnd, setInjEnd] = useState(windowAfter('13:00').end)

  const simulation = useMutation({
    mutationFn: (spec: ScenarioSpec) => runSimulation(spec),
    onError: (error) => useStore.getState().notify(`Имитация не посчиталась: ${String(error)}`),
  })

  if (!open) return null
  const close = () => store.setSimOpen(false)
  const result: SimulationResult | undefined = simulation.data
  const run = () =>
    simulation.mutate({
      dataset_id: store.datasetId,
      seed: seed ?? 1,
      new_requests: newRequests,
      cancels: cancels ?? 0,
      no_shows: noShows ?? 0,
      reschedules: reschedules ?? 0,
      delays: delays ?? 0,
      engineer_off: engineerOff ?? 0,
      policy,
      accept_prob: Number(accept) / 100,
      settings: store.settings,
      time_limit_s: 3,
      injected,
    })

  const addInjected = () => {
    const place = store.dataset?.requests.find((item) => item.address === injAddress)
    if (!place) return
    setInjected((list) => [
      ...list,
      {
        time: injTime, lat: place.lat, lon: place.lon, address: place.address, duration_min: 60,
        window_start: injStart, window_end: injEnd, skill: 'connect',
      },
    ])
  }
  const fromMap = store.drafts.flatMap((event) =>
    event.type === 'new_request'
      ? [{
          time: event.time, lat: event.request.lat, lon: event.request.lon, address: event.request.address,
          duration_min: event.request.duration_min, window_start: event.request.window_start,
          window_end: event.request.window_end, skill: event.request.skill,
        }]
      : [],
  )
  // Итог вброшенной — последняя строка ленты о ней: отказы бригад идут раньше.
  const verdict = (runItem: SimulationRun, id: string) =>
    [...runItem.timeline].reverse().find((item) => item.request_id === id && item.type === 'new_request')

  const dynamic: SimulationRun | undefined = result?.runs.find((item) => item.policy !== 'static')
  const timeline = result?.runs.find((item) => item.policy === (shown || dynamic?.policy || 'static'))

  return (
    <div className="b-drawer fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={close} aria-hidden="true" />
      <aside
        role="dialog"
        aria-label="Имитация операционного дня"
        className="b-set relative flex w-[560px] max-w-[96vw] flex-col bg-[var(--b-float)]"
        style={{ boxShadow: 'var(--b-shadow-float)' }}
      >
        <div className="b-set-head">
          <div className="min-w-0 flex-1">
            <h2>Имитация операционного дня</h2>
            <p>
              Утренний план, затем события по ходу дня. День проживается дважды: «всё новое на завтра»
              и выбранное правило ответа. События одни и те же, отличается только ответ на них.
            </p>
          </div>
          <Button view="flat" size="m" onClick={close} title="Закрыть">
            <IconClose />
          </Button>
        </div>

        <div className="b-set-body">
          <section className="b-set-group">
            <h3>Что случится за день</h3>
            <div className="b-sim-grid">
              <Row label="Новых заявок">
                <NumberInput size="m" min={0} max={40} value={newRequests} onUpdate={setNewRequests} placeholder={autoNew} />
              </Row>
              <Row label="Отмен">
                <NumberInput size="m" min={0} max={10} value={cancels} onUpdate={setCancels} />
              </Row>
              <Row label="Клиента нет">
                <NumberInput size="m" min={0} max={10} value={noShows} onUpdate={setNoShows} />
              </Row>
              <Row label="Переносов окна">
                <NumberInput size="m" min={0} max={10} value={reschedules} onUpdate={setReschedules} />
              </Row>
              <Row label="Задержек бригад">
                <NumberInput size="m" min={0} max={10} value={delays} onUpdate={setDelays} />
              </Row>
              <Row label="Выбытий бригад">
                <NumberInput size="m" min={0} max={3} value={engineerOff} onUpdate={setEngineerOff} />
              </Row>
              <Row label="Зерно случайности">
                <NumberInput size="m" min={1} max={9999} value={seed} onUpdate={setSeed} />
              </Row>
              <Row label="Доля согласий бригад, %">
                <Select
                  size="m"
                  width="max"
                  value={[accept]}
                  onUpdate={([value]) => setAccept(value ?? '70')}
                  options={['30', '50', '70', '90', '100'].map((value) => ({ value, content: `${value} %` }))}
                />
              </Row>
            </div>
            <div className="b-set-row">
              <span className="b-set-label">Правило ответа на новую заявку</span>
              <SegmentedRadioGroup
                size="m"
                width="max"
                value={policy}
                onUpdate={(value) => setPolicy(value as SimPolicy)}
                options={[
                  { value: 'offer', content: POLICY_LABEL.offer },
                  { value: 'direct', content: POLICY_LABEL.direct },
                ]}
              />
              <small className="b-set-hint">
                Авария и срочная всегда идут директивно. Настройки расчёта — тарифы, горизонт блокировки,
                допустимый сдвиг — берутся текущие.
              </small>
            </div>
          </section>

          <section className="b-set-group">
            <h3>Вбросить заявку в день</h3>
            {injected.length ? (
              <ol className="b-sim-line">
                {injected.map((item, index) => (
                  <li key={index} className="muted">
                    <time>{item.time}</time>
                    <b>v{index + 1}</b>
                    <span>
                      {item.address} · окно {item.window_start}–{item.window_end}
                    </span>
                    <Button view="flat" size="xs" onClick={() => setInjected((list) => list.filter((_, i) => i !== index))}>
                      <IconClose />
                    </Button>
                  </li>
                ))}
              </ol>
            ) : null}
            <div className="b-sim-grid">
              <Row label="Звонок в">
                <TextInput
                  size="m"
                  controlProps={{ type: 'time' }}
                  value={injTime}
                  onUpdate={(value) => {
                    setInjTime(value)
                    const window = windowAfter(value)
                    setInjStart(window.start)
                    setInjEnd(window.end)
                  }}
                />
              </Row>
              <Row label="Адрес">
                <Select
                  size="m"
                  width="max"
                  filterable
                  value={injAddress ? [injAddress] : []}
                  placeholder="Адрес региона"
                  onUpdate={([value]) => setInjAddress(value ?? '')}
                  options={(store.dataset?.requests ?? []).map((item) => ({ value: item.address, content: item.address }))}
                />
              </Row>
              <Row label="Окно с">
                <TextInput size="m" controlProps={{ type: 'time' }} value={injStart} onUpdate={setInjStart} />
              </Row>
              <Row label="Окно до">
                <TextInput size="m" controlProps={{ type: 'time' }} value={injEnd} onUpdate={setInjEnd} />
              </Row>
            </div>
            <div className="b-acts-row">
              <Button view="outlined" size="m" disabled={!injAddress} onClick={addInjected}>
                Добавить заявку
              </Button>
              {fromMap.length ? (
                <Button view="outlined" size="m" onClick={() => setInjected((list) => [...list, ...fromMap])}>
                  Взять с карты: {fromMap.length}
                </Button>
              ) : null}
            </div>
            <small className="b-set-hint">
              Заявка встаёт событием в минуту звонка, после всего, что к ней уже случилось. В итогах видно,
              вписалась ли она сегодня.
            </small>
          </section>

          {simulation.isPending ? (
            <section className="b-set-group">
              <h3>Проживаем день…</h3>
              <p className="text-[var(--b-text-2)]">Утренний план и два прогона событий, около минуты.</p>
              <div className="flex flex-col gap-1.5">
                {Array.from({ length: 8 }, (_, i) => (
                  <div key={i} className="b-skeleton h-7 w-full" />
                ))}
              </div>
            </section>
          ) : null}

          {result && !simulation.isPending ? (
            <>
              <section className="b-set-group">
                <h3>Итоги дня</h3>
                <table className="b-cmp">
                  <thead>
                    <tr>
                      <th>Показатель</th>
                      {result.runs.map((item) => (
                        <th key={item.policy} className={item.policy !== 'static' ? 'ours' : undefined}>
                          {POLICY_LABEL[item.policy]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.kpi_labels.map((kpi) => {
                      const values = result.runs.map((item) => item.kpis[kpi.key] ?? 0)
                      const distinct = new Set(values).size > 1
                      const best = kpi.less_is_better ? Math.min(...values) : Math.max(...values)
                      const worst = kpi.less_is_better ? Math.max(...values) : Math.min(...values)
                      const neutral = kpi.key === 'intraday_total' || kpi.key === 'offers_sent'
                      return (
                        <tr key={kpi.key}>
                          <td>{kpi.label}</td>
                          {result.runs.map((item, index) => {
                            const value = values[index]
                            const cls = !distinct || neutral ? '' : value === best ? 'best' : value === worst ? 'worst' : ''
                            return (
                              <td key={item.policy} className={[cls, item.policy !== 'static' ? 'ours' : ''].join(' ').trim() || undefined}>
                                {num(value, Number.isInteger(value) ? 0 : 1)}
                                {kpi.unit ? ` ${kpi.unit}` : ''}
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </section>

              {result.spec.injected?.length ? (
                <section className="b-set-group">
                  <h3>Вписались ли вброшенные</h3>
                  <table className="b-cmp">
                    <thead>
                      <tr>
                        <th>Заявка</th>
                        {result.runs.map((item) => (
                          <th key={item.policy} className={item.policy !== 'static' ? 'ours' : undefined}>
                            {POLICY_LABEL[item.policy]}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.spec.injected.map((item, index) => {
                        const id = `v${index + 1}`
                        return (
                          <tr key={id}>
                            <td>
                              {id} · звонок {item.time}
                            </td>
                            {result.runs.map((runItem) => {
                              const row = verdict(runItem, id)
                              const ok = row && (row.outcome_code === 'assigned' || row.outcome_code === 'accepted')
                              return (
                                <td key={runItem.policy} className={ok ? 'best' : row?.outcome_code === 'deferred' ? 'worst' : undefined}>
                                  {row?.outcome ?? '—'}
                                </td>
                              )
                            })}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </section>
              ) : null}

              <section className="b-set-group">
                <div className="flex items-center justify-between gap-2">
                  <h3>Лента событий</h3>
                  <SegmentedRadioGroup
                    size="s"
                    value={timeline?.policy ?? 'static'}
                    onUpdate={(value) => setShown(value)}
                    options={result.runs.map((item) => ({ value: item.policy, content: POLICY_LABEL[item.policy] }))}
                  />
                </div>
                <ol className="b-sim-line">
                  {timeline?.timeline.map((item, index) => (
                    <li key={`${item.time}-${index}`} className={OUTCOME_TONE[item.outcome_code]}>
                      <time>{item.time}</time>
                      <b>
                        {EVENT_LABEL[item.type] ?? item.type}
                        {item.request_id ? ` ${item.request_id}` : item.engineer_id ? ` · ${item.engineer_id}` : ''}
                      </b>
                      <span>{item.outcome}</span>
                      {item.changed_requests ? <small>сдвинуто {item.changed_requests}</small> : null}
                    </li>
                  ))}
                </ol>
              </section>
            </>
          ) : null}
        </div>

        <div className="b-set-foot">
          <Button view="action" size="l" onClick={run} disabled={simulation.isPending || store.offline}>
            {simulation.isPending ? 'Считаем…' : result ? 'Прожить ещё раз' : 'Прожить день'}
          </Button>
          {timeline ? (
            <Button
              view="outlined"
              size="l"
              onClick={() => {
                store.showPlan(timeline.plan)
                close()
              }}
            >
              Открыть план «{POLICY_LABEL[timeline.policy]}»
            </Button>
          ) : null}
        </div>
      </aside>
    </div>
  )
}
