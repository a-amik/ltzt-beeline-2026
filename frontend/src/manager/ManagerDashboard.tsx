/**
 * Сводка руководителя — пять виджетов на один план «Всей Москвы» и его
 * разбивку по участкам (`GET /manager/dashboard`). Руководителю нужны три
 * ответа: идёт ли день к цели, где не хватает людей и во что обходится день.
 * Что горит сейчас, видит диспетчер в ленте от бригад; тревога бригады
 * здесь — красная точка у её имени. Отсюда порядок экрана:
 *
 * 1. Итоги города и строка «против контроля» — главный довод одной строкой.
 * 2. День по часам: визиты по плану к концу часа, отмеченные сделанными,
 *    окна, закрывшиеся к этому часу. Отставание видно раньше опоздания.
 * 3. Нагрузка: участки × окна; клетка ведёт в «Нагрузку» диспетчера.
 * 4. Бригады по загрузке: нормо-минуты против нормы дня, сверх нормы, бонус.
 *    Карточки 3 и 4 стоят рядом одной высоты: список бригад прокручивается.
 * 5. Из чего сложился итог: ценность выполненного минус оклады, бонусы, дорога.
 *
 * Графики — свой SVG без библиотек: цвета — токены темы, подписи — набором.
 * Пояснения «как посчитано» — в подсказках ⓘ, на экране только числа.
 */

import { useRef } from 'react'
import { HelpMark } from '@gravity-ui/uikit'
import { useWidth } from '../lib/media'
import { num, plural } from '../lib/ui'
import type { Dashboard } from './managerApi'
import './dashboard.css'

