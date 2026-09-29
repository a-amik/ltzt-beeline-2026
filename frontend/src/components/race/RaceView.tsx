/**
 * Имитация: три плана на одних событиях — по кальке транспортного стенда,
 * где модели копят счёт по датам истории. У нас история — один день
 * заказчика, поэтому ось — прогоны дня: в обычный и тяжёлый день каждый
 * участок проживает его двадцать раз, и каждый раз приходит свой набор
 * событий; день без событий и день с событиями из набора — по разу. Утро
 * у планов своё, события одни, минута в минуту; контроль и базовый
 * отвечают правилом п. 2.3, наш план — перепланированием.
 *
 * Экран ничего не считает: прогоны лежат в `data/race/race.json`
 * (`python -m bee_routing.race`), `GET /race`; свои события — день одного
 * участка, считается по запросу (`POST /race/custom`). Сайд-шит «Сценарий»
 * тот же, что у «Живого дня» (`ScenarioForm`); номер набора переводит
 * к дню с этим набором. Кнопка сценария в шапке подписана тем, что прогоняется.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, HelpMark, SegmentedRadioGroup, Select } from '@gravity-ui/uikit'
import { api } from '../../api'
import { useStore } from '../../store'
import { num, plural } from '../../lib/ui'
import { IconPlay } from '../../lib/icons'
import type { RacePlayer, RaceRun } from '../../types'
import DemoShell, { DemoBusy, useFirstRun } from '../demo/DemoShell'
import { ScenarioButton, ScenarioFooter, ScenarioForm, ScenarioSheet } from '../scenario/ScenarioSheet'
import {
  DAY_LABELS, DEFAULT_SCENARIO, SEEDS, isRandom, scenarioLabel, type LiveKind, type ScenarioDraft, type StartKind,
} from '../scenario/scenario'
import './race.css'

export const PLAYERS: { key: RacePlayer; title: string; note: string; color: string }[] = [
  { key: 'control', title: 'Контроль', note: 'Утро — распределение из файла заказчика; днём — правило п. 2.3: заявку получает первый подходящий свободный инженер.', color: 'var(--race-control)' },
  { key: 'baseline', title: 'Базовый', note: 'Правило п. 2.3 задания и утром, и днём: заявки по порядку файла, каждая — первой подходящей бригаде в конец маршрута.', color: 'var(--race-baseline)' },
  { key: 'ours', title: 'Наш план', note: 'Утро — решатель с текущими настройками; днём — перепланирование: план чинится на месте, обещанное клиенту не двигается.', color: 'var(--race-ours)' },
]

export const REGION_NAMES: Record<string, string> = {
  vostok: 'Восток',
  'yugo-vostok': 'Юго-восток',
  yugocentr: 'Югоцентр',
}

const DURATIONS = [
  { value: '10', content: '10 с' },
  { value: '20', content: '20 с' },
  { value: '30', content: '30 с' },
]

const share = (on: number, due: number) => (due ? on / due : 1)
const pct = (v: number, d = 1) => `${num(v * 100, d)} %`

/** Цвет клетки прогона: доля заявок вовремя. */
// Норма — серым в два тона, красным — только провал ниже 80 %: зелёный здесь путался
// с цветом «Нашего плана», а тёплые тона у хороших дней отвлекали от настоящих провалов.
const cellColor = (s: number) => (s >= 0.95 ? 'var(--race-l0)' : s >= 0.8 ? 'var(--race-l1)' : 'var(--race-bad)')

