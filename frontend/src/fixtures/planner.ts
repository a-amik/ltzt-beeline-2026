/**
 * Планировщик демо-режима. Настоящий расчёт живёт на сервере; здесь —
 * жадная развозка, чтобы интерфейс жил и без него. Ответ повторяет контракт
 * целиком: маршруты, неназначенные с причиной, метрики, объяснения и diff.
 * Случайности нет: всё, что дрожит, посеяно номером заявки.
 */

import type {
  Alternative,
  Check,
  Coord,
  Dataset,
  Engineer,
  Explanation,
  Plan,
  PlanDiff,
  PlanEvent,
  ReasonCode,
  RequestItem,
  Route,
  Skill,
  Stop,
  Transport,
  Unassigned,
} from '../types'
import { fromMin, toMin } from '../lib/time'

interface Point {
  lat: number
  lon: number
}

/** Коэффициент дороги: по прямой никто не ездит. */
const ROAD_FACTOR = 1.28
const SPEED: Record<Transport, number> = { car: 32, bike: 14, foot: 5, transit: 18 }
const WAITING: Record<Transport, number> = { car: 0, bike: 0, foot: 0, transit: 8 }

export const SKILL_NAME: Record<Skill, string> = {
  local: 'локальные работы',
  connect: 'подключение и дозаказы',
  emergency: 'аварийные работы',
}

const TRANSPORT_NAME: Record<Transport, string> = {
  car: 'автомобиль',
  bike: 'велосипед',
  foot: 'пешком',
  transit: 'общественный транспорт',
}

function haversine(a: Point, b: Point): number {
  const rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad
  const dLon = (b.lon - a.lon) * rad
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(s)))
}

function travelOf(a: Point, b: Point, transport: Transport) {
  const km = haversine(a, b) * ROAD_FACTOR
  const min = Math.round((km / SPEED[transport]) * 60) + WAITING[transport]
  return { km: Math.round(km * 10) / 10, min }
}

/** Дрожание посеяно числом, а не `Math.random()`: тот же набор — та же картина. */
function rnd(seed: number): number {
  const x = Math.sin(seed * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function hash(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) % 100000
  return h
}

/** Ломаная «по дорогам»: прямая с отводом вбок — линия не должна быть отрезком. */
function polyline(a: Point, b: Point, seed: number): Coord[] {
  const steps = 6
  const out: Coord[] = []
  const dx = b.lon - a.lon
  const dy = b.lat - a.lat
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps
    const wobble = Math.sin(t * Math.PI) * (rnd(seed + i * 7) - 0.5) * 0.3
    out.push([a.lon + dx * t - dy * wobble, a.lat + dy * t + dx * wobble])
  }
  return out
}

export interface PlanOptions {
  algorithm: 'solver' | 'baseline'
  id?: string
  skipRequestIds?: string[]
  offEngineerIds?: string[]
  extraRequests?: RequestItem[]
  /** Что уже началось до времени события — не трогаем. */
  freeze?: { plan: Plan; atMin: number }
}

interface Slot {
  engineer: Engineer
  atMin: number
  at: Point
  stops: Stop[]
  km: number
  travelMin: number
  workMin: number
}

interface Attempt {
  slot: Slot
  arrive: number
  start: number
  end: number
  km: number
  min: number
  late: number
}

/** Какие визиты считаются начатыми к моменту события. */
export function frozenRequestIds(plan: Plan, atMin: number): string[] {
  const out: string[] = []
  for (const route of plan.routes) {
    for (const stop of route.stops) {
      if (toMin(stop.start) < atMin) out.push(stop.request_id)
    }
  }
  return out
}

