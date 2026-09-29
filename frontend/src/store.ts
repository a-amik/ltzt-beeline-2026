/**
 * Состояние экрана. Два плана живут рядом — прежний и нынешний, — потому что
 * переключатель «До события / После» показывает не пересчёт, а два готовых
 * ответа.
 *
 * Куда смотрит карта, решает не выбор сам по себе, а названное движение:
 * `focus` отдаёт карте приказ вместе с номером, и по смене номера она
 * его исполняет. Иначе выбор заявки, который заодно выбирает инженера,
 * приводил бы карту в два места разом.
 */

import { create } from 'zustand'
import type { Comparison, Dataset, Plan, PlanEvent, ReplanVariant, Settings } from './types'

export type Theme = 'light' | 'dark'
export type View = 'before' | 'after'
export type DialogKind = 'urgent' | 'new_request' | 'cancel' | 'no_show' | 'reschedule' | 'delay' | 'engineer_off'
export type PhoneTab = 'requests' | 'engineers' | 'metrics'
/** Ручной приоритет заявки: обычный уровень не хранится. */
export type RequestPriority = 'urgent' | 'high' | 'low'

export type DemoKind = 'compare' | 'race' | 'deficit' | 'versions' | 'reports'
export type ReportPage = 'solution' | 'design' | 'models' | 'method' | 'settings' | 'ops' | 'mileage'
export type FocusKind = 'none' | 'all' | 'engineer' | 'request'

/** Загрузка своего файла: `upload` — сервер разбирает файл, `plan` — строится первый план. */
export interface Importing {
  name: string
  rows: number
  stage: 'upload' | 'plan'
  datasetId?: string
  /** Что вышло из файла: заявки, бригады, факт. */
  facts?: string
}

export interface MapFocus {
  kind: FocusKind
  id: string | null
  seed: number
}

export interface State {
  datasetId: string
  /** Фильтр участка в наборе «Вся Москва»: null — все участки. */
  sector: string | null
  /** Страница раздела «О проекте»: она же в адресе (`/about/<страница>`). */
  reportPage: ReportPage
  dataset: Dataset | null
  plan: Plan | null
  previousPlan: Plan | null
  baselinePlan: Plan | null
  selectedRequestId: string | null
  selectedEngineerId: string | null
  /** Бригада, чьи детали открыты слева: список заявок сужается до её маршрута. */
  crewView: string | null
  /** Открыта ли лента от бригад. */
  feedOpen: boolean
  /** Телефон: шторка с деталями бригады поверх экрана. */
  crewSheet: boolean
  setCrewSheet: (open: boolean) => void
  view: View
  theme: Theme
  /** Поиск по номеру и адресу — одно поле над списком. */
  search: string
  /** Сервер не ответил — интерфейс живёт на демо-данных. */
  offline: boolean
  planning: boolean
  dialog: DialogKind | null
  compareOpen: boolean
  simOpen: boolean
  demo: DemoKind | null
  /** Подхватывать ли «последний план» с сервера: выключено, пока открыт план имитации. */
  followLatest: boolean
  /** Что стоит в левой панели на широком экране: заявки или инженеры (`true`). */
  panelOpen: boolean
  /** Левая панель развёрнута; свёрнутая отдаёт место карте. */
  sideOpen: boolean
  phoneTab: PhoneTab
  /** Короткое уведомление поверх карты. */
  notice: string | null
  /** Заголовок уведомления; нет — «Пока нельзя». */
  noticeTitle: string | null
  /** Свой файл грузится: разбор на сервере, затем первый план нового набора. */
  importing: Importing | null
  /** Ждём тычка по карте: диалог срочной заявки просит координаты. */
  picking: boolean
  pickedPoint: { lat: number; lon: number } | null
  /** Меняется с каждым новым планом — по нему карта перечерчивает маршруты. */
  drawSeed: number
  focus: MapFocus
  /**
   * Оперативное диспетчера, которое уходит с запросом плана: ручной приоритет
   * заявок (`requests`). Общих правил здесь нет — их задаёт руководитель,
   * и сервер ставит их под расчёт сам (`rules`).
   */
  settings: Settings
  /** Общие правила дня с сервера (`GET /rules`) — только для чтения на этом экране. */
  rules: Settings
  rulesVersion: number | null
  settingsOpen: boolean
  /** Сравнение с контрольным распределением и базовым вариантом. */
  comparison: Comparison | null
  /**
   * Пачка событий, сохранённых диспетчером и ещё не принятых. План дня
   * от них не меняется: сервер считает по ним варианты в фоне, а план
   * становится другим, только когда вариант приняли.
   */
  drafts: PlanEvent[]
  /** Варианты ответа на пачку; `null` — ещё считаются или пачки нет. */
  variants: ReplanVariant[] | null
  /** Какой вариант сейчас показан на карте вместо плана дня. */
  preview: ReplanVariant['key'] | null
  /** Режим вброса: каждый тычок по карте ставит новую заявку в эту точку. */
  dropping: boolean
  /** Сервер сейчас примеряет пачку: булавки на карте пульсируют. */
  crunching: boolean
  /** Час, от которого считаются новые события: последний названный диспетчером. */
  clock: string

