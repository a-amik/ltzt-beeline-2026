/** Типы контракта «сервер ↔ клиент» — см. app/CONTRACT.md. */

export type Skill = 'local' | 'connect' | 'emergency'
export type Transport = 'car' | 'foot' | 'bike' | 'transit'
export type Priority = 'normal' | 'urgent'
export type GeoQuality = 'house' | 'street' | 'district'

export type ReasonCode =
  | 'no_skill'
  | 'no_transport'
  | 'no_fit_window'
  | 'no_fit_shift'
  | 'all_busy'
  | 'buffer'
  | 'no_engineer'
  | 'no_stock'
  | 'offered'

export interface Office {
  address: string
  lat: number
  lon: number
}

export interface RequestItem {
  /** Устройства к заявке: router | tv_box | speaker; синтетика по типу заявки. */
  equipment?: string[]
  id: string
  type_bk: string
  type_hd: string
  address: string
  district: string
  lat: number
  lon: number
  geo_quality: GeoQuality
  duration_min: number
  window_start: string
  window_end: string
  priority: Priority
  skill: Skill
  transport: Transport | null
  /** Сколько квартир задевает авария: синтетика от номера заявки (`households.py`); у прочих заявок нет. */
  households?: number | null
  /** Участок заявки в наборе «Вся Москва». */
  sector?: string | null
}

export interface Engineer {
  id: string
  name: string
  start: { lat: number; lon: number }
  shift_start: string
  shift_end: string
  skills: Skill[]
  transport: Transport
  /** Все виды транспорта бригады; вид на переезд выбирает решатель. */
  transports?: Transport[]
  /** Дом: старт по практике. */
  /** address — ближайший дом с номером к точке (`homes.py`): подпись условная, координаты — прежние. */
  home?: { lat: number; lon: number; address?: string | null } | null
  /** Согласие брать заявки сверх нормы дня за бонус. */
  extra_load?: boolean
  extra_limit_min?: number
  /** Удалённость подучастка: медиана расстояния визитов от офиса, км. */
  remote_km?: number
  /** Опорная точка района дальней бригады. */
  anchor?: { lat: number; lon: number } | null
  anchor_name?: string | null
  /** Участок бригады в наборе «Вся Москва»: свой офис, выезд в чужой участок стоит денег. */
  sector?: string | null
}

export type EventPolicy = 'offer' | 'direct'
export type NoShowNote =
  | 'waiting'
  | 'unreachable'
  | 'absent'
  | 'partial'
  | 'cancelled_on_site'
  | 'client_moved'
  | 'we_moved'

export type PlanEvent =
  | { id: string; type: 'urgent'; time: string; request: RequestItem; policy?: EventPolicy }
  | { id: string; type: 'new_request'; time: string; request: RequestItem; policy?: EventPolicy }
  | { id: string; type: 'cancel'; time: string; request_id: string }
  | { id: string; type: 'no_show'; time: string; request_id: string; note?: NoShowNote }
  | { id: string; type: 'reschedule'; time: string; request_id: string; window_start: string; window_end: string }
  | { id: string; type: 'delay'; time: string; engineer_id: string; delay_min: number }
  | { id: string; type: 'engineer_off'; time: string; engineer_id: string }
  | { id: string; type: 'manual'; time: string; request_id: string; engineer_id: string }

/** Заявка, явно перенесённая на следующий день, и почему. */
export interface Deferred {
  request_id: string
  reason: string
  since: string
}

export interface Sector {
  id: string
  name: string
  office: Office
}

export interface Dataset {
  id: string
  name: string
  date: string
  office: Office
  /** Участки набора «Вся Москва»; у набора одного участка — пусто. */
  sectors?: Sector[]
  requests: RequestItem[]
  engineers: Engineer[]
  events: PlanEvent[]
}

export interface DatasetSummary {
  id: string
  name: string
  date: string
  requests_count: number
  engineers_count: number
  /** customer — данные заказчика, upload — свой файл диспетчера. */
  source?: 'customer' | 'upload'
}

/** Ответ на загрузку своего файла: что из него получилось. */
export interface UploadSummary {
  id: string
  name: string
  requests: number
  engineers: number
  control: number
  geo: Record<string, number>
}

/** Ломаная приходит парами [долгота, широта] — как в GeoJSON. */
export type Coord = [number, number]

