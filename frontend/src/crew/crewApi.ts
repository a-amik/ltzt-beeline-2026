/**
 * Ручки приложения бригады для показа (`crew_app.py` на сервере): профиль
 * с адресами, способы поездки, подменный номер, переписка, отчёт, смена,
 * история, линия пути. Отдельно от `api.ts` нарочно: это витрина для показа,
 * и её ручки не должны смешиваться с проектными.
 */

const BASE: string = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export interface Address {
  id: string
  label: string
  address: string
  lat: number
  lon: number
}

export interface CrewProfile {
  engineer_id: string
  addresses: Address[]
  start_id: string | null
  since: string | null
  since_plan: string | null
}

export interface Vehicle {
  id: string
  kind: 'carsharing' | 'scooter' | 'ebike'
  operator: string
  lat: number
  lon: number
  charge: number
  walk_min: number
}

export interface Way {
  kind: 'car' | 'transit' | 'carsharing' | 'scooter' | 'ebike' | 'foot'
  label: string
  minutes: number
  walk_min: number
  price_rub: number
  arrive: string
  late_min: number
  vehicle: Vehicle | null
  note: string
}

export interface Ways {
  request_id: string
  depart: string
  plan_arrive: string
  origin: [number, number]
  target: [number, number]
  ways: Way[]
  vehicles: Vehicle[]
}

export interface Message {
  id: number
  author: 'crew' | 'dispatcher'
  kind: 'text' | 'problem' | 'sos' | 'call' | 'report' | 'delay'
  text: string
  time: string
  request_id: string | null
  read: boolean
}

export interface FeedItem {
  id: string
  kind: Message['kind'] | 'flag'
  author: 'crew' | 'dispatcher' | 'control'
  engineer_id: string
  engineer: string
  time: string
  text: string
  request_id: string | null
  unread: boolean
  severity?: 'info' | 'warn' | 'alert'
}

export interface Feed {
  items: FeedItem[]
  unread: number
  urgent: number
}

export interface CallOut {
  request_id: string
  proxy: string
  client_masked: string
  valid_until: string
  note: string
}

export interface Report {
  request_id: string
  checklist: string[]
  photos_before: number
  photos_after: number
  equipment: string[]
  signed: boolean
  comment: string
}

export interface ShiftEvent {
  kind: 'start' | 'pause' | 'resume' | 'end'
  time: string
}

export interface History {
  rating: number
  reviews_count: number
  days: { date: string; visits: number; on_time: number; km: number; earned_rub: number }[]
  reviews: { date: string; stars: number; text: string; type_bk: string }[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(8000),
  })
  if (!response.ok) {
    let detail = `${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // тело не JSON
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

const send = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })
const crew = (region: string, eng: string) => `/crew/${region}/${encodeURIComponent(eng)}`

export const crewApi = {
  profile: (region: string, eng: string) => call<CrewProfile>(`${crew(region, eng)}/profile`),
  saveProfile: (region: string, eng: string, profile: CrewProfile) =>
    call<CrewProfile>(`${crew(region, eng)}/profile`, send('PUT', profile)),
  geocode: (q: string) => call<{ lat: number; lon: number; quality: string }>(`/geocode?q=${encodeURIComponent(q)}`),
  ways: (planId: string, eng: string, requestId: string) =>
    call<Ways>(`/plan/${planId}/crew/${encodeURIComponent(eng)}/ways?request_id=${encodeURIComponent(requestId)}`),
  call: (planId: string, eng: string, requestId: string) =>
    call<CallOut>(`/plan/${planId}/crew/${encodeURIComponent(eng)}/call`, send('POST', { request_id: requestId })),
  messages: (region: string, eng: string) => call<Message[]>(`${crew(region, eng)}/messages`),
  say: (region: string, eng: string, body: { text: string; kind?: Message['kind']; request_id?: string | null; author?: string }) =>
    call<Message>(`${crew(region, eng)}/messages`, send('POST', body)),
  read: (region: string, eng: string, reader: 'crew' | 'dispatcher') =>
    call<{ ok: boolean }>(`${crew(region, eng)}/messages/read?reader=${reader}`, { method: 'POST' }),
  inbox: (region: string) =>
    call<Record<string, { unread: number; last: Message; sos: boolean; problem: boolean }>>(`/crew/${region}/inbox`),
  report: (region: string, eng: string, report: Report) =>
    call<Report>(`${crew(region, eng)}/report`, send('POST', report)),
  reports: (region: string, eng: string) => call<Record<string, Report>>(`${crew(region, eng)}/reports`),
  shift: (region: string, eng: string) => call<ShiftEvent[]>(`${crew(region, eng)}/shift`),
  shiftEvent: (region: string, eng: string, event: ShiftEvent) =>
    call<ShiftEvent[]>(`${crew(region, eng)}/shift`, send('POST', event)),
  delay: (planId: string, eng: string, minutes: number, time: string, requestId: string | null) =>
    call<{ replanned: boolean; plan_id: string; changed: number; text: string }>(
      `/plan/${planId}/crew/${encodeURIComponent(eng)}/delay`,
      send('POST', { minutes, time, request_id: requestId }),
    ),
  feed: (region: string) => call<Feed>(`/crew/${region}/feed`),
  history: (region: string, eng: string) => call<History>(`${crew(region, eng)}/history`),
  line: (profile: string, coords: [number, number][]) =>
    call<{ coordinates: [number, number][]; source: string }>(
      `/route?profile=${profile}&coords=${encodeURIComponent(coords.map(([lon, lat]) => `${lon.toFixed(6)},${lat.toFixed(6)}`).join(';'))}`,
    ),
}

/** Ссылки навигаторов: путь от точки до точки выбранным способом. */
export function navLinks(from: [number, number], to: [number, number], kind: Way['kind'] | 'car') {
  const rtt = { car: 'auto', carsharing: 'auto', transit: 'mt', foot: 'pd', scooter: 'sc', ebike: 'bc' }[kind] ?? 'auto'
  return {
    yandex: `https://yandex.ru/maps/?rtext=${from[0]},${from[1]}~${to[0]},${to[1]}&rtt=${rtt}`,
    dgis: `https://2gis.ru/moscow/directions/points/${from[1]},${from[0]}%7C${to[1]},${to[0]}`,
  }
}
