/** Ручки экрана руководителя и версий дня. */

import type { RulesState, Settings } from '../types'

const BASE: string = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export interface ManagerCrew {
  id: string
  name: string
  visits: number
  done: number
  late: number
  norm_min: number
  bonus_rub: number
  km: number
  flags: number
  sos: boolean
  delays: number
}

export interface ManagerRegion {
  dataset_id: string
  name: string
  date: string
  plan_id: string
  requests: number
  on_time: number
  on_time_pct: number
  crews_used: number
  crews_total: number
  net_rub: number
  unassigned: number
  deferred: number
  utilization_pct: number
  distance_km: number
  late: number
  events: number
  queue: number
  flags: number
  versions: number
  targets: { on_time_pct: number; utilization_pct: number }
  ok: { on_time: boolean; utilization: boolean }
  crews: ManagerCrew[]
}

export interface Overview {
  regions: ManagerRegion[]
  order: 'on_time_crews_rub' | 'on_time_rub_crews' | 'sum'
}

export interface Version {
  id: string
  parent_id: string | null
  created_at: string
  algorithm: string
  what: string
  time: string | null
  events: number
  unassigned: number
  deferred: number
  on_time: number | null
  crews: number | null
  net_rub: number | null
  current: boolean
  on_line: boolean
}

/** Сводка руководителя (`GET /manager/dashboard`): один план города, участки — его разбивка. */
export interface DashFigures {
  requests: number
  on_time: number
  on_time_pct: number
  late: number
  crews_used: number
  crews_total: number
  utilization_pct: number
  km: number
  unassigned: number
  deferred: number
  ok: { on_time: boolean; utilization: boolean }
}

export interface Dashboard {
  dataset_id: string
  name: string
  date: string
  plan_id: string
  targets: { on_time_pct: number; utilization_pct: number }
  totals: DashFigures & { net_rub: number }
  sectors: (DashFigures & { id: string; name: string })[]
  hours: { hours: number[]; planned: number[]; done: number[]; due: number[] }
  load: {
    windows: string[]
    rows: { id: string; name: string; cells: { window: string; pressure: number; level: 'deficit' | 'tight' | 'ok' | 'free'; demand_min: number; unassigned: number }[] }[]
  }
  crews: { id: string; name: string; sector: string | null; visits: number; norm_min: number; norm_day: number; over_min: number; bonus_rub: number; km: number; late: number; alarms: string[] }[]
  economy: {
    sectors: { id: string; name: string; value_rub: number; payroll_rub: number; bonus_rub: number; travel_rub: number; wait_rub: number; sector_rub: number; net_rub: number }[]
  }
  signals: { kind: string; time: string; engineer_id: string | null; engineer: string | null; request_id: string | null; text: string; sector: string | null }[]
  versus: {
    benchmark?: Record<'control' | 'solver', { on_time: number; requests_total: number; engineers_used: number; distance_km: number; net_rub: number }>
    race?: { days: number; start: string; ours_pct: number; control_pct: number; baseline_pct: number; ours_best: number }
  }
}

async function call<T>(path: string, init?: RequestInit, timeout = 15000): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    // Экран руководителя шлёт свою роль: общие правила дня сервер меняет только по ней (`PUT /rules`).
    headers: { 'content-type': 'application/json', 'x-bee-role': 'manager', ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(timeout),
  })
  if (!response.ok) {
    let detail = `${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // тело не JSON — остаётся код ответа
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const managerApi = {
  overview: () => call<Overview>('/manager/overview'),
  // Первый заход может сам строить утренний план города: ждём дольше обычного.
  dashboard: () => call<Dashboard>('/manager/dashboard', undefined, 90000),
  versions: (region: string) => call<Version[]>(`/day/${region}/versions`),
  restore: <T,>(planId: string) => call<T>(`/plan/${planId}/restore`, { method: 'POST' }),
  rules: () => call<RulesState>('/rules'),
  saveRules: (rules: Settings) => call<RulesState>('/rules', { method: 'PUT', body: JSON.stringify({ rules }) }),
}

export const ORDER_RU: Record<Overview['order'], string> = {
  on_time_crews_rub: 'вовремя → бригады → итог в рублях',
  on_time_rub_crews: 'вовремя → итог в рублях → бригады',
  sum: 'одна сумма в рублях',
}
