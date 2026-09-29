/**
 * Воспроизведение дня: где каждая бригада в минуту t и что к этой минуте
 * сделано. Общий движок для «Дня за минуту» и для «Контроль против нашего
 * плана»: оба показа читают один и тот же план одним и тем же способом,
 * иначе сравнение в движении было бы сравнением двух анимаций.
 *
 * Геометрии дорог у переездов нет, бригада едет по прямой между точками —
 * это видно и честно: карта показывает порядок и время, а не улицы.
 * Время берётся из плана как есть: выезд, приезд, начало, конец работ.
 */

import type { Coord, Dataset, Plan, PlanEvent, RequestItem } from '../types'
import { knownRequests } from './plan'
import { toMin } from './time'

export type SegmentKind = 'idle' | 'drive' | 'wait' | 'work'

export interface Segment {
  t0: number
  t1: number
  from: Coord
  to: Coord
  kind: SegmentKind
  km: number
  requestId?: string
}

export interface Track {
  engineerId: string
  name: string
  color: string
  start: Coord
  segments: Segment[]
  breakStart: number | null
  breakEnd: number | null
}

export interface StopInfo {
  requestId: string
  engineerId: string
  color: string
  point: Coord
  seq: number
  start: number
  end: number
  windowEnd: number
  late: number
  value: number
  emergency: boolean
  title: string
}

export interface MissingInfo {
  requestId: string
  point: Coord
  windowStart: number
  windowEnd: number
  value: number
  title: string
}

export interface DayScene {
  tracks: Track[]
  stops: StopInfo[]
  missing: MissingInfo[]
  office: Coord
  bounds: [Coord, Coord] | null
  events: TimedEvent[]
}

export interface TimedEvent {
  t: number
  kind: 'start' | 'late' | 'missed' | 'emergency' | 'event' | 'done'
  text: string
}

export type StopState = 'planned' | 'working' | 'done' | 'late' | 'overdue'

const EVENT_TEXT: Record<string, string> = {
  urgent: 'Срочная заявка',
  new_request: 'Новая заявка день в день',
  cancel: 'Отмена заявки',
  no_show: 'Клиента нет на месте',
  reschedule: 'Перенос окна',
  delay: 'Бригада задерживается',
  engineer_off: 'Бригада выбыла',
}

function lerp(a: Coord, b: Coord, k: number): Coord {
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]
}

function eventText(event: PlanEvent, names: Map<string, string>): string {
  const head = EVENT_TEXT[event.type] ?? 'Событие'
  if ('request' in event && event.request) return `${head} · ${event.request.id}, ${event.request.address}`
  if ('request_id' in event && event.request_id) return `${head} · ${event.request_id}`
  if ('engineer_id' in event && event.engineer_id) return `${head} · ${names.get(event.engineer_id) ?? event.engineer_id}`
  return head
}

/** Собрать сцену дня из плана: дорожки бригад, визиты, неназначенные, события. */
export function buildDay(dataset: Dataset, plan: Plan, colors: string[]): DayScene {
  const requests = new Map<string, RequestItem>(knownRequests(dataset, plan).map((r) => [r.id, r]))
  const names = new Map(dataset.engineers.map((e) => [e.id, e.name]))
  const office: Coord = [dataset.office.lon, dataset.office.lat]
  const crews = ((plan.settings as Record<string, unknown> | undefined)?.crews ?? {}) as Record<
    string,
    { home?: { lat: number; lon: number } }
  >
  const order = dataset.engineers.map((e) => e.id)
  const tracks: Track[] = []
  const stops: StopInfo[] = []
  const events: TimedEvent[] = []
  const points: Coord[] = [office]

  for (const route of plan.routes) {
    const engineer = dataset.engineers.find((e) => e.id === route.engineer_id)
    if (!engineer) continue
    const color = colors[Math.max(0, order.indexOf(engineer.id)) % colors.length]
    const own = crews[engineer.id]?.home
    const home = own ? ([own.lon, own.lat] as Coord) : engineer.home ? ([engineer.home.lon, engineer.home.lat] as Coord) : null
    const start = plan.start === 'home' && home ? home : office
    const segments: Segment[] = []
    let here = start
    let clock = toMin(engineer.shift_start)
    for (const stop of route.stops) {
      const request = requests.get(stop.request_id)
      if (!request) continue
      const point: Coord = [request.lon, request.lat]
      points.push(point)
      const depart = toMin(stop.depart_prev)
      const arrive = toMin(stop.arrive)
      const begin = toMin(stop.start)
      const end = toMin(stop.end)
      if (depart > clock) segments.push({ t0: clock, t1: depart, from: here, to: here, kind: 'idle', km: 0 })
      segments.push({ t0: depart, t1: Math.max(arrive, depart + 1), from: here, to: point, kind: 'drive', km: stop.travel_km, requestId: request.id })
      if (begin > arrive) segments.push({ t0: arrive, t1: begin, from: point, to: point, kind: 'wait', km: 0, requestId: request.id })
      segments.push({ t0: begin, t1: end, from: point, to: point, kind: 'work', km: 0, requestId: request.id })
      here = point
      clock = end
      if (stop.status === 'no_show') continue
      const emergency = request.skill === 'emergency' || request.priority === 'urgent'
      const info: StopInfo = {
        requestId: request.id,
        engineerId: engineer.id,
        color,
        point,
        seq: stop.seq,
        start: begin,
        end,
        windowEnd: toMin(request.window_end),
        late: stop.late_min,
        value: stop.value_rub ?? 0,
        emergency,
        title: request.type_bk,
      }
      stops.push(info)
      events.push({
        t: begin,
        kind: emergency ? 'emergency' : 'start',
        text: `${engineer.name} начал ${emergency ? 'аварию' : 'работу'} · ${request.id}, ${request.type_bk}`,
      })
      if (stop.late_min > 0) {
        events.push({
          t: toMin(request.window_end),
          kind: 'late',
          text: `${engineer.name} опаздывает к ${request.id}: окно закрылось в ${request.window_end}, опоздание ${stop.late_min} мин`,
        })
      }
    }
    tracks.push({
      engineerId: engineer.id,
      name: engineer.name,
      color,
      start,
      segments,
      breakStart: route.break_start ? toMin(route.break_start) : null,
      breakEnd: route.break_end ? toMin(route.break_end) : null,
    })
    points.push(start)
  }

  const missing: MissingInfo[] = []
  for (const item of plan.unassigned) {
    const request = requests.get(item.request_id)
    if (!request) continue
    const point: Coord = [request.lon, request.lat]
    points.push(point)
    missing.push({
      requestId: request.id,
      point,
      windowStart: toMin(request.window_start),
      windowEnd: toMin(request.window_end),
      value: 0,
      title: request.type_bk,
    })
    events.push({
      t: toMin(request.window_end),
      kind: 'missed',
      text: `${request.id} не выполнена: окно ${request.window_start}–${request.window_end} закрылось без бригады`,
    })
  }
  for (const event of plan.history ?? []) {
    events.push({ t: toMin(event.time), kind: 'event', text: eventText(event, names) })
  }
  events.sort((a, b) => a.t - b.t)

  let bounds: [Coord, Coord] | null = null
  if (points.length) {
    const lons = points.map((p) => p[0])
    const lats = points.map((p) => p[1])
    bounds = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ]
  }
  return { tracks, stops, missing, office, bounds, events }
}

