/**
 * Экран один: колонка разделов у левого края во всю высоту, полоса сверху,
 * левая панель с заявками или инженерами, карта, метрики снизу. Вкладок
 * на широком экране нет нарочно — диспетчер смотрит на всё разом, и то, что
 * он выбрал слева, обязано подсветиться и на карте, и на ленте.
 *
 * Левая панель — между колонкой разделов и картой, как у транспортных
 * диспетчерских: в ней заявки или инженеры, смотря что выбрано в колонке
 * разделов. Кнопка на её границе сворачивает панель и отдаёт место карте.
 * Окна разделов (лента, правила, имитация) тоже выезжают слева, от колонки.
 *
 * До 760 px остаётся одна
 * колонка: карта сверху, лист под ней с вкладками, внизу закреплённая полоса
 * с двумя действиями. Выпадающие окна на телефоне открываются листом снизу —
 * это делает сам Gravity, которому сказано `mobile`.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MobileProvider, ThemeProvider } from '@gravity-ui/uikit'
import { loadDataset, loadDatasets, runPlan } from './data'
import { applyTheme, useStore, type DialogKind } from './store'
import { usePhone } from './lib/media'
import TopBar from './components/TopBar'
import Rail, { PhoneNav } from './components/Rail'
import RequestList from './components/RequestList'
import MapView from './components/MapView'
import MapBoundary from './components/MapBoundary'
import EngineerPanel from './components/EngineerPanel'
import MetricsBar from './components/MetricsBar'
import SummaryChip from './dispatch/SummaryChip'
import FeedPanel from './dispatch/FeedPanel'
import DetailSheet from './components/DetailSheet'
import { IconMap } from './lib/icons'
import { useAutoHide } from './crew/useAutoHide'
import EventDialog from './components/EventDialog'
import CompareDrawer from './components/CompareDrawer'
import SettingsDrawer from './components/SettingsDrawer'
import SimulationDrawer from './components/SimulationDrawer'
import VersionsView from './manager/VersionsView'
import DemoCompare from './components/demo/DemoCompare'
import { DeficitMapPane, DeficitPanel } from './components/demo/DeficitView'
import DayPicker from './components/DayPicker'
import CommandPalette from './components/search/CommandPalette'
import { useHotkeys } from './lib/hotkeys'
import ReportsView from './components/demo/ReportsView'
import RaceView from './components/race/RaceView'
import { api } from './api'
import { managerApi } from './manager/managerApi'
import { ApiError } from './api'
import { IconChevron } from './lib/icons'
import { startMapCache } from './lib/mapCache'
import { startRouter } from './lib/router'
import { hideBoot } from './lib/boot'

export default function App() {
  const store = useStore()
  const phone = usePhone()
  // Для какого набора план уже запрошен сам: сменили регион — готовый план запрашивается снова.
  const autoPlanned = useRef<string | null>(null)

  useEffect(() => {
    applyTheme(useStore.getState().theme)
    startMapCache()
    startRouter()
  }, [])

  const datasetsQuery = useQuery({
    queryKey: ['datasets'],
    queryFn: loadDatasets,
    staleTime: Infinity,
  })

  const datasetQuery = useQuery({
    queryKey: ['dataset', store.datasetId],
    queryFn: () => loadDataset(store.datasetId),
    staleTime: Infinity,
  })

  useEffect(() => {
    useStore.getState().setDataset(datasetQuery.data ?? null)
  }, [datasetQuery.data])
  useEffect(() => {
    if (datasetQuery.data || datasetQuery.isError) hideBoot()
  }, [datasetQuery.data, datasetQuery.isError])

  // Общие правила дня задаёт руководитель на своём экране; здесь они только читаются.
  // Поменял их руководитель — диспетчер узнаёт об этом уведомлением, а план
  // пересчитывает сам, когда ему удобно: день посреди работы сам не перестраивается.
  const rulesQuery = useQuery({
    queryKey: ['rules'],
    queryFn: () => api.rules(),
    refetchInterval: 15_000,
    retry: false,
  })
  useEffect(() => {
    const data = rulesQuery.data
    if (!data) return
    const state = useStore.getState()
    const before = state.rulesVersion
    state.setRules(data.rules, data.version)
    if (before !== null && before !== data.version && state.plan) {
      state.notify('Руководитель изменил правила дня — пересчитайте план, чтобы они вступили в силу')
    }
  }, [rulesQuery.data])
  const rulesNote = (() => {
    const at = rulesQuery.data?.updated_at
    const time = at ? new Date(at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : null
    return `Правила общие на день: их задаёт эксперт, диспетчеру этот экран не нужен${time ? `. Изменены в ${time}` : ''}. Сохранение пересчитывает план`
  })()

  const planMutation = useMutation({
    mutationFn: (algorithm: 'solver' | 'baseline') => {
      const dataset = useStore.getState().dataset
      if (!dataset) throw new Error('Набор ещё не загружен')
      return runPlan(dataset, algorithm)
    },
    onMutate: () => {
      useStore.getState().setPlanning(true)
    },
    onSettled: () => {
      useStore.getState().setPlanning(false)
    },
    onError: (error) => {
      const text = error instanceof ApiError ? error.message : String(error)
      useStore.getState().notify(`План не построился: ${text}`)
    },
    onSuccess: (plan, algorithm) => {
      // Куда класть план, решает то, что запрашивали, а не поле ответа:
      // пока решателя нет, сервер честно отдаёт baseline и помечает его так.
      if (algorithm === 'baseline') useStore.getState().setBaseline(plan)
      else {
        useStore.getState().setPlan(plan)
        if (plan.unassigned.length > 0) improve(plan)
        // Две обязательные метрики задания — бригады и пробег — читаются рядом
        // с базовым вариантом п. 2.3 сразу, а не после отдельной кнопки.
        const dataset = useStore.getState().dataset
        if (dataset && !useStore.getState().offline) {
          runPlan(dataset, 'baseline', useStore.getState().settings, false)
            .then((base) => {
              const now = useStore.getState()
              if (now.plan?.id === plan.id) now.setBaseline(base)
            })
            .catch(() => undefined)
        }
      }
    },
  })

  // Быстрый план показывается сразу, а решатель продолжает искать дольше
  // в фоне. Нашёл план с меньшим числом неназначенных или большим итогом
  // дня — подменяет, если диспетчер за это время ничего не менял.
  const improve = (quick: import('./types').Plan) => {
    const state = useStore.getState()
    if (state.offline || !state.dataset) return
    const settings = { ...state.settings, options: { ...((state.settings.options as object) ?? {}), time_limit_s: 12 } }
    runPlan(state.dataset, 'solver', settings, false)
      .then((better) => {
        const now = useStore.getState()
        if (!now.plan || now.plan.id !== quick.id) return
        const fewer = better.unassigned.length < quick.unassigned.length
        const richer = (better.economy?.net_rub ?? 0) > (quick.economy?.net_rub ?? 0) + 1000
        if (!fewer && !richer) return
        now.setPlan(better)
        now.notify(
          fewer
            ? `Решатель нашёл план лучше: не назначено ${better.unassigned.length} вместо ${quick.unassigned.length}`
            : 'Решатель нашёл план лучше: итог дня выше',
        )
      })
      .catch(() => undefined)
  }

  // Первый расчёт и расчёт после смены региона делаются сами: пустая карта ничего не рассказывает
  // о плане, а на телефоне кнопка «Спланировать» убрана в меню.
  const startPlan = planMutation.mutate
  useEffect(() => {
    const dataset = store.dataset
    if (!dataset || dataset.id !== store.datasetId || store.plan || store.planning) return
    if (autoPlanned.current === dataset.id) return
    autoPlanned.current = dataset.id
    // Утренние планы регионов сервер держит готовыми (`ready.py`): ответ приходит сразу.
    startPlan('solver')
  }, [store.dataset, store.datasetId, store.plan, store.planning, startPlan])

  const onSimulate = () => store.setSimOpen(true)

  // Бригады отвечают на предложения и отмечаются в своём приложении, и план
  // на сервере меняется без диспетчера. Экран раз в пять секунд спрашивает
  // «последний план» и подхватывает его как ответ на событие.
  useEffect(() => {
    if (store.offline) return
    const timer = window.setInterval(async () => {
      const state = useStore.getState()
      if (!state.plan || state.planning || !state.followLatest || state.drafts.length) return
      try {
        const latest = await api.latestPlan(state.datasetId)
        if (latest.id === state.plan.id || latest.dataset_id !== state.datasetId) return
        if (latest.id === state.previousPlan?.id) return
        state.applyReplan(latest)
        state.notify('План обновился: бригада ответила на предложение или отметилась')
      } catch {
        // сервер не ответил — попробуем через пять секунд
      }
    }, 5000)
    return () => window.clearInterval(timer)
  }, [store.offline])

  // Ручной приоритет заявки — настройка плана: поменяли — день пересчитывается сам.
  const manualKey = JSON.stringify(store.settings.requests ?? {})
  const lastManual = useRef(manualKey)
  useEffect(() => {
    if (lastManual.current === manualKey) return
    lastManual.current = manualKey
    if (useStore.getState().plan && !useStore.getState().planning) {
      startPlan('solver')
      useStore.getState().notify('Приоритет заявки изменён — день пересчитывается')
    }
  }, [manualKey, startPlan])

  const covered = Boolean(store.demo || store.simOpen || store.compareOpen || store.settingsOpen || store.feedOpen)
  // Дефицит на десктопе — раздел, а не окно: колонка стоит и при свёрнутой панели.
  const deficit = store.demo === 'deficit' && !phone
  const side = store.sideOpen
  // Правила расчёта правит эксперт на своём экране: сохранили — план пересчитан по новым.
  const queryClient = useQueryClient()
  const saveRules = useMutation({
    mutationFn: (draft: import('./types').Settings) => managerApi.saveRules(draft),
    onSuccess: (data) => {
      useStore.getState().setRules(data.rules, data.version)
      queryClient.setQueryData(['rules'], data)
      useStore.getState().setSettingsOpen(false)
      planMutation.mutate('solver')
      useStore.getState().notify('Правила сохранены — план пересчитывается')
    },
    onError: (error) => useStore.getState().notify(`Правила не сохранились: ${String(error)}`),
  })
  const onEvent = (kind: DialogKind) => store.openDialog(kind)
  const onPlan = () => planMutation.mutate('solver')
  useHotkeys()
  // В дефицит приходят за колонкой районов: свёрнутая раньше панель раскрывается.
  useEffect(() => {
    if (deficit) useStore.getState().setSideOpen(true)
  }, [deficit])

  const dialogs = (
    <>
      {store.dialog ? (
        <EventDialog key={store.dialog} kind={store.dialog} />
      ) : null}
      <FeedPanel />
      <CommandPalette onPlan={onPlan} onEvent={onEvent} />
      <CompareDrawer />
      <SimulationDrawer />
      {store.demo === 'compare' ? <DemoCompare onClose={() => store.setDemo(null)} /> : null}
      {store.demo === 'race' ? <RaceView onClose={() => store.setDemo(null)} /> : null}
      {store.demo === 'reports' ? <ReportsView onClose={() => store.setDemo(null)} /> : null}
      {store.demo === 'versions' && store.datasetId ? (
        <VersionsView region={store.datasetId} onRestore={(plan) => store.setPlan(plan)} onClose={() => store.setDemo(null)} />
      ) : null}
      {store.settingsOpen ? (
        <SettingsDrawer
          key={store.rulesVersion ?? 'none'}
          layout="screen"
          mode="edit"
          initial={store.rules}
          engineers={store.dataset?.engineers ?? []}
          note={rulesNote}
          busy={store.planning || saveRules.isPending}
          submitLabel={saveRules.isPending ? 'Сохраняем…' : 'Сохранить и пересчитать'}
          onClose={() => store.setSettingsOpen(false)}
          onSubmit={(draft) => saveRules.mutate(draft)}
        />
      ) : null}
    </>
  )

  return (
    <ThemeProvider theme={store.theme}>
      <MobileProvider mobile={phone}>
        {phone ? (
          <PhoneScreen
            datasets={datasetsQuery.data ?? []}
            onPlan={onPlan}
            onEvent={onEvent}
            dialogs={dialogs}
          />
        ) : (
          <div className="b-app railed">
            <Rail />
            {/* Колонка раздела поднята во всю высоту, шапка — только над картой:
                название продукта и так стоит знаком в колонке разделов. */}
            <div
              className="b-body b-desk relative"
              style={{
                '--side': side ? '360px' : 'auto',
                gridTemplateColumns: side ? 'var(--side) minmax(0, 1fr)' : 'minmax(0, 1fr)',
              } as React.CSSProperties}
            >
              {/* Дефицит — раздел, как заявки и инженеры: своя колонка слева и своя карта справа. */}
              {!side ? null : deficit ? (
                <aside className="b-col l wide">
                  <DeficitPanel />
                </aside>
              ) : (
                <aside className={`b-col l${store.panelOpen ? ' wide' : ''}`}>
                  {store.panelOpen ? <EngineerPanel /> : <RequestList />}
                </aside>
              )}

              {/* Кнопка на границе панели, как у транспортных диспетчерских: сворачивает её и возвращает.
                  Под открытым окном раздела её нет — окно закрывает панель; у дефицита она есть: он раздел. */}
              {covered && !deficit ? null : (
              <button
                type="button"
                className={`b-side-tg${side ? '' : ' shut'}`}
                onClick={() => store.setSideOpen(!side)}
                title={side ? 'Свернуть панель' : 'Развернуть панель'}
                aria-label={side ? 'Свернуть панель' : 'Развернуть панель'}
                aria-expanded={side}
              >
                <IconChevron />
              </button>
              )}

              <div className="flex min-h-0 min-w-0 flex-col">
                <TopBar
                  datasets={datasetsQuery.data ?? []}
                  phone={false}
                  onPlan={onPlan}
                  onEvent={onEvent}
                  onSimulate={onSimulate}
                />
                {/* isolate: слои карты (у «Нагрузки» z-index 30) считаются внутри неё и не накрывают
                    колонку слева — её место под полосу прокрутки вынесено на кромку карты. */}
                <div className="relative isolate flex min-h-0 flex-1 flex-col">
                  <MapBoundary>
                    <MapView />
                  </MapBoundary>
                  <SummaryChip />
                  {deficit ? <DeficitMapPane /> : null}
                </div>
              </div>
            </div>

            {store.offline ? <p className="b-offline-note">демо-данные: сервер не отвечает</p> : null}
            {dialogs}
          </div>
        )}
      </MobileProvider>
    </ThemeProvider>
  )
}

