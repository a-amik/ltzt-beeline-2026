import { num } from '../../lib/ui'
import { IconChart, IconRoute, IconUsers } from '../../lib/icons'
import type { Reports } from '../../types'
import { ArtMileage } from './art'
import { Figure, GroupBars, Tiles } from './charts'

/** Отчёт по исполнителям (`GET /reports` → `mileage`, прогон `python -m bee_routing.mileage`). */
export interface Mileage {
  date: string
  commit?: string
  plans: { key: PlanKey; label: string }[]
  zones: {
    id: string
    name: string
    start: string
    engineers: ({ id: string; name: string } & Record<PlanKey, { km: number; stops: number }>)[]
    totals: Record<PlanKey, { engineers: number; km: number; on_time: number; unassigned: number; requests: number }>
  }[]
}
type PlanKey = 'control' | 'baseline' | 'solver'

const PLANS: { key: PlanKey; label: string; color: string }[] = [
  { key: 'control', label: 'Контроль', color: 'var(--race-control)' },
  { key: 'baseline', label: 'Базовый', color: 'var(--b-route-5)' },
  { key: 'solver', label: 'Наш план', color: 'var(--race-ours)' },
]
const km = (v: number) => (v ? `${num(v, 1)}` : '—')

export default function MileagePage({ reports }: { reports: Reports }) {
  const m = (reports as Reports & { mileage?: Mileage | null }).mileage
  if (!m?.zones.length) {
    return <article className="b-an"><p className="b-demo-empty">Отчёт по исполнителям ещё не посчитан: <code>python -m bee_routing.mileage</code>.</p></article>
  }
  // Участки — наборы, где у каждой бригады своя зона; «Вся Москва» — те же заявки одним планом без границ зон.
  const whole = m.zones.find((z) => z.id === 'moskva')
  const parts = m.zones.filter((z) => z.id !== 'moskva')
  const sum = (key: PlanKey, f: 'engineers' | 'km' | 'on_time' | 'unassigned' | 'requests') => parts.reduce((a, z) => a + z.totals[key][f], 0)
  const t = (key: PlanKey) => ({ engineers: sum(key, 'engineers'), km: sum(key, 'km'), on_time: sum(key, 'on_time'), unassigned: sum(key, 'unassigned'), requests: sum(key, 'requests') })
  const ours = t('solver'), ctrl = t('control'), base = t('baseline')

  return (
    <article className="b-an">
      <header className="b-an-hero">
        <div className="b-an-art"><ArtMileage /></div>
        <p className="kick">О проекте · отчёт по&nbsp;исполнителям</p>
        <h1>Пробег каждого исполнителя</h1>
        <p className="lede">
          Вторая обязательная метрика задания&nbsp;— пробег каждого исполнителя. Мы посчитали три плана на&nbsp;одних
          заявках и&nbsp;одной модели дорог: контрольное распределение, базовый вариант из&nbsp;п.&nbsp;2.3 и&nbsp;наш план. По&nbsp;участкам
          в&nbsp;нашем плане {num(ours.on_time)} из&nbsp;{num(ours.requests)} заявок начинаются вовремя; работают {ours.engineers} исполнителей
          против {ctrl.engineers} в&nbsp;контроле.{whole ? <> Пробег за&nbsp;день, когда бригада может заехать в&nbsp;чужой участок,&nbsp;— {km(whole.totals.solver.km)}&nbsp;км
          против {km(whole.totals.control.km)} у&nbsp;контроля и&nbsp;{km(whole.totals.baseline.km)} у&nbsp;базового; в&nbsp;границах своих участков&nbsp;— {km(ours.km)}&nbsp;км.</>
            : <> Пробег&nbsp;— {km(ours.km)}&nbsp;км против {km(ctrl.km)} у&nbsp;контроля и&nbsp;{km(base.km)} у&nbsp;базового.</>}
        </p>
        <Tiles items={[
          { value: `${ours.engineers} из ${ctrl.engineers}`, icon: <IconUsers />, label: 'исполнителей в нашем плане', note: `контроль и базовый — ${ctrl.engineers}` },
          // Главное число пробега — без границ участков: оно же стоит на странице «Решение и результат».
          ...(whole ? [{ value: `${km(whole.totals.solver.km)} км`, icon: <IconRoute />, label: 'пробег за день, без границ участков', note: `контроль — ${km(whole.totals.control.km)} км, базовый — ${km(whole.totals.baseline.km)} км` }] : []),
          { value: `${km(ours.km)} км`, icon: whole ? <IconChart /> : <IconRoute />, label: 'в границах своих участков', note: `контроль — ${km(ctrl.km)} км, базовый — ${km(base.km)} км` },
        ]} />
      </header>

      <section id="mi-sum">
        <h2><span className="ic"><IconChart /></span>Сводка по&nbsp;участкам</h2>
        <p>
          Исполнителем считаем бригаду хотя&nbsp;бы с&nbsp;одной заявкой. Возвращение в&nbsp;стартовую точку в&nbsp;пробег
          не&nbsp;входит (п.&nbsp;2.4 задания). Время поиска плана ограничено, поэтому от&nbsp;прогона к&nbsp;прогону пробег
          может немного отличаться.
        </p>
        <Figure n={1} title="Суммарный пробег, км" legend={PLANS}>
          <GroupBars groups={m.zones.map((z) => ({ label: z.name, values: PLANS.map((p) => z.totals[p.key].km) }))}
            series={PLANS} fmt={(v) => num(v, 1)} />
        </Figure>
        <table className="b-an-table num">
          <thead><tr><th>Участок</th><th>План</th><th>Исполнителей</th><th>Пробег, км</th><th>В срок</th><th>Без исполнителя</th></tr></thead>
          <tbody>{m.zones.flatMap((z) => PLANS.map((p) => (
            <tr key={`${z.id}-${p.key}`}><td>{p.key === 'control' ? z.name : ''}</td><td>{p.label}</td><td>{z.totals[p.key].engineers}</td>
              <td>{km(z.totals[p.key].km)}</td><td>{z.totals[p.key].on_time}</td><td>{z.totals[p.key].unassigned}</td></tr>
          )))}</tbody>
        </table>
      </section>

      {parts.map((z) => (
        <section key={z.id} id={`mi-${z.id}`}>
          <h2><span className="ic"><IconRoute /></span>{z.name}: пробег по&nbsp;исполнителям</h2>
          <table className="b-an-table num">
            <thead><tr><th>Исполнитель</th>{PLANS.map((p) => <th key={p.key}>{p.label}, км</th>)}{PLANS.map((p) => <th key={`s-${p.key}`}>{p.label}, визитов</th>)}</tr></thead>
            <tbody>
              {z.engineers.map((e) => (
                <tr key={e.id}><td>{e.name}</td>{PLANS.map((p) => <td key={p.key}>{e[p.key].stops ? km(e[p.key].km) : '—'}</td>)}
                  {PLANS.map((p) => <td key={`s-${p.key}`}>{e[p.key].stops || '—'}</td>)}</tr>
              ))}
              <tr><td><b>Итого</b></td>{PLANS.map((p) => <td key={p.key}><b>{km(z.totals[p.key].km)}</b></td>)}
                {PLANS.map((p) => <td key={`s-${p.key}`}><b>{z.engineers.reduce((a, e) => a + e[p.key].stops, 0)}</b></td>)}</tr>
            </tbody>
          </table>
        </section>
      ))}
      <p className="b-an-note">Прогон {m.date}{m.commit ? `, коммит ${m.commit}` : ''}. Таблицы отчёта лежат в&nbsp;<code>data/mileage/report.md</code>.</p>
    </article>
  )
}
