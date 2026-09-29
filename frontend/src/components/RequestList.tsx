/**
 * Левая колонка: заявки группами. Кнопок-фильтров наверху нет — то, ради
 * чего в них ходили, теперь сказано подписью группы и её числом, а строка
 * при этом остаётся на месте: диспетчер не переключает отбор, а ведёт
 * глазами вниз. Сверху одно поле поиска по номеру и адресу, а в нём —
 * фильтр мест: участок и районы (`search/ColumnSearch`).
 *
 * Группы не пересекаются: изменившаяся заявка стоит в «Изменились», и второй
 * раз среди назначенных её нет.
 *
 * Наверху две группы-тревоги: «Просрочены» (приезд по плану позже окна)
 * и «Не назначены». Они стоят всегда, даже пустые — ноль тоже ответ, — и число
 * в них красное, когда оно не ноль. «Не назначены» по умолчанию свёрнуты:
 * у каждой заявки там красная причина, и раскрытая группа встречала диспетчера
 * стеной предупреждений. Свернуть можно любую группу щелчком по подписи;
 * свёрнутая раскрывается сама, когда заявка из неё выбрана на карте или
 * нашлась поиском.
 *
 * Над группами — «Окна дня» (`DayWindows`): где будет плотно, и отбор списка по окну.
 */

import { useMemo, useState } from 'react'
import { activePlan, useStore } from '../store'
import { assignmentIndex, changedIds, deferredIndex, frozenIds, knownRequests, unassignedIndex } from '../lib/plan'
import { colorIndex } from '../lib/colors'
import { usePlaceMatch } from '../lib/places'
import { KIND_LABEL, kindOf, useKindMatch } from '../lib/kinds'
import { SkeletonFill } from './Loading'
import ColumnSearch from './search/ColumnSearch'
import DayPicker from './DayPicker'
import RequestCard from './RequestCard'
import DayWindows, { slotOf } from './DayWindows'
import { colorVar } from '../lib/colors'
import type { RequestItem } from '../types'