const LEVEL: Record<string, string> = { deficit: 'Дефицит', tight: 'Напряжённо', ok: 'В норме', free: 'Свободно' }
const SIGNAL: Record<string, string> = {
  sos: 'SOS', problem: 'Проблема', delay: 'Задерживается', flag: 'Контроль', unassigned: 'Без бригады',
}
const pct = (v: number) => `${num(v, Number.isInteger(v) ? 0 : 1)} %`
const signed = (v: number, digits = 0) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${num(Math.abs(v), digits)}`

function Help({ children }: { children: React.ReactNode }) {
  return (
    <HelpMark aria-label="Как посчитано" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
      <div className="b-dash-help">{children}</div>
    </HelpMark>
  )
}

export default function ManagerDashboard({ data }: { data: Dashboard }) {
  const names = new Map(data.sectors.map((s) => [s.id, s.name]))
  return (
    <div className="b-dash">
      <Totals data={data} />
      <HoursChart data={data} />
      <div className="b-dash-row">
        <LoadGrid data={data} />
        <CrewBars data={data} names={names} />
      </div>
      <Economy data={data} />
    </div>
  )
}

function Totals({ data }: { data: Dashboard }) {
  const t = data.totals
  const b = data.versus.benchmark
  const race = data.versus.race
  return (
    <section className="b-dash-totals" aria-label="Итоги дня">
      <div className={`b-dash-kpi${t.ok.on_time ? '' : ' bad'}`}>
        <small>Вовремя</small>
        <b>{num(t.on_time)} из {num(t.requests)}</b>
        <span>цель {data.targets.on_time_pct} %</span>
      </div>
      <div className="b-dash-kpi">
        <small>Бригад в работе</small>
        <b>{t.crews_used} из {t.crews_total}</b>
        <span>загрузка {pct(t.utilization_pct)}</span>
      </div>
      <div className="b-dash-kpi">
        <small>Итог дня</small>
        <b>{num(t.net_rub)} ₽</b>
        <span>пробег {num(t.km)} км</span>
      </div>
      <div className={`b-dash-kpi${t.unassigned ? ' bad' : ''}`}>
        <small>Без бригады и на завтра</small>
        <b>{t.unassigned + t.deferred}</b>
        <span>{t.late ? `опозданий ${t.late}` : 'опозданий нет'}</span>
      </div>
      {b ? (
        <div className="b-dash-vs">
          <small>
            Наш план против контроля заказчика
            <Help>
              Тот же день 17.08 и те же заявки: распределение из файла заказчика против нашего плана, дорога у обоих
              одной моделью. Ниже — синтетические дни со случайными событиями, где оба отвечают на одни и те же события.
            </Help>
          </small>
          <b>
            {signed(b.solver.engineers_used - b.control.engineers_used)} бригад · {signed(b.solver.on_time - b.control.on_time)} вовремя ·{' '}
            {signed((b.solver.net_rub - b.control.net_rub) / 1000)} тыс. ₽
          </b>
          {race ? (
            <span>
              На {race.days} синтетических {plural(race.days, 'дне', 'днях', 'днях')}: вовремя {pct(race.ours_pct)} против {pct(race.control_pct)} у контроля
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

/** День по часам: накопленные визиты по плану, отметки «сделано», окна, закрывшиеся к часу. */
function HoursChart({ data }: { data: Dashboard }) {
  const { hours, planned, done, due } = data.hours
  // Холст в ширину карточки: подписи осей — 12 px и на компьютере, и на телефоне.
  const box = useRef<HTMLElement>(null)
  const width = useWidth(box)
  const W = width ? Math.max(300, width) : 1200
  const H = W < 600 ? 180 : 220
  const max = Math.max(4, ...planned, ...due, ...done)
  const x = (i: number) => 44 + ((W - 60) * i) / Math.max(1, hours.length - 1)
  const y = (v: number) => H - 26 - ((H - 40) * v) / max
  const line = (vals: number[]) => vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const lastDone = done[done.length - 1] ?? 0
  const now = lastDone ? done.findIndex((v) => v === lastDone) : -1
  const ticks = [0, 0.5, 1].map((k) => Math.round(max * k))
  return (
    <figure ref={box} className="b-dash-card">
      <figcaption>
        <h3>День по часам</h3>
        <Help>
          Накопленно к концу часа: сколько визитов закончится по плану, сколько бригады отметили сделанными в своём
          приложении и у скольких заявок окно клиента уже закрылось. Линия плана выше линии окон — план идёт с запасом.
        </Help>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Визиты по плану, отметки и закрытые окна по часам">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={44} x2={W - 12} y1={y(v)} y2={y(v)} className="grid" />
            <text x={38} y={y(v) + 4} textAnchor="end">{num(v)}</text>
          </g>
        ))}
        <path d={line(due)} className="due" />
        <path d={line(planned)} className="planned" />
        {lastDone ? <path d={line(done.slice(0, now + 1))} className="done" /> : null}
        {now >= 0 ? <line x1={x(now)} x2={x(now)} y1={10} y2={H - 26} className="now" /> : null}
        {hours.map((h, i) => (h % (W < 600 ? 4 : 2) === 0 ? <text key={h} x={x(i)} y={H - 8} textAnchor="middle">{String(h).padStart(2, '0')}</text> : null))}
      </svg>
      <div className="b-dash-legend">
        <span><i className="planned" />По плану</span>
        <span><i className="done" />Сделано{lastDone ? '' : ' — отметок пока нет'}</span>
        <span><i className="due" />Окна закрылись</span>
      </div>
    </figure>
  )
}

/** Участки × окна: цвет — как на карте нагрузки; клетка ведёт в «Нагрузку» этого участка. */
function LoadGrid({ data }: { data: Dashboard }) {
  const { windows, rows } = data.load
  return (
    <section className="b-dash-card" aria-label="Нагрузка по участкам и окнам">
      <header>
        <h3>Нагрузка</h3>
        <Help>
          Спрос окна к тому, что бригады участка могут закрыть: визиты плана и свободное время рядом. Больше 100 % —
          дефицит, окно лучше не обещать. Клетка открывает «Нагрузку» у диспетчера.
        </Help>
      </header>
      <table className="b-dash-load">
        <thead>
          <tr>
            <th />
            {windows.map((w) => <th key={w}>{w.split('–')[0]}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th>{row.name}</th>
              {row.cells.map((c) => (
                <td key={c.window} className={c.level}>
                  <a href={`/deficit?sector=${encodeURIComponent(row.id)}`} title={`${row.name}, ${c.window}: ${LEVEL[c.level]}`}>
                    {c.demand_min ? pct(Math.round(c.pressure * 100)) : '—'}
                  </a>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="b-dash-legend">
        {(['deficit', 'tight', 'ok', 'free'] as const).map((l) => <span key={l}><i className={`lv ${l}`} />{LEVEL[l]}</span>)}
      </div>
      <SectorTable data={data} />
    </section>
  )
}

function SectorTable({ data }: { data: Dashboard }) {
  return (
    <table className="b-dash-sectors">
      <thead>
        <tr>
          <th>Участок</th>
          <th>Вовремя</th>
          <th>Бригад</th>
          <th>Загрузка</th>
          <th>Пробег</th>
        </tr>
      </thead>
      <tbody>
        {data.sectors.map((s) => (
          <tr key={s.id}>
            <th>{s.name}</th>
            <td className={s.ok.on_time ? '' : 'bad'}>{s.on_time} из {s.requests}</td>
            <td>{s.crews_used} из {s.crews_total}</td>
            <td className={s.ok.utilization ? '' : 'bad'}>{pct(s.utilization_pct)}</td>
            <td>{num(s.km)} км</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Бригады по загрузке: полоса — нормо-минуты, черта — норма дня, сверх нормы — другим цветом. */
function CrewBars({ data, names }: { data: Dashboard; names: Map<string, string> }) {
  const crews = data.crews
  const norm = crews[0]?.norm_day ?? 480
  const max = Math.max(norm * 1.5, ...crews.map((c) => c.norm_min))
  const over = crews.filter((c) => c.over_min > 0).length
  const idle = crews.filter((c) => c.norm_min < norm * 0.5).length
  return (
    <section className="b-dash-card b-dash-crewcard" aria-label="Бригады по загрузке">
      <header>
        <h3>Бригады по загрузке</h3>
        <span>
          сверх нормы {over} · меньше половины нормы {idle}
        </span>
        <Help>
          Нормо-минуты бригады за день против нормы дня ({norm} мин). Сверх нормы бригада работает за бонус — он
          справа. Короткая полоса — бригада простаивает, её можно отдать соседям или не выводить.
        </Help>
      </header>
      <ol className="b-dash-crews b-scroll">
        {crews.map((c) => {
          const base = Math.min(c.norm_min, norm)
          return (
            <li key={c.id}>
              <a href={`#crew/${c.id}`} target="_blank" rel="noreferrer" className="n" title={c.sector ? names.get(c.sector) : undefined}>
                {c.name}
                {c.alarms.length ? <i className="alarm" title={c.alarms.map((a) => SIGNAL[a] ?? a).join(', ')} /> : null}
              </a>
              <span className="bar">
                <span className="in" style={{ width: `${(100 * base) / max}%` }} />
                {c.over_min ? <span className="over" style={{ left: `${(100 * norm) / max}%`, width: `${(100 * c.over_min) / max}%` }} /> : null}
                <span className="norm" style={{ left: `${(100 * norm) / max}%` }} />
              </span>
              <span className="v">
                {c.norm_min} мин{c.bonus_rub ? ` · ${num(c.bonus_rub)} ₽` : ''}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Из чего сложился итог дня: полоса ценности, в ней затраты по статьям, остаток — итог. */