/**
 * Телефон. Карта во весь экран, заявки и бригады — в шторке над ней, как
 * в картографических приложениях. Закреплённого почти нет: полоса сверху
 * и ручка шторки с вкладками, всё прочее отдано списку.
 *
 * Шторка стоит в трёх положениях: «внизу» — от неё остаются ручка и вкладки,
 * карта почти во весь экран; «наполовину»; «во весь экран». Прокрутили список
 * вниз — шторка поднимается и закрывает карту, полоса сверху уезжает (правило
 * уходящей шапки: накопление, у верха стоит всегда, прыжок не жест, под открытым
 * листом не двигается). Вернулись к началу списка и потянули ещё — шторка
 * опускается. Смахнули ручку вниз — шторка уходит вниз, и карту видно целиком.
 * Ручку можно тянуть и тыкать. Двигается всё трансформом, текст под пальцем
 * не переверстывается.
 *
 * Внизу — панель разделов (`PhoneNav`): «Диспетчер» — этот экран, остальные
 * открывают свой. В шторке вкладки «Заявки», «Бригады», «Нагрузка» и «Итог
 * дня», у правого края строки — день плана. Нагрузка кладёт свою карту поверх
 * общей. Пересчёт и новая заявка — жёлтый «плюс» в шапке (лист снизу).
 * Закрытая шторкой карта возвращается значком карты в строке вкладок, ручкой
 * шторки и выбором заявки или бригады.
 */