/** Разница к контролю подписью: меньше пробег и бригад — лучше, больше итог дня — лучше. */
function Delta({ r, base }: { r: RaceRun['players'][RacePlayer]; base: RaceRun['players'][RacePlayer] }) {
  const dk = r.km - base.km
  const dc = r.engineers - base.engineers
  const dr = (r.net_rub - base.net_rub) / 1000
  const sign = (v: number) => (v > 0 ? '+' : v < 0 ? '−' : '±')
  const tone = (better: number) => (better > 0 ? 'good' : better < 0 ? 'bad' : undefined)
  return (
    <span className="d">
      {' · к контролю '}
      <b className={tone(-dk)}>{sign(dk)}{num(Math.abs(dk), 0)} км</b>,{' '}
      <b className={tone(-dc)}>{sign(dc)}{Math.abs(dc)} бр.</b>,{' '}
      <b className={tone(Math.round(dr))}>{sign(dr)}{num(Math.abs(dr), 0)} тыс.&nbsp;₽</b>
    </span>
  )
}

/** Лучший за день: больше вовремя, при равенстве — меньше пробег. */
function winnerOf(run: RaceRun): RacePlayer {
  return PLAYERS.map((p) => p.key).reduce((best, key) => {
    const a = run.players[key]
    const b = run.players[best]
    return a.on_time > b.on_time || (a.on_time === b.on_time && a.km < b.km) ? key : best
  }, 'ours' as RacePlayer)
}

function prepare(runs: RaceRun[]) {
  const out = {} as Record<RacePlayer, { cum: number[]; day: number[] }>
  for (const p of PLAYERS) {
    let on = 0
    let due = 0
    const cum: number[] = []
    const day: number[] = []
    for (const run of runs) {
      on += run.players[p.key].on_time
      due += run.due
      cum.push(share(on, due))
      day.push(share(run.players[p.key].on_time, run.due))
    }
    out[p.key] = { cum, day }
  }
  return { by: out, winner: runs.map(winnerOf) }
}

/** Как назван день имитации: тем же словом, что в сценарии, у случайного — с номером набора. */
const runName = (run: RaceRun) => (run.mode === 'normal' || run.mode === 'hard'
  ? `набор событий № ${run.seed}`
  : (DAY_LABELS[run.mode as LiveKind] ?? run.mode).toLowerCase())

