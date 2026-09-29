/**
 * Карта. Источники и слои у неё свои, а не из стиля: тему меняют на ходу,
 * `setStyle` уносит всё нарисованное, и по событию `styledata` слои встают
 * заново. Выбранный инженер идёт в полную силу, остальные в четверть —
 * это feature-state, а не пересборка данных.
 *
 * Маршруты не появляются, а чертятся: координаты наращиваются с разбегом
 * по инженерам. При «меньше движения» линия ложится целиком сразу.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  type GeoJSONSource,
  type MapMouseEvent,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// Воркер MapLibre 6 — отдельный ES-модуль, который качает и разбирает тайлы.
// Библиотека ищет его рядом со своим бандлом, поэтому в боевую сборку файлы
// пакета копируются как есть в assets/ (scripts/vendor-maplibre.mjs, хуки
// predev и prebuild), а в dev пакет исключён из предсборки Vite. Явный адрес
// через setWorkerUrl не годится: тогда воркер создаётся классическим скриптом,
// а файл — модуль.
import { useReducedMotion } from 'motion/react'
import { Button, SegmentedRadioGroup } from '@gravity-ui/uikit'
import { activePlan, useStore, type Theme } from '../store'
import { usePlaces } from '../lib/places'
import { colorIndex, readRouteColors, readToken } from '../lib/colors'
import { changedRoutes, knownRequests } from '../lib/plan'
import { MAX_BOUNDS, STYLE_URL, collapseAttribution, tilesRequest } from '../lib/mapStyle'
import { IconAlert, IconFit, IconPin } from '../lib/icons'
import { dropEvent } from '../lib/drafts'
import DraftPanel from './DraftPanel'
import type { Coord, Dataset, Plan } from '../types'
import RequestPopup from './RequestPopup'
import { AreaWait, onMapReady } from './Loading'
import ImportOverlay from './ImportOverlay'

const SRC_ROUTES = 'b-routes'
const SRC_STOPS = 'b-stops'
const SRC_MISSING = 'b-missing'
const SRC_OFFICE = 'b-office'

interface Line {
  id: number
  engineerId: string
  color: string
  changed: boolean
  coords: Coord[]
}

interface Dot {
  id: number
  requestId: string
  engineerId: string
  color: string
  seq: number
  urgent: boolean
  point: Coord
}

interface Missing {
  id: number
  requestId: string
  point: Coord
  leg: Coord[]
}

interface Scene {
  lines: Line[]
  dots: Dot[]
  missing: Missing[]
  office: Coord
  colors: { grey: string; accent: string; office: string }
}

const EMPTY: Scene = {
  lines: [],
  dots: [],
  missing: [],
  office: [37.66, 55.596],
  colors: { grey: '#8f959d', accent: '#ffc800', office: '#13171b' },
}

interface Palette {
  routes: string[]
  grey: string
  accent: string
  ink: string
}

/** Краски спрашиваются у листа: тему меняют на ходу, и записанная — чужая. */
function readPalette(theme: Theme): Palette {
  const dark = theme === 'dark'
  return {
    routes: readRouteColors(),
    grey: readToken('--b-text-3', dark ? '#757c85' : '#8f959d'),
    accent: readToken('--b-accent', '#ffc800'),
    ink: readToken('--b-text', dark ? '#fdfdfe' : '#13171b'),
  }
}

