/** Путь общественным транспортом к заявке — ответ `/plan/{id}/crew/{eng}/transit`. */

export interface TransitLeg {
  kind: 'walk' | 'ride' | 'transfer'
  minutes: number
  wait_min: number
  place: string
  vehicle: string
  lines: string[]
  hint?: string
}

export interface TransitOption {
  total_min: number
  arrive: string
  transfers: number
  walk: string
  departures: string[]
  legs: TransitLeg[]
}

export interface TransitTrip {
  request_id: string
  depart: string
  date: string
  origin: string
  target: string
  plan_arrive?: string
  options: TransitOption[]
  note: string | null
}