function PhoneScreen({
  datasets,
  onPlan,
  onEvent,
  dialogs,
}: {
  datasets: import('./types').DatasetSummary[]
  onPlan: () => void
  onEvent: (kind: DialogKind) => void
  dialogs: React.ReactNode
}) {
  const store = useStore()
  // Три положения шторки: «внизу» — карта почти во весь экран, видны ручка и вкладки;
  // «наполовину»; «во весь экран». Ручку тянут (шторка идёт за пальцем и доводится
  // до ближайшего положения) или нажимают.
  const [level, setLevel] = useState<'peek' | 'half' | 'full'>('half')
  const [pull, setPull] = useState<number | null>(null)
  const full = level === 'full'
  const setFull = (on: boolean) => setLevel((now) => (on ? 'full' : now === 'full' ? 'half' : now))
  const drag = useRef<{ y: number; base: number; moved: boolean } | null>(null)
  const header = useRef<HTMLDivElement>(null)
  const sheet = useRef<HTMLDivElement>(null)
  // Нагрузка на телефоне — вкладка шторки, а не экран поверх: шапка и шторка живут как обычно.
  const deficit = store.demo === 'deficit'
  const busy = Boolean(store.dialog || store.feedOpen || store.settingsOpen || (store.demo && !deficit) || store.compareOpen || store.simOpen || store.crewSheet)
  const hidden = useAutoHide(busy, header, sheet) && full

  const requests = store.dataset?.requests.length ?? 0
  const engineers = store.dataset?.engineers.length ?? 0

  // Вкладка шторки: нагрузка — раздел `deficit` (адрес /deficit), бригады — панель инженеров
  // (в ней же маршрут открытой бригады), итог дня — числа плана, заявки — всё прочее.
  type Tab = 'requests' | 'engineers' | 'deficit' | 'metrics'
  const tab: Tab = deficit ? 'deficit' : store.phoneTab === 'metrics' ? 'metrics' : store.panelOpen ? 'engineers' : 'requests'
  const pick = (next: Tab) => {
    if (next === tab && !store.crewView) return
    if (next === 'deficit') {
      store.setDemo('deficit')
      return
    }
    if (deficit) store.setDemo(null)
    if (store.crewView) store.openCrew(null)
    if (next === 'metrics') store.setPhoneTab('metrics')
    else {
      store.setPanelOpen(next === 'engineers')
      store.setPhoneTab(next)
    }
  }

  // Прокрутка списка управляет шторкой: вниз — во весь экран, вверх у начала — наполовину.
  useEffect(() => {
    const node = sheet.current
    if (!node) return
    let run = 0
    const last = new WeakMap<EventTarget, number>()
    const onScroll = (event: Event) => {
      const el = event.target as HTMLElement
      if (!(el instanceof HTMLElement) || busy) return
      const y = el.scrollTop
      const delta = y - (last.get(el) ?? y)
      last.set(el, y)
      if (Math.abs(delta) > 240) return
      run = Math.sign(delta) === Math.sign(run) ? run + delta : delta
      if (run > 8 && y > 0) setLevel('full')
    }
    let touchY: number | null = null
    const onTouchStart = (e: TouchEvent) => (touchY = e.touches[0]?.clientY ?? null)
    const onTouchMove = (e: TouchEvent) => {
      const list = (e.target as HTMLElement).closest('.b-cb, .b-psheet-body') as HTMLElement | null
      if (touchY === null || !list || list.scrollTop > 0) return
      if ((e.touches[0]?.clientY ?? 0) - touchY > 40) setFull(false)
    }
    const onWheel = (e: WheelEvent) => {
      const list = (e.target as HTMLElement).closest('.b-cb, .b-psheet-body') as HTMLElement | null
      if (list && list.scrollTop <= 0 && e.deltaY < -20) setFull(false)
    }
    node.addEventListener('scroll', onScroll, true)
    node.addEventListener('touchstart', onTouchStart, { passive: true })
    node.addEventListener('touchmove', onTouchMove, { passive: true })
    node.addEventListener('wheel', onWheel, { passive: true })
    return () => {
      node.removeEventListener('scroll', onScroll, true)
      node.removeEventListener('touchstart', onTouchStart)
      node.removeEventListener('touchmove', onTouchMove)
      node.removeEventListener('wheel', onWheel)
    }
  }, [busy])

  const TOP = 48
  const HANDLE = 52 // ручка и ряд вкладок: то, что остаётся от шторки внизу
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight
  // Нижняя панель разделов: шторка стоит над ней. Высота с учётом полосы «домой» у iPhone
  // известна только после отрисовки — её меряет сама панель.
  const [nav, setNav] = useState(56)
  const navRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const node = navRef.current
    if (!node) return
    const measure = () => setNav(node.offsetHeight || 56)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  const bottom = vh - nav
  const offsetOf = (at: 'peek' | 'half' | 'full') =>
    at === 'full' ? (hidden ? 0 : TOP) : at === 'half' ? TOP + Math.round(Math.min(320, (bottom - TOP) * 0.45)) : bottom - HANDLE

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    drag.current = { y: event.clientY, base: offsetOf(level), moved: false }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = drag.current
    if (!start) return
    const dy = event.clientY - start.y
    if (Math.abs(dy) > 6) start.moved = true
    if (start.moved) setPull(Math.max(0, Math.min(bottom - HANDLE, start.base + dy)))
  }
  const onPointerUp = () => {
    const start = drag.current
    drag.current = null
    if (!start) return
    if (!start.moved) {
      // Нажатие: снизу — наполовину, наполовину — во весь экран, оттуда — обратно к карте.
      setLevel(level === 'peek' ? 'half' : level === 'half' ? 'full' : 'half')
    } else if (pull !== null) {
      const order = ['full', 'half', 'peek'] as const
      const near = order.reduce((best, at) => (Math.abs(offsetOf(at) - pull) < Math.abs(offsetOf(best) - pull) ? at : best))
      const moved = pull - start.base
      // Смахнули уверенно — на положение дальше, даже если до него не дотянули.
      const step = Math.abs(moved) > 60 && near === level ? order[Math.max(0, Math.min(2, order.indexOf(level) + Math.sign(moved)))] : near
      setLevel(step)
    }
    setPull(null)
  }

  // «Ткнуть на карте» из «плюса» в шапке — шторка открывает карту.
  const dropping = store.dropping
  useEffect(() => {
    if (dropping) setLevel((now) => (now === 'full' ? 'half' : now))
  }, [dropping])

  // Выбрали заявку или бригаду — ответ рисует карта: шторка её открывает.
  const focusSeed = store.focus.seed
  useEffect(() => {
    if (focusSeed > 0 && store.focus.kind !== 'none') setLevel((now) => (now === 'full' ? 'half' : now))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSeed])

  const offset = pull ?? offsetOf(level)
  // Пока шторку тянут, карта стоит в полный рост и просто открывается из-под неё:
  // менять ей размер на каждом кадре незачем. Размер меняется один раз, когда шторка встала.
  const mapHeight = Math.max(120, offsetOf(pull !== null ? 'peek' : level === 'full' ? 'half' : level) - TOP)

  return (
    <div className="b-app b-phone">
      <div ref={header} className={`b-phone-top${hidden ? ' away' : ''}`}>
        <TopBar datasets={datasets} phone onPlan={onPlan} onEvent={onEvent} onSimulate={() => store.setSimOpen(true)} />
      </div>

      <div className="b-phone-map" style={{ top: TOP, height: mapHeight }}>
        <MapBoundary>
          <MapView />
        </MapBoundary>
        {deficit ? <DeficitMapPane /> : null}
      </div>

      <div
        ref={sheet}
        className={`b-psheet${full ? ' full' : ''}${pull !== null ? ' drag' : ''}`}
        style={{ transform: `translateY(${offset}px)` }}
      >
        <div
          className="b-grabzone"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          role="button"
          aria-label={level === 'full' ? 'Показать карту' : level === 'half' ? 'Развернуть список' : 'Поднять список'}
        >
          <div className="b-grab" />
        </div>

        {/* Вкладки «Диспетчера»: что в шторке. День плана — календарём у правого края строки. */}
        <div className="b-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'requests'} onClick={() => pick('requests')}>
            Заявки<em>{requests}</em>
          </button>
          <button type="button" role="tab" aria-selected={tab === 'engineers'} onClick={() => pick('engineers')}>
            Бригады<em>{engineers}</em>
          </button>
          <button type="button" role="tab" aria-selected={tab === 'deficit'} disabled={!store.plan} onClick={() => pick('deficit')}>
            Нагрузка
          </button>
          <button type="button" role="tab" aria-selected={tab === 'metrics'} onClick={() => pick('metrics')}>
            Итог дня
          </button>
          <span className="b-tabs-end">
            {/* Дорога к карте видна всегда: шторка, закрывшая карту, иначе выглядит экраном без карты. */}
            {full ? (
              <button type="button" className="b-tabs-map" onClick={() => setFull(false)} aria-label="Показать карту" title="Показать карту">
                <IconMap />
              </button>
            ) : null}
            <DayPicker />
          </span>
        </div>

        <div className="b-psheet-body" style={{ height: `calc(100dvh - ${offset}px - 52px - ${nav}px)` }}>
          {tab === 'deficit' ? <DeficitPanel /> : null}
          {tab === 'requests' || (tab === 'engineers' && store.crewView) ? <RequestList compact /> : null}
          {tab === 'engineers' && !store.crewView ? <EngineerPanel /> : null}
          {tab === 'metrics' ? (
            <div className="b-psheet-scroll b-daygrid">
              <MetricsBar bare />
            </div>
          ) : null}
        </div>
      </div>

      {/* Телефон: детали заявки и бригады — нижней шторкой поверх экрана; на широком — справа в карте. */}
      <DetailSheet placement="phone" />

      <div ref={navRef} className="b-pnav-wrap">
        <PhoneNav />
      </div>

      {dialogs}
    </div>
  )
}