export function buildPlan(dataset: Dataset, options: PlanOptions): Plan {
  const skip = new Set(options.skipRequestIds ?? [])
  const off = new Set(options.offEngineerIds ?? [])
  const pool: RequestItem[] = [...dataset.requests, ...(options.extraRequests ?? [])]
  const byId = new Map(pool.map((item) => [item.id, item]))

  const slots: Slot[] = dataset.engineers.map((engineer) => ({
    engineer,
    atMin: toMin(engineer.shift_start),
    at: { lat: engineer.start.lat, lon: engineer.start.lon },
    stops: [],
    km: 0,
    travelMin: 0,
    workMin: 0,
  }))
  const slotById = new Map(slots.map((slot) => [slot.engineer.id, slot]))

  // Замороженные визиты переносим как есть — они уже идут.
  const frozen = new Set<string>()
  if (options.freeze) {
    const atMin = options.freeze.atMin
    for (const route of options.freeze.plan.routes) {
      const slot = slotById.get(route.engineer_id)
      if (!slot) continue
      for (const stop of route.stops) {
        if (toMin(stop.start) >= atMin) continue
        const request = byId.get(stop.request_id)
        if (!request) continue
        frozen.add(stop.request_id)
        slot.stops.push({ ...stop, seq: slot.stops.length + 1 })
        slot.km += stop.travel_km
        slot.travelMin += stop.travel_min
        slot.workMin += request.duration_min
        slot.atMin = toMin(stop.end)
        slot.at = { lat: request.lat, lon: request.lon }
      }
    }
  }

  const queue = pool.filter((item) => !skip.has(item.id) && !frozen.has(item.id))
  if (options.algorithm === 'solver') {
    queue.sort((a, b) => {
      if (a.priority !== b.priority) return a.priority === 'urgent' ? -1 : 1
      const w = toMin(a.window_start) - toMin(b.window_start)
      return w !== 0 ? w : b.duration_min - a.duration_min
    })
  }

  const unassigned: Unassigned[] = []
  const explanations: Record<string, Explanation> = {}
  let rotation = 0

  for (const request of queue) {
    const withSkill = slots.filter(
      (slot) => !off.has(slot.engineer.id) && slot.engineer.skills.includes(request.skill),
    )
    if (withSkill.length === 0) {
      unassigned.push({
        request_id: request.id,
        reason: `Навык «${SKILL_NAME[request.skill]}» не заявлен ни у одной свободной бригады`,
        reason_code: 'no_skill',
      })
      continue
    }

    const attempts: Attempt[] = []
    for (const slot of withSkill) {
      const trip = travelOf(slot.at, request, slot.engineer.transport)
      const arrive = slot.atMin + trip.min
      const start = Math.max(arrive, toMin(request.window_start))
      const end = start + request.duration_min
      if (end > toMin(slot.engineer.shift_end)) continue
      const late = Math.max(0, end - toMin(request.window_end))
      attempts.push({ slot, arrive, start, end, km: trip.km, min: trip.min, late })
    }

    const inTime = attempts.filter((a) => a.late === 0)
    const usable = inTime.length > 0 ? inTime : attempts.filter((a) => a.late <= 45)
    if (usable.length === 0) {
      const windowSpan = toMin(request.window_end) - toMin(request.window_start)
      const code: ReasonCode =
        request.duration_min > windowSpan ? 'no_fit_window' : attempts.length === 0 ? 'no_fit_shift' : 'all_busy'
      const reason =
        code === 'no_fit_window'
          ? `Работа ${request.duration_min} мин не помещается в окно ${request.window_start}–${request.window_end} ни у кого с учётом дороги`
          : code === 'no_fit_shift'
            ? `Визит кончался бы позже смены: до ${dataset.engineers[0]?.shift_end ?? '22:00'} не успевает никто`
            : 'Все бригады с нужным навыком заняты в это окно'
      unassigned.push({ request_id: request.id, reason, reason_code: code })
      continue
    }

    let chosen: Attempt
    if (options.algorithm === 'solver') {
      chosen = usable.reduce((best, a) => (a.km + a.late * 0.5 < best.km + best.late * 0.5 ? a : best))
    } else {
      // Базовый алгоритм: по кругу, без выбора ближайшего — так возят «как придётся».
      const start = rotation % usable.length
      chosen = usable[(start + usable.length) % usable.length] as Attempt
      rotation += 1
    }

    const slot = chosen.slot
    const stop: Stop = {
      request_id: request.id,
      seq: slot.stops.length + 1,
      depart_prev: fromMin(slot.atMin),
      arrive: fromMin(chosen.arrive),
      start: fromMin(chosen.start),
      end: fromMin(chosen.end),
      travel_min: chosen.min,
      travel_km: chosen.km,
      wait_min: Math.max(0, chosen.start - chosen.arrive),
      late_min: chosen.late,
      geometry: polyline(slot.at, request, hash(request.id) + hash(slot.engineer.id)),
    }
    slot.stops.push(stop)
    slot.km += chosen.km
    slot.travelMin += chosen.min
    slot.workMin += request.duration_min
    slot.atMin = chosen.end
    slot.at = { lat: request.lat, lon: request.lon }

    explanations[request.id] = explain(request, chosen, attempts, slots, off)
  }

  const routes: Route[] = slots
    .filter((slot) => slot.stops.length > 0)
    .map((slot) => ({
      engineer_id: slot.engineer.id,
      distance_km: Math.round(slot.km * 10) / 10,
      travel_min: slot.travelMin,
      work_min: slot.workMin,
      stops: slot.stops,
    }))

  const late = routes.reduce(
    (sum, route) => sum + route.stops.filter((stop) => stop.late_min > 0).length,
    0,
  )

  return {
    id: options.id ?? `local-${options.algorithm}-${Date.now()}`,
    dataset_id: dataset.id,
    algorithm: options.algorithm,
    created_at: new Date().toISOString(),
    routes,
    unassigned,
    metrics: {
      engineers_used: routes.length,
      distance_km: Math.round(routes.reduce((s, r2) => s + r2.distance_km, 0) * 10) / 10,
      travel_min: routes.reduce((s, r2) => s + r2.travel_min, 0),
      unassigned: unassigned.length,
      late,
      changed_requests: 0,
    },
    explanations,
  }
}