export default function RequestList({ compact = false }: { compact?: boolean }) {
  const store = useStore()
  const plan = activePlan(store)
  const dataset = store.dataset

  const assigned = useMemo(() => assignmentIndex(plan), [plan])
  const unassigned = useMemo(() => unassignedIndex(plan), [plan])
  const changed = useMemo(() => changedIds(store.plan), [store.plan])
  const frozen = useMemo(() => frozenIds(store.plan), [store.plan])
  const deferred = useMemo(() => deferredIndex(plan), [plan])
  // Свёрнутые группы; «Не назначены» свёрнуты с самого начала.
  const [folded, setFolded] = useState<Set<string>>(() => new Set(['unassigned']))
  const toggle = (key: string, open: boolean) =>
    setFolded((prev) => {
      const next = new Set(prev)
      if (open) next.add(key)
      else next.delete(key)
      return next
    })

  const order = useMemo(() => (dataset?.engineers ?? []).map((item) => item.id), [dataset])
  const names = useMemo(
    () => new Map((dataset?.engineers ?? []).map((item) => [item.id, item.name])),
    [dataset],
  )

  // Заявки событий дня в наборе нет — добавляем из истории плана.
  const all = useMemo(() => knownRequests(dataset, store.plan), [dataset, store.plan])
  // Фильтр мест из поля поиска: участок и районы.
  const place = usePlaceMatch()
  // Фильтр типов — вид заявки или подтип заказчика, из того же окна фильтра, что места.
  const kindMatch = useKindMatch()
  const requests = useMemo(() => all.filter((item) => place(item) && kindMatch(item)), [all, place, kindMatch])

  const needle = store.search.trim().toLowerCase()
  const found = needle
    ? requests.filter(
        (item) =>
          item.id.toLowerCase().includes(needle) ||
          item.address.toLowerCase().includes(needle) ||
          item.type_bk.toLowerCase().includes(needle) ||
          item.type_hd.toLowerCase().includes(needle) ||
          KIND_LABEL[kindOf(item)].toLowerCase().includes(needle),
      )
    : requests
  // Отбор по окну — щелчком по столбику «Окон дня» над группами.
  const [slot, setSlot] = useState<string | null>(null)
  const shown = slot && !store.crewView ? found.filter((item) => slotOf(item) === slot) : found

  // Детали бригады: список сужен до её маршрута, по порядку визитов.
  const crew = store.crewView
  const route = crew ? plan?.routes.find((r) => r.engineer_id === crew) : null
  const byId = new Map(requests.map((r) => [r.id, r]))
  const manual = (store.settings.requests as Record<string, { priority: string }> | undefined) ?? {}

  const late = (item: RequestItem) => (assigned.get(item.id)?.stop.late_min ?? 0) > 0
  const groups: { key: string; title: string; items: RequestItem[]; alarm?: string }[] = crew
    ? [
        {
          key: 'route',
          title: 'Визиты по порядку',
          items: (route?.stops ?? [])
            .map((s) => byId.get(s.request_id))
            .filter((r): r is RequestItem => Boolean(r) && (!needle || shown.includes(r as RequestItem))),
        },
      ]
    : [
    {
      key: 'late',
      title: 'Просрочены',
      items: shown.filter(late),
      alarm: 'Приезд по плану позже конца окна',
    },
    {
      key: 'unassigned',
      title: 'Не назначены',
      items: shown.filter((item) => !assigned.has(item.id) && !deferred.has(item.id)),
      alarm: 'Заявки без бригады: причина — под каждой',
    },
    {
      key: 'deferred',
      title: 'На следующий день',
      items: shown.filter((item) => !assigned.has(item.id) && deferred.has(item.id)),
    },
    {
      key: 'changed',
      title: 'Изменились',
      items: shown.filter((item) => assigned.has(item.id) && changed.has(item.id) && !late(item)),
    },
    {
      key: 'assigned',
      title: 'Назначены',
      items: shown.filter((item) => assigned.has(item.id) && !changed.has(item.id) && !late(item)),
    },
  ]
  // Группы-тревоги стоят и пустыми; при поиске пустые прячутся — ищут заявку, а не ноль.
  const shownGroups = groups.filter((group) => group.items.length > 0 || (group.alarm && !needle && plan))

  const select = (id: string) => {
    const next = store.selectedRequestId === id ? null : id
    store.selectRequest(next)
    store.selectEngineer(next ? (assigned.get(id)?.engineerId ?? null) : crew)
    if (next) store.focusRequest(next)
  }

  // Бригада выбрана — в поле стоит её тег: список ищется по маршруту бригады,
  // текст рядом с тегом уточняет поиск внутри него. Backspace в пустом поле снимает тег.
  const searchField = (
    <ColumnSearch
      value={store.search}
      onUpdate={store.setSearch}
      placeholder={crew ? 'в маршруте бригады' : 'Номер, адрес или тип'}
      kinds
      onDropLead={() => store.openCrew(null)}
      lead={
        crew ? (
          <button
            type="button"
            className="b-tagchip"
            style={{ ['--c' as string]: colorVar(colorIndex(crew, order)) }}
            onClick={() => store.openCrew(null)}
            title="Убрать бригаду из поиска"
            aria-label={`Бригада ${names.get(crew) ?? crew}: убрать из поиска`}
          >
            <i />
            <span>{names.get(crew) ?? crew}</span>
            <b>✕</b>
          </button>
        ) : null
      }
    />
  )

  return (
    <>
      {compact ? null : (
        <div className="b-ch">
          <b>Заявки</b>
          <DayPicker />
        </div>
      )}

      {compact ? null : searchField}

      <div className="b-cb">
        {store.planning || store.importing?.stage === 'upload' ? (
          <SkeletonFill block={52} />
        ) : (
          <div className="b-list" role="listbox" aria-label="Заявки">
            {/* На телефоне поиск уезжает вместе со списком: закреплённое отнимает место у заявок. */}
            {compact ? searchField : null}
            {!crew && plan ? (
              <DayWindows requests={found} assigned={assigned} deferred={deferred} value={slot} onChange={setSlot} />
            ) : null}
            {shownGroups.map((group) => {
              const open =
                !folded.has(group.key) ||
                Boolean(needle) ||
                group.items.some((item) => item.id === store.selectedRequestId)
              const count = group.items.length
              return (
                <div key={group.key}>
                  <button
                    type="button"
                    className="b-list-g b-list-g-fold"
                    aria-expanded={count ? open : undefined}
                    disabled={!count}
                    onClick={() => toggle(group.key, open)}
                    title={group.alarm ?? (open ? 'Свернуть' : 'Развернуть')}
                  >
                    <span>{group.title}</span>
                    <span className={group.alarm && count ? 'b-list-g-bad' : undefined}>{count}</span>
                  </button>
                  {(open ? group.items : []).map((request) => (
                    <RequestCard
                      key={request.id}
                      request={request}
                      assignment={assigned.get(request.id) ?? null}
                      unassigned={unassigned.get(request.id) ?? null}
                      deferred={deferred.get(request.id) ?? null}
                      engineerName={names.get(assigned.get(request.id)?.engineerId ?? '') ?? null}
                      colorIndex={colorIndex(assigned.get(request.id)?.engineerId ?? '', order)}
                      selected={store.selectedRequestId === request.id}
                      frozen={frozen.has(request.id)}
                      manual={manual[request.id]?.priority ?? null}
                      onSelect={() => select(request.id)}
                    />
                  ))}
                </div>
              )
            })}
            {shownGroups.length === 0 ? (
              <p className="px-3 py-6 text-center text-[var(--b-text-3)]">
                По этому запросу заявок нет
              </p>
            ) : null}
          </div>
        )}
      </div>
    </>
  )
}