export default function RaceView({ onClose }: { onClose: () => void }) {
  const store = useStore()
  const data = useQuery({ queryKey: ['race'], queryFn: () => api.race(), staleTime: Infinity, retry: false })
  const [region, setRegion] = useState('all')
  const [mode, setMode] = useState<LiveKind>(DEFAULT_SCENARIO.kind)
  const [start, setStart] = useState<StartKind>(DEFAULT_SCENARIO.start)
  const [draft, setDraft] = useState<ScenarioDraft>(DEFAULT_SCENARIO)
  const [custom, setCustom] = useState<{ region: string; events: ScenarioDraft['custom'] } | null>(null)
  // Набор, к которому перейти, когда отфильтруются дни нового сценария.
  const [goSeed, setGoSeed] = useState<number | null>(null)
  const [sheet, setSheet] = useState(false)
  const options = (store.rules as { options?: { intraday_share_pct?: number; hybrid_home_km?: number } } | null)?.options
  const sharePct = Number(options?.intraday_share_pct ?? 12)
  const hybridKm = Number(options?.hybrid_home_km ?? 4.6)
  const [seconds, setSeconds] = useState(20)
  const [pos, setPos] = useState(0)
  const [playing, setPlaying] = useState(false)

  // Участок для состава наборов и своих событий: выбранный, а при «Все участки» — первый.
  const formRegion = region === 'all' ? data.data?.meta.regions[0] ?? 'vostok' : region
  const formData = useQuery({
    queryKey: ['dataset', formRegion],
    queryFn: () => api.dataset(formRegion),
    staleTime: Infinity,
    enabled: sheet && (draft.kind === 'custom' || draft.kind === 'data'),
  })
  // Свои события в файле гонки не лежат: день считается по запросу, для одного участка.
  const customRun = useQuery({
    queryKey: ['race-custom', custom, start],
    queryFn: () => api.raceCustom({ dataset_id: custom!.region, start, custom: custom!.events }),
    staleTime: Infinity,
    retry: false,
    enabled: mode === 'custom' && !!custom,
  })

  const first = useFirstRun(custom?.region, start, null, mode === 'custom' && customRun.isFetching)

  const runs = useMemo(() => {
    if (mode === 'custom') return customRun.data ? [customRun.data] : []
    const all = data.data?.runs ?? []
    const order = data.data?.meta.regions ?? []
    return all
      .filter((r) => r.mode === mode && (r.start ?? 'office') === start && (region === 'all' || r.region === region))
      .sort((a, b) => order.indexOf(a.region) - order.indexOf(b.region) || a.seed - b.seed)
  }, [data.data, mode, start, region, customRun.data])
  const n = runs.length
  const prep = useMemo(() => prepare(runs), [runs])

  useEffect(() => { setPos((p) => Math.min(p, Math.max(0, n - 1))) }, [n])
  useEffect(() => {
    if (goSeed === null || !n) return
    setPos(Math.max(0, runs.findIndex((r) => r.seed === goSeed)))
    setGoSeed(null)
  }, [goSeed, runs, n])

  const apply = () => {
    setMode(draft.kind)
    setStart(draft.start)
    setPlaying(false)
    setPos(0)
    if (draft.kind === 'custom') {
      setRegion(formRegion)
      setCustom({ region: formRegion, events: draft.custom })
    }
    setGoSeed(isRandom(draft.kind) ? draft.seed : null)
    setSheet(false)
  }
  useEffect(() => {
    if (!playing || !n) return
    const step = Math.max(60, (seconds * 1000) / n)
    const timer = window.setInterval(() => {
      setPos((p) => {
        if (p >= n - 1) {
          setPlaying(false)
          return p
        }
        return p + 1
      })
    }, step)
    return () => window.clearInterval(timer)
  }, [playing, n, seconds])

  const toggle = () => {
    if (!playing && pos >= n - 1) setPos(0)
    setPlaying((v) => !v)
  }

  const controls = (
    <>
      <ScenarioButton label={scenarioLabel(mode, start)} open={sheet} onClick={() => setSheet((v) => !v)} />
      <Select
        size="m"
        width={150}
        value={[region]}
        onUpdate={([v]) => { setRegion(v); setPos(0); setPlaying(false) }}
        options={[{ value: 'all', content: 'Все участки' }, ...Object.entries(REGION_NAMES).map(([value, content]) => ({ value, content }))]}
      />
      <SegmentedRadioGroup size="m" value={String(seconds)} onUpdate={(v) => setSeconds(Number(v))} options={DURATIONS} />
    </>
  )
  const playButton = (
    <Button view="action" size="m" onClick={toggle} disabled={!n} title="Пуск и пауза">
      <span className="flex items-center gap-1.5">
        {playing ? <span className="b-demo-pause" aria-hidden="true" /> : <IconPlay />}
        {playing ? 'Пауза' : pos >= n - 1 && n ? 'Ещё раз' : 'Пуск'}
      </span>
    </Button>
  )

  return (
    <DemoShell
      title="Имитация"
      info={
        <>
          Три плана на&nbsp;одних событиях. В&nbsp;обычный и&nbsp;тяжёлый день каждый участок проживает 17&nbsp;августа {SEEDS}&nbsp;раз, у&nbsp;каждого раза свой
          набор событий; день без событий и&nbsp;день с&nbsp;событиями из&nbsp;набора&nbsp;— по&nbsp;разу; свои события&nbsp;— один день выбранного участка,
          он считается на&nbsp;месте. Сценарий тот&nbsp;же, что в&nbsp;«Живом дне»:
          утро у&nbsp;планов своё, события и&nbsp;старт бригад одни. Контроль и&nbsp;базовый отвечают правилом п.&nbsp;2.3, наш план&nbsp;— перепланированием.
        </>
      }
      onClose={onClose}
      inRail
      menu
      extra={controls}
      play={playButton}
    >
      <ScenarioSheet open={sheet} onClose={() => setSheet(false)}
        footer={<ScenarioFooter draft={draft} onApply={apply} onReset={() => setDraft(DEFAULT_SCENARIO)} />}>
        <ScenarioForm draft={draft} onChange={setDraft} datasetId={formRegion} dataset={formData.data}
          settings={store.settings} sharePct={sharePct} hybridKm={hybridKm} offline={store.offline} />
      </ScenarioSheet>
      {data.isError ? (
        <p className="b-demo-empty">Гонка не посчитана: <code>uv run python -m bee_routing.race</code></p>
      ) : !data.data ? (
        <p className="b-demo-empty">Загружаем дни имитации…</p>
      ) : mode === 'custom' && customRun.isFetching ? (
        <div className="b-race-busy"><DemoBusy title="Проживаем день" detail={`${scenarioLabel(mode, start)} · ${REGION_NAMES[custom?.region ?? ''] ?? custom?.region}`} first={first} /></div>
      ) : mode === 'custom' && customRun.isError ? (
        <p className="b-demo-empty">День со&nbsp;своими событиями не&nbsp;посчитался: {String(customRun.error)}</p>
      ) : !n ? (
        <p className="b-demo-empty">В файле нет дней этого сценария.</p>
      ) : (
        <RaceBody runs={runs} prep={prep} pos={pos} region={region}
          onSeek={(p) => { setPlaying(false); setPos(p) }} />
      )}
    </DemoShell>
  )
}

