/**
 * Карта воспроизведения дня: маршруты тенью, пройденный путь цветом бригады,
 * бригады точками, которые едут, ждут и работают, визиты с состоянием
 * к текущей минуте. Своей логики времени у карты нет — минуту даёт хозяин,
 * сцену строит `lib/playback`.
 *
 * Две такие карты в сравнении двигаются вместе: камера одной повторяет
 * другую (`sync`), пока её двигает рука, а не соседка.
 */

import { useEffect, useRef } from 'react'
import { LngLatBounds, Map as MapLibreMap, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { crewAt, stopState, type DayScene } from '../../lib/playback'
import { readToken } from '../../lib/colors'
import { MAX_BOUNDS, STYLE_URL, collapseAttribution, tilesRequest } from '../../lib/mapStyle'
import type { Theme } from '../../store'

export interface MapSync {
  maps: MapLibreMap[]
  busy: boolean
}

interface Props {
  scene: DayScene | null
  time: number
  theme: Theme
  sync?: MapSync
  labels?: boolean
}

const SRC = { bg: 'p-bg', trail: 'p-trail', stops: 'p-stops', missing: 'p-missing', crews: 'p-crews', office: 'p-office' }

function fc(features: object[]) {
  return { type: 'FeatureCollection', features } as never
}

export default function PlaybackMap({ scene, time, theme, sync, labels = true }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const ready = useRef(false)
  const pending = useRef<(() => void)[]>([])
  const whenReady = (fn: () => void) => {
    if (ready.current) fn()
    else pending.current.push(fn)
  }
  const lastStops = useRef('')

  useEffect(() => {
    if (!box.current) return
    // Карта заводится на следующем тике: в режиме разработки React монтирует
    // эффект дважды подряд, и карта, удалённая посреди загрузки стиля,
    // оставляла вторую без стиля навсегда.
    const holder: { map: MapLibreMap | null } = { map: null }
    let observer: ResizeObserver | null = null
    const container = box.current
    const timer = window.setTimeout(() => {
    const map = new MapLibreMap({
      container,
      style: STYLE_URL[theme],
      transformRequest: tilesRequest,
      center: [37.7, 55.6],
      zoom: 9.3,
      minZoom: 7,
      maxBounds: MAX_BOUNDS,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    collapseAttribution(map)
    holder.map = map
    const danger = readToken('--b-danger', '#c8341a')
    const accent = readToken('--b-accent', '#ffc800')
    const surface = readToken('--b-surface', '#ffffff')
    const ink = readToken('--b-text', '#13171b')
    const grey = readToken('--b-text-3', '#8f959d')
    map.on('load', () => {
      for (const id of Object.values(SRC)) map.addSource(id, { type: 'geojson', data: fc([]) })
      map.addLayer({ id: 'p-bg', type: 'line', source: SRC.bg, paint: { 'line-color': ['get', 'color'] as never, 'line-width': 2, 'line-opacity': 0.18 } })
      map.addLayer({ id: 'p-trail', type: 'line', source: SRC.trail, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': ['get', 'color'] as never, 'line-width': 3.5, 'line-opacity': 0.9 } })
      map.addLayer({
        id: 'p-missing',
        type: 'circle',
        source: SRC.missing,
        paint: {
          'circle-radius': 7,
          'circle-color': ['case', ['get', 'missed'], danger, surface] as never,
          'circle-stroke-width': 2,
          'circle-stroke-color': ['case', ['get', 'missed'], danger, grey] as never,
        },
      })
      map.addLayer({
        id: 'p-stops',
        type: 'circle',
        source: SRC.stops,
        paint: {
          'circle-radius': ['match', ['get', 'state'], 'working', 9, 'planned', 5, 6] as never,
          'circle-color': ['match', ['get', 'state'], 'planned', surface, 'late', danger, 'overdue', surface, ['get', 'color']] as never,
          'circle-stroke-width': ['match', ['get', 'state'], 'working', 3, 'overdue', 2.5, 1.5] as never,
          'circle-stroke-color': ['match', ['get', 'state'], 'working', accent, 'overdue', danger, 'late', danger, ['get', 'color']] as never,
        },
      })
      map.addLayer({
        id: 'p-crews',
        type: 'circle',
        source: SRC.crews,
        paint: {
          'circle-radius': 8,
          'circle-color': ['get', 'color'] as never,
          'circle-stroke-width': ['match', ['get', 'state'], 'work', 4, 2.5] as never,
          'circle-stroke-color': ['match', ['get', 'state'], 'work', accent, 'wait', danger, surface] as never,
          'circle-opacity': ['match', ['get', 'state'], 'off', 0.35, 1] as never,
        },
      })
      if (labels) {
        map.addLayer({
          id: 'p-crew-label',
          type: 'symbol',
          source: SRC.crews,
          layout: {
            'text-field': ['get', 'name'] as never,
            'text-font': ['Noto Sans Regular'],
            'text-size': 11,
            'text-anchor': 'left',
            'text-offset': [1.1, 0],
            'text-allow-overlap': false,
          },
          paint: { 'text-color': ink, 'text-halo-color': surface, 'text-halo-width': 1.5 },
        })
      }
      map.addLayer({ id: 'p-office', type: 'circle', source: SRC.office, paint: { 'circle-radius': 7, 'circle-color': accent, 'circle-stroke-width': 2, 'circle-stroke-color': ink } })
      ready.current = true
      const queued = pending.current.splice(0)
      for (const fn of queued) {
        try {
          fn()
        } catch {
          // вызов от прежней карты: её уже сняли
        }
      }
    })
    if (sync) {
      sync.maps.push(map)
      map.on('move', (event) => {
        if (sync.busy || !(event as { originalEvent?: unknown }).originalEvent) return
        sync.busy = true
        for (const other of sync.maps) {
          if (other !== map) other.jumpTo({ center: map.getCenter(), zoom: map.getZoom() })
        }
        sync.busy = false
      })
    }
    observer = new ResizeObserver(() => map.resize())
    observer.observe(container)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
      pending.current = []
      const map = holder.map
      if (map) {
        if (sync) sync.maps.splice(sync.maps.indexOf(map), 1)
        map.remove()
      }
      mapRef.current = null
      ready.current = false
    }
  }, [theme, sync, labels])

  // Сцена сменилась — тень маршрутов, офис и камера по всем точкам.
  useEffect(() => {
    if (!scene) return
    const apply = () => {
      const map = mapRef.current
      if (!map || !map.getSource(SRC.bg)) return
      const bg = scene.tracks.map((track) => ({
        type: 'Feature',
        properties: { color: track.color },
        geometry: { type: 'LineString', coordinates: [track.start, ...track.segments.filter((s) => s.kind === 'drive').map((s) => s.to)] },
      }))
      ;(map.getSource(SRC.bg) as GeoJSONSource).setData(fc(bg))
      ;(map.getSource(SRC.office) as GeoJSONSource).setData(fc([{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: scene.office } }]))
      if (scene.bounds) {
        const bounds = new LngLatBounds(scene.bounds[0], scene.bounds[1])
        const fit = () => map.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 12.5 })
        fit()
        // Сразу после загрузки стиля камера ещё переустанавливается — повторяем на первом покое.
        map.once('idle', fit)
      }
      lastStops.current = ''
    }
    whenReady(apply)
  }, [scene])

  // Минута сменилась — бригады, пройденный путь и состояния визитов.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !scene || !ready.current) return
    const crews = []
    const trails = []
    for (const track of scene.tracks) {
      if (!track.segments.length) continue
      const at = crewAt(track, time)
      crews.push({ type: 'Feature', properties: { color: track.color, state: at.state, name: track.name }, geometry: { type: 'Point', coordinates: at.point } })
      if (at.trail.length > 1) trails.push({ type: 'Feature', properties: { color: track.color }, geometry: { type: 'LineString', coordinates: at.trail } })
    }
    ;(map.getSource(SRC.crews) as GeoJSONSource).setData(fc(crews))
    ;(map.getSource(SRC.trail) as GeoJSONSource).setData(fc(trails))
    const states = scene.stops.map((stop) => stopState(stop, time))
    const missed = scene.missing.map((m) => time > m.windowEnd)
    const key = states.join('') + missed.join('')
    if (key !== lastStops.current) {
      lastStops.current = key
      ;(map.getSource(SRC.stops) as GeoJSONSource).setData(
        fc(scene.stops.map((stop, i) => ({ type: 'Feature', properties: { color: stop.color, state: states[i], request: stop.requestId }, geometry: { type: 'Point', coordinates: stop.point } }))),
      )
      ;(map.getSource(SRC.missing) as GeoJSONSource).setData(
        fc(scene.missing.map((m, i) => ({ type: 'Feature', properties: { missed: missed[i], request: m.requestId }, geometry: { type: 'Point', coordinates: m.point } }))),
      )
    }
  }, [scene, time])

  return <div ref={box} className="b-play-map" />
}
