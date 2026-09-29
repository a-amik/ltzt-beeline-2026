import { useState } from 'react'
import { Button, SegmentedRadioGroup } from '@gravity-ui/uikit'
import { activePlan, useStore } from '../../store'
import { num } from '../../lib/ui'
import { IconBolt, IconClock, IconCompare, IconRoute, IconSearch, IconSliders, IconUsers } from '../../lib/icons'
import type { Reports } from '../../types'
import KpiTable from '../KpiTable'
import { ArtSolution } from './art'
import { Chain, Figure, GroupBars, Tiles } from './charts'
import { REPAIR, STAND, reportKpis } from './facts'

export const PLAN_SERIES = [
  { key: 'control', label: 'Контроль', color: 'var(--race-control)' },
  { key: 'baseline', label: 'Базовый, п. 2.3', color: 'var(--race-baseline)' },
  { key: 'solver', label: 'Наш план', color: 'var(--race-ours)' },
]

type Bench = NonNullable<Reports['benchmark']>

const kpi = (b: Bench, region: string, key: string, name: string) =>
  b.regions.find((r) => r.dataset_id === region)?.rows.find((row) => row.key === key)?.kpis[name] ?? null

const total = (b: Bench, key: string, name: string) =>
  b.regions.reduce((a, r) => a + (r.rows.find((row) => row.key === key)?.kpis[name] ?? 0), 0)

/** Пример объяснения из текущего плана: кому отдали, какие проверки прошли, почему не другой. */
function ExplainExample() {
  const store = useStore()
  const plan = activePlan(store)
  const entry = plan ? Object.entries(plan.explanations ?? {}).find(([, e]) => e.alternatives.length > 0) : undefined
  if (!entry || !store.dataset) {
    return <p className="b-muted">Откройте план дня, чтобы увидеть объяснение назначения на&nbsp;конкретном примере.</p>
  }
  const [rid, exp] = entry
  const req = store.dataset.requests.find((r) => r.id === rid)
  const name = (id: string) => store.dataset?.engineers.find((e) => e.id === id)?.name ?? id
  return (
    <div className="b-an-explain">
      <div className="q"><b>Заявка {rid}</b>{req ? <span>{req.address} · окно {req.window_start}–{req.window_end}</span> : null}</div>
      <div className="a"><b>Почему {name(exp.engineer_id)}</b>
        <ul>{exp.checks.map((c) => <li key={c.kind} className={c.ok ? 'ok' : 'bad'}>{c.text}</li>)}</ul>
      </div>
      <div className="a"><b>Почему не другая бригада</b>
        <ul>{exp.alternatives.slice(0, 3).map((a) => <li key={a.engineer_id} className={a.feasible ? 'muted' : 'bad'}>{name(a.engineer_id)}: {a.text}</li>)}</ul>
      </div>
    </div>
  )
}