/** Ломаная маршрута: у пустой геометрии остаётся прямая между точками. */
function buildScene(dataset: Dataset | null, plan: Plan | null, colors: Palette, sector: string | null = null, districts: string[] = []): Scene {
  if (!dataset) return EMPTY
  const palette = colors.routes
  const grey = colors.grey
  const accent = colors.accent
  const office: Coord = [dataset.office.lon, dataset.office.lat]
  const order = dataset.engineers.map((engineer) => engineer.id)
  const touched = changedRoutes(plan)

  const requests = new Map(knownRequests(dataset, plan).map((item) => [item.id, item]))

  const lines: Line[] = []
  const dots: Dot[] = []
  let id = 1

  // «Вся Москва»: у бригады офис своего участка; фильтр участка оставляет его бригады и заявки.
  // Фильтр районов оставляет маршруты, заходящие в эти районы, целиком — как список инженеров.
  const wanted = new Set(districts)
  const crews = new Map(dataset.engineers.map((engineer) => [engineer.id, engineer]))
  const offices = new Map((dataset.sectors ?? []).map((item) => [item.id, [item.office.lon, item.office.lat] as Coord]))
  for (const route of plan?.routes ?? []) {
    const crew = crews.get(route.engineer_id)
    if (sector && crew?.sector !== sector) continue
    if (wanted.size && !route.stops.some((stop) => wanted.has(requests.get(stop.request_id)?.district ?? ''))) continue
    const color = palette[colorIndex(route.engineer_id, order)] ?? grey
    const home = (crew?.sector && offices.get(crew.sector)) || office
    const coords: Coord[] = [home]
    let previous: Coord = home
    for (const stop of route.stops) {
      const request = requests.get(stop.request_id)
      if (!request) continue
      const point: Coord = [request.lon, request.lat]
      if (stop.geometry.length > 1) coords.push(...stop.geometry)
      else coords.push(previous, point)
      previous = point
      dots.push({
        id: id++,
        requestId: request.id,
        engineerId: route.engineer_id,
        color,
        seq: stop.seq,
        urgent: request.priority === 'urgent',
        point,
      })
    }
    if (coords.length > 1) {
      lines.push({
        id: id++,
        engineerId: route.engineer_id,
        color,
        changed: touched.has(route.engineer_id),
        coords,
      })
    }
  }

  const missing: Missing[] = []
  for (const item of plan?.unassigned ?? []) {
    const request = requests.get(item.request_id)
    if (!request || (sector && request.sector !== sector) || (wanted.size && !wanted.has(request.district))) continue
    const point: Coord = [request.lon, request.lat]
    const from = (request.sector && offices.get(request.sector)) || office
    missing.push({ id: id++, requestId: request.id, point, leg: [from, point] })
  }

  return { lines, dots, missing, office, colors: { grey, accent, office: colors.ink } }
}

function lineData(scene: Scene, progress: Record<string, number>) {
  return {
    type: 'FeatureCollection',
    features: scene.lines.map((line) => {
      const share = progress[line.engineerId] ?? 1
      const count = Math.max(2, Math.ceil(line.coords.length * share))
      return {
        type: 'Feature',
        id: line.id,
        properties: { engineer: line.engineerId, color: line.color, changed: line.changed },
        geometry: { type: 'LineString', coordinates: line.coords.slice(0, count) },
      }
    }),
  }
}

function dotData(scene: Scene) {
  return {
    type: 'FeatureCollection',
    features: scene.dots.map((dot) => ({
      type: 'Feature',
      id: dot.id,
      properties: {
        request: dot.requestId,
        engineer: dot.engineerId,
        color: dot.urgent ? scene.colors.accent : dot.color,
        seq: String(dot.seq),
      },
      geometry: { type: 'Point', coordinates: dot.point },
    })),
  }
}

function missingData(scene: Scene) {
  return {
    type: 'FeatureCollection',
    features: scene.missing.flatMap((item) => [
      {
        type: 'Feature',
        id: item.id,
        properties: { request: item.requestId, kind: 'leg' },
        geometry: { type: 'LineString', coordinates: item.leg },
      },
      {
        type: 'Feature',
        id: item.id + 10000,
        properties: { request: item.requestId, kind: 'dot' },
        geometry: { type: 'Point', coordinates: item.point },
      },
    ]),
  }
}

function officeData(scene: Scene) {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: 1,
        properties: {},
        geometry: { type: 'Point', coordinates: scene.office },
      },
    ],
  }
}

const DIM = ['case', ['boolean', ['feature-state', 'dim'], false], 0.25, 1]
const SEL = ['boolean', ['feature-state', 'sel'], false]