function Economy({ data }: { data: Dashboard }) {
  const rows = data.economy.sectors
  const max = Math.max(1, ...rows.map((r) => r.value_rub))
  const parts = [
    { key: 'payroll_rub', label: 'Оклады' },
    { key: 'bonus_rub', label: 'Бонусы' },
    { key: 'travel_rub', label: 'Дорога' },
    { key: 'wait_rub', label: 'Ожидание' },
    { key: 'sector_rub', label: 'Чужой участок' },
  ] as const
  return (
    <section className="b-dash-card" aria-label="Из чего сложился итог дня">
      <header>
        <h3>Из чего сложился итог дня</h3>
        <Help>
          Ценность выполненных визитов по тарифам минус оклады, бонусы за работу сверх нормы, дорога, ожидание у клиентов
          и выезды в чужой участок. Всё — по участку бригады, которая работала; сумма участков равна итогу дня.
        </Help>
      </header>
      <ol className="b-dash-econ">
        {rows.map((r) => (
          <li key={r.id}>
            <span className="n">{r.name}</span>
            <span className="bar" style={{ width: `${(100 * r.value_rub) / max}%` }}>
              {parts.map((p) => (r[p.key] ? <span key={p.key} className={p.key} style={{ flexGrow: r[p.key] }} title={`${p.label}: ${num(r[p.key])} ₽`} /> : null))}
              <span className="net_rub" style={{ flexGrow: Math.max(0, r.net_rub) }} title={`Итог: ${num(r.net_rub)} ₽`} />
            </span>
            <span className="v">
              <b>{num(r.net_rub)} ₽</b> из {num(r.value_rub)}
            </span>
          </li>
        ))}
      </ol>
      <div className="b-dash-legend">
        {parts.map((p) => <span key={p.key}><i className={`ec ${p.key}`} />{p.label}</span>)}
        <span><i className="ec net_rub" />Итог</span>
      </div>
    </section>
  )
}
