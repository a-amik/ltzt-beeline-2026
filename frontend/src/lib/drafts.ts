/**
 * Заготовка события из тычка по карте. Для показа заявку ставят не формой,
 * а пальцем: ткнули — в этой точке позвонил клиент. Всё остальное берётся
 * умолчанием, которое читается как обычный звонок днём: звонок в час,
 * названный последним событием, окно через час после звонка на три часа,
 * час работы, подключение, предложение бригадам.
 */

import type { PlanEvent, RequestItem } from '../types'

let serial = 0

export function toMin(clock: string): number {
  const [h, m] = clock.split(':').map(Number)
  return h * 60 + (m || 0)
}

export function toClock(min: number): string {
  const safe = Math.max(0, Math.min(23 * 60 + 59, Math.round(min)))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}

/** Окно через час после звонка, круглое по получасу, на три часа, не позже 21:00. */
export function windowAfter(clock: string): { start: string; end: string } {
  const start = Math.ceil((toMin(clock) + 60) / 30) * 30
  return { start: toClock(start), end: toClock(Math.min(start + 180, 21 * 60)) }
}

export function nextRequestId(prefix: string): string {
  serial += 1
  return `${prefix}${(Math.floor(Date.now() / 1000) % 10000) * 10 + serial}`
}

export function requestAt(point: { lat: number; lon: number }, clock: string, urgent = false): RequestItem {
  const window = windowAfter(clock)
  return {
    id: nextRequestId(urgent ? 'u' : 'n'),
    type_bk: urgent ? 'Авария' : 'Подключение и дозаказы',
    type_hd: urgent ? 'Срочный выезд' : 'Заявка день в день',
    address: 'Точка на карте',
    district: '—',
    lat: Number(point.lat.toFixed(5)),
    lon: Number(point.lon.toFixed(5)),
    geo_quality: 'house',
    duration_min: 60,
    window_start: urgent ? clock : window.start,
    window_end: urgent ? toClock(toMin(clock) + 240) : window.end,
    priority: urgent ? 'urgent' : 'normal',
    skill: urgent ? 'emergency' : 'connect',
    transport: null,
  }
}

export function dropEvent(point: { lat: number; lon: number }, clock: string): PlanEvent {
  return { id: `e-${Date.now()}-${serial}`, type: 'new_request', time: clock, request: requestAt(point, clock), policy: 'offer' }
}

/** Как событие называется в пачке: одна строка без подробностей. */
export function draftLabel(event: PlanEvent): string {
  switch (event.type) {
    case 'new_request':
      return `Новая заявка ${event.request.id} · окно ${event.request.window_start}–${event.request.window_end}`
    case 'urgent':
      return `Авария ${event.request.id}`
    case 'cancel':
      return `Отмена ${event.request_id}`
    case 'no_show':
      return `Клиента нет · ${event.request_id}`
    case 'reschedule':
      return `Перенос окна ${event.request_id} на ${event.window_start}–${event.window_end}`
    case 'delay':
      return `Задержка ${event.engineer_id} на ${event.delay_min} мин`
    case 'engineer_off':
      return `Выбыл ${event.engineer_id}`
    default:
      return 'Событие'
  }
}
