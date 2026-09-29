/**
 * Нагрузка (прежде «Дефицит») — раздел диспетчера, устроенный как «Заявки» и «Инженеры»: слева
 * колонка с шапкой, поиском и фильтром мест, справа карта. В колонке сверху
 * окна дня — они же выбор окна и цифры по отобранным районам; ниже районы
 * полосой окон: где спрос выше того, что бригады могут закрыть, и где
 * свободные бригады стоят без дела. На карте районы закрашены по своим
 * границам, как зоны спроса в такси: цвет — давление. На обзоре города
 * район красится цветом своего участка — участки читаются целиком; при
 * приближении каждый район получает свой цвет и подпись. Границы — все
 * районы Москвы (`lib/districts`); район, которого среди них нет, стоит
 * кругом по центру своих заявок. Окно не выбрано — районы и участки стоят
 * по худшему окну дня.
 *
 * Считает сервер по текущему плану (`GET /plan/{id}/deficit`): мощность —
 * свободное время бригад именно в этом плане. На телефоне раздел — экраном
 * показа (`DeficitView`): карта сверху, колонка под ней.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LngLatBounds, Map as MapLibreMap, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { create } from 'zustand'
import { api } from '../../api'
import { activePlan, useStore } from '../../store'
import { readToken } from '../../lib/colors'
import { MAX_BOUNDS, STYLE_URL, collapseAttribution, tilesRequest } from '../../lib/mapStyle'
import { useDistrictSector, usePlaceMatch } from '../../lib/places'
import { matchDistrict, useDistrictShapes, type DistrictShapes } from '../../lib/districts'
import type { DeficitArea, DeficitLevel, DeficitMap, DeficitSlot } from '../../types'
import { AreaWait, SkeletonFill, onMapReady } from '../Loading'
import ColumnSearch from '../search/ColumnSearch'
import DayPicker from '../DayPicker'
import DemoShell from './DemoShell'

const LEVEL_TEXT: Record<DeficitLevel, string> = {
  deficit: 'Дефицит',
  tight: 'Напряжённо',
  ok: 'В норме',
  free: 'Свободно',
}

const RANK: Record<DeficitLevel, number> = { deficit: 3, tight: 2, ok: 1, free: 0 }

/** Давление в процентах; когда закрыть нечем, число теряет смысл — пишем порог. */
function pct(pressure: number): string {
  return pressure >= 3 ? '> 300 %' : `${Math.round(pressure * 100)} %`
}

function palette(): Record<DeficitLevel, string> {
  return {
    deficit: readToken('--b-danger', '#c8341a'),
    tight: '#e67700',
    ok: readToken('--b-text-3', '#8f959d'),
    free: readToken('--b-success', '#00804a'),
  }
}

/** Ячейка района в выбранном окне; «весь день» — худшее окно района. */
function pick(area: DeficitArea, slot: string) {
  if (slot !== 'all') return area.slots.find((s) => s.window === slot) ?? area.slots[0]
  return [...area.slots].sort((a, b) => RANK[b.level] - RANK[a.level] || b.pressure - a.pressure)[0]
}

/** «10:00–12:00» → «10–12»: в плитке колонки места под минуты нет. */
const short = (window: string) => window.replace(/:00/g, '')

/**
 * Итог окна по отобранным районам — той же формулой, что сервер считает итог
 * по набору (`deficit.py`, `_level`): спрос к закрытому и свободному рядом.
 */
function total(areas: DeficitArea[], window: string): DeficitSlot {
  let demand = 0
  let served = 0
  let free = 0
  let unassigned = 0
  for (const area of areas) {
    const cell = area.slots.find((s) => s.window === window)
    if (!cell) continue
    demand += cell.demand_min
    served += cell.served_min
    free += cell.free_min
    unassigned += cell.unassigned
  }
  const pressure = demand ? Math.round((demand / Math.max(served + free, 1)) * 100) / 100 : 0
  const level: DeficitLevel =
    pressure >= 1.1 || unassigned ? 'deficit' : pressure >= 0.8 ? 'tight' : pressure < 0.5 && free >= 60 ? 'free' : 'ok'
  return { window, demand_min: demand, served_min: served, free_min: free, unassigned, pressure, level }
}

