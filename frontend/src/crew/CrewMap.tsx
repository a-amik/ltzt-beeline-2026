/**
 * Карта дня бригады: откуда стартует, визиты по порядку с состоянием,
 * путь по улицам (OSRM через сервер, не ответил — прямыми), ближайший
 * переезд выделен. Выбран прокат — вокруг точки выезда видны машины,
 * самокаты и велосипеды (синтетика, помечена «демо»).
 *
 * Нажатие на точку открывает карточку визита; «Построить маршрут» рисует
 * путь до неё от места, где бригада сейчас (точка перед ближайшим визитом),
 * и даёт ссылки навигаторов на тот же путь.
 *
 * Карта заводится на следующем тике, как карты показа: в режиме разработки
 * React монтирует эффект дважды, и карта, снятая посреди загрузки стиля,
 * оставалась бы без стиля.
 */

import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { readToken } from '../lib/colors'
import { MAX_BOUNDS, STYLE_URL, collapseAttribution, tilesRequest } from '../lib/mapStyle'
import type { Theme } from '../store'
import type { CrewDay, MarkKind } from '../types'
import { IconClose } from '../lib/icons'
import { crewApi, navLinks, type Way } from './crewApi'

type Status = MarkKind | 'planned'

interface Props {
  day: CrewDay
  start: [number, number] | null
  statusOf: (requestId: string) => Status
  nextId: string | null
  way: Way['kind'] | null
  theme: Theme
}

const fc = (features: object[]) => ({ type: 'FeatureCollection', features }) as never
const KIND_RU: Record<string, string> = { carsharing: 'Каршеринг', scooter: 'Самокат', ebike: 'Велосипед' }
const STATUS_RU: Record<Status, string> = {
  planned: 'в плане', depart: 'в пути', arrive: 'на месте', start: 'в работе', done: 'готово', no_show: 'клиента нет',
}

/** Длина ломаной в километрах: у линии пути с сервера есть только точки. */
function lengthKm(coords: [number, number][]): number {
  let km = 0
  for (let i = 1; i < coords.length; i++) {
    const [lon1, lat1] = coords[i - 1]
    const [lon2, lat2] = coords[i]
    const dx = (lon2 - lon1) * 111.32 * Math.cos((((lat1 + lat2) / 2) * Math.PI) / 180)
    const dy = (lat2 - lat1) * 110.57
    km += Math.hypot(dx, dy)
  }
  return km
}