export default function SolutionPage({ reports, onOpen }: { reports: Reports; onOpen: (demo: 'compare' | 'race') => void }) {
  const b = reports.benchmark
  const [region, setRegion] = useState(b?.regions[0]?.dataset_id ?? '')
  if (!b) return <p className="b-demo-empty">Данные сравнения пока недоступны. Для пересчёта: <code>python -m bee_routing.benchmark</code></p>
  const requests = total(b, 'control', 'requests_total')
  const current = b.regions.find((r) => r.dataset_id === region) ?? b.regions[0]
  const groups = (name: string) => b.regions.map((r) => ({ label: r.name, values: PLAN_SERIES.map((s) => kpi(b, r.dataset_id, s.key, name)) }))

  return (
    <article className="b-an">
      <header className="b-an-hero">
        <div className="b-an-art"><ArtSolution /></div>
        <p className="kick">О проекте · решение</p>
        <h1>Все заявки вовремя с&nbsp;меньшим числом бригад</h1>
        <p className="lede">
          Сервис распределяет заявки между бригадами, строит маршруты с&nbsp;учётом дорожной обстановки и&nbsp;объясняет назначения.
          Когда условия дня меняются, план пересчитывается. На&nbsp;данных заказчика за&nbsp;17&nbsp;августа наш план обеспечил своевременное
          начало всех {num(requests)} заявок. В&nbsp;распределении заказчика вовремя начались {num(total(b, 'control', 'on_time'))},
          в&nbsp;базовом варианте из&nbsp;задания&nbsp;— {num(total(b, 'baseline', 'on_time'))}.
        </p>
        <Tiles items={[
          { value: `${num(total(b, 'solver', 'on_time'))} из ${num(requests)}`, icon: <IconClock />, label: 'заявок вовремя', note: `контроль ${num(total(b, 'control', 'on_time'))}, базовый ${num(total(b, 'baseline', 'on_time'))}` },
          { value: num(total(b, 'solver', 'engineers_used')), icon: <IconUsers />, label: 'бригад в работе', note: `у контроля и базового ${num(total(b, 'control', 'engineers_used'))}` },
          { value: `${num(total(b, 'solver', 'distance_km'))} км`, icon: <IconRoute />, label: 'пробег за день', note: `контроль ${num(total(b, 'control', 'distance_km'))}, базовый ${num(total(b, 'baseline', 'distance_km'))}` },
          { value: '4 с', icon: <IconSearch />, label: 'поиск решения', note: 'бюджет на один участок' },
        ]} />
      </header>

      <section id="s-chain">
        <h2><span className="ic"><IconRoute /></span>От&nbsp;заявки до&nbsp;маршрута</h2>
        <p>
          Сервис получает файл заявок и&nbsp;определяет координаты адресов. Время в&nbsp;пути он считает по&nbsp;дорожной сети Москвы с&nbsp;учётом
          пробок по&nbsp;часам. Затем решатель назначает бригады и&nbsp;строит маршруты. Причины назначений формируются из&nbsp;тех&nbsp;же проверок,
          которые использованы при расчёте. Все три экрана получают данные через единый API.
        </p>
        <Figure n={1} title="Устройство решения">
          <Chain cols={[
            { title: 'Данные', items: [
              { b: 'Заявки дня', s: 'файл заказчика: время визита, тип работ, адрес' },
              { b: 'Дороги и пробки', s: 'OSRM по карте OpenStreetMap, профиль часа по 2ГИС' },
              { b: 'Допущения', s: 'тарифы, состав бригад и запасы — в настройках' },
            ] },
            { title: 'Расчёт на Python', items: [
              { b: 'Решатели', s: 'OR-Tools, PyVRP и LNS; выбирается лучший результат' },
              { b: 'Проверки', s: 'навык, транспорт, время визита, смена, норма дня' },
              { b: 'Перепланирование', s: 'точечное изменение плана после события' },
            ] },
            { title: 'Сервис', items: [
              { b: 'API', s: 'FastAPI: план, событие, сравнение, отчёты' },
              { b: 'Экраны', s: 'React, Gravity UI, MapLibre' },
              { b: 'Стенд', s: `${STAND.url}, Yandex Cloud` },
            ] },
            { title: 'Кто пользуется', items: [
              { b: 'Диспетчер', s: 'заявки, инженеры, дефицит, события' },
              { b: 'Бригада', s: 'маршрут, отметки о работе, новые заявки' },
              { b: 'Руководитель', s: 'итог дня и правила расчёта' },
            ] },
          ]} />
        </Figure>
      </section>

      <section id="s-result">
        <h2><span className="ic"><IconCompare /></span>Контрольный день: все заявки вовремя</h2>
        <p>
          Мы сравнили три плана на&nbsp;одних заявках и&nbsp;с&nbsp;одной моделью дорог: распределение заказчика, базовый вариант из&nbsp;п.&nbsp;2.3
          задания и&nbsp;наш расчёт. Заявка считается выполненной с&nbsp;опозданием, если работа началась после конца согласованного окна.
          На&nbsp;Юго-востоке распределение заказчика даёт меньший пробег, но&nbsp;приводит к&nbsp;{num(kpi(b, 'yugo-vostok', 'control', 'late') ?? 0)} опозданиям
          на&nbsp;{num(kpi(b, 'yugo-vostok', 'control', 'late_min') ?? 0)} минут суммарно.
        </p>
        <Figure n={2} title="Заявки вовремя по&nbsp;участкам" legend={PLAN_SERIES}>
          <GroupBars groups={groups('on_time')} series={PLAN_SERIES} fmt={(v) => num(v)} />
        </Figure>
        <Figure n={3} title="Бригады в&nbsp;работе и&nbsp;пробег: две метрики задания" legend={PLAN_SERIES}>
          <div className="b-an-pair">
            <GroupBars groups={groups('engineers_used')} series={PLAN_SERIES} fmt={(v) => num(v)} />
            <GroupBars groups={groups('distance_km')} series={PLAN_SERIES} fmt={(v) => `${num(v)} км`} />
          </div>
        </Figure>
        <details className="b-an-more">
          <summary>Все 20&nbsp;показателей по&nbsp;участку</summary>
          <div className="b-rep-bar">
            <SegmentedRadioGroup size="m" value={region} onUpdate={setRegion}
              options={b.regions.map((r) => ({ value: r.dataset_id, content: r.name }))} />
          </div>
          <KpiTable kpis={reportKpis(b.kpis)} columns={current.rows.map((row) => ({ ...row, ours: row.key === 'solver' }))} />
        </details>
      </section>

      <section id="s-explain">
        <h2><span className="ic"><IconUsers /></span>Почему заявка досталась этой бригаде</h2>
        <p>
          Сервис показывает, какие проверки прошла выбранная бригада и&nbsp;почему заявку не&nbsp;получили другие. Объяснение берётся из&nbsp;условий
          расчёта: навыков, времени, транспорта и&nbsp;запасов. Для заявки без назначения также указана причина.
        </p>
        <Figure n={4} title="Объяснение одного назначения в&nbsp;текущем плане">
          <ExplainExample />
        </Figure>
      </section>

      <section id="s-replan">
        <h2><span className="ic"><IconBolt /></span>Когда условия меняются, план пересчитывается</h2>
        <p>
          Событием может стать новая или отменённая заявка, отсутствие клиента, перенос визита, задержка или выбытие бригады.
          После одной отмены на&nbsp;Юго-востоке полный пересчёт сдвинул {REPAIR.fullOneCancel} визитов; точечный пересчёт обычно меняет
          {REPAIR.perEvent} визитов на&nbsp;событие. Визиты, до&nbsp;которых осталось менее {REPAIR.lockMin} минут, не&nbsp;переносятся.
          Поведение в&nbsp;течение дня показано в&nbsp;«Живом дне», проверка на&nbsp;60&nbsp;сценариях&nbsp;— в&nbsp;«Имитации».
        </p>
        <div className="b-an-acts">
          <Button view="action" size="l" onClick={() => onOpen('compare')}>Открыть живой день</Button>
          <Button view="outlined" size="l" onClick={() => onOpen('race')}>Открыть имитацию</Button>
        </div>
      </section>

      <section id="s-run">
        <h2><span className="ic"><IconSliders /></span>Как запустить</h2>
        <p>В&nbsp;репозитории уже есть данные трёх участков, координаты адресов и&nbsp;матрицы времени в&nbsp;пути. Поэтому для запуска прототипа не&nbsp;нужно отдельно готовить данные или поднимать маршрутизатор.</p>
        <pre className="b-an-code">{`make setup      # зависимости сервера и интерфейса
make dev-api    # API на http://localhost:8000
make dev-web    # интерфейс на http://localhost:5173
make test       # тесты сервера
uv run python -m bee_routing.race   # гонка планов для «Имитации»`}</pre>
        <p className="b-muted">Стенд: <a href={STAND.url} target="_blank" rel="noreferrer">{STAND.url.replace('https://', '')}</a>.</p>
      </section>
    </article>
  )
}