function explain(
  request: RequestItem,
  chosen: Attempt,
  attempts: Attempt[],
  slots: Slot[],
  off: Set<string>,
): Explanation {
  const engineer = chosen.slot.engineer
  const checks: Check[] = [
    {
      kind: 'skill',
      ok: true,
      text: `Навык «${SKILL_NAME[request.skill]}» есть у бригады ${engineer.name}`,
    },
    {
      kind: 'transport',
      ok: true,
      text: `Транспорт бригады — ${TRANSPORT_NAME[engineer.transport]}, дорога заняла ${chosen.min} мин`,
    },
    {
      kind: 'window',
      ok: chosen.late === 0,
      text:
        chosen.late === 0
          ? `Приезд ${fromMin(chosen.arrive)} — внутри окна ${request.window_start}–${request.window_end}`
          : `Работа кончается ${fromMin(chosen.end)} — позже окна ${request.window_end} на ${chosen.late} мин`,
    },
    {
      kind: 'shift',
      ok: true,
      text: `Визит кончается ${fromMin(chosen.end)}, смена до ${engineer.shift_end}`,
    },
    {
      kind: 'distance',
      ok: true,
      text: `От предыдущей точки ${String(chosen.km).replace('.', ',')} км — короче, чем у остальных подходящих`,
    },
  ]

  const alternatives: Alternative[] = []
  for (const attempt of attempts) {
    if (attempt.slot.engineer.id === engineer.id) continue
    const delta = Math.round((attempt.km - chosen.km) * 10) / 10
    alternatives.push({
      engineer_id: attempt.slot.engineer.id,
      feasible: attempt.late === 0,
      delta_km: delta,
      text:
        attempt.late === 0
          ? `${attempt.slot.engineer.name} успевал, но добавил бы ${String(Math.abs(delta)).replace('.', ',')} км`
          : `${attempt.slot.engineer.name} приехал бы позже окна на ${attempt.late} мин`,
    })
    if (alternatives.length >= 2) break
  }
  const without = slots.find(
    (slot) => !off.has(slot.engineer.id) && !slot.engineer.skills.includes(request.skill),
  )
  if (without) {
    alternatives.push({
      engineer_id: without.engineer.id,
      feasible: false,
      reason_code: 'no_skill',
      text: `У ${without.engineer.name} нет навыка «${SKILL_NAME[request.skill]}»`,
    })
  }
  return { engineer_id: engineer.id, checks, alternatives }
}

/** Кто и когда делает заявку — для сравнения двух планов. */
function assignmentMap(plan: Plan): Map<string, { engineer: string; start: string }> {
  const out = new Map<string, { engineer: string; start: string }>()
  for (const route of plan.routes) {
    for (const stop of route.stops) {
      out.set(stop.request_id, { engineer: route.engineer_id, start: stop.start })
    }
  }
  return out
}

export function diffPlans(
  prev: Plan,
  next: Plan,
  event: PlanEvent,
  frozen: string[],
): PlanDiff {
  const before = assignmentMap(prev)
  const after = assignmentMap(next)
  const ids = new Set([...before.keys(), ...after.keys()])
  const changed = []
  const routes = new Set<string>()
  for (const id of ids) {
    const a = before.get(id)
    const b = after.get(id)
    if (a && b && a.engineer === b.engineer && a.start === b.start) continue
    changed.push({
      request_id: id,
      from_engineer: a?.engineer ?? null,
      to_engineer: b?.engineer ?? null,
      from_start: a?.start ?? null,
      to_start: b?.start ?? null,
    })
    if (a) routes.add(a.engineer)
    if (b) routes.add(b.engineer)
  }
  return {
    event,
    changed_requests: changed,
    changed_routes: [...routes],
    frozen_requests: frozen,
  }
}

/** Перепланирование по событию — то же, что делает сервер на /replan. */
export function localReplan(dataset: Dataset, plan: Plan, event: PlanEvent): Plan {
  const atMin = toMin(event.time)
  const frozen = frozenRequestIds(plan, atMin)
  const options: PlanOptions = {
    algorithm: plan.algorithm === 'baseline' ? 'baseline' : 'solver',
    id: `local-replan-${Date.now()}`,
    freeze: { plan, atMin },
  }
  if (event.type === 'urgent') options.extraRequests = [event.request]
  if (event.type === 'cancel') options.skipRequestIds = [event.request_id]
  if (event.type === 'engineer_off') options.offEngineerIds = [event.engineer_id]

  const next = buildPlan(dataset, options)
  next.diff = diffPlans(plan, next, event, frozen)
  next.metrics.changed_requests = next.diff.changed_requests.length
  return next
}