  setDatasetId: (id: string) => void
  setSector: (sector: string | null) => void
  setReportPage: (page: ReportPage) => void
  setDataset: (dataset: Dataset | null) => void
  setPlan: (plan: Plan) => void
  applyReplan: (plan: Plan) => void
  setBaseline: (plan: Plan | null) => void
  selectRequest: (id: string | null) => void
  selectEngineer: (id: string | null) => void
  /** Открыть детали бригады (или закрыть — `null`). */
  openCrew: (id: string | null) => void
  setFeedOpen: (open: boolean) => void
  /** Ручной приоритет заявки: уходит в настройки плана (`settings.requests`). */
  setRequestPriority: (id: string, level: RequestPriority | null) => void
  setView: (view: View) => void
  setSearch: (search: string) => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  setOffline: (offline: boolean) => void
  setPlanning: (planning: boolean) => void
  openDialog: (kind: DialogKind | null) => void
  setCompareOpen: (open: boolean) => void
  setSimOpen: (open: boolean) => void
  setDemo: (demo: DemoKind | null) => void
  /** Показать план другой ветки дня, не делая его текущим для сервера. */
  showPlan: (plan: Plan) => void
  setPanelOpen: (open: boolean) => void
  setSideOpen: (open: boolean) => void
  setPhoneTab: (tab: PhoneTab) => void
  notify: (notice: string | null, title?: string) => void
  setImporting: (importing: Importing | null) => void
  setPicking: (picking: boolean) => void
  setPickedPoint: (point: { lat: number; lon: number } | null) => void
  focusAll: () => void
  focusEngineer: (id: string) => void
  focusRequest: (id: string) => void
  setSettings: (settings: Settings) => void
  setRules: (rules: Settings, version: number) => void
  setSettingsOpen: (open: boolean) => void
  setComparison: (comparison: Comparison | null) => void
  addDraft: (event: PlanEvent) => void
  removeDraft: (id: string) => void
  clearDrafts: () => void
  setVariants: (variants: ReplanVariant[] | null) => void
  setPreview: (key: ReplanVariant['key'] | null) => void
  setDropping: (dropping: boolean) => void
  setCrunching: (crunching: boolean) => void
}

const THEME_KEY = 'b-theme'
const SETTINGS_KEY = 'b-settings'

/**
 * Из браузера поднимается только оперативное — ручной приоритет заявок.
 * Правила и тарифы, сохранённые здесь до 25.09.2026, когда их ещё правил
 * диспетчер, отбрасываются: теперь их задаёт руководитель.
 */
function initialSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    const saved = raw ? (JSON.parse(raw) as Settings) : {}
    return saved.requests && typeof saved.requests === 'object' ? { requests: saved.requests } : {}
  } catch {
    return {}
  }
}

export function initialTheme(): Theme {
  if (typeof window === 'undefined') return 'light'
  const saved = window.localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Приватное окно — тема просто не запомнится.
  }
}

