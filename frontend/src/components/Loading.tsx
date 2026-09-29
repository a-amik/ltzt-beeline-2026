/**
 * Ожидание загрузки на рабочих экранах — одним приёмом везде.
 *
 * Слева (колонки «Заявки», «Инженеры», «Нагрузка») — скелетон, блоки которого
 * повторяются до нижнего края экрана и уходят за него: колонка не обрывается
 * пустотой посередине. Справа (карта, страница отчётов) — лоадер «М» по центру
 * области, пока в ней нечего показать. Карта считается загруженной, когда
 * пришла первая плитка подложки и все плитки вида на месте (`areTilesLoaded`)
 * или карта затихла (`idle`); `idle` один не годится — обновления слоёв его откладывают.
 * Не пришли плитки — лоадер уходит сам через 15 с, чтобы не висеть без конца.
 */

import { useMemo } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { RouteLoader } from './RouteLoader'

export function SkeletonFill({ block, gap = 8 }: { block: number; gap?: number }) {
  const count = useMemo(() => {
    const tall = typeof window === 'undefined' ? 1000 : Math.max(window.innerHeight, window.screen?.height ?? 0)
    return Math.ceil(tall / (block + gap)) + 2
  }, [block, gap])
  return (
    <div className="b-skel-fill" style={{ gap }} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="b-skeleton" style={{ height: block }} />
      ))}
    </div>
  )
}

export function AreaWait({ label, size = 56 }: { label: string; size?: number }) {
  return (
    <div className="b-area-wait" role="status" aria-label={label}>
      <RouteLoader size={size} label={label} />
    </div>
  )
}

const MAP_WAIT_MS = 15000

/** Первая полная отрисовка карты: `idle` или, если плиток нет, запасной срок. Возвращает отписку. */
export function onMapReady(map: MapLibreMap, done: () => void): () => void {
  let fired = false
  let poll = 0
  const fire = () => {
    if (fired) return
    fired = true
    window.clearInterval(poll)
    done()
  }
  // `isStyleLoaded()` и событие `load` здесь не помощники: приложение всё время
  // обновляет свои слои, стиль числится незагруженным, и `load` может не прийти.
  // Готовность — пришла хотя бы одна плитка подложки, и плитки вида все на месте.
  let styled = false
  const onData = (event: { dataType?: string; tile?: unknown }) => {
    if (event.dataType === 'source' && event.tile) {
      styled = true
      map.off('data', onData)
    }
  }
  map.on('data', onData)
  map.once('idle', fire)
  const timer = window.setTimeout(fire, MAP_WAIT_MS)
  poll = window.setInterval(() => {
    try {
      if (styled && map.areTilesLoaded()) fire()
    } catch {
      // карта ещё собирается — следующая проверка
    }
  }, 250)
  const stop = () => window.clearInterval(poll)
  map.once('remove', stop)
  return () => {
    window.clearTimeout(timer)
    stop()
    map.off('idle', fire)
    map.off('data', onData)
  }
}
