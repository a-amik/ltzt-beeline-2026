import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, SegmentedRadioGroup } from '@gravity-ui/uikit'
import { api } from '../../api'
import { num } from '../../lib/ui'
import { IconBolt, IconChart, IconCheck, IconClock, IconCompass, IconFlask, IconSliders, IconStar, IconUsers } from '../../lib/icons'
import type { RacePlayer, Reports } from '../../types'
import KpiTable from '../KpiTable'
import { ArtModels } from './art'
import { Figure, GroupBars, LineChart, Tiles } from './charts'
import { reportKpis } from './facts'

const SOLVERS = [
  { key: 'control', label: 'Контроль', color: 'var(--race-control)' },
  { key: 'ortools', label: 'OR-Tools', color: 'var(--b-route-2)' },
  { key: 'pyvrp', label: 'PyVRP', color: 'var(--b-route-5)' },
  { key: 'lns', label: 'LNS', color: 'var(--race-ours)' },
]

const RACE: { key: RacePlayer; label: string; color: string }[] = [
  { key: 'control', label: 'Контроль', color: 'var(--race-control)' },
  { key: 'baseline', label: 'Базовый, п. 2.3', color: 'var(--race-baseline)' },
  { key: 'ours', label: 'Наш план', color: 'var(--race-ours)' },
]

const median = (a: number[]) => {
  const s = [...a].sort((x, y) => x - y)
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : 0
}