export type CrewState = 'off' | 'idle' | 'drive' | 'wait' | 'work' | 'break'

/** Где бригада в минуту t, что делает и какую часть пути уже прошла. */
export function crewAt(track: Track, t: number): { point: Coord; state: CrewState; trail: Coord[]; km: number; wait: number } {
  const trail: Coord[] = [track.start]
  let km = 0
  let wait = 0
  let point = track.start
  let state: CrewState = 'off'
  for (const seg of track.segments) {
    if (t < seg.t0) break
    if (t >= seg.t1) {
      if (seg.kind === 'drive') {
        trail.push(seg.to)
        km += seg.km
      }
      if (seg.kind === 'wait') wait += seg.t1 - seg.t0
      point = seg.to
      state = 'idle'
      continue
    }
    const k = (t - seg.t0) / Math.max(seg.t1 - seg.t0, 1)
    if (seg.kind === 'drive') {
      point = lerp(seg.from, seg.to, k)
      trail.push(point)
      km += seg.km * k
    } else {
      point = seg.to
    }
    if (seg.kind === 'wait') wait += t - seg.t0
    state = seg.kind
    break
  }
  if (track.segments.length && t >= track.segments[track.segments.length - 1].t1) state = 'off'
  if (track.breakStart !== null && track.breakEnd !== null && t >= track.breakStart && t < track.breakEnd && state !== 'work' && state !== 'drive') state = 'break'
  return { point, state, trail, km, wait }
}

export function stopState(stop: StopInfo, t: number): StopState {
  if (t >= stop.end) return stop.late > 0 ? 'late' : 'done'
  if (t >= stop.start) return 'working'
  if (t > stop.windowEnd) return 'overdue'
  return 'planned'
}

export interface DayStats {
  total: number
  done: number
  onTime: number
  late: number
  missed: number
  value: number
  km: number
  wait: number
  working: number
  moving: number
  idle: number
  crews: number
}

/** Счётчики к минуте t: что выполнено, сколько заработано, кто чем занят. */
export function statsAt(scene: DayScene, t: number): DayStats {
  let done = 0
  let onTime = 0
  let late = 0
  let value = 0
  for (const stop of scene.stops) {
    if (t < stop.end) continue
    done += 1
    if (stop.late > 0) late += 1
    else {
      onTime += 1
      value += stop.value
    }
  }
  let km = 0
  let wait = 0
  let working = 0
  let moving = 0
  let idle = 0
  let crews = 0
  for (const track of scene.tracks) {
    if (!track.segments.length) continue
    crews += 1
    const at = crewAt(track, t)
    km += at.km
    wait += at.wait
    if (at.state === 'work') working += 1
    else if (at.state === 'drive') moving += 1
    else if (at.state === 'wait' || at.state === 'idle') idle += 1
  }
  const missed = scene.missing.filter((m) => t > m.windowEnd).length
  return {
    total: scene.stops.length + scene.missing.length,
    done,
    onTime,
    late,
    missed,
    value,
    km,
    wait,
    working,
    moving,
    idle,
    crews,
  }
}