/** Выбор раздела: окно и район в фокусе — общие у колонки и карты. */
const useDeficit = create<{ slot: string; focus: string | null; setSlot: (slot: string) => void; setFocus: (focus: string | null) => void }>((set) => ({
  slot: 'all',
  focus: null,
  setSlot: (slot) => set({ slot }),
  setFocus: (focus) => set({ focus }),
}))

function useDeficitData() {
  const store = useStore()
  const plan = activePlan(store)
  const data = useQuery({
    queryKey: ['deficit', plan?.id],
    queryFn: () => api.deficit(plan!),
    enabled: Boolean(plan) && !store.offline,
    retry: false,
  })
  const place = usePlaceMatch()
  const sectorOf = useDistrictSector()
  const result: DeficitMap | undefined = data.data
  const areas = useMemo(
    () => (result?.areas ?? []).filter((area) => place({ district: area.district, sector: sectorOf.get(area.district) ?? null })),
    [result, place, sectorOf],
  )
  return { plan, data, result, areas, filtered: Boolean(result && areas.length < result.areas.length) }
}

/** Колонка раздела: шапка, поиск с фильтром мест, окна дня, районы. */
export function DeficitPanel() {
  const { plan, data, result, areas, filtered } = useDeficitData()
  const { slot, setSlot, focus, setFocus } = useDeficit()
  const [query, setQuery] = useState('')

  const totals = useMemo(
    () => (result ? (filtered ? result.windows.map((w) => total(areas, w)) : result.totals) : []),
    [result, areas, filtered],
  )

  const needle = query.trim().toLowerCase()
  const rows = useMemo(
    () =>
      areas
        .filter((area) => !needle || area.district.toLowerCase().includes(needle))
        .map((area) => ({ area, cell: pick(area, slot) }))
        .sort((a, b) => RANK[b.cell.level] - RANK[a.cell.level] || b.cell.pressure - a.cell.pressure),
    [areas, needle, slot],
  )
  // Группы — участки набора; у набора без участков группа одна. Свернуть можно любую.
  const sectorOf = useDistrictSector()
  const sectors = useStore((s) => s.dataset?.sectors) ?? []
  const groups = (
    sectors.length
      ? [
          ...sectors.map((sector) => ({ key: sector.id, title: sector.name, rows: rows.filter((r) => sectorOf.get(r.area.district) === sector.id) })),
          { key: '', title: 'Без участка', rows: rows.filter((r) => !sectors.some((sector) => sector.id === sectorOf.get(r.area.district))) },
        ]
      : [{ key: 'all', title: 'Районы', rows }]
  ).filter((group) => group.rows.length > 0)
  const [folded, setFolded] = useState<Set<string>>(() => new Set())
  const toggle = (key: string, open: boolean) =>
    setFolded((prev) => {
      const next = new Set(prev)
      if (open) next.add(key)
      else next.delete(key)
      return next
    })

  return (
    <>
      <div className="b-ch">
        <b>Нагрузка</b>
        <DayPicker />
      </div>

      <ColumnSearch value={query} onUpdate={setQuery} placeholder="Район" />

      <div className="b-cb">
        {!plan ? (
          <p className="b-def-none">Сначала постройте план: нагрузка считается по нему.</p>
        ) : data.isError ? (
          <p className="b-def-none">Сервер не посчитал нагрузку: {String(data.error)}</p>
        ) : !result ? (
          <SkeletonFill block={24} />
        ) : (
          <>
            {/* Окна — и выбор, и цифры по отобранным районам: давление и состояние стоят на плитке.
                Ничего не выбрано — районы и карта по худшему окну дня; повторное нажатие снимает выбор. */}
            <div className="b-def-slots" role="radiogroup" aria-label="Окно">
              {totals.map((t) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={slot === t.window}
                  key={t.window}
                  className={`${t.level}${slot === t.window ? ' on' : ''}`}
                  onClick={() => setSlot(slot === t.window ? 'all' : t.window)}
                  title={`${t.window}: спрос ${t.demand_min} нормо-мин, закрыто ${t.served_min}, свободно рядом ${t.free_min}`}
                >
                  <small>{short(t.window)}</small>
                  <b>{pct(t.pressure)}</b>
                  <span>{LEVEL_TEXT[t.level]}</span>
                </button>
              ))}
            </div>

            {/* Районы — группами по участкам, как в фильтре мест. Часы окон подписаны
                внутри квадратиков строки при наведении, отдельной шкалы над списком нет. */}
            {groups.map((group) => {
              const open = !folded.has(group.key) || Boolean(needle) || group.rows.some((r) => r.area.district === focus)
              return (
                <div key={group.key}>
                  <button
                    type="button"
                    className="b-list-g b-list-g-fold"
                    aria-expanded={open}
                    onClick={() => toggle(group.key, open)}
                    title={open ? 'Свернуть' : 'Развернуть'}
                  >
                    <span>{group.title}</span>
                    <span>{group.rows.length}</span>
                  </button>
                  <div role="listbox" aria-label={group.title}>
                    {(open ? group.rows : []).map(({ area, cell }) => (
                      <button
                        key={area.district}
                        type="button"
                        role="option"
                        aria-selected={focus === area.district}
                        className={`b-def-row${focus === area.district ? ' on' : ''}`}
                        onClick={() => setFocus(focus === area.district ? null : area.district)}
                        title={`${area.district}: ${area.requests} заявок · ${LEVEL_TEXT[cell.level].toLowerCase()} ${slot === 'all' ? `в худшее окно ${cell.window}` : `в ${cell.window}`}`}
                      >
                        <span className="nm">
                          <b>{area.district}</b>
                          <small>{area.requests}</small>
                        </span>
                        <span className="strip" style={{ gridTemplateColumns: `repeat(${area.slots.length}, 14px)` }}>
                          {area.slots.map((c) => (
                            <i
                              key={c.window}
                              data-h={short(c.window).split('–')[0]}
                              className={`${c.level}${slot === c.window ? ' on' : ''}`}
                              title={`${c.window}: ${c.demand_min || c.free_min ? pct(c.pressure) : '—'}${c.unassigned ? ` · без бригады ${c.unassigned}` : ''}`}
                            />
                          ))}
                        </span>
                        <em className={cell.level}>{cell.demand_min || cell.free_min ? pct(cell.pressure) : '—'}</em>
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
            {rows.length === 0 ? <p className="b-def-none">Районов по этому запросу нет</p> : null}
          </>
        )}
      </div>
    </>
  )
}

/** Участок на обзорной карте: цвет и подпись по его районам. */
interface SectorPaint {
  color: string
  label: string
  lon: number
  lat: number
}

/** Карта раздела: районы по границам, фокус из колонки, щелчок по району — фокус. */
export function DeficitMapPane() {
  const { result, areas } = useDeficitData()
  const { slot, focus, setFocus } = useDeficit()
  const theme = useStore((s) => s.theme)
  const sectors = useStore((s) => s.dataset?.sectors)
  const sectorOf = useDistrictSector()
  const colors = useMemo(() => palette(), [])
  const shapes = useDistrictShapes()

  // Участок — итог его районов той же формулой, что итог окна в колонке; «весь день» — худшее окно.
  const sectorPaint = useMemo(() => {
    const out = new Map<string, SectorPaint>()
    if (!result || !sectors?.length) return out
    for (const sector of sectors) {
      const own = areas.filter((area) => sectorOf.get(area.district) === sector.id)
      if (!own.length) continue
      const cells = (slot === 'all' ? result.windows : [slot]).map((w) => total(own, w))
      const cell = [...cells].sort((a, b) => RANK[b.level] - RANK[a.level] || b.pressure - a.pressure)[0]
      const weight = own.reduce((sum, area) => sum + area.requests, 0) || 1
      out.set(sector.id, {
        color: colors[cell.level],
        label: `${sector.name}\n${cell.demand_min || cell.free_min ? pct(cell.pressure) : '—'}`,
        lon: own.reduce((sum, area) => sum + area.lon * area.requests, 0) / weight,
        lat: own.reduce((sum, area) => sum + area.lat * area.requests, 0) / weight,
      })
    }
    return out
  }, [result, sectors, areas, sectorOf, slot, colors])

  if (!result) return <div className="b-def-map"><AreaWait label="Считаем нагрузку" /></div>
  return (
    <div className="b-def-map">
      <DeficitMapView
        areas={areas}
        slot={slot}
        focus={focus}
        colors={colors}
        theme={theme}
        shapes={shapes.data ?? null}
        sectorOf={sectorOf}
        sectorPaint={sectorPaint}
        onPick={(district) => setFocus(focus === district ? null : district)}
      />
    </div>
  )
}

/** Телефон: раздел экраном показа — карта сверху, колонка под ней. */
export default function DeficitView({ onClose }: { onClose: () => void }) {
  const name = useStore((s) => s.dataset?.name)
  return (
    // День — в шапке экрана, рядом с крестиком: второй заголовок «Нагрузка» под картой на телефоне не нужен.
    <DemoShell title="Нагрузка" subtitle={name} tools={<DayPicker />} onClose={onClose}>
      <div className="b-def-phone">
        <DeficitMapPane />
        <div className="b-col">
          <DeficitPanel />
        </div>
      </div>
    </DemoShell>
  )
}

/** С этого зума участки распадаются на районы: свой цвет и подпись у каждого. */
const DISTRICT_ZOOM = 10

const EMPTY = { type: 'FeatureCollection', features: [] }

function DeficitMapView({
  areas,
  slot,
  focus,
  colors,
  theme,
  shapes,
  sectorOf,
  sectorPaint,
  onPick,
}: {
  areas: DeficitArea[]
  slot: string
  focus: string | null
  colors: Record<DeficitLevel, string>
  theme: 'light' | 'dark'
  shapes: DistrictShapes | null
  sectorOf: Map<string, string | null>
  sectorPaint: Map<string, SectorPaint>
  onPick: (district: string) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [mapReady, setMapReady] = useState(false)
  const mapRef = useRef<MapLibreMap | null>(null)
  const ready = useRef(false)
  const refit = useRef<(() => void) | null>(null)
  const pick$ = useRef(onPick)
  pick$.current = onPick
  const pending = useRef<(() => void)[]>([])
  const whenReady = (fn: () => void) => {
    if (ready.current) fn()
    else pending.current.push(fn)
  }
  const bySector = sectorPaint.size > 0
  const bySectorRef = useRef(bySector)
  bySectorRef.current = bySector

  // Районы набора — к контурам; без контура район остаётся кругом. Два имени
  // одного района («Даниловский» и «GPON Даниловский») ложатся в один контур:
  // цвет — по худшему из них, имя и подпись — по тому, где заявок больше.
  const layers = useMemo(() => {
    const matched = new Map<string, DeficitArea[]>()
    const loose: DeficitArea[] = []
    for (const area of areas) {
      const shape = shapes ? matchDistrict(area.district, shapes) : null
      if (shape) matched.set(shape.properties.key, [...(matched.get(shape.properties.key) ?? []), area])
      else loose.push(area)
    }
    const cellOf = (area: DeficitArea) => pick(area, slot)
    const labelOf = (area: DeficitArea) => {
      const cell = cellOf(area)
      return `${area.district}\n${cell.demand_min || cell.free_min ? pct(cell.pressure) : '—'}`
    }
    const main = (own: DeficitArea[]) => [...own].sort((a, b) => b.requests - a.requests)[0]
    const worst = (own: DeficitArea[]) =>
      own.map(cellOf).sort((a, b) => RANK[b.level] - RANK[a.level] || b.pressure - a.pressure)[0]
    const polygons = (shapes?.features ?? []).map((shape) => {
      const own = matched.get(shape.properties.key)
      const area = own ? main(own) : null
      const color = own ? colors[worst(own).level] : colors.ok
      const sector = area ? sectorPaint.get(sectorOf.get(area.district) ?? '') : undefined
      return {
        type: 'Feature',
        properties: {
          has: own ? 1 : 0,
          district: area?.district ?? '',
          focus: own?.some((a) => a.district === focus) ? 1 : 0,
          color,
          scolor: sector?.color ?? color,
        },
        geometry: shape.geometry,
      }
    })
    const labels = (shapes?.features ?? []).flatMap((shape) => {
      const own = matched.get(shape.properties.key)
      if (!own) return []
      return [{
        type: 'Feature',
        properties: { label: labelOf(main(own)), focus: own.some((a) => a.district === focus) ? 1 : 0 },
        geometry: { type: 'Point', coordinates: [shape.properties.lx, shape.properties.ly] },
      }]
    })
    // Подпись участка — среди его районов в городе: середина заявок участка с Каширой
    // и Ступином падала в поле между ними и Москвой.
    const anchors = new Map<string, [number, number][]>()
    for (const shape of shapes?.features ?? []) {
      const own = matched.get(shape.properties.key)
      const sector = own ? sectorOf.get(main(own).district) : null
      if (!sector || shape.properties.kind !== 'district') continue
      anchors.set(sector, [...(anchors.get(sector) ?? []), [shape.properties.lx, shape.properties.ly]])
    }
    const circles = loose.map((area) => {
      const cell = cellOf(area)
      return {
        type: 'Feature',
        properties: {
          focus: area.district === focus ? 1 : 0,
          district: area.district,
          color: colors[cell.level],
          radius: Math.max(9, Math.min(46, Math.sqrt(Math.max(cell.demand_min, 20)) * 2.4)),
          label: labelOf(area),
        },
        geometry: { type: 'Point', coordinates: [area.lon, area.lat] },
      }
    })
    const sectorLabels = [...sectorPaint.entries()].map(([id, sector]) => {
      const points = anchors.get(id)
      const at = points?.length
        ? [points.reduce((sum, p) => sum + p[0], 0) / points.length, points.reduce((sum, p) => sum + p[1], 0) / points.length]
        : [sector.lon, sector.lat]
      return { type: 'Feature', properties: { label: sector.label }, geometry: { type: 'Point', coordinates: at } }
    })
    return {
      polygons: { type: 'FeatureCollection', features: polygons },
      labels: { type: 'FeatureCollection', features: labels },
      circles: { type: 'FeatureCollection', features: circles },
      sectors: { type: 'FeatureCollection', features: sectorLabels },
    }
  }, [areas, shapes, slot, focus, colors, sectorOf, sectorPaint])

  useEffect(() => {
    if (!box.current) return
    // Карта заводится на следующем тике: в режиме разработки React монтирует
    // эффект дважды подряд, и карта, удалённая посреди загрузки стиля,
    // оставляла вторую без стиля навсегда.
    const holder: { map: MapLibreMap | null; stop?: () => void } = { map: null }
    let observer: ResizeObserver | null = null
    const container = box.current
    const timer = window.setTimeout(() => {
    const map = new MapLibreMap({
      container,
      style: STYLE_URL[theme],
      transformRequest: tilesRequest,
      center: [37.7, 55.6],
      zoom: 9.5,
      minZoom: 7,
      maxBounds: MAX_BOUNDS,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    collapseAttribution(map)
    holder.map = map
    setMapReady(false)
    holder.stop = onMapReady(map, () => setMapReady(true))
    const surface = readToken('--b-surface', '#ffffff')
    const ink = readToken('--b-text', '#13171b')
    const text = {
      'text-font': ['Noto Sans Regular'],
      'text-size': 12,
      'text-allow-overlap': false,
    }
    const halo = { 'text-color': ink, 'text-halo-color': surface, 'text-halo-width': 1.6 }
    map.on('load', () => {
      for (const id of ['d-poly', 'd-labels', 'd-circles', 'd-sectors']) map.addSource(id, { type: 'geojson', data: EMPTY as never })
      // Заливка: на обзоре — цвет участка, ближе — цвет района. Районы без заявок не закрашены.
      map.addLayer({
        id: 'd-fill',
        type: 'fill',
        source: 'd-poly',
        paint: {
          'fill-color': ['step', ['zoom'], ['get', 'scolor'], DISTRICT_ZOOM, ['get', 'color']] as never,
          'fill-color-transition': { duration: 400 },
          'fill-opacity': ['case', ['==', ['get', 'has'], 0], 0, ['==', ['get', 'focus'], 1], 0.62, 0.42] as never,
        },
      })
      map.addLayer({
        id: 'd-line',
        type: 'line',
        source: 'd-poly',
        paint: {
          'line-color': ['case', ['==', ['get', 'has'], 1], ['get', 'color'], ink] as never,
          'line-opacity': ['case', ['==', ['get', 'has'], 1], 0.9, 0.14] as never,
          'line-width': [
            'step', ['zoom'],
            ['case', ['==', ['get', 'focus'], 1], 3, 0.6],
            DISTRICT_ZOOM, ['case', ['==', ['get', 'focus'], 1], 3, ['==', ['get', 'has'], 1], 1.4, 0.6],
          ] as never,
        },
      })
      map.addLayer({
        id: 'd-circles',
        type: 'circle',
        source: 'd-circles',
        paint: {
          'circle-radius': ['get', 'radius'] as never,
          'circle-color': ['get', 'color'] as never,
          'circle-opacity': ['case', ['==', ['get', 'focus'], 1], 0.8, 0.55] as never,
          'circle-stroke-width': ['case', ['==', ['get', 'focus'], 1], 4, 2] as never,
          'circle-stroke-color': ['get', 'color'] as never,
        },
      })
      map.addLayer({
        id: 'd-labels',
        type: 'symbol',
        source: 'd-labels',
        minzoom: bySectorRef.current ? DISTRICT_ZOOM : 0,
        layout: { ...text, 'text-field': ['get', 'label'], 'symbol-sort-key': ['-', 0, ['get', 'focus']] } as never,
        paint: halo,
      })
      map.addLayer({
        id: 'd-circle-labels',
        type: 'symbol',
        source: 'd-circles',
        layout: { ...text, 'text-field': ['get', 'label'] } as never,
        paint: halo,
      })
      map.addLayer({
        id: 'd-sectors',
        type: 'symbol',
        source: 'd-sectors',
        maxzoom: DISTRICT_ZOOM,
        // Трёх подписей участков на узкой карте не хватает места в одной точке: подпись
        // сдвигается в сторону, где свободно, а не ложится поверх соседней.
        layout: {
          ...text,
          'text-size': 14,
          'text-field': ['get', 'label'],
          'text-variable-anchor': ['center', 'top', 'bottom', 'left', 'right'],
          'text-radial-offset': 0.6,
        } as never,
        paint: { ...halo, 'text-halo-width': 2 },
      })
      // Щелчок по району — фокус, как щелчок по строке в колонке.
      for (const id of ['d-fill', 'd-circles']) {
        map.on('click', id, (event) => {
          const district = event.features?.[0]?.properties?.district as string | undefined
          if (district) pick$.current(district)
        })
        map.on('mouseenter', id, (event) => {
          if (event.features?.[0]?.properties?.district) map.getCanvas().style.cursor = 'pointer'
        })
        map.on('mouseleave', id, () => {
          map.getCanvas().style.cursor = ''
        })
      }
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
    // Размер карты меняется, когда под ней встаёт витрина окон: районы вписываются заново,
    // иначе они остаются прижатыми к краю, под которым карта была до этого.
    observer = new ResizeObserver(() => {
      map.resize()
      window.requestAnimationFrame(() => refit.current?.())
    })
    observer.observe(container)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
      pending.current = []
      holder.stop?.()
      holder.map?.remove()
      mapRef.current = null
      ready.current = false
    }
  }, [theme])

  // У набора без участков подписи районов стоят на любом зуме.
  useEffect(() => {
    whenReady(() => mapRef.current?.setLayerZoomRange('d-labels', bySector ? DISTRICT_ZOOM : 0, 24))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bySector])

  useEffect(() => {
    const apply = () => {
      const map = mapRef.current
      ;(map?.getSource('d-poly') as GeoJSONSource | undefined)?.setData(layers.polygons as never)
      ;(map?.getSource('d-labels') as GeoJSONSource | undefined)?.setData(layers.labels as never)
      ;(map?.getSource('d-circles') as GeoJSONSource | undefined)?.setData(layers.circles as never)
      ;(map?.getSource('d-sectors') as GeoJSONSource | undefined)?.setData(layers.sectors as never)
    }
    whenReady(apply)
  }, [layers])

  // Вписываем отобранные районы; район в фокусе — наезд на него.
  const key = areas.map((a) => a.district).join('|')
  useEffect(() => {
    if (!areas.length) return
    const fit = () => {
      const map = mapRef.current
      if (!map) return
      const bounds = new LngLatBounds([areas[0].lon, areas[0].lat], [areas[0].lon, areas[0].lat])
      for (const area of areas) bounds.extend([area.lon, area.lat])
      const apply = () => map.fitBounds(bounds, { padding: 70, duration: 0, maxZoom: 12 })
      refit.current = apply
      apply()
      map.once('idle', apply)
    }
    whenReady(fit)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    const area = focus ? areas.find((a) => a.district === focus) : null
    if (!area) return
    const shape = shapes ? matchDistrict(area.district, shapes) : null
    const center: [number, number] = shape ? [shape.properties.lx, shape.properties.ly] : [area.lon, area.lat]
    whenReady(() => mapRef.current?.easeTo({ center, zoom: Math.max(mapRef.current.getZoom(), 11.5), duration: 500 }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus])

  return (
    <>
      <div ref={box} className="b-play-map" />
      {mapReady ? null : <AreaWait label="Загружаем карту" />}
    </>
  )
}
