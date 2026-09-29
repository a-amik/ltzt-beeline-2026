/**
 * Клиент серверных ручек. Адрес берётся из окружения, чтобы стенд и демо
 * смотрели в разные места. Ответ не разбирается и не досочиняется:
 * тексты причин и объяснений приходят готовыми (см. CONTRACT.md).
 *
 * Сроков ожидания два. Список наборов спрашивается коротко: не ответил —
 * сервера нет, и экран уходит на демо-данные. Расчёт ждётся долго:
 * решатель ищет план столько секунд, сколько задано в настройках.
 */

import type {
  Comparison,
  CrewDay,
  Dataset,
  DeficitMap,
  DatasetSummary,
  FraudFlag,
  Mark,
  OfferResponse,
  Plan,
  PlanEvent,
  RaceData,
  RaceDay,
  ScenarioSpec,
  EventSet,
  RaceRun,
  CustomEvent,
  RulesState,
  Settings,
  SettingsForm,
  SimulationResult,
  ReplanVariant,
  Reports,
  UploadSummary,
} from './types'
import type { TransitTrip } from './crew/transitTypes'

export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

const QUICK_MS = 3500
const SOLVE_MS = 120_000

/** Ошибка сервера с причиной словами — её показывают диспетчеру как есть. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * Роль экрана в каждом запросе. Экран диспетчера шлёт `dispatcher`: сервер
 * берёт из присланных настроек только оперативное — ручной приоритет заявок
 * и бюджет поиска, — а общие правила ставит свои, те, что задал руководитель
 * (`GET /rules`, CONTRACT.md). Входа у прототипа нет: роль — это экран.
 */
const ROLE = 'dispatcher'

async function call<T>(path: string, init?: RequestInit, timeout = QUICK_MS): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', 'x-bee-role': ROLE, ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(timeout),
  })
  if (!response.ok) {
    let detail = `${path}: ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // тело не JSON — оставляем код ответа
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const api = {
  datasets: () => call<DatasetSummary[]>('/datasets'),
  upload: (filename: string, content: string, engineers?: number) =>
    call<UploadSummary>('/datasets/upload', post({ filename, content, engineers }), SOLVE_MS),
  dataset: (id: string) => call<Dataset>(`/datasets/${id}`),
  settings: () => call<SettingsForm>('/settings'),
  /** Общие правила дня: их задаёт руководитель, диспетчер только читает. */
  rules: () => call<RulesState>('/rules'),
  plan: (dataset_id: string, algorithm: 'solver' | 'baseline', settings: Settings, remember_latest = true) =>
    call<Plan>('/plan', post({ dataset_id, algorithm, settings, remember_latest }), SOLVE_MS),
  variants: (plan_id: string, events: PlanEvent[], keys?: ReplanVariant['key'][]) =>
    call<{ plan_id: string; variants: ReplanVariant[] }>('/replan/variants', post({ plan_id, events, keys }), SOLVE_MS),
  adopt: (plan_id: string) => call<Plan>(`/plan/${plan_id}/adopt`, post({})),
  replan: (plan_id: string, event: PlanEvent) =>
    call<Plan>('/replan', post({ plan_id, event }), SOLVE_MS),
  assign: (plan_id: string, request_id: string, engineer_id: string, insert_after: string | null) =>
    call<Plan>(`/plan/${plan_id}/assign`, post({ request_id, engineer_id, insert_after }), SOLVE_MS),
  compare: (dataset_id: string, settings: Settings) =>
    call<Comparison>('/compare', post({ dataset_id, settings }), SOLVE_MS),
  reports: () => call<Reports>('/reports', undefined, 20_000),
  race: () => call<RaceData>('/race', undefined, 20_000),
  raceDay: (spec: ScenarioSpec) => call<RaceDay>('/race/day', post(spec), SOLVE_MS * 5),
  raceCustom: (body: { dataset_id: string; start: string; custom: CustomEvent[] }) =>
    call<RaceRun>('/race/custom', post(body), SOLVE_MS * 5),
  raceMorning: (body: { dataset_id: string; start: string; settings?: Settings | null; time_limit_s?: number }) =>
    call<{ ready: boolean }>('/race/morning', post(body), 10_000),
  raceSets: (body: { dataset_id: string; kind: 'normal' | 'hard'; start: string; settings?: Settings | null }) =>
    call<EventSet[]>('/race/sets', post(body), 20_000),
  control: (dataset_id: string) => call<Plan>(`/datasets/${dataset_id}/control`, undefined, 20_000),
  deficit: (plan: Plan) => call<DeficitMap>('/deficit', post({ plan }), 20_000),
  simulate: (spec: ScenarioSpec) => call<SimulationResult>('/simulate', post(spec), SOLVE_MS * 5),
  latestPlan: (dataset_id?: string) => call<Plan>(`/plan/latest${dataset_id ? `?dataset_id=${dataset_id}` : ''}`),
  crew: (plan_id: string, engineer_id: string) => call<CrewDay>(`/plan/${plan_id}/crew/${engineer_id}`),
  crewTransit: (plan_id: string, engineer_id: string, request_id: string) =>
    call<TransitTrip>(`/plan/${plan_id}/crew/${engineer_id}/transit?request_id=${encodeURIComponent(request_id)}`),
  mark: (plan_id: string, mark: Mark) =>
    call<{ plan_id: string; marks: Mark[]; flags: FraudFlag[] }>(`/plan/${plan_id}/marks`, post({ mark })),
  fraud: (plan_id: string) =>
    call<{ plan_id: string; marks: Mark[]; flags: FraudFlag[] }>(`/plan/${plan_id}/fraud`),
  defer: (plan_id: string, request_id: string, reason?: string, time?: string) =>
    call<Plan>(`/plan/${plan_id}/defer`, post({ request_id, reason, time })),
  geocode: (q: string) =>
    call<{ q: string; lat: number; lon: number; quality: 'house' | 'street' | 'district' }>(
      `/geocode?q=${encodeURIComponent(q)}`, undefined, 40_000,
    ),
  respond: (plan_id: string, response: OfferResponse) =>
    call<{ plan: Plan; text: string }>(`/plan/${plan_id}/offers/respond`, post({ response }), SOLVE_MS),
}
