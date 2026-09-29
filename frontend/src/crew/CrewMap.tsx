/**
 * Карта дня бригады: откуда стартует, визиты по порядку с состоянием,
 * путь по улицам (OSRM через сервер, не ответил — прямыми), ближайший
 * переезд выделен. Выбран прокат — вокруг точки выезда видны машины,
 * самокаты и велосипеды (синтетика, помечена «демо»).
 *
 * Нажатие на точку сразу строит путь до неё, как построение маршрута
 * в Яндекс Картах: сверху «откуда — куда», снизу плашка «Как поеду» к этому
 * адресу — способы с временем и ценой из расчёта сервера. Откуда — точка
 * перед визитом по плану (предыдущий визит или старт дня). Выбранный способ
 * сразу перерисовывает путь и ссылки навигаторов.
 * Плашка «Маршрут» открывает поверх карты визиты дня списком; строка
 * списка строит путь так же, как нажатие точки. Легенда — в значке ⓘ.
 *
 * Карта заводится на следующем тике, как карты показа: в режиме разработки
 * React монтирует эффект дважды, и карта, снятая посреди загрузки стиля,
 * оставалась бы без стиля.
 */

import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useQuery } from '@tanstack/react-query'
import { Label } from '@gravity-ui/uikit'
import { readToken } from '../lib/colors'
import { MAX_BOUNDS, STYLE_URL, collapseAttribution, tilesRequest } from '../lib/mapStyle'
import type { Theme } from '../store'
import type { CrewDay, MarkKind, Standby } from '../types'
import { num, plural } from '../lib/ui'
import { IconBike, IconCar, IconCarShare, IconClose, IconNavigate, IconScooter, IconTransit, IconWalk } from '../lib/icons'
import { crewApi, navLinks, type Way } from './crewApi'
import InfoTip from './InfoTip'

type Status = MarkKind | 'planned'

interface Props {
  day: CrewDay
  start: [number, number] | null
  statusOf: (requestId: string) => Status
  nextId: string | null
  way: Way['kind'] | null
  /** Способ, выбранный к каждому визиту, и запись нового выбора. */
  chosen: Record<string, Way['kind']>
  onWay: (requestId: string, kind: Way['kind']) => void
  theme: Theme
  /** Где ждать между визитами — строки под списком маршрута. */
  waits: Standby[]
}

const fc = (features: object[]) => ({ type: 'FeatureCollection', features }) as never
const WAY_ICON: Record<Way['kind'], (p: { className?: string }) => React.ReactNode> = {
  car: IconCar, carsharing: IconCarShare, transit: IconTransit, scooter: IconScooter, ebike: IconBike, foot: IconWalk,
}
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

