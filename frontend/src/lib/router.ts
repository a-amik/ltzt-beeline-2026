/**
 * Адрес следует за разделом, раздел — за адресом, как на транспортном стенде:
 * ссылкой можно поделиться, «назад» и «вперёд» браузера возвращают раздел.
 *
 *   /                    заявки (по умолчанию)      /deficit     дефицит
 *   /engineers           инженеры                   /sim         имитация: гонка трёх планов
 *   /live                живой день (/control — старый адрес)   /about/…     «О проекте» и его страница
 *                                                              (/reports/… — старый адрес)
 *   /simulation          тест одного дня — прежняя форма имитации
 *   /settings            настройки (старая ссылка /rules тоже открывает их)
 *   /versions            версии дня из «…»; /compare — пересчёт сравнения
 *
 * Набор и участок — в запросе: `?set=vostok`, `?sector=yugocentr`; набор по
 * умолчанию («Вся Москва») в адрес не пишется. Смена раздела — новая запись
 * истории, смена набора или участка — замена текущей: это фильтр, а не переход.
 * Приложения бригады и руководителя живут в `#crew/…` и `#manager` — их адрес
 * здесь не трогается.
 */

import { useStore, type ReportPage, type State } from '../store'

const DEFAULT_SET = 'moskva'
const PAGES: ReportPage[] = ['solution', 'design', 'models', 'method', 'settings', 'ops']

type Screen =
  | 'requests' | 'engineers' | 'deficit' | 'simulation' | 'live' | 'sim'
  | 'reports' | 'versions' | 'settings' | 'compare'

function screenOf(s: State): Screen {
  if (s.demo === 'deficit') return 'deficit'
  if (s.demo === 'compare') return 'live'
  if (s.demo === 'race') return 'sim'
  if (s.demo === 'reports') return 'reports'
  if (s.demo === 'versions') return 'versions'
  if (s.simOpen) return 'simulation'
  if (s.settingsOpen) return 'settings'
  if (s.compareOpen) return 'compare'
  return s.panelOpen ? 'engineers' : 'requests'
}

function pathOf(s: State): string {
  const screen = screenOf(s)
  if (screen === 'requests') return '/'
  if (screen === 'reports') return `/about/${s.reportPage}`
  return `/${screen}`
}

function queryOf(s: State): string {
  const q = new URLSearchParams()
  if (s.datasetId !== DEFAULT_SET) q.set('set', s.datasetId)
  if (s.sector) q.set('sector', s.sector)
  const text = q.toString()
  return text ? `?${text}` : ''
}

/** Состояние по адресу: раздел, страница отчётов, набор и участок. */
function apply(): void {
  const st = useStore.getState()
  const [, head = '', page = ''] = location.pathname.split('/')
  const q = new URLSearchParams(location.search)
  const set = q.get('set') || DEFAULT_SET
  if (set !== st.datasetId) st.setDatasetId(set)
  const sector = q.get('sector')
  if (sector !== useStore.getState().sector) useStore.getState().setSector(sector)

  const now = useStore.getState()
  now.setDemo(null)
  now.setSimOpen(false)
  now.setSettingsOpen(false)
  now.setCompareOpen(false)
  now.setFeedOpen(false)
  if (head === 'engineers') now.setPanelOpen(true)
  else if (head === '' || head === 'requests') now.setPanelOpen(false)
  if (head === 'deficit') now.setDemo('deficit')
  if (head === 'live' || head === 'control') now.setDemo('compare')
  if (head === 'sim') now.setDemo('race')
  if (head === 'versions') now.setDemo('versions')
  if (head === 'simulation') now.setSimOpen(true)
  if (head === 'settings' || head === 'rules') now.setSettingsOpen(true)
  if (head === 'compare') now.setCompareOpen(true)
  // «О проекте» — /about; прежний адрес /reports открывает то же, чтобы розданные ссылки не ломались.
  if (head === 'about' || head === 'reports') {
    if (PAGES.includes(page as ReportPage)) now.setReportPage(page as ReportPage)
    now.setDemo('reports')
  }
}

let started = false

export function startRouter(): void {
  if (started || location.hash.startsWith('#crew') || location.hash.startsWith('#manager')) return
  started = true
  apply()
  let path = pathOf(useStore.getState())
  let query = queryOf(useStore.getState())
  history.replaceState(history.state, '', path + query + location.hash)

  useStore.subscribe((s) => {
    const nextPath = pathOf(s)
    const nextQuery = queryOf(s)
    if (nextPath === path && nextQuery === query) return
    const push = nextPath !== path
    path = nextPath
    query = nextQuery
    if (location.pathname + location.search === path + query) return
    if (push) history.pushState(null, '', path + query)
    else history.replaceState(history.state, '', path + query)
  })

  window.addEventListener('popstate', () => {
    apply()
    path = pathOf(useStore.getState())
    query = queryOf(useStore.getState())
  })
}
