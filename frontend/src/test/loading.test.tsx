import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { onMapReady } from '../components/Loading'

/** Подставная карта: события и `areTilesLoaded`, как у MapLibre. */
function fakeMap(tilesLoaded: () => boolean) {
  const handlers = new Map<string, Set<(e?: unknown) => void>>()
  const on = (type: string, fn: (e?: unknown) => void) => {
    if (!handlers.has(type)) handlers.set(type, new Set())
    handlers.get(type)!.add(fn)
  }
  const off = (type: string, fn: (e?: unknown) => void) => handlers.get(type)?.delete(fn)
  const map = {
    on,
    off,
    once: (type: string, fn: (e?: unknown) => void) => {
      const wrap = (e?: unknown) => {
        off(type, wrap)
        fn(e)
      }
      on(type, wrap)
    },
    areTilesLoaded: tilesLoaded,
    emit: (type: string, e?: unknown) => [...(handlers.get(type) ?? [])].forEach((fn) => fn(e)),
  }
  return map
}

describe('лоадер карты уходит, когда подложка на месте', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('первая плитка пришла и плитки вида загружены — готово, без запасного срока', () => {
    const map = fakeMap(() => true)
    const done = vi.fn()
    onMapReady(map as unknown as MapLibreMap, done)
    vi.advanceTimersByTime(1000)
    expect(done).not.toHaveBeenCalled() // плиток ещё не было: «загружено» по пустому виду не в счёт
    map.emit('data', { dataType: 'source', tile: {} })
    vi.advanceTimersByTime(300)
    expect(done).toHaveBeenCalledTimes(1)
  })

  it('карта затихла — готово', () => {
    const map = fakeMap(() => false)
    const done = vi.fn()
    onMapReady(map as unknown as MapLibreMap, done)
    map.emit('idle')
    expect(done).toHaveBeenCalledTimes(1)
  })

  it('плитки не пришли — лоадер уходит через 15 с, один раз', () => {
    const map = fakeMap(() => false)
    const done = vi.fn()
    onMapReady(map as unknown as MapLibreMap, done)
    vi.advanceTimersByTime(14000)
    expect(done).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1500)
    map.emit('idle')
    expect(done).toHaveBeenCalledTimes(1)
  })
})