function RaceBody({ runs, prep, pos, region, onSeek }: {
  runs: RaceRun[]
  prep: ReturnType<typeof prepare>
  pos: number
  region: string
  onSeek: (p: number) => void
}) {
  const n = runs.length
  const run = runs[pos]
  const upto = runs.slice(0, pos + 1)
  const scores = PLAYERS.map((p) => ({
    ...p,
    cum: prep.by[p.key].cum[pos],
    day: prep.by[p.key].day[pos],
    wins: prep.winner.slice(0, pos + 1).filter((w) => w === p.key).length,
    crews: upto.reduce((a, r) => a + r.players[p.key].engineers, 0) / upto.length,
    km: upto.reduce((a, r) => a + r.players[p.key].km, 0) / upto.length,
    rub: upto.reduce((a, r) => a + r.players[p.key].net_rub, 0) / upto.length,
  }))
  const leader = scores.reduce((b, s) => (s.cum > b.cum ? s : b), scores[0])

  const base = run.players.control

  // Гонка накопленного счёта: ось — по устоявшемуся счёту после первых трёх прогонов.
  const RW = 760
  const RH = 290
  const settled = PLAYERS.flatMap((p) => prep.by[p.key].cum.slice(Math.min(3, n - 1)))
  const lo = Math.max(0.4, Math.floor(Math.min(...settled) * 20) / 20)
  const hi = Math.min(1, Math.ceil(Math.max(...settled) * 20) / 20 + 0.01)
  const rx = (i: number) => 44 + ((RW - 56) * i) / Math.max(1, n - 1)
  const ry = (v: number) => RH - 22 - ((RH - 34) * (Math.max(lo, Math.min(hi, v)) - lo)) / Math.max(0.001, hi - lo)
  const cumPath = (a: number[]) => a.slice(0, pos + 1).map((v, i) => `${i ? 'L' : 'M'}${rx(i).toFixed(1)},${ry(v).toFixed(1)}`).join('')
  const bands = region === 'all'
    ? runs.map((r, i) => (i === 0 || r.region !== runs[i - 1].region ? i : -1)).filter((i) => i >= 0)
    : []
  const ticks = [lo, (lo + hi) / 2, hi]

  return (
    <div className="b-race b-scroll">
      <div className="b-race-cards">
        {scores.map((s) => (
          <div key={s.key} className={`b-race-card ${s.key}${s.key === leader.key && pos > 2 ? ' lead' : ''}`} style={{ '--c': s.color } as React.CSSProperties}>
            <div className="h">
              <i />{s.title}
              <HelpMark aria-label="Как этот план живёт день" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
                <div className="b-demo-info">{s.note}</div>
              </HelpMark>
              {s.key === leader.key && pos > 2 ? <em>впереди</em> : null}
            </div>
            <b>{pct(s.cum)}</b>
            <div className="n">вовремя с&nbsp;начала</div>
            <div className="row"><span>Этот день</span><span>{pct(s.day, 0)}</span></div>
            <div className="row"><span>Бригад в&nbsp;работе</span><span>{num(s.crews, 1)}</span></div>
            <div className="row"><span>Пробег за&nbsp;день</span><span>{num(s.km, 0)} км</span></div>
            <div className="row"><span>Итог дня</span><span>{num(Math.round(s.rub / 1000))} тыс. ₽</span></div>
            <div className="row"><span>Лучший за&nbsp;день</span><span>{s.wins} из&nbsp;{pos + 1}</span></div>
          </div>
        ))}
      </div>

      <div className="b-race-grid">
        <figure className="b-race-fig">
          <figcaption className="t">
            <span>
              День {pos + 1} из&nbsp;{n}: <b>{REGION_NAMES[run.region] ?? run.region}</b>,{' '}
              {runName(run)} · {run.due} заявок, {run.events.length} {plural(run.events.length, 'событие', 'события', 'событий')}
            </span>
            <HelpMark aria-label="Что такое день имитации" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
              <div className="b-race-help">
                День имитации&nbsp;— участок заново проживает 17&nbsp;августа. Утром каждый из&nbsp;трёх планов раскладывает заявки по&nbsp;бригадам
                по-своему. Днём на&nbsp;все три в&nbsp;одну и&nbsp;ту&nbsp;же минуту приходят одни и&nbsp;те&nbsp;же события: новые заявки, отмены, «клиента нет»,
                задержки, выбытие бригады. Вечером считаем, сколько заявок каждый сделал вовремя, сколько проехал и&nbsp;заработал.
                Набор событий №&nbsp;N&nbsp;— тот&nbsp;же день, что набор №&nbsp;N в&nbsp;«Живом дне».
              </div>
            </HelpMark>
          </figcaption>
          <div className="b-race-out" role="img" aria-label="Чем кончился день у каждого плана: вовремя, с опозданием, не сделано">
            {[...PLAYERS].sort((p, q) => run.players[q.key].on_time - run.players[p.key].on_time || run.players[p.key].km - run.players[q.key].km).map((p, k) => {
              const r = run.players[p.key]
              const part = (v: number) => `${(100 * v) / Math.max(1, run.due)}%`
              return (
                <div key={p.key} className={`o${k === 0 ? ' first' : ''}`}>
                  <div className="oh">
                    <span className="name" style={{ color: p.color }}>{p.title}</span>
                    {k === 0 ? <em style={{ background: p.color }}>Лучший</em> : null}
                    <span className="sum"><b>{r.on_time}</b> из&nbsp;{run.due} вовремя · {pct(r.on_time / Math.max(1, run.due), 0)}</span>
                  </div>
                  <div className="track">
                    <span className="ok" style={{ width: part(r.on_time), background: p.color }}>{r.on_time}</span>
                    {r.late ? <span className="late" style={{ width: part(r.late) }}>{r.late}</span> : null}
                    {r.missed ? <span className="miss" style={{ width: part(r.missed) }}>{r.missed}</span> : null}
                  </div>
                  {/* Путь и экономия — подписью: пробег, бригады, итог дня и разница к контролю, каждая цифра своим цветом. */}
                  <div className="meta">
                    {num(r.km, 0)} км · {r.engineers} {plural(r.engineers, 'бригада', 'бригады', 'бригад')} · {num(Math.round(r.net_rub / 1000))} тыс.&nbsp;₽
                    {p.key === 'control' ? null : <Delta r={r} base={base} />}
                  </div>
                </div>
              )
            })}
            <div className="key"><span><i className="ok" />вовремя</span><span><i className="late" />с&nbsp;опозданием</span><span><i className="miss" />не&nbsp;сделано</span></div>
          </div>
        </figure>

        <figure className="b-race-fig">
          <figcaption className="t">Доля заявок вовремя за&nbsp;все дни с&nbsp;первого</figcaption>
          <svg viewBox={`0 0 ${RW} ${RH}`} role="img" aria-label="Накопленная доля заявок вовремя у трёх планов по дням имитации">
            {bands.map((i, k) => (
              <g key={i} className={i <= pos ? 'band on' : 'band'}>
                <line x1={rx(i)} x2={rx(i)} y1={10} y2={RH - 22} />
                <text x={rx(i) + 4} y={k % 2 ? 32 : 20}>{REGION_NAMES[runs[i].region] ?? runs[i].region}</text>
              </g>
            ))}
            {ticks.map((v) => (
              <g key={v}>
                <line x1={44} x2={RW - 8} y1={ry(v)} y2={ry(v)} className="grid" />
                <text x={38} y={ry(v) + 4} textAnchor="end">{num(v * 100, 0)}&nbsp;%</text>
              </g>
            ))}
            {PLAYERS.map((p) => <path key={p.key} d={cumPath(prep.by[p.key].cum)} fill="none" stroke={p.color} strokeWidth={2.5} strokeLinejoin="round" />)}
            {PLAYERS.map((p) => <circle key={p.key} cx={rx(pos)} cy={ry(prep.by[p.key].cum[pos])} r={4} fill={p.color} />)}
            <line x1={rx(pos)} x2={rx(pos)} y1={10} y2={RH - 22} className="cursor" />
          </svg>
        </figure>
      </div>

      <figure className="b-race-fig b-race-strip">
        <figcaption className="t">
          Каждый день: доля заявок вовремя, красное&nbsp;— ниже 80&nbsp;%
          <HelpMark aria-label="Как считается" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
            <div className="b-race-help">
              Заявки дня&nbsp;— утренние и&nbsp;пришедшие днём, без отменённых и&nbsp;тех, где клиента не&nbsp;оказалось. Вовремя&nbsp;— работа началась
              до&nbsp;конца окна. Дорога у&nbsp;всех трёх считается одной моделью. Итог дня&nbsp;— ценность сделанного вовремя минус оклады, бонусы
              и&nbsp;дорога по&nbsp;тарифам из&nbsp;допущений.
            </div>
          </HelpMark>
        </figcaption>
        <div className="rows">
          {PLAYERS.map((p) => (
            <div key={p.key} className="r">
              <span className="l" style={{ color: p.color }}>{p.title}</span>
              <div className="cells" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>
                {prep.by[p.key].day.map((s, i) => (
                  <button key={i} type="button" onClick={() => onSeek(i)} style={{ background: i <= pos ? cellColor(s) : undefined }}
                    title={`${REGION_NAMES[runs[i].region] ?? runs[i].region}, ${runName(runs[i])}: ${pct(s, 0)}`} aria-label={`День ${i + 1}`} />
                ))}
              </div>
            </div>
          ))}
          <div className="r">
            <span className="l">Лучший за&nbsp;день</span>
            <div className="cells" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>
              {prep.winner.map((w, i) => (
                <i key={i} style={{ background: i <= pos ? PLAYERS.find((p) => p.key === w)!.color : undefined }} />
              ))}
            </div>
          </div>
        </div>
        <div className="scrub">
          <input type="range" min={0} max={n - 1} step={1} value={pos} aria-label="День имитации" onChange={(e) => onSeek(Number(e.target.value))} />
          <span>день 1</span><span>день {n}</span>
        </div>
      </figure>
    </div>
  )
}