export default function ModelsPage({ reports, onOpen }: { reports: Reports; onOpen: (demo: 'race') => void }) {
  const race = useQuery({ queryKey: ['race'], queryFn: () => api.race(), staleTime: Infinity, retry: false })
  const [budget, setBudget] = useState('4')
  const [simRegion, setSimRegion] = useState(reports.simulation?.regions[0]?.dataset_id ?? '')
  const search = reports.search
  const gen = reports.generalize
  const sim = reports.simulation

  const runs = (race.data?.runs ?? []).filter((r) => r.mode === 'normal' && (r.start ?? 'office') === 'office')
    .sort((a, b) => (race.data!.meta.regions.indexOf(a.region) - race.data!.meta.regions.indexOf(b.region)) || a.seed - b.seed)
  const due = runs.reduce((a, r) => a + r.due, 0)
  const shareOf = (key: RacePlayer) => (due ? runs.reduce((a, r) => a + r.players[key].on_time, 0) / due : 0)
  const cum = (key: RacePlayer) => {
    let on = 0
    let d = 0
    return runs.map((r) => { on += r.players[key].on_time; d += r.due; return d ? on / d : null })
  }
  const bands = runs.map((r, i) => (i === 0 || r.region !== runs[i - 1].region ? { from: i, label: { vostok: 'Восток', 'yugo-vostok': 'Юго-восток', yugocentr: 'Югоцентр' }[r.region] ?? r.region } : null))
    .filter((b): b is { from: number; label: string } => b !== null)
  const wins = runs.filter((r) => RACE.every((p) => r.players.ours.on_time >= r.players[p.key].on_time)).length

  const genDays = gen?.regions.reduce((a, r) => a + r.days.length, 0) ?? 0
  const genOk = gen?.regions.reduce((a, r) => a + r.days.filter((d) => d.solver.on_time >= d.baseline.on_time).length, 0) ?? 0

  return (
    <article className="b-an">
      <header className="b-an-hero">
        <div className="b-an-art"><ArtModels /></div>
        <p className="kick">О проекте · модели</p>
        <h1>Как выбирается план и&nbsp;как мы его проверяли</h1>
        <p className="lede">
          Сервис ищет маршруты, которые укладываются в&nbsp;согласованное с&nbsp;клиентом время. Из&nbsp;ценности заявок, начатых вовремя,
          он вычитает оклады, бонусы и&nbsp;расходы на&nbsp;дорогу. Три решателя рассчитывают варианты, после чего выбирается лучший по&nbsp;этой
          цели. Результат проверен на&nbsp;новых наборах заявок и&nbsp;в&nbsp;сравнении трёх планов при&nbsp;одинаковых событиях дня.
        </p>
        <Tiles items={[
          { value: runs.length ? `${num(shareOf('ours') * 100, 1)} %` : '—', icon: <IconClock />, label: 'заявок вовремя в сравнении', note: runs.length ? `контроль ${num(shareOf('control') * 100, 1)} %, базовый ${num(shareOf('baseline') * 100, 1)} %` : 'сравнение ещё не рассчитано' },
          { value: runs.length ? `${wins} из ${runs.length}` : '—', icon: <IconStar />, label: 'прогонов без проигрыша', note: 'по числу заявок вовремя' },
          { value: `${genOk} из ${genDays}`, icon: <IconCompass />, label: 'новых сценариев без проигрыша', note: 'по числу заявок вовремя' },
          { value: '3', icon: <IconSliders />, label: 'способа расчёта', note: 'OR-Tools, PyVRP, LNS' },
        ]} />
      </header>

      <section id="m-goal">
        <h2><span className="ic"><IconCheck /></span>Что делает план допустимым и&nbsp;выгодным</h2>
        <p>
          Решатель ищет план с&nbsp;наибольшим итогом дня: ценность заявок, начатых вовремя, за&nbsp;вычетом окладов вышедших бригад,
          бонусов сверх нормы и&nbsp;расходов на&nbsp;дорогу. Заявку разрешено оставить без бригады, но&nbsp;это снижает оценку плана.
          Тарифы заданы как допущения команды; руководитель может изменить их в&nbsp;настройках.
        </p>
        <div className="b-an-cards">
          <div><h4>Кто может приехать</h4><p>Нужный навык, подходящий транспорт, выход бригады в&nbsp;смену и&nbsp;запас оборудования.</p></div>
          <div><h4>Когда нужно приехать</h4><p>Согласованное с&nbsp;клиентом время, срок реакции на&nbsp;аварию и&nbsp;обед бригады.</p></div>
          <div><h4>Сколько успеют сделать</h4><p>Длительность смены, норма дня, дорога с&nbsp;учётом пробок и&nbsp;выезд в&nbsp;другой участок.</p></div>
        </div>
      </section>

      <section id="m-base">
        <h2><span className="ic"><IconUsers /></span>С&nbsp;чем сравниваем</h2>
        <p>
          <b>Базовый вариант</b>&nbsp;— правило из&nbsp;п.&nbsp;2.3 задания: заявки идут в&nbsp;порядке файла, срочные&nbsp;— первыми. Каждую заявку
          добавляют в&nbsp;конец маршрута первой подходящей бригады. <b>Контроль</b>&nbsp;— распределение заказчика из&nbsp;контрольного файла:
          бригады сохранены, визиты упорядочены по&nbsp;времени клиента. Для всех планов используется одна модель дорог;
          просрочки в&nbsp;контрольном плане не&nbsp;исправляются.
        </p>
      </section>

      {search ? (
        <section id="m-portfolio">
          <h2><span className="ic"><IconChart /></span>Три решателя, одна оценка</h2>
          <p>
            Победитель зависит от&nbsp;участка и&nbsp;времени расчёта. PyVRP чаще сокращает пробег, OR-Tools и&nbsp;LNS чаще дают более высокий
            итог дня. Поэтому решатели работают параллельно, а&nbsp;их планы сравниваются по&nbsp;одной формуле. В&nbsp;этих замерах увеличение
            времени поиска с&nbsp;4&nbsp;секунд до&nbsp;минуты улучшало итог не&nbsp;более чем на&nbsp;3&nbsp;%.
          </p>
          <div className="b-rep-bar">
            <SegmentedRadioGroup size="m" value={budget} onUpdate={setBudget}
              options={search.budgets.map((b) => ({ value: String(b), content: `Поиск ${b} с` }))} />
          </div>
          <Figure n={1} title="Итог дня, тыс. ₽: ценность вовремя минус затраты" legend={SOLVERS}>
            <GroupBars
              groups={search.regions.map((r) => ({
                label: r.name,
                values: SOLVERS.map((s) => {
                  const row = r.rows[s.key === 'control' ? 'control' : `${s.key}@${budget}`]
                  return row ? Number(row.net_rub) / 1000 : null
                }),
              }))}
              series={SOLVERS} fmt={(v) => num(v, 0)} />
          </Figure>
        </section>
      ) : null}

      {gen ? (
        <section id="m-general">
          <h2><span className="ic"><IconSliders /></span>Проверка на&nbsp;новых днях: {gen.meta.days ?? 10} сценариев на&nbsp;участок</h2>
          <p>
            Каждый сценарий составлен на&nbsp;основе дня заказчика: сохранены время визитов, навыки и&nbsp;длительность работ,
            а&nbsp;адреса сдвинуты поблизости. Наш и&nbsp;базовый планы рассчитаны для&nbsp;одних и&nbsp;тех&nbsp;же сценариев. На&nbsp;графике&nbsp;—
            медиана числа заявок вовремя.
          </p>
          <Figure n={2} title="Заявки вовремя, медиана по&nbsp;синтетическим дням" legend={[
            { label: 'Базовый, п. 2.3', color: 'var(--race-baseline)' }, { label: 'Наш план', color: 'var(--race-ours)' }]}>
            <GroupBars
              groups={gen.regions.map((r) => ({ label: `${r.name}, ${r.requests} заявок`, values: [median(r.days.map((d) => d.baseline.on_time)), median(r.days.map((d) => d.solver.on_time))] }))}
              series={[{ label: 'Базовый, п. 2.3', color: 'var(--race-baseline)' }, { label: 'Наш план', color: 'var(--race-ours)' }]}
              fmt={(v) => num(v, 1)} />
          </Figure>
        </section>
      ) : null}

      <section id="m-race">
        <h2><span className="ic"><IconFlask /></span>Три плана в&nbsp;одинаковых условиях</h2>
        <p>
          Для каждого участка смоделированы 20&nbsp;дней с&nbsp;новыми заявками, отменами, отсутствием клиента, переносами и&nbsp;задержками.
          Все три плана получают одинаковые события. Контрольный и&nbsp;базовый планы отвечают на&nbsp;них правилом из&nbsp;п.&nbsp;2.3,
          наш&nbsp;— пересчитывает назначения. Видно и&nbsp;ограничение: новая заявка иногда вытесняет визит, намеченный на&nbsp;утро.
        </p>
        {runs.length ? (
          <Figure n={3} title="Доля заявок вовремя по&nbsp;мере накопления 60&nbsp;прогонов; все бригады стартуют из&nbsp;офиса" legend={RACE}>
            <LineChart x={runs.map((_, i) => String(i + 1))} lo={0.6} hi={1} ticks={[0.6, 0.7, 0.8, 0.9, 1]} fmt={(v) => `${num(v * 100, 0)} %`}
              series={RACE.map((p) => ({ key: p.key, label: p.label, color: p.color, values: cum(p.key) }))} bands={bands} />
          </Figure>
        ) : (
          <p className="b-muted">Данных сравнения пока нет. Для расчёта: <code>uv run python -m bee_routing.race</code></p>
        )}
        <div className="b-an-acts"><Button view="action" size="l" onClick={() => onOpen('race')}>Открыть имитацию</Button></div>
      </section>

      {sim ? (
        <section id="m-rules">
          <h2><span className="ic"><IconBolt /></span>Как отвечать на&nbsp;новую заявку</h2>
          <p>
            Новую заявку можно предложить бригадам с&nbsp;бонусом, назначить подходящей бригаде без предложения или перенести
            на&nbsp;следующий день. Эти правила проверены на&nbsp;одинаковых событиях. Диспетчер выбирает правило в&nbsp;настройках;
            ниже приведены средние результаты прогонов.
          </p>
          <div className="b-rep-bar">
            <SegmentedRadioGroup size="m" value={simRegion} onUpdate={setSimRegion}
              options={sim.regions.map((r) => ({ value: r.dataset_id, content: r.name }))} />
          </div>
          {(() => {
            const current = sim.regions.find((r) => r.dataset_id === simRegion) ?? sim.regions[0]
            return <KpiTable kpis={reportKpis(sim.kpis)} columns={current.runs.map((run) => ({ key: run.policy, label: run.label, kpis: run.kpis, ours: run.policy === 'offer' }))} />
          })()}
        </section>
      ) : null}
    </article>
  )
}
