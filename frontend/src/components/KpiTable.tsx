/**
 * Таблица показателей рядом: строки — показатели, столбцы — планы или прогоны.
 * Лучшее значение строки набрано жирным, худшее — красным: «на 25 заявок
 * больше вовремя» читается только тогда, когда видны все числа. Строки без
 * «лучше» (сколько заявок пришло, загрузка) не красятся.
 */

import type { KpiLabel } from '../types'
import { num } from '../lib/ui'

export interface KpiColumn {
  key: string
  label: string
  kpis: Record<string, number>
  ours?: boolean
}

const NEUTRAL = new Set(['requests_total', 'breaks', 'over_norm_engineers', 'utilization_pct', 'intraday_total', 'offers_sent'])

function show(value: number, unit: string): string {
  // Рубли — без копеек, даже когда число — среднее по прогонам.
  const digits = Number.isInteger(value) || unit === '₽' ? 0 : 1
  return `${num(value, digits)}${unit ? ` ${unit}` : ''}`
}

export default function KpiTable({ columns, kpis }: { columns: KpiColumn[]; kpis: KpiLabel[] }) {
  return (
    <table className="b-cmp">
      <thead>
        <tr>
          <th>Показатель</th>
          {columns.map((column) => (
            <th key={column.key} className={column.ours ? 'ours' : undefined}>
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {kpis.map((kpi) => {
          const values = columns.map((column) => column.kpis[kpi.key] ?? 0)
          const distinct = new Set(values).size > 1
          const best = kpi.less_is_better ? Math.min(...values) : Math.max(...values)
          const worst = kpi.less_is_better ? Math.max(...values) : Math.min(...values)
          return (
            <tr key={kpi.key}>
              <td>{kpi.label}</td>
              {columns.map((column, index) => {
                const value = values[index]
                const tone = !distinct || NEUTRAL.has(kpi.key) ? '' : value === best ? 'best' : value === worst ? 'worst' : ''
                return (
                  <td key={column.key} className={[tone, column.ours ? 'ours' : ''].join(' ').trim() || undefined}>
                    {show(value, kpi.unit)}
                  </td>
                )
              })}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