export interface Stop {
  request_id: string
  seq: number
  depart_prev: string
  arrive: string
  start: string
  end: string
  travel_min: number
  travel_km: number
  wait_min: number
  late_min: number
  /** Чем ехали на этом переезде. */
  mode?: Transport | null
  geometry: Coord[]
  status?: 'planned' | 'no_show'
  value_rub?: number
  /** Доля прогонов со случайным шумом дороги и работы, где начало вышло за окно. */
  late_risk?: number
  /** Приезд, которого не превысят 90 % прогонов. */
  arrive_p90?: string | null
}

export interface Route {
  engineer_id: string
  distance_km: number
  travel_min: number
  work_min: number
  stops: Stop[]
  break_start?: string | null
  break_end?: string | null
  norm_min?: number
  over_norm_min?: number
  bonus_rub?: number
  earnings_rub?: number
}

export interface Unassigned {
  request_id: string
  reason: string
  reason_code: ReasonCode
}

export interface Metrics {
  engineers_used: number
  distance_km: number
  travel_min: number
  unassigned: number
  late: number
  changed_requests: number
  /** Ожидаемое число визитов с началом позже окна при шуме дороги и работы. */
  risk_late?: number
  risky_stops?: number
}

export interface Check {
  kind: 'skill' | 'transport' | 'window' | 'shift' | 'distance'
  ok: boolean
  text: string
}

export interface Alternative {
  engineer_id: string
  feasible: boolean
  delta_km?: number
  reason_code?: ReasonCode
  text: string
}

export interface Explanation {
  engineer_id: string
  checks: Check[]
  alternatives: Alternative[]
}

export interface ChangedRequest {
  request_id: string
  from_engineer: string | null
  to_engineer: string | null
  from_start: string | null
  to_start: string | null
}

export interface PlanDiff {
  event: PlanEvent
  changed_requests: ChangedRequest[]
  changed_routes: string[]
  frozen_requests: string[]
}

export interface Deficit {
  window: string
  demand_min: number
  capacity_min: number
  coef: number
}

export interface Economy {
  value_done_rub: number
  value_lost_rub: number
  payroll_rub: number
  bonus_rub: number
  travel_rub: number
  wait_rub?: number
  /** Выезды бригад в чужой участок по цене `economy.sector_cross_rub`. */
  sector_rub?: number
  sector_entries?: number
  total_cost_rub: number
  net_rub: number
  deficit: Deficit[]
}

export interface OfferCandidate {
  engineer_id: string
  insert_after: string | null
  arrive: string
  start: string
  delta_travel_min: number
  delta_norm_min: number
  delta_shift_min?: number
  bonus_rub: number
  text: string
}

export interface Offer {
  request_id: string
  coef: number
  candidates: OfferCandidate[]
}

export interface Standby {
  engineer_id: string
  after_request_id: string
  before_request_id: string | null
  start: string
  end: string
  lat: number
  lon: number
  district: string
  km: number
  share_pct: number
  text: string
}

export interface Plan {
  id: string
  dataset_id: string
  algorithm: 'solver' | 'baseline' | 'control'
  created_at: string
  start?: 'office' | 'home'
  settings?: Settings
  routes: Route[]
  unassigned: Unassigned[]
  metrics: Metrics
  explanations: Record<string, Explanation>
  diff?: PlanDiff
  economy?: Economy | null
  offers?: Offer[]
  deferred?: Deferred[]
  history?: PlanEvent[]
  day_type?: 'workday' | 'friday' | 'saturday' | 'sunday' | 'holiday'
  /** Где ждать бригадам в окнах без визитов. */
  standby?: Standby[]
  /** Утренний запас устройств: бригада → устройство → штук. */
  stock?: Record<string, Record<string, number>>
  /** Версия дня, из которой выросла эта. */
  parent_id?: string | null
  /** Порядок целей и три его числа. */
  objective?: { order?: string; on_time?: number; crews?: number; net_rub?: number }
  /** Вес аварий по масштабу словами: заявка → «Авария: затронуто ≈240 квартир…». */
  weights?: Record<string, string>
}

// ── Приложение бригады и контроль ──

export type MarkKind = 'depart' | 'arrive' | 'start' | 'done' | 'no_show'

export interface Mark {
  engineer_id: string
  request_id: string
  kind: MarkKind
  time: string
  lat?: number | null
  lon?: number | null
}

export interface Earnings {
  day_rub: number
  bonus_planned_rub: number
  bonus_confirmed_rub: number
  norm_day_min: number
  norm_planned_min: number
  norm_confirmed_min: number
  over_norm_min: number
}

