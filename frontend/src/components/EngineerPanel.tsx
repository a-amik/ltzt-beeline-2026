/**
 * Колонка бригад с лентой дня. Сверху — «Загрузка бригад» (`CrewLoad`):
 * кто свободен, кто в норме, кто сверх нормы. Ниже бригады группами по
 * участкам, с числом справа; группу сворачивают щелчком по подписи.
 * Клик по бригаде ведёт карту к её маршруту, повторный — снимает выбор
 * и возвращает общий вид.
 *
 * Клик по бригаде открывает её детали в шторке справа поверх карты (`DetailSheet`):
 * там её маршрут, запас, переписка и действия — задержка, выбытие, «Написать».
 */

import { Fragment, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { api } from '../api'
import { IconPhone, IconShield } from '../lib/icons'
import type { FraudFlag } from '../types'
import { activePlan, useStore } from '../store'
import { changedIds, changedRoutes, frozenIds, knownRequests } from '../lib/plan'
import { colorIndex, colorVar } from '../lib/colors'
import { DAY_END, DAY_START, toMin } from '../lib/time'
import DayTimeline from './DayTimeline'
import { usePhone } from '../lib/media'
import { useInbox } from '../crew/DispatcherChat'
import { usePlaces } from '../lib/places'
import { SkeletonFill } from './Loading'
import ColumnSearch from './search/ColumnSearch'
import DayPicker from './DayPicker'
import CrewLoad, { loadKind, type LoadKind } from './CrewLoad'

export default function EngineerPanel() {
  const store = useStore()
  // На телефоне детали бригады — шторкой снизу (`App`, PhoneScreen), не в строке.
  const phone = usePhone()
  const plan = activePlan(store)
  const dataset = store.dataset

  const routes = useMemo(
    () => new Map((plan?.routes ?? []).map((route) => [route.engineer_id, route])),
    [plan],
  )
  const requests = useMemo(
    () => new Map(knownRequests(dataset, store.plan).map((item) => [item.id, item])),
    [dataset, store.plan],
  )

  const frozen = useMemo(() => frozenIds(store.plan), [store.plan])
  const changed = useMemo(() => changedIds(store.plan), [store.plan])
  const touched = useMemo(() => changedRoutes(store.plan), [store.plan])
  const eventMin = store.plan?.diff ? toMin(store.plan.diff.event.time) : null

  // Флаги контроля по отметкам бригад: сервер пересчитывает их на каждую отметку.
  const control = useQuery({
    queryKey: ['fraud', plan?.id],
    queryFn: () => api.fraud(plan!.id),
    enabled: Boolean(plan) && !store.offline && plan?.algorithm !== 'control',
    refetchInterval: 5000,
    retry: false,
  })
  const flagsBy = useMemo(() => {
    const map = new Map<string, FraudFlag[]>()
    for (const flag of control.data?.flags ?? []) {
      map.set(flag.engineer_id, [...(map.get(flag.engineer_id) ?? []), flag])
    }
    return map
  }, [control.data])

  // Сообщения из приложения бригад: непрочитанное, «проблема» и SOS.
  const inbox = useInbox(dataset?.id, !store.offline)

  // Поиск по фамилии и фильтр мест. Инженер закреплён за участком; район —
  // это где у него визиты по плану, а до плана — районы его участка.
  const [query, setQuery] = useState('')
  const districts = usePlaces((s) => s.districts)
  const visited = useMemo(() => {
    if (!districts.length) return null
    const wanted = new Set(districts)
    const ids = new Set<string>()
    if (plan) {
      for (const route of plan.routes) {
        if (route.stops.some((stop) => wanted.has(requests.get(stop.request_id)?.district ?? ''))) ids.add(route.engineer_id)
      }
    } else {
      const sectors = new Set((dataset?.requests ?? []).filter((r) => wanted.has(r.district)).map((r) => r.sector))
      for (const engineer of dataset?.engineers ?? []) if (sectors.has(engineer.sector)) ids.add(engineer.id)
    }
    return ids
  }, [districts, plan, requests, dataset])
  const needle = query.trim().toLowerCase()
  const all = dataset?.engineers ?? []
  const listed = all.filter(
    (item) =>
      (!store.sector || item.sector === store.sector) &&
      (!visited || visited.has(item.id)) &&
      (!needle || item.name.toLowerCase().includes(needle) || item.id.toLowerCase().includes(needle)),
  )
  // Отбор по загрузке — щелчком по числу «Загрузки бригад» над лентами.
  const [load, setLoad] = useState<LoadKind | null>(null)
  const engineers = load && plan ? listed.filter((item) => loadKind(item, routes.get(item.id) ?? null) === load) : listed
  const order = (dataset?.engineers ?? []).map((item) => item.id) // цвет бригады — по полному списку, фильтр его не меняет
  // Группы — участки набора, как в фильтре мест; у набора без участков группа одна.
  // Свернуть можно любую; свёрнутая раскрывается сама, если бригада в ней выбрана.
  const [folded, setFolded] = useState<Set<string>>(() => new Set())
  const toggle = (key: string, open: boolean) =>
    setFolded((prev) => {
      const next = new Set(prev)
      if (open) next.add(key)
      else next.delete(key)
      return next
    })
  const sectors = dataset?.sectors ?? []
  const groups = (
    sectors.length
      ? [
          ...sectors.map((sector) => ({ key: sector.id, title: sector.name, items: engineers.filter((e) => e.sector === sector.id) })),
          { key: '', title: 'Без участка', items: engineers.filter((e) => !sectors.some((sector) => sector.id === e.sector)) },
        ]
      : [{ key: 'all', title: 'Бригады', items: engineers }]
  ).filter((group) => group.items.length > 0)
  const hours = Array.from({ length: (DAY_END - DAY_START) / 240 + 1 }, (_, i) => DAY_START + i * 240)

  // Клик по бригаде открывает её детали слева и сужает список заявок до её маршрута;
  // повторный — возвращает все заявки и общий вид карты.
  const pick = (id: string) => store.openCrew(store.crewView === id ? null : id)

  return (
    <>
      <div className="b-ch">
        <b>Инженеры</b>
        {/* На телефоне день плана — в шапке экрана. */}
        {phone ? null : <DayPicker />}
      </div>

      <ColumnSearch value={query} onUpdate={setQuery} placeholder="Фамилия инженера" />

      {store.crewView ? (
        <div className="b-ch-sub">
          <span />
          <Button view="flat" size="s" onClick={() => store.openCrew(null)}>
            Все заявки
          </Button>
        </div>
      ) : null}

      <div className="b-cb">
        {store.planning ? (
          <SkeletonFill block={24} />
        ) : (
          <>
            {plan && !store.crewView ? <CrewLoad engineers={listed} routes={routes} value={load} onChange={setLoad} /> : null}
            <div className="b-tl">
              {groups.map((group) => {
                const open =
                  !folded.has(group.key) ||
                  Boolean(needle) ||
                  group.items.some((item) => item.id === store.selectedEngineerId)
                return (
                  <Fragment key={group.key}>
                    <button
                      type="button"
                      className="b-list-g b-list-g-fold b-tl-g"
                      aria-expanded={open}
                      onClick={() => toggle(group.key, open)}
                      title={open ? 'Свернуть' : 'Развернуть'}
                    >
                      <span>{group.title}</span>
                      <span>{group.items.length}</span>
                    </button>
                    {(open ? group.items : []).map((engineer) => {
                    const route = routes.get(engineer.id) ?? null
                    const selected = store.selectedEngineerId === engineer.id
                    const index = colorIndex(engineer.id, order)
                    return (
                      <div
                        key={engineer.id}
                        className={`b-tl-row${store.crewView === engineer.id && !phone ? ' open' : ''}`}
                        style={{ ['--c' as string]: route ? colorVar(index) : 'var(--b-text-3)' }}
                      >
                        <button
                          type="button"
                          className="eng"
                          aria-pressed={selected}
                          onClick={() => pick(engineer.id)}
                          style={{
                            ['--c' as string]: route ? colorVar(index) : 'var(--b-text-3)',
                          }}
                          title={
                            route
                              ? [
                                  `${route.stops.length} визитов · ${route.distance_km} км`,
                                  route.norm_min ? `норма ${route.norm_min} нормо-мин` : '',
                                  route.break_start ? `обед ${route.break_start}` : '',
                                  (engineer.transports ?? [engineer.transport]).join(', '),
                                  engineer.extra_load === false ? 'сверх нормы не берёт' : '',
                                ].filter(Boolean).join(' · ')
                              : 'Свободен весь день'
                          }
                        >
                          <i />
                          <em>{engineer.name}</em>
                          <small>
                            {/* Непрочитанное от бригады — внутри её строки: клик по строке и открывает детали с перепиской. */}
                            {inbox.data?.[engineer.id] ? (
                              <b
                                role="img"
                                className={`b-inbox ${inbox.data[engineer.id].sos ? 'sos' : inbox.data[engineer.id].problem ? 'problem' : ''}`}
                                title={`Новых: ${inbox.data[engineer.id].unread} · ${inbox.data[engineer.id].last.text} · ${inbox.data[engineer.id].last.time}`}
                                aria-label={`Новых сообщений: ${inbox.data[engineer.id].unread}`}
                              />
                            ) : null}
                            {flagsBy.get(engineer.id)?.length ? (
                              <b
                                className={`b-flag ${flagsBy.get(engineer.id)!.some((f) => f.severity === 'alert') ? 'alert' : 'warn'}`}
                                title={flagsBy
                                  .get(engineer.id)!
                                  .map((f) => `${f.text}. ${f.action}`)
                                  .join('\n')}
                              >
                                <IconShield /> {flagsBy.get(engineer.id)!.length}
                              </b>
                            ) : null}
                            {route?.stops.length ?? 0}
                            {touched.has(engineer.id) ? ' ·' : ''}
                          </small>
                        </button>
                        <a
                          className="b-crew-link"
                          href={`#crew/${engineer.id}`}
                          target="_blank"
                          rel="noreferrer"
                          title={`Приложение бригады ${engineer.name}`}
                        >
                          <IconPhone />
                        </a>
                        <DayTimeline
                          route={route}
                          requests={requests}
                          colorIndex={index}
                          frozen={frozen}
                          changedRequests={changed}
                          eventMin={eventMin}
                          dimmed={Boolean(store.selectedEngineerId) && !selected}
                        />
                      </div>
                    )
                    })}
                  </Fragment>
                )
              })}
              {engineers.length === 0 ? <p className="px-3 py-6 text-center text-[var(--b-text-3)]">Никого не нашлось</p> : null}
              <div className="axis">
                {hours.map((min) => (
                  <span key={min}>{String(min / 60).padStart(2, '0')}:00</span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