export default function CrewMap({ day, start, statusOf, nextId, way, chosen, onWay, theme, waits }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const ready = useRef(false)
  const pending = useRef<(() => void)[]>([])
  const [focus, setFocus] = useState<'all' | 'next'>('all')
  // Список визитов дня поверх карты — плашка «Маршрут».
  const [listOpen, setListOpen] = useState(false)
  const [broken, setBroken] = useState<string | null>(null)
  // Точка, нажатая на карте: путь до неё строится сразу.
  const [picked, setPicked] = useState<string | null>(null)
  const built = picked !== null
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
  // Нажатая точка: способы доезда до неё — тот же расчёт, что у «Как поеду».
  const pickedRequest = picked ? byId.get(picked) ?? null : null
  const pickedIndex = picked ? stops.findIndex((s) => s.request_id === picked) : -1
  const pickedStop = pickedIndex >= 0 ? stops[pickedIndex] : null
  const pickWays = useQuery({
    queryKey: ['crew-ways', day.plan_id, day.engineer.id, picked],
    queryFn: () => crewApi.ways(day.plan_id, day.engineer.id, picked!),
    enabled: Boolean(picked),
    staleTime: 60_000,
    retry: false,
  })
  const pw = pickWays.data
  const pickWay = pw ? pw.ways.find((w) => w.kind === (picked ? chosen[picked] : null)) ?? pw.ways[0] ?? null : null
  const pickProfile = !pickWay ? 'foot' : pickWay.kind === 'car' || pickWay.kind === 'carsharing' ? 'car' : pickWay.kind === 'scooter' || pickWay.kind === 'ebike' ? 'bike' : 'foot'
  // С сервера точки приходят широтой вперёд, линия и карта — долготой.
  const from: [number, number] | null = pw ? [pw.origin[1], pw.origin[0]] : null
  const target: [number, number] | null = pw ? [pw.target[1], pw.target[0]] : null
  const pickLine = useQuery({
    queryKey: ['crew-pick', from, target, pickProfile],
    queryFn: () => crewApi.line(pickProfile, [from!, target!]),
    enabled: Boolean(built && from && target),
    staleTime: Infinity,
    retry: false,
  })
  const pickCoords = built && from && target ? (pickLine.data?.coordinates ?? [from, target]) : null
  const choose = (id: string | null) => {
    setPicked(id)
    if (id) setListOpen(false)
  }
  // «Откуда» словами: визит перед нажатым по плану, иначе старт дня.
  const fromStop = pickedIndex > 0 ? stops[pickedIndex - 1] : null
  const fromLabel = fromStop ? `Визит ${fromStop.seq} · ${byId.get(fromStop.request_id)?.address ?? ''}` : 'Старт дня'

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
  }, [signature, line.data, leg.data, picked, built, pickLine.data, pw])

  // Прокат вокруг точки выезда.
  useEffect(() => {
    whenReady(() => {
      const map = mapRef.current
      if (!map) return
      const kind = pickWay ? pickWay.kind : way
      const source = pickWay ? pw?.vehicles : ways.data?.vehicles
      const fleet = kind === 'carsharing' || kind === 'scooter' || kind === 'ebike' ? (source ?? []).filter((v) => v.kind === kind) : []
      ;(map.getSource('c-fleet') as GeoJSONSource).setData(fc(fleet.map((v) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [v.lon, v.lat] }, properties: { kind: v.kind } }))))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ways.data, way, pw, pickWay?.kind])

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
      const padding = pickCoords ? { top: 150, right: 40, bottom: 230, left: 40 } : { top: 64, right: 48, bottom: 48, left: 48 }
      map.fitBounds(bounds, { padding, maxZoom: 15, duration: 0 })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, points.length, nextId, leg.data, line.data, built, pickLine.data, pw])

  const fleetCount = rental ? (ways.data?.vehicles ?? []).filter((v) => v.kind === way).length : 0
  const km = pickLine.data ? lengthKm(pickLine.data.coordinates).toFixed(1).replace('.', ',') : null
  const nav = pw && pickWay ? navLinks(pw.origin, pw.target, pickWay.kind) : null
  return (
    <div className="b-crew-map">
      <div ref={box} className="b-crew-map-box" />
      {broken ? <p className="b-crew-map-broken">{broken}</p> : null}
      {pickedRequest && pickedStop ? (
        // Как построение маршрута в Яндекс Картах: откуда — куда.
        <section className="b-map-rt" aria-label="Маршрут до визита">
          <ol>
            <li>
              <i className="from" aria-hidden="true" />
              <span>
                <small>Откуда</small>
                <b>{fromLabel}</b>
              </span>
            </li>
            <li>
              <i className="to" aria-hidden="true" />
              <span>
                <small>Куда</small>
                <b>
                  Визит {pickedStop.seq} · {pickedRequest.address}
                </b>
              </span>
            </li>
          </ol>
          <button type="button" className="b-sheet-x" aria-label="Закрыть маршрут" onClick={() => choose(null)}>
            <IconClose />
          </button>
        </section>
      ) : (
        <div className="b-map-chips" role="group" aria-label="Что показать">
          <button type="button" className={focus === 'all' && !listOpen ? 'on' : ''} aria-pressed={focus === 'all' && !listOpen} onClick={() => { setFocus('all'); setListOpen(false) }}>
            Весь день
          </button>
          <button type="button" className={focus === 'next' && !listOpen ? 'on' : ''} aria-pressed={focus === 'next' && !listOpen} disabled={!nextId} onClick={() => { setFocus('next'); setListOpen(false) }}>
            Переезд
          </button>
          <button type="button" className={listOpen ? 'on' : ''} aria-pressed={listOpen} onClick={() => setListOpen(!listOpen)}>
            Маршрут · {stops.length}
          </button>
        </div>
      )}
      {!pickedRequest ? (
        <InfoTip label="Что на карте" className="b-map-tip">
          <ul className="b-map-legend">
            <li><i className="start" />Старт дня</li>
            <li><i className="next" />Ближайший визит и путь до него</li>
            <li><i className="done" />Готово</li>
            <li><i className="noshow" />Клиента нет</li>
          </ul>
          <p>Нажмите точку — маршрут до неё.</p>
          {line.data?.source === 'straight' ? <p>Путь дня прямыми: маршрутизатор не ответил.</p> : null}
          {fleetCount ? <p>{KIND_RU[way!]}: {fleetCount} рядом с точкой выезда, демо.</p> : null}
        </InfoTip>
      ) : null}
      {listOpen && !pickedRequest ? (
        <section className="b-map-list" aria-label="Маршрут дня">
          <header>
            <h3>
              {stops.length} {plural(stops.length, 'визит', 'визита', 'визитов')}
              {day.route.break_start ? <small> · обед {day.route.break_start}–{day.route.break_end}</small> : null}
            </h3>
            <button type="button" className="b-sheet-x" aria-label="Скрыть маршрут" onClick={() => setListOpen(false)}>
              <IconClose />
            </button>
          </header>
          <div className="b-map-list-body b-scroll">
            <ol className="b-crew-route">
              {stops.map((stop) => {
                const request = byId.get(stop.request_id)
                const status: Status = stop.status === 'no_show' ? 'no_show' : statusOf(stop.request_id)
                return (
                  <li key={stop.request_id} className={`${status}${stop.request_id === nextId ? ' next' : ''}`}>
                    <button type="button" onClick={() => choose(stop.request_id)} aria-label={`Маршрут до визита ${stop.seq}`}>
                      <time>{stop.arrive}</time>
                      <span>
                        <b>
                          {stop.seq}. {request?.type_bk ?? stop.request_id}
                        </b>
                        <em>{request?.address ?? ''}</em>
                        <em>
                          окно {request?.window_start}–{request?.window_end} · дорога {stop.travel_min} мин
                        </em>
                      </span>
                      <Label size="xs" theme={status === 'done' ? 'success' : status === 'no_show' ? 'danger' : 'normal'}>
                        {STATUS_RU[status]}
                      </Label>
                    </button>
                  </li>
                )
              })}
            </ol>
            {waits.length ? (
              <div className="b-waits">
                <h4>Где ждать между визитами</h4>
                {waits.map((w) => (
                  <p key={`${w.after_request_id}-${w.start}`}>
                    <time>
                      {w.start}–{w.end}
                    </time>
                    {w.text}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      {pickedRequest && pickedStop ? (
        // Плашка «Как поеду» к нажатому адресу: способы посчитаны заранее.
        <section className="b-crew-map-card" aria-label={`Как поеду к визиту ${pickedStop.seq}`}>
          {pickWays.isError ? (
            <p className="b-crew-muted">Способы не посчитались: {String(pickWays.error)}</p>
          ) : !pw || !pickWay ? (
            <p className="b-crew-muted">Считаем способы…</p>
          ) : (
            <>
              <div className="b-map-km">
                <b>{pickWay.minutes} мин</b>
                <span>
                  {km ? `${km} км${pickLine.data?.source === 'straight' ? ' по прямой' : ''} · ` : ''}
                  {pickWay.late_min ? <em className="late">опоздание {pickWay.late_min} мин</em> : `на месте в ${pickWay.arrive}`}
                </span>
              </div>
              <em>
                {pickedRequest.type_bk} · выезд {pw.depart} · окно {pickedRequest.window_start}–{pickedRequest.window_end}
              </em>
              <ul className="b-map-ways" role="radiogroup" aria-label="Способ поездки">
                {pw.ways.map((w) => {
                  const Icon = WAY_ICON[w.kind]
                  return (
                    <li key={w.kind}>
                      <button
                        type="button"
                        role="radio"
                        aria-checked={w.kind === pickWay.kind}
                        aria-label={`${w.label}: ${w.minutes} мин${w.price_rub ? `, ${num(w.price_rub)} ₽` : ''}`}
                        className={`${w.kind === pickWay.kind ? 'on' : ''}${w.late_min ? ' late' : ''}`}
                        onClick={() => onWay(pickedRequest.id, w.kind)}
                      >
                        <Icon />
                        <b>{w.minutes} мин</b>
                        <small>{w.price_rub ? `≈ ${num(w.price_rub)} ₽` : 'бесплатно'}</small>
                      </button>
                    </li>
                  )
                })}
              </ul>
              {pickWay.note || pickWay.walk_min ? (
                <em>
                  {pickWay.label}
                  {pickWay.walk_min ? ` · ${pickWay.walk_min} мин пешком до ${pickWay.kind === 'carsharing' ? 'машины' : 'проката'}` : ''}
                  {pickWay.note ? ` · ${pickWay.note}` : ''}
                </em>
              ) : null}
              {nav ? (
                <div className="b-nav-links">
                  <a href={nav.yandex} target="_blank" rel="noreferrer">
                    <IconNavigate />
                    Яндекс Карты
                  </a>
                  <a href={nav.dgis} target="_blank" rel="noreferrer" className="alt">
                    2ГИС
                  </a>
                </div>
              ) : null}
            </>
          )}
        </section>
      ) : null}
    </div>
  )
}