export default function MapView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [mapReady, setMapReady] = useState(false)
  const mapRef = useRef<MapLibreMap | null>(null)
  const styleThemeRef = useRef<Theme | null>(null)
  const sceneRef = useRef<Scene>(EMPTY)
  const progressRef = useRef<Record<string, number>>({})
  const fittedRef = useRef(false)
  const reduced = useReducedMotion()

  const dataset = useStore((s) => s.dataset)
  const theme = useStore((s) => s.theme)
  const picking = useStore((s) => s.picking)
  const selectedEngineerId = useStore((s) => s.selectedEngineerId)
  const selectedRequestId = useStore((s) => s.selectedRequestId)
  const drawSeed = useStore((s) => s.drawSeed)
  const plan = useStore((s) => activePlan(s))

  const palette = useMemo(() => readPalette(theme), [theme])
  const sector = useStore((s) => s.sector)
  const districts = usePlaces((s) => s.districts)
  const scene = useMemo(() => buildScene(dataset, plan, palette, sector, districts), [dataset, plan, palette, sector, districts])

  // Сцену держим ссылкой: её спрашивают обработчики карты, а не отрисовка.
  useEffect(() => {
    sceneRef.current = scene
  }, [scene])

  /**
   * Слои свои: после смены стиля их некому вернуть, кроме нас. Ждать
   * `isStyleLoaded()` нельзя — он остаётся ложным, пока не приехали плитки
   * подложки, и на плохой сети маршруты не появились бы вовсе.
   */
  const ensure = useRef((map: MapLibreMap) => {
    if (map.getSource(SRC_ROUTES)) return
    if (!map.getStyle()?.layers?.length) return
    const current = sceneRef.current
    map.addSource(SRC_MISSING, { type: 'geojson', data: missingData(current) as never })
    map.addSource(SRC_ROUTES, {
      type: 'geojson',
      data: lineData(current, progressRef.current) as never,
    })
    map.addSource(SRC_STOPS, { type: 'geojson', data: dotData(current) as never })
    map.addSource(SRC_OFFICE, { type: 'geojson', data: officeData(current) as never })

    map.addLayer({
      id: 'b-missing-leg',
      type: 'line',
      source: SRC_MISSING,
      filter: ['==', ['get', 'kind'], 'leg'],
      paint: {
        'line-color': current.colors.grey,
        'line-width': 1.5,
        'line-dasharray': [2, 2],
        'line-opacity': 0.7,
      },
    })
    map.addLayer({
      id: 'b-route-line',
      type: 'line',
      source: SRC_ROUTES,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['get', 'color'] as never,
        'line-width': ['case', ['boolean', ['get', 'changed'], false], 5, 3] as never,
        'line-opacity': DIM as never,
      },
    })
    map.addLayer({
      id: 'b-missing-dot',
      type: 'circle',
      source: SRC_MISSING,
      filter: ['==', ['get', 'kind'], 'dot'],
      paint: {
        'circle-radius': ['case', SEL, 11, 7] as never,
        'circle-color': current.colors.grey,
        'circle-opacity': ['case', SEL, 0.9, 0.55] as never,
        'circle-stroke-width': ['case', SEL, 4, 1.5] as never,
        'circle-stroke-color': ['case', SEL, current.colors.accent, current.colors.grey] as never,
      },
    })
    map.addLayer({
      id: 'b-missing-label',
      type: 'symbol',
      source: SRC_MISSING,
      filter: ['==', ['get', 'kind'], 'dot'],
      layout: {
        'text-field': ['get', 'request'] as never,
        'text-font': ['Noto Sans Regular'],
        'text-size': 13,
        'text-anchor': 'left',
        'text-offset': [1.2, 0],
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: {
        // Состояние объекта доступно только краске: номер есть у всех точек,
        // виден — у выбранной.
        'text-opacity': ['case', SEL, 1, 0] as never,
        'text-color': readToken('--b-text', '#111'),
        'text-halo-color': readToken('--b-surface', '#fff'),
        'text-halo-width': 1.6,
      },
    })
    map.addLayer({
      id: 'b-stop-dot',
      type: 'circle',
      source: SRC_STOPS,
      paint: {
        // Выбранная в списке заявка — крупнее и в жёлтом кольце: иначе
        // тычок в список и точку на карте нечем сличить.
        'circle-radius': ['case', SEL, 14, 10] as never,
        'circle-color': ['get', 'color'] as never,
        'circle-opacity': DIM as never,
        'circle-stroke-width': ['case', SEL, 4, 1.5] as never,
        'circle-stroke-color': ['case', SEL, current.colors.accent, readToken('--b-surface', '#fff')] as never,
        'circle-stroke-opacity': DIM as never,
      },
    })
    map.addLayer({
      id: 'b-stop-seq',
      type: 'symbol',
      source: SRC_STOPS,
      layout: {
        'text-field': ['get', 'seq'] as never,
        'text-font': ['Noto Sans Regular'],
        'text-size': 11,
        'text-allow-overlap': true,
      },
      paint: {
        'text-color': '#ffffff',
        'text-opacity': DIM as never,
        'text-halo-color': 'rgba(0,0,0,0.35)',
        'text-halo-width': 0.6,
      },
    })
    // Номер выбранной заявки рядом с точкой — тот же, что в списке слева.
    map.addLayer({
      id: 'b-stop-label',
      type: 'symbol',
      source: SRC_STOPS,
      layout: {
        'text-field': ['get', 'request'] as never,
        'text-font': ['Noto Sans Regular'],
        'text-size': 13,
        'text-anchor': 'left',
        'text-offset': [1.3, 0],
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: {
        // Состояние объекта доступно только краске: номер есть у всех точек,
        // виден — у выбранной.
        'text-opacity': ['case', SEL, 1, 0] as never,
        'text-color': readToken('--b-text', '#111'),
        'text-halo-color': readToken('--b-surface', '#fff'),
        'text-halo-width': 1.6,
      },
    })
    map.addLayer({
      id: 'b-office-dot',
      type: 'circle',
      source: SRC_OFFICE,
      paint: {
        'circle-radius': 7,
        'circle-color': current.colors.accent,
        'circle-stroke-width': 2,
        'circle-stroke-color': current.colors.office,
      },
    })
  })

  // Карта заводится один раз: пересоздавать её на каждую правку нельзя.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const map = new MapLibreMap({
      container,
      style: STYLE_URL[useStore.getState().theme],
      transformRequest: tilesRequest,
      center: [37.72, 55.6],
      zoom: 9.3,
      minZoom: 7,
      maxBounds: MAX_BOUNDS,
      attributionControl: { compact: true },
    })
    map.addControl(new NavigationControl({ showCompass: false, showZoom: true }), 'top-right')
    mapRef.current = map
    collapseAttribution(map)
    styleThemeRef.current = useStore.getState().theme
    // На стенде разработки картой правят из консоли — в сборку это не едет.
    // Отладочный доступ: в dev всегда, в сборке — по ?debug в адресе.
    if (import.meta.env.DEV || window.location.search.includes('debug'))
      (window as unknown as { __map?: MapLibreMap }).__map = map

    const onStyle = () => {
      try {
        ensure.current(map)
      } catch {
        // Стиль ещё не разобран — вернёмся на следующем событии.
      }
    }
    map.on('style.load', onStyle)
    map.on('styledata', onStyle)
    map.on('load', onStyle)

    const onClick = (event: MapMouseEvent) => {
      const state = useStore.getState()
      if (state.picking) {
        state.setPickedPoint({ lat: event.lngLat.lat, lon: event.lngLat.lng })
        return
      }
      if (state.dropping) {
        if (!state.plan) return
        state.addDraft(dropEvent({ lat: event.lngLat.lat, lon: event.lngLat.lng }, state.clock))
        return
      }
      const hit = map.queryRenderedFeatures(event.point, {
        layers: ['b-stop-dot', 'b-missing-dot'].filter((id) => map.getLayer(id)),
      })
      const request = hit[0]?.properties?.request as string | undefined
      if (!request) {
        state.selectRequest(null)
        return
      }
      state.selectRequest(request)
      const engineer = hit[0]?.properties?.engineer as string | undefined
      state.selectEngineer(engineer ?? null)
    }
    map.on('click', onClick)
    // До первой полной отрисовки поверх карты — лоадер «М».
    const stopWait = onMapReady(map, () => setMapReady(true))

    return () => {
      stopWait()
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Тема: стиль меняется целиком, слои возвращает `styledata`. При монтировании
  // стиль уже тот, что нужен: повторный setStyle заставлял MapLibre пересобирать
  // ещё не загруженный стиль с нуля.
  useEffect(() => {
    const map = mapRef.current
    if (!map || styleThemeRef.current === theme) return
    styleThemeRef.current = theme
    map.setStyle(STYLE_URL[theme])
  }, [theme])

  // Черчение маршрутов: наращиваем координаты с разбегом по инженерам.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const lines = scene.lines
    const push = () => {
      const source = map.getSource(SRC_ROUTES) as GeoJSONSource | undefined
      if (source) source.setData(lineData(sceneRef.current, progressRef.current) as never)
      const stops = map.getSource(SRC_STOPS) as GeoJSONSource | undefined
      if (stops) stops.setData(dotData(sceneRef.current) as never)
      const missing = map.getSource(SRC_MISSING) as GeoJSONSource | undefined
      if (missing) missing.setData(missingData(sceneRef.current) as never)
      const office = map.getSource(SRC_OFFICE) as GeoJSONSource | undefined
      if (office) office.setData(officeData(sceneRef.current) as never)
    }

    if (reduced || lines.length === 0) {
      progressRef.current = Object.fromEntries(lines.map((line) => [line.engineerId, 1]))
      push()
      return
    }

    const started = performance.now()
    const DURATION = 900
    const STEP = 120
    let frame = 0
    const tick = (now: number) => {
      let done = true
      const next: Record<string, number> = {}
      lines.forEach((line, index) => {
        const share = (now - started - index * STEP) / DURATION
        const clamped = Math.max(0, Math.min(1, share))
        next[line.engineerId] = clamped
        if (clamped < 1) done = false
      })
      progressRef.current = next
      push()
      if (!done) frame = requestAnimationFrame(tick)
    }
    progressRef.current = Object.fromEntries(lines.map((line) => [line.engineerId, 0]))
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [scene, drawSeed, reduced])

  // Приглушение чужих маршрутов — состоянием объектов, а не новой отрисовкой.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getSource(SRC_ROUTES)) return
    for (const line of scene.lines) {
      map.setFeatureState(
        { source: SRC_ROUTES, id: line.id },
        { dim: Boolean(selectedEngineerId) && line.engineerId !== selectedEngineerId },
      )
    }
    for (const dot of scene.dots) {
      map.setFeatureState(
        { source: SRC_STOPS, id: dot.id },
        { dim: Boolean(selectedEngineerId) && dot.engineerId !== selectedEngineerId, sel: dot.requestId === selectedRequestId },
      )
    }
    if (map.getSource(SRC_MISSING)) {
      for (const item of scene.missing) {
        map.setFeatureState({ source: SRC_MISSING, id: item.id + 10000 }, { sel: item.requestId === selectedRequestId })
      }
    }
  }, [scene, selectedEngineerId, selectedRequestId, drawSeed])

  /**
   * Куда смотрит карта, решает приказ из стора, а не сам по себе выбор:
   * тычок в заявку выбирает заодно и её инженера, и два правила разом
   * увели бы карту в два места.
   */
  const fitPoints = useRef((points: Coord[], animated: boolean) => {
    const map = mapRef.current
    if (!map || points.length === 0) return
    const bounds = new LngLatBounds(points[0], points[0])
    for (const point of points) bounds.extend(point)
    map.fitBounds(bounds, {
      padding: { top: 64, right: 64, bottom: 64, left: 64 },
      maxZoom: 15,
      bearing: 0,
      pitch: 0,
      duration: animated ? 600 : 0,
    })
  })

  const allPoints = useRef((): Coord[] => {
    const set = useStore.getState().dataset
    if (!set) return []
    const points: Coord[] = set.requests.map((item) => [item.lon, item.lat])
    points.push([set.office.lon, set.office.lat])
    for (const item of knownRequests(useStore.getState().dataset, useStore.getState().plan)) {
      if (!useStore.getState().dataset?.requests.includes(item)) points.push([item.lon, item.lat])
    }
    return points
  })

  const showAll = () => {
    useStore.getState().focusAll()
  }

  // Набор загрузился — показываем его целиком, без движения.
  useEffect(() => {
    if (!dataset || fittedRef.current) return
    fittedRef.current = true
    fitPoints.current(allPoints.current(), false)
  }, [dataset])

  // Приказ карте: показать всё, маршрут инженера или точку заявки.
  const focus = useStore((s) => s.focus)
  useEffect(() => {
    const map = mapRef.current
    if (!map || focus.kind === 'none') return
    if (focus.kind === 'all') {
      fitPoints.current(allPoints.current(), true)
      return
    }
    if (focus.kind === 'engineer' && focus.id) {
      const line = sceneRef.current.lines.find((item) => item.engineerId === focus.id)
      const dots = sceneRef.current.dots.filter((item) => item.engineerId === focus.id)
      const points = line ? [...line.coords] : dots.map((dot) => dot.point)
      fitPoints.current(points, true)
      return
    }
    if (focus.kind === 'request' && focus.id) {
      const dot = sceneRef.current.dots.find((item) => item.requestId === focus.id)
      const gone = sceneRef.current.missing.find((item) => item.requestId === focus.id)
      const point = dot?.point ?? gone?.point
      if (!point) return
      // Карточка заявки стоит в левом нижнем углу карты: точку уводим
      // правее и выше центра, чтобы карточка её не накрыла.
      const short = map.getContainer().clientHeight < 700
      map.flyTo({ center: point, zoom: Math.max(map.getZoom(), 12), duration: 600, offset: [short ? 160 : 120, short ? -120 : -60] })
    }
  }, [focus])

  // Заявки пачки — булавками: в плане их ещё нет, и точкой маршрута они
  // читались бы уже назначенными.
  const drafts = useStore((s) => s.drafts)
  const crunching = useStore((s) => s.crunching)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const pins = drafts.flatMap((event, index) => {
      if (event.type !== 'new_request' && event.type !== 'urgent') return []
      const element = document.createElement('div')
      // Пока сервер примеряет пачку, булавки пульсируют — с разбегом, чтобы
      // читаться работой, а не миганием; при «меньше движения» стоят.
      element.className = `b-draft-pin${event.type === 'urgent' ? ' urgent' : ''}${crunching && !reduced ? ' busy' : ''}`
      element.style.animationDelay = `${(index % 5) * 180}ms`
      element.title = `${event.request.id} · звонок ${event.time} · окно ${event.request.window_start}–${event.request.window_end}`
      return [new Marker({ element, anchor: 'bottom-left' }).setLngLat([event.request.lon, event.request.lat]).addTo(map)]
    })
    return () => pins.forEach((pin) => pin.remove())
  }, [drafts, crunching, reduced])

  const dropping = useStore((s) => s.dropping)
  const clock = useStore((s) => s.clock)
  const hasPlanNow = useStore((s) => Boolean(s.plan))
  const hasDrafts = drafts.length > 0
  const hasPrevious = useStore((s) => Boolean(s.previousPlan) && !s.drafts.length)
  const view = useStore((s) => s.view)
  const setView = useStore((s) => s.setView)

  // Уведомление живёт недолго: это реплика, а не сообщение об ошибке.
  const notice = useStore((s) => s.notice)
  const noticeTitle = useStore((s) => s.noticeTitle)
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => useStore.getState().notify(null), 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  return (
    <div className="relative h-full min-h-0 flex-1">
      {/* Рост холста — долями, а не `inset-0`: свой `position: relative`
          из maplibre-gl.css перебивает `absolute`, и карта осталась бы
          нулевой высоты. */}
      <div
        ref={containerRef}
        className="h-full w-full"
        style={{ cursor: picking || dropping ? 'crosshair' : undefined }}
      />
      {mapReady ? null : <AreaWait label="Загружаем карту" />}
      {hasPrevious ? (
        <span className="b-map-view absolute top-3 left-3 z-10">
          <SegmentedRadioGroup
            size="m"
            value={view}
            onUpdate={(value) => setView(value as 'before' | 'after')}
            options={[
              { value: 'before', content: 'До события' },
              { value: 'after', content: 'После' },
            ]}
          />
        </span>
      ) : null}

      <span className="absolute top-3 right-3 z-10 flex gap-2">
        {hasPlanNow ? (
          <Button
            view={dropping ? 'action' : 'normal'}
            size="m"
            selected={dropping}
            onClick={() => useStore.getState().setDropping(!dropping)}
            title="Каждый тычок по карте — новая заявка день в день в этой точке"
          >
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              <IconPin />
              {dropping ? 'Готово' : 'Заявка на карте'}
            </span>
          </Button>
        ) : null}
        <Button view="normal" size="m" onClick={showAll} title="Показать весь набор">
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <IconFit />
            Показать всё
          </span>
        </Button>
      </span>

      {notice ? (
        <div className="absolute right-3 bottom-8 z-10">
          <div className="b-toast" role="status">
            <IconAlert />
            <span>
              <b>{noticeTitle ?? 'Пока нельзя'}</b>
              <span>{notice}</span>
            </span>
          </div>
        </div>
      ) : null}

      {picking ? (
        <div className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 rounded-full bg-[var(--b-accent)] px-3 py-1 text-[12px] font-medium text-[var(--b-on-accent)]">
          Ткните в карту — это будет адрес заявки
        </div>
      ) : dropping ? (
        <div className="pointer-events-none absolute bottom-8 left-1/2 -translate-x-1/2 rounded-full bg-[var(--b-accent)] px-3 py-1 text-[12px] font-medium text-[var(--b-on-accent)]">
          Каждый тычок — новая заявка, звонок в {clock}
        </div>
      ) : null}
      {hasDrafts ? <DraftPanel /> : null}
      <RequestPopup />
      <ImportOverlay />
    </div>
  )
}