export const useStore = create<State>((set, get) => ({
  // По умолчанию — вся Москва: диспетчер видит все участки и фильтрует нужный.
  datasetId: 'moskva',
  sector: null,
  reportPage: 'solution',
  dataset: null,
  plan: null,
  previousPlan: null,
  baselinePlan: null,
  selectedRequestId: null,
  selectedEngineerId: null,
  crewView: null,
  feedOpen: false,
  crewSheet: false,
  setCrewSheet: (crewSheet) => set({ crewSheet }),
  view: 'after',
  theme: initialTheme(),
  search: '',
  offline: false,
  planning: false,
  dialog: null,
  compareOpen: false,
  simOpen: false,
  demo: null,
  followLatest: true,
  panelOpen: false,
  sideOpen: true,
  phoneTab: 'requests',
  notice: null,
  noticeTitle: null,
  importing: null,
  picking: false,
  pickedPoint: null,
  drawSeed: 0,
  focus: { kind: 'none', id: null, seed: 0 },
  settings: initialSettings(),
  rules: {},
  rulesVersion: null,
  settingsOpen: false,
  comparison: null,
  drafts: [],
  variants: null,
  preview: null,
  dropping: false,
  crunching: false,
  clock: '12:30',

  setDatasetId: (datasetId) =>
    set((s) => ({
      datasetId,
      sector: null,
      plan: null,
      previousPlan: null,
      baselinePlan: null,
      selectedRequestId: null,
      selectedEngineerId: null,
      view: 'after',
      search: '',
      comparison: null,
      drafts: [],
      variants: null,
      preview: null,
      dropping: false,
      focus: { kind: 'all', id: null, seed: s.focus.seed + 1 },
    })),
  setDataset: (dataset) => set({ dataset }),
  setReportPage: (reportPage) => set({ reportPage }),
  setSector: (sector) => set((s) => ({ sector, focus: { kind: 'all', id: null, seed: s.focus.seed + 1 } })),
  setPlan: (plan) =>
    set((s) => ({
      plan,
      previousPlan: null,
      baselinePlan: null,
      followLatest: true,
      view: 'after',
      drawSeed: s.drawSeed + 1,
      focus: { kind: 'all', id: null, seed: s.focus.seed + 1 },
    })),
  applyReplan: (plan) =>
    set((s) => ({
      plan,
      previousPlan: s.plan,
      view: 'after',
      drawSeed: s.drawSeed + 1,
      focus: { kind: 'all', id: null, seed: s.focus.seed + 1 },
    })),
  setBaseline: (baselinePlan) => set({ baselinePlan }),
  selectRequest: (selectedRequestId) => set({ selectedRequestId }),
  selectEngineer: (selectedEngineerId) => set({ selectedEngineerId }),
  openCrew: (crewView) =>
    set((s) => ({
      crewView,
      selectedEngineerId: crewView,
      selectedRequestId: crewView ? null : s.selectedRequestId,
      search: crewView ? '' : s.search,
      phoneTab: crewView ? 'requests' : s.phoneTab,
      // Детали раскрываются в панели инженеров: её надо показать и развернуть.
      panelOpen: crewView ? true : s.panelOpen,
      sideOpen: crewView ? true : s.sideOpen,
      crewSheet: Boolean(crewView),
      focus: crewView ? { kind: 'engineer', id: crewView, seed: s.focus.seed + 1 } : { kind: 'all', id: null, seed: s.focus.seed + 1 },
    })),
  setFeedOpen: (feedOpen) => set({ feedOpen }),
  setRequestPriority: (id, level) => {
    const current = get().settings
    const own = { ...((current.requests as Record<string, { priority: RequestPriority }> | undefined) ?? {}) }
    if (level) own[id] = { priority: level }
    else delete own[id]
    get().setSettings({ ...current, requests: own })
  },
  setView: (view) => set({ view, drawSeed: get().drawSeed + 1 }),
  setSearch: (search) => set({ search }),
  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  setOffline: (offline) => set({ offline }),
  setPlanning: (planning) => set({ planning }),
  openDialog: (dialog) => set({ dialog, picking: false, pickedPoint: null }),
  setCompareOpen: (compareOpen) => set({ compareOpen }),
  setSimOpen: (simOpen) => set({ simOpen }),
  setDemo: (demo) => set({ demo }),
  showPlan: (plan) =>
    set((s) => ({
      plan,
      previousPlan: null,
      followLatest: false,
      view: 'after',
      selectedRequestId: null,
      selectedEngineerId: null,
      drawSeed: s.drawSeed + 1,
      focus: { kind: 'all', id: null, seed: s.focus.seed + 1 },
    })),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  setSideOpen: (sideOpen) => set({ sideOpen }),
  setPhoneTab: (phoneTab) => set({ phoneTab }),
  notify: (notice, title) => set({ notice, noticeTitle: title ?? null }),
  setImporting: (importing) => set({ importing }),
  setPicking: (picking) => set({ picking }),
  setPickedPoint: (pickedPoint) => set({ pickedPoint, picking: false }),
  focusAll: () => set((s) => ({ focus: { kind: 'all', id: null, seed: s.focus.seed + 1 } })),
  focusEngineer: (id) =>
    set((s) => ({ focus: { kind: 'engineer', id, seed: s.focus.seed + 1 } })),
  focusRequest: (id) => set((s) => ({ focus: { kind: 'request', id, seed: s.focus.seed + 1 } })),
  setSettings: (settings) => {
    try {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
    } catch {
      // приватное окно — настройки проживут до перезагрузки
    }
    set({ settings, comparison: null })
  },
  setRules: (rules, rulesVersion) => set({ rules, rulesVersion }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setComparison: (comparison) => set({ comparison }),
  addDraft: (event) =>
    set((s) => ({ drafts: [...s.drafts, event], variants: null, preview: null, clock: event.time, drawSeed: s.drawSeed + 1 })),
  removeDraft: (id) =>
    set((s) => ({ drafts: s.drafts.filter((item) => item.id !== id), variants: null, preview: null, drawSeed: s.drawSeed + 1 })),
  clearDrafts: () => set((s) => ({ drafts: [], variants: null, preview: null, dropping: false, crunching: false, drawSeed: s.drawSeed + 1 })),
  setVariants: (variants) => set({ variants }),
  setPreview: (preview) => set((s) => ({ preview, drawSeed: s.drawSeed + 1 })),
  setDropping: (dropping) => set({ dropping, picking: false }),
  setCrunching: (crunching) => set({ crunching }),
}))

/** План, который сейчас на экране: «До события» показывает прежний ответ. */
export function activePlan(state: State): Plan | null {
  if (state.preview && state.variants) {
    const shown = state.variants.find((item) => item.key === state.preview)
    if (shown) return shown.plan
  }
  if (state.view === 'before' && state.previousPlan) return state.previousPlan
  return state.plan
}
