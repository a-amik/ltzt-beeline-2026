/**
 * Тип заявки для глаза и для фильтра: четыре вида со значком — авария,
 * ремонт, подключение, дозаказ — и подтип заказчика внутри («Нет линка»,
 * «Разрывы», «Низкая скорость»…). Вид выводится так же, как на сервере
 * (`kind_of`): навык «авария» — авария, тип «Дозаказ» — дозаказ, навык
 * подключения — подключение, остальное — ремонт.
 *
 * Фильтр типов живёт рядом с фильтром мест (`places.ts`): выбранное встаёт
 * метками в поле поиска «Заявок», сбрасывается со сменой набора.
 */

import { useMemo } from 'react'
import { create } from 'zustand'
import { useStore } from '../store'
import type { Dataset, RequestItem } from '../types'

export type Kind = 'accident' | 'repair' | 'connect' | 'upsell'

export const KINDS: { key: Kind; label: string }[] = [
  { key: 'accident', label: 'Авария' },
  { key: 'repair', label: 'Ремонт' },
  { key: 'connect', label: 'Подключение' },
  { key: 'upsell', label: 'Дозаказ' },
]

export const KIND_LABEL: Record<Kind, string> = Object.fromEntries(KINDS.map((k) => [k.key, k.label])) as Record<Kind, string>

export function kindOf(request: Pick<RequestItem, 'skill' | 'type_bk'>): Kind {
  if (request.skill === 'emergency') return 'accident'
  if (request.type_bk === 'Дозаказ') return 'upsell'
  if (request.skill === 'connect') return 'connect'
  return 'repair'
}

/** Выбор фильтра: вид целиком (`kind:repair`) или подтип внутри вида (`sub:repair|Нет линка`). */
interface KindState {
  picked: string[]
  toggle: (key: string) => void
  set: (keys: string[]) => void
}

export const useKinds = create<KindState>((set) => ({
  picked: [],
  toggle: (key) => set((s) => ({ picked: s.picked.includes(key) ? s.picked.filter((k) => k !== key) : [...s.picked, key] })),
  set: (picked) => set({ picked }),
}))

useStore.subscribe((s, prev) => {
  if (s.datasetId !== prev.datasetId) useKinds.getState().set([])
})

export const kindKey = (kind: Kind) => `kind:${kind}`
export const subKey = (kind: Kind, sub: string) => `sub:${kind}|${sub}`

/** Подпись выбранного для метки в поле: «Ремонт» или «Нет линка». */
export function pickedLabel(key: string): string {
  if (key.startsWith('kind:')) return KIND_LABEL[key.slice(5) as Kind] ?? key
  return key.split('|')[1] ?? key
}

export interface KindNode {
  kind: Kind
  count: number
  subs: { name: string; count: number }[]
}

/** Дерево типов набора: вид → подтипы со счётом, виды в постоянном порядке. */
export function kindTree(dataset: Dataset | null | undefined): KindNode[] {
  const by = new Map<Kind, Map<string, number>>()
  for (const request of dataset?.requests ?? []) {
    const kind = kindOf(request)
    const subs = by.get(kind) ?? new Map<string, number>()
    subs.set(request.type_hd, (subs.get(request.type_hd) ?? 0) + 1)
    by.set(kind, subs)
  }
  return KINDS.filter((k) => by.has(k.key)).map((k) => {
    const subs = [...by.get(k.key)!.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
    return { kind: k.key, count: subs.reduce((sum, s) => sum + s.count, 0), subs }
  })
}

/** Проходит ли заявка через фильтр типов: пусто — все; иначе вид или подтип из выбранного. */
export function useKindMatch() {
  const picked = useKinds((s) => s.picked)
  return useMemo(() => {
    const set = new Set(picked)
    return (item: Pick<RequestItem, 'skill' | 'type_bk' | 'type_hd'>) => {
      if (!set.size) return true
      const kind = kindOf(item)
      return set.has(kindKey(kind)) || set.has(subKey(kind, item.type_hd))
    }
  }, [picked])
}
