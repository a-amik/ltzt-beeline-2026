import { act } from '@testing-library/react'
import { renderHook } from '@testing-library/react'
import { kindOf, kindTree, kindKey, subKey, useKindMatch, useKinds } from '../lib/kinds'
import type { Dataset, RequestItem } from '../types'

const req = (id: string, skill: RequestItem['skill'], type_bk: string, type_hd: string) =>
  ({ id, skill, type_bk, type_hd }) as RequestItem

const items = [
  req('1', 'emergency', 'Глобальная проблема', 'Авария'),
  req('2', 'local', 'Локальная заявка', 'Нет линка'),
  req('3', 'local', 'Локальная заявка', 'Разрывы'),
  req('4', 'connect', 'Подключение', 'Конвергенция абонента'),
  req('5', 'connect', 'Дозаказ', 'Дозаказ оборудования'),
]

test('вид заявки — как на сервере: авария, ремонт, подключение, дозаказ', () => {
  expect(items.map(kindOf)).toEqual(['accident', 'repair', 'repair', 'connect', 'upsell'])
  const tree = kindTree({ requests: items } as Dataset)
  expect(tree.map((n) => n.kind)).toEqual(['accident', 'repair', 'connect', 'upsell'])
  expect(tree.find((n) => n.kind === 'repair')?.subs.map((s) => s.name).sort()).toEqual(['Нет линка', 'Разрывы'])
})

test('фильтр типов пропускает подтип и вид целиком', () => {
  const { result, rerender } = renderHook(() => useKindMatch())
  expect(items.filter(result.current)).toHaveLength(5)
  act(() => useKinds.getState().set([subKey('repair', 'Нет линка')]))
  rerender()
  expect(items.filter(result.current).map((r) => r.id)).toEqual(['2'])
  act(() => useKinds.getState().set([kindKey('accident'), subKey('repair', 'Разрывы')]))
  rerender()
  expect(items.filter(result.current).map((r) => r.id)).toEqual(['1', '3'])
  act(() => useKinds.getState().set([]))
})
