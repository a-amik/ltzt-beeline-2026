/**
 * Границы районов Москвы для карты «Нагрузки» — `public/geo/moscow-districts.geojson`,
 * собирает `tools/geo/moscow_districts.py` из OpenStreetMap. В файле все районы
 * города и три подмосковных города задания по застройке, поэтому районы любого
 * загруженного набора находятся по имени, а не только районы задания.
 *
 * Имя в заявке и в OSM пишется по-разному: «Бирюлево Восточное» и «район
 * Бирюлёво Восточное», «Москворечье - Сабурово» и «Москворечье-Сабурово»,
 * «Выхино» и «Выхино-Жулебино». Сопоставляются ключи — строчные буквы без
 * «район», «ё» и знаков; нет точного — ищется контур, чей ключ начинается
 * с ключа района (или наоборот). Ключ строит тот же код, что в скрипте.
 */

import { useQuery } from '@tanstack/react-query'

export interface DistrictShape {
  type: 'Feature'
  properties: { name: string; key: string; kind: 'district' | 'town'; lx: number; ly: number }
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown }
}

export interface DistrictShapes {
  type: 'FeatureCollection'
  features: DistrictShape[]
}

export function districtKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/(^|\s)(район|поселение|городской округ|gpon)(?=\s|$)/g, ' ')
    .replace(/[^a-zа-я0-9]/g, '')
}

/** Короче — слишком многое начинается так же: «Северное» подошло бы и к Бутову, и к Тушину. */
const PREFIX_MIN = 5

export function matchDistrict(name: string, shapes: DistrictShapes): DistrictShape | null {
  const key = districtKey(name)
  if (!key) return null
  const exact = shapes.features.find((f) => f.properties.key === key)
  if (exact || key.length < PREFIX_MIN) return exact ?? null
  return shapes.features.find((f) => f.properties.key.startsWith(key) || key.startsWith(f.properties.key)) ?? null
}

export function useDistrictShapes() {
  return useQuery({
    queryKey: ['district-shapes'],
    queryFn: async (): Promise<DistrictShapes> => {
      const response = await fetch(`${import.meta.env.BASE_URL}geo/moscow-districts.geojson`)
      if (!response.ok) throw new Error(`границы районов: ${response.status}`)
      return (await response.json()) as DistrictShapes
    },
    staleTime: Infinity,
    retry: 1,
  })
}
