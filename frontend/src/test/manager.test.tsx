/**
 * Экран руководителя: итоги города против цели и против контроля,
 * нагрузка участков и бригады. Версии дня: действующая помечена, «Вернуть» зовёт сервер.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ManagerApp from '../manager/ManagerApp'
import VersionsView from '../manager/VersionsView'

const restored: string[] = []

vi.mock('../manager/managerApi', () => ({
  ORDER_RU: { on_time_crews_rub: 'вовремя → бригады → итог в рублях', on_time_rub_crews: '', sum: '' },
  managerApi: {
    dashboard: async () => ({
      dataset_id: 'moskva', name: 'Вся Москва', date: '2026-08-17', plan_id: 'p9',
      targets: { on_time_pct: 95, utilization_pct: 65 },
      totals: { requests: 205, on_time: 190, on_time_pct: 92.7, late: 3, crews_used: 25, crews_total: 35, utilization_pct: 74.9, km: 755, unassigned: 2, deferred: 1, ok: { on_time: false, utilization: true }, net_rub: 1309608 },
      sectors: [{ id: 'vostok', name: 'Восток', requests: 66, on_time: 60, on_time_pct: 90.9, late: 1, crews_used: 8, crews_total: 12, utilization_pct: 70, km: 200, unassigned: 1, deferred: 0, ok: { on_time: false, utilization: true } }],
      hours: { hours: [8, 9, 10], planned: [0, 5, 10], done: [0, 3, 0], due: [0, 2, 8] },
      load: { windows: ['10:00–12:00'], rows: [{ id: 'vostok', name: 'Восток', cells: [{ window: '10:00–12:00', pressure: 1.2, level: 'deficit', demand_min: 300, unassigned: 1 }] }] },
      crews: [{ id: 'lebedev', name: 'Лебедев', sector: 'vostok', visits: 7, norm_min: 600, norm_day: 480, over_min: 120, bonus_rub: 2160, km: 40, late: 0, alarms: ['sos'] }],
      economy: { sectors: [{ id: 'vostok', name: 'Восток', value_rub: 400000, payroll_rub: 56000, bonus_rub: 2160, travel_rub: 9000, wait_rub: 0, sector_rub: 0, net_rub: 332840 }] },
      signals: [{ kind: 'sos', time: '12:40', engineer_id: 'lebedev', engineer: 'Лебедев', request_id: null, text: 'Нужна помощь', sector: 'vostok' }],
      versus: {
        benchmark: { control: { on_time: 172, requests_total: 205, engineers_used: 35, distance_km: 756, net_rub: 1075626 }, solver: { on_time: 205, requests_total: 205, engineers_used: 25, distance_km: 781, net_rub: 1305364 } },
        race: { days: 60, start: 'home', ours_pct: 94.3, control_pct: 82.6, baseline_pct: 71.6, ours_best: 54 },
      },
    }),
    overview: async () => ({
      order: 'on_time_crews_rub',
      regions: [{
        dataset_id: 'yugo-vostok', name: 'Юго-восток', date: '2026-08-17', plan_id: 'p7', requests: 83, on_time: 78,
        on_time_pct: 94, crews_used: 11, crews_total: 12, net_rub: 301200, unassigned: 2, deferred: 3,
        utilization_pct: 66.5, distance_km: 360, late: 0, events: 4, queue: 1, flags: 2, versions: 5,
        targets: { on_time_pct: 95, utilization_pct: 65 }, ok: { on_time: false, utilization: true },
        crews: [{ id: 'lebedev', name: 'Лебедев', visits: 7, done: 3, late: 0, norm_min: 510, bonus_rub: 540, km: 40, flags: 1, sos: true, delays: 1 }],
      }],
    }),
    versions: async () => [
      { id: 'p1', parent_id: null, created_at: '', algorithm: 'solver', what: 'Утренний план', time: null, events: 0, unassigned: 0, deferred: 0, on_time: 83, crews: 12, net_rub: 307000, current: false, on_line: true },
      { id: 'p2', parent_id: 'p1', created_at: '', algorithm: 'solver', what: 'Авария', time: '14:00', events: 1, unassigned: 1, deferred: 0, on_time: 83, crews: 12, net_rub: 309000, current: true, on_line: true },
    ],
    restore: async (id: string) => {
      restored.push(id)
      return { id }
    },
    rules: async () => ({ rules: {}, version: 0, updated_at: null }),
    saveRules: async (rules: Record<string, unknown>) => ({ rules, version: 1, updated_at: '2026-09-25T12:00:00+00:00' }),
  },
}))

const wrap = (node: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>)

test('руководитель видит итоги города, довод против контроля и бригады', async () => {
  wrap(<ManagerApp />)
  expect(await screen.findByText('190 из 205')).toBeInTheDocument()
  expect(screen.getByText('190 из 205').closest('.b-dash-kpi')).toHaveClass('bad')
  expect(screen.getByText('−10 бригад · +33 вовремя · +230 тыс. ₽')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Лебедев' })).toHaveAttribute('href', '#crew/lebedev')
  expect(screen.getByRole('link', { name: '120 %' })).toHaveAttribute('href', '/deficit?sector=vostok')
})

test('общие правила дня открывает руководитель', async () => {
  wrap(<ManagerApp />)
  // Правила дня — пункт меню «…» в шапке.
  fireEvent.click(await screen.findByRole('button', { name: /Ещё/ }))
  const item = await screen.findByRole('menuitem', { name: /Правила дня/ })
  await waitFor(() => expect(item).not.toHaveAttribute('aria-disabled', 'true'))
  fireEvent.click(item)
  expect(await screen.findByRole('dialog', { name: 'Правила дня' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Сохранить правила' })).toBeInTheDocument()
})

test('версию дня можно вернуть, действующая помечена', async () => {
  const got: string[] = []
  wrap(<VersionsView region="yugo-vostok" onRestore={(plan) => got.push(plan.id)} onClose={() => undefined} />)
  expect(await screen.findByText('p2 · Авария, 14:00')).toBeInTheDocument()
  expect(screen.getByText('действует')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Вернуть' }))
  await waitFor(() => expect(restored).toEqual(['p1']))
  await waitFor(() => expect(got).toEqual(['p1']))
})