export interface CrewOffer {
  request_id: string
  address: string
  window: string
  duration_min: number
  arrive: string
  delta_travel_min: number
  bonus_rub: number
  text: string
  expires_in_min: number
}

export interface CrewDay {
  plan_id: string
  engineer: Engineer
  route: Route
  requests: RequestItem[]
  marks: Mark[]
  offers: CrewOffer[]
  earnings: Earnings
  next_request_id: string | null
  /** Что взять утром: устройство → сколько. */
  kit?: Record<string, number>
  /** Утренний запас бригады: маршрут плюс резерв из настроек. */
  stock?: Record<string, number>
  /** Свободный остаток сверх стоящих визитов: им бригада берёт заявки дня. */
  stock_left?: Record<string, number>
}

export interface FraudFlag {
  engineer_id: string
  request_id: string | null
  code: string
  severity: 'info' | 'warn' | 'alert'
  text: string
  action: string
}

export interface OfferResponse {
  request_id: string
  engineer_id: string
  accepted: boolean
  time?: string
  reason?: string | null
}

// ── Имитация дня ──

export type SimPolicy = 'offer' | 'direct' | 'static'

/** Что стало с новой заявкой пачки в одном варианте. */
export interface VariantRequest {
  request_id: string
  time: string
  outcome: string
  code: 'assigned' | 'offered' | 'deferred'
}

/** Один ответ на пачку событий и его цена. */
export interface ReplanVariant {
  key: 'keep' | 'full' | 'tomorrow'
  title: string
  hint: string
  plan: Plan
  placed: number
  offered: number
  deferred: number
  changed: number
  unassigned: number
  net_rub: number
  net_delta_rub: number
  same_as: string | null
  requests: VariantRequest[]
}

/** Заявка, вброшенная в имитацию руками: когда позвонили, где и в какое окно. */
export interface InjectedRequest {
  time: string
  lat: number
  lon: number
  address: string
  duration_min: number
  window_start: string
  window_end: string
  skill: Skill
}

export interface ScenarioSpec {
  dataset_id: string
  seed: number
  /** Не задано — сервер берёт долю региона из настройки «Доля заявок день в день». */
  new_requests: number | null
  cancels: number
  no_shows: number
  reschedules: number
  engineer_off: number
  delays: number
  policy: SimPolicy
  accept_prob: number
  settings?: Settings | null
  time_limit_s: number
  injected?: InjectedRequest[]
  /** random — события по номеру набора и счётчикам; data — события, заложенные в набор участка. */
  events_from?: 'random' | 'data'
  /** События, заданные руками: что, во сколько и с кем. */
  custom?: CustomEvent[]
}

export type CustomEventType = 'new_request' | 'cancel' | 'no_show' | 'reschedule' | 'delay' | 'engineer_off'

export interface CustomEvent {
  type: CustomEventType
  time: string
  /** Какая заявка; у новой — с чьего адреса звонок. */
  request_id?: string | null
  engineer_id?: string | null
  delay_min?: number
}

/** Событие набора в кратком виде: когда и что. */
export interface SetEvent {
  time: string
  type: string
  delay_min?: number | null
}

export interface EventSet {
  seed: number
  events: SetEvent[]
}

export interface SimEvent {
  time: string
  type: string
  request_id: string | null
  engineer_id: string | null
  outcome: string
  outcome_code: 'assigned' | 'offered' | 'accepted' | 'declined' | 'deferred' | 'removed' | 'shifted'
  changed_requests: number
  kpis: Record<string, number>
}

export interface SimulationRun {
  policy: SimPolicy
  timeline: SimEvent[]
  kpis: Record<string, number>
  plan: Plan
}

export interface SimulationResult {
  spec: ScenarioSpec
  events: PlanEvent[]
  runs: SimulationRun[]
  kpi_labels: KpiLabel[]
}

/** Переопределения расчёта: вложенный словарь по путям схемы (`economy.norm_day_min`). */
export type Settings = Record<string, unknown>

export type FieldType = 'bool' | 'number' | 'choice' | 'multi' | 'time'

export interface SettingsField {
  path: string
  type: FieldType
  label: string
  hint?: string
  unit?: string
  min?: number
  max?: number
  step?: number
  choices?: { value: string; label: string }[]
}

export interface SettingsGroup {
  key: string
  title: string
  /** Строка под названием группы на экране «Настройки». */
  note?: string
  /** Настройка модели, а не диспетчера: живёт на вкладке «Модель». */
  tech?: boolean
  fields: SettingsField[]
}