export default function CrewMap({ day, start, statusOf, nextId, way, theme }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const ready = useRef(false)
  const pending = useRef<(() => void)[]>([])
  const [focus, setFocus] = useState<'all' | 'next'>('all')
  const [broken, setBroken] = useState<string | null>(null)
  // Точка, нажатая на карте, и построен ли до неё маршрут.
  const [picked, setPicked] = useState<string | null>(null)
  const [built, setBuilt] = useState(false)
  const whenReady = (fn: () => void) => {
    if (ready.current) fn()
    else pending.current.push(fn)
  }

  const byId = new Map(day.requests.map((r) => [r.id, r]))
  const stops = day.route.stops.filter((s) => byId.has(s.request_id))
  const points: [number, number][] = [
    ...(start ? [[start[1], start[0]] as [number, number]] : []),
    ...stops.map((s) => [byId.get(s.request_id)!.lon, byId.get(s.request_id)!.lat] as [number, number]),
  ]
  const profile = day.engineer.transports?.includes('car') ? 'car' : 'foot'
  const line = useQuery({
    queryKey: ['crew-line', day.plan_id, day.engineer.id, profile, points.length],
    queryFn: () => crewApi.line(profile, points.slice(0, 25)),
    enabled: points.length >= 2,
    staleTime: Infinity,
    retry: false,
  })
  // Ближайший переезд — своей линией: кусок линии дня по ближайшим вершинам
  // захватывал лишнее там, где путь дня проходит мимо той же точки дважды.
  const nextIndex = stops.findIndex((s) => s.request_id === nextId)
  const legFrom = nextIndex > 0 ? points[nextIndex - 1 + (start ? 1 : 0)] : start ? points[0] : null
  const legTo = nextIndex >= 0 ? points[nextIndex + (start ? 1 : 0)] : null
  const legProfile = way === 'car' || way === 'carsharing' ? 'car' : way === 'scooter' || way === 'ebike' ? 'bike' : 'foot'
  const leg = useQuery({
    queryKey: ['crew-leg', legFrom, legTo, legProfile],
    queryFn: () => crewApi.line(legProfile, [legFrom!, legTo!]),
    enabled: Boolean(legFrom && legTo),
    staleTime: Infinity,
    retry: false,
  })
  // Маршрут до нажатой точки — от места, где бригада сейчас: точка перед
  // ближайшим визитом; смена кончилась — последний визит.
  const here: [number, number] | null = legFrom ?? (points.length ? points[points.length - 1] : null)
  const pickedRequest = picked ? byId.get(picked) ?? null : null
  const pickedStop = picked ? stops.find((s) => s.request_id === picked) ?? null : null
  const target: [number, number] | null = pickedRequest ? [pickedRequest.lon, pickedRequest.lat] : null
  const pickLine = useQuery({
    queryKey: ['crew-pick', here, target, legProfile],
    queryFn: () => crewApi.line(legProfile, [here!, target!]),
    enabled: Boolean(built && here && target),
    staleTime: Infinity,
    retry: false,
  })
  const pickCoords = built && here && target ? (pickLine.data?.coordinates ?? [here, target]) : null
  const choose = (id: string | null) => {
    setPicked(id)
    setBuilt(false)
  }

  const rental = way === 'carsharing' || way === 'scooter' || way === 'ebike'
  const ways = useQuery({
    queryKey: ['crew-ways', day.plan_id, day.engineer.id, nextId],
    queryFn: () => crewApi.ways(day.plan_id, day.engineer.id, nextId!),
    enabled: Boolean(nextId && rental),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!box.current) return
    const container = box.current
    const holder: { map: MapLibreMap | null } = { map: null }
    let observer: ResizeObserver | null = null
    const timer = window.setTimeout(() => {
      let map: MapLibreMap
      try {
        map = new MapLibreMap({
          container,
          style: STYLE_URL[theme],
          transformRequest: tilesRequest,
          center: [37.7, 55.6],
          zoom: 10,
          minZoom: 7,
          maxBounds: MAX_BOUNDS,
          attributionControl: { compact: true },
        })
      } catch {
        // Без WebGL2 карты нет: говорим словами, а маршрут остаётся списком.
        setBroken('Карта не открылась: браузеру нужен WebGL2. Маршрут дня — во вкладке «Маршрут».')
        return
      }
      holder.map = map
      mapRef.current = map
      collapseAttribution(map)
      const accent = readToken('--b-accent', '#ffc800')
      const ink = readToken('--b-text', '#13171b')
      const surface = readToken('--b-surface', '#ffffff')
      const ok = readToken('--b-success', '#15803d')
      const danger = readToken('--b-danger', '#c8341a')
      const info = readToken('--b-info', '#2563eb')
      map.on('load', () => {
        for (const id of ['c-line', 'c-next', 'c-stops', 'c-start', 'c-fleet']) map.addSource(id, { type: 'geojson', data: fc([]) })
        map.addLayer({ id: 'c-line', type: 'line', source: 'c-line', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': ink, 'line-width': 3, 'line-opacity': 0.35 } })
        map.addLayer({ id: 'c-next', type: 'line', source: 'c-next', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': info, 'line-width': 5 } })
        map.addLayer({
          id: 'c-fleet', type: 'circle', source: 'c-fleet',
          paint: { 'circle-radius': 6, 'circle-color': ['match', ['get', 'kind'], 'carsharing', info, 'scooter', ok, accent] as never, 'circle-stroke-width': 1.5, 'circle-stroke-color': surface },
        })
        map.addLayer({
          id: 'c-stops', type: 'circle', source: 'c-stops',
          paint: {
            'circle-radius': ['case', ['get', 'next'], 14, 11] as never,
            'circle-color': ['match', ['get', 'status'], 'done', ok, 'no_show', danger, 'planned', surface, accent] as never,
            'circle-stroke-width': ['case', ['get', 'next'], 3, 2] as never,
            'circle-stroke-color': ['case', ['get', 'next'], info, ink] as never,
          },
        })
        map.addLayer({
          id: 'c-stop-no', type: 'symbol', source: 'c-stops',
          layout: { 'text-field': ['get', 'seq'] as never, 'text-font': ['Noto Sans Regular'], 'text-size': 12, 'text-allow-overlap': true },
          paint: { 'text-color': ['match', ['get', 'status'], 'done', surface, 'no_show', surface, ink] as never },
        })
        map.addLayer({ id: 'c-start', type: 'circle', source: 'c-start', paint: { 'circle-radius': 8, 'circle-color': accent, 'circle-stroke-width': 3, 'circle-stroke-color': ink } })
        // Нажатие на визит — карточка с «Построить маршрут».
        map.on('click', 'c-stops', (event) => {
          const id = event.features?.[0]?.properties?.id
          if (typeof id === 'string') choose(id)
        })
        map.on('mouseenter', 'c-stops', () => (map.getCanvas().style.cursor = 'pointer'))
        map.on('mouseleave', 'c-stops', () => (map.getCanvas().style.cursor = ''))
        ready.current = true
        for (const fn of pending.current.splice(0)) {
          try {
            fn()
          } catch {
            // вызов от прежней карты
          }
        }
      })
      observer = new ResizeObserver(() => map.resize())
      observer.observe(container)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
      holder.map?.remove()
      mapRef.current = null
      ready.current = false
      pending.current = []
    }
  }, [theme])

  // Визиты, старт и путь.
  const signature = `${stops.map((s) => `${s.request_id}:${statusOf(s.request_id)}`).join('|')}|${nextId}|${line.data?.source}`
  useEffect(() => {
    whenReady(() => {
      const map = mapRef.current
      if (!map) return
      ;(map.getSource('c-stops') as GeoJSONSource).setData(fc(stops.map((s) => {
        const r = byId.get(s.request_id)!
        return { type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] }, properties: { id: s.request_id, seq: String(s.seq), status: statusOf(s.request_id), next: s.request_id === nextId || s.request_id === picked } }
      })))
      ;(map.getSource('c-start') as GeoJSONSource).setData(fc(start ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [start[1], start[0]] }, properties: {} }] : []))
      const coords = line.data?.coordinates ?? points
      ;(map.getSource('c-line') as GeoJSONSource).setData(fc(coords.length >= 2 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} }] : []))
      // Построенный маршрут до нажатой точки занимает синюю линию ближайшего переезда.
      const legLine = pickCoords ?? leg.data?.coordinates ?? (legFrom && legTo ? [legFrom, legTo] : [])
      ;(map.getSource('c-next') as GeoJSONSource).setData(fc(legLine.length >= 2 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: legLine }, properties: {} }] : []))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, line.data, leg.data, picked, built, pickLine.data])

  // Прокат вокруг точки выезда.
  useEffect(() => {
    whenReady(() => {
      const map = mapRef.current
      if (!map) return
      const fleet = rental ? (ways.data?.vehicles ?? []).filter((v) => v.kind === way) : []
      ;(map.getSource('c-fleet') as GeoJSONSource).setData(fc(fleet.map((v) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [v.lon, v.lat] }, properties: { kind: v.kind } }))))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ways.data, way])

  // Камера: весь день или ближайший переезд.
  useEffect(() => {
    whenReady(() => {
      const map = mapRef.current
      if (!map || !points.length) return
      // Камера берёт всю линию переезда: пешая дорога огибает рельсы и реки,
      // и рамка по одним концам обрезала бы её.
      const pick = pickCoords
        ? pickCoords
        : focus === 'next' && legFrom && legTo
        ? (leg.data?.coordinates ?? [legFrom, legTo])
        : (line.data?.coordinates ?? points)
      const bounds = new LngLatBounds()
      for (const p of pick) bounds.extend(p)
      // Под построенным маршрутом снизу стоит карточка точки — камера оставляет ей место.
      const padding = pickCoords ? { top: 64, right: 40, bottom: 240, left: 40 } : 48
      map.fitBounds(bounds, { padding, maxZoom: 15, duration: 0 })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, points.length, nextId, leg.data, line.data, built, pickLine.data])

  const fleetCount = rental ? (ways.data?.vehicles ?? []).filter((v) => v.kind === way).length : 0
  return (
    <div className="b-crew-map">
      <div ref={box} className="b-crew-map-box" />
      {broken ? <p className="b-crew-map-broken">{broken}</p> : null}
      <div className="b-crew-map-bar">
        <Button view={focus === 'all' ? 'action' : 'normal'} size="m" onClick={() => setFocus('all')}>
          Весь день
        </Button>
        <Button view={focus === 'next' ? 'action' : 'normal'} size="m" disabled={!nextId} onClick={() => setFocus('next')}>
          Ближайший переезд
        </Button>
      </div>
      {pickedRequest && pickedStop ? (
        <section className="b-crew-map-card" aria-label={`Визит ${pickedStop.seq}`}>
          <header>
            <b>
              {pickedStop.seq}. {pickedRequest.type_bk}
            </b>
            <button type="button" className="b-sheet-x" aria-label="Закрыть" onClick={() => choose(null)}>
              <IconClose />
            </button>
          </header>
          <span>{pickedRequest.address}</span>
          <em>
            окно {pickedRequest.window_start}–{pickedRequest.window_end} · приезд {pickedStop.arrive} · {STATUS_RU[statusOf(pickedRequest.id)]}
          </em>
          {built && here && target ? (
            <>
              <em>
                {pickLine.isFetching ? 'Строим путь…' : `${lengthKm(pickCoords ?? []).toFixed(1).replace('.', ',')} км${pickLine.data?.source === 'straight' ? ' по прямой' : ''}`}
              </em>
              <div className="b-nav-links">
                <a href={navLinks([here[1], here[0]], [target[1], target[0]], way ?? 'car').yandex} target="_blank" rel="noreferrer">
                  Яндекс Карты
                </a>
                <a href={navLinks([here[1], here[0]], [target[1], target[0]], way ?? 'car').dgis} target="_blank" rel="noreferrer">
                  2ГИС
                </a>
              </div>
            </>
          ) : (
            <Button view="action" size="l" width="max" disabled={!here} onClick={() => setBuilt(true)}>
              Построить маршрут
            </Button>
          )}
        </section>
      ) : null}
      <p className="b-crew-map-note">
        {line.data?.source === 'straight' ? 'Путь прямыми: маршрутизатор не ответил. ' : ''}
        {fleetCount ? `${KIND_RU[way!]}: ${fleetCount} рядом с точкой выезда, демо. ` : ''}
        Жёлтый круг — старт, синий — ближайший визит. Нажмите точку — маршрут до неё.
      </p>
    </div>
  )
}
