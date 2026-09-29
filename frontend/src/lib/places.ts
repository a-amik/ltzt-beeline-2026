/**
 * Фильтр мест: участок и районы. Участок живёт в общем хранилище (`sector`):
 * им сужаются и карта, и ссылка на экран. Районы — здесь, рядом: их выбирают
 * в том же окне фильтра под участком, и сбрасываются они вместе со сменой набора.
 *
 * Район входит ровно в один участок (так в наборах заказчика), поэтому дерево
 * «участок → районы» строится прямо из заявок набора.
 */

import { useMemo } from 'react'
import { create } from 'zustand'
import { useStore } from '../store'
import type { Dataset } from '../types'

interface PlaceState {
  districts: string[]
  toggleDistrict: (name: string) => void
  setDistricts: (names: string[]) => void
}

export const usePlaces = create<PlaceState>((set) => ({
  districts: [],
  toggleDistrict: (name) =>
    set((s) => ({ districts: s.districts.includes(name) ? s.districts.filter((d) => d !== name) : [...s.districts, name] })),
  setDistricts: (districts) => set({ districts }),
}))

// Другой набор — другие районы: прежний выбор в нём ничего не значит.
useStore.subscribe((s, prev) => {
  if (s.datasetId !== prev.datasetId) usePlaces.getState().setDistricts([])
})

export interface PlaceSector {
  id: string | null
  name: string
  count: number
  districts: { name: string; count: number }[]
}

/** Дерево мест набора: участки с районами; у набора без участков — один узел без имени. */
export function placeTree(dataset: Dataset | null | undefined): PlaceSector[] {
  if (!dataset) return []
  const sectors = dataset.sectors ?? []
  const by = new Map<string | null, Map<string, number>>()
  for (const request of dataset.requests) {
    const key = sectors.length ? (request.sector ?? null) : null
    const districts = by.get(key) ?? new Map<string, number>()
    districts.set(request.district, (districts.get(request.district) ?? 0) + 1)
    by.set(key, districts)
  }
  const node = (id: string | null, name: string): PlaceSector => {
    const districts = [...(by.get(id) ?? new Map()).entries()]
      .map(([n, count]) => ({ name: n, count }))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    return { id, name, count: districts.reduce((sum, d) => sum + d.count, 0), districts }
  }
  if (!sectors.length) return [node(null, dataset.name)]
  return sectors.map((s) => node(s.id, s.name))
}

/** Участок района — по заявкам набора. */
export function useDistrictSector() {
  const dataset = useStore((s) => s.dataset)
  return useMemo(() => new Map((dataset?.requests ?? []).map((r) => [r.district, r.sector ?? null])), [dataset])
}

/** Проходит ли место через фильтр: участок из общего хранилища и районы отсюда. */
export function usePlaceMatch() {
  const sector = useStore((s) => s.sector)
  const districts = usePlaces((s) => s.districts)
  return useMemo(() => {
    const set = new Set(districts)
    return (item: { sector?: string | null; district?: string | null }) =>
      // Заявка без участка (вброшенная днём) видна при любом участке, как и раньше.
      (!sector || !item.sector || item.sector === sector) && (!set.size || (item.district != null && set.has(item.district)))
  }, [sector, districts])
}

/** Есть ли вообще что выбирать: у набора больше одного района. */
export function useHasPlaces() {
  const dataset = useStore((s) => s.dataset)
  return useMemo(() => new Set((dataset?.requests ?? []).map((r) => r.district)).size > 1, [dataset])
}