/** Общие правила дня (`GET /rules`): переопределения поверх допущений, задаёт руководитель. */
export interface RulesState {
  rules: Settings
  version: number
  updated_at: string | null
}

export interface SettingsForm {
  schema: SettingsGroup[]
  defaults: Settings
}

export interface KpiLabel {
  key: string
  label: string
  unit: string
  less_is_better: boolean
}

export interface Comparison {
  dataset_id: string
  rows: { key: string; label: string; kpis: Record<string, number> }[]
  kpis: KpiLabel[]
}

// ── Отчёты о прогонах (`GET /reports`) ──

/** Счёт одного плана в прогоне гонки (`data/race/race.json`). */
export interface RaceScore {
  on_time: number
  late: number
  late_min: number
  missed: number
  engineers: number
  km: number
  net_rub: number
  /** Сделано вовремя к концу часа, часы — `RaceData.meta.hours`. */
  done_by_hour: number[]
  late_by_hour: number[]
}

export type RacePlayer = 'control' | 'baseline' | 'ours'

export interface RaceRun {
  region: string
  mode: string
  seed: number
  /** Откуда стартуют бригады всех трёх планов: office | hybrid | home. */
  start?: string
  /** Заявок дня: утренние и новые, без отменённых и тех, где клиента не было. */
  due: number
  demand_by_hour: number[]
  events: { t: string; type: string }[]
  players: Record<RacePlayer, RaceScore>
  seconds: number
}

export interface RaceData {
  meta: {
    seeds: number
    regions: string[]
    hours: number[]
    modes: Record<string, string>
    starts?: Record<string, string>
    spec: Record<string, Record<string, number | null>>
    players: RacePlayer[]
    seconds: number
  }
  runs: RaceRun[]
}

/** День по сценарию для «Живого дня»: контроль по правилу п. 2.3 и наш план на одних событиях. */
export interface RaceDay {
  control: Plan
  ours: Plan
  requests: RequestItem[]
  events: PlanEvent[]
}

export interface Reports {
  benchmark: {
    kpis: KpiLabel[]
    regions: { dataset_id: string; name: string; rows: { key: string; label: string; kpis: Record<string, number> }[] }[]
  } | null
  simulation: {
    kpis: KpiLabel[]
    regions: {
      dataset_id: string
      name: string
      seeds: number
      runs: { policy: string; label: string; runs: number; kpis: Record<string, number> }[]
    }[]
  } | null
  scale: {
    rows: {
      requests: number
      engineers: number
      budget_s: number
      portfolio: boolean
      first_solution_s: number
      last_improvement_s: number
      elapsed_s: number
      assigned: number
      net_rub: number
      rss_mb_after: number
    }[]
  } | null
  /** Три решателя портфеля и контроль, ключи строк — `control`, `ortools@4`, `pyvrp@60`… */
  search?: {
    budgets: number[]
    regions: { dataset_id: string; name: string; rows: Record<string, Record<string, number | boolean | null>> }[]
  } | null
  /** Замер нагрузки и злоупотреблений на живом API (`bee_routing.loadtest`). */
  load?: {
    base: string
    dataset: string
    steps: { users: number; requests: number; rps: number; p50_ms: number; p95_ms: number; p99_ms: number; errors: number }[]
    solves: { parallel: number; slowest_s: number; fastest_s: number; statuses: number[]; read_during_p95_ms: number }[]
    abuse: { case: string; status: number | string; seconds: number; note?: string }[]
    fixed?: string[]
  } | null
  /** Наш план против базового на синтетических днях участка. */
  generalize?: {
    meta: { days?: number; budget_s?: number; matrix?: string }
    regions: {
      dataset_id: string
      name: string
      requests: number
      engineers: number
      days: Record<'baseline' | 'solver', { on_time: number; unassigned: number; engineers_used: number; distance_km: number; net_rub: number }>[]
    }[]
  } | null
}

// ── Карта дефицита ──

export type DeficitLevel = 'deficit' | 'tight' | 'ok' | 'free'

export interface DeficitSlot {
  window: string
  demand_min: number
  served_min: number
  free_min: number
  unassigned: number
  pressure: number
  level: DeficitLevel
}

export interface DeficitArea {
  district: string
  lat: number
  lon: number
  requests: number
  slots: DeficitSlot[]
}

export interface DeficitMap {
  plan_id: string
  windows: string[]
  areas: DeficitArea[]
  totals: DeficitSlot[]
  advice: { district: string; window: string; level: DeficitLevel; text: string }[]
}
