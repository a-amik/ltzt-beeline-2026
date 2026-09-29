/**
 * Колонка разделов слева во всю высоту экрана, как в диспетчерских
 * транспорта; знак бренда — в её верхней ячейке. Сверху — то, чем
 * диспетчер ведёт день: заявки, инженеры, дефицит. Снизу первыми — два
 * показа, как на транспортном стенде: живой день (контроль и наш план на двух
 * картах) и имитация (гонка трёх планов на одних событиях); под чертой —
 * отчёты о решении и настройки расчёта.
 * Прежняя форма имитации — тест одного дня — открывается кнопками в шапках
 * этих экранов, отдельного раздела у неё нет.
 *
 * Лента от бригад — колокольчиком в шапке; версии дня, правила расчёта,
 * приложения бригады и руководителя, тема — в меню «…» шапки: это работа
 * супервайзера и технические переходы, а не разделы диспетчера.
 *
 * «Заявки» и «Инженеры» выбирают, что стоит в левой панели; нажатие на
 * выбранный сворачивает панель. Остальные разделы — окна и экраны, которые
 * открываются справа от колонки; колонка стоит над ними, и из одного раздела
 * переходят в другой, не закрывая первый. Нажали на открытый — он закрылся.
 *
 * На телефоне разделы стоят нижней панелью (`PhoneNav`): «Диспетчер» — карта
 * со шторкой, где «Заявки», «Бригады» и «Нагрузка» — вкладки; остальные —
 * экраны между шапкой и панелью, без крестиков: уходят из них панелью.
 */

import { activePlan, useStore, type DemoKind } from '../store'
import { IconGauge, IconFlask, IconInfo, IconPlay, IconRoute, IconSliders, IconUsers } from '../lib/icons'

type Section = 'plan' | 'engineers' | 'settings' | DemoKind

interface Item {
  key: Section
  label: string
  /** Подпись в нижней панели телефона, если короче нужна своя. */
  short?: string
  title: string
  icon: React.ReactNode
  needsPlan?: boolean
}

/** Закрыть всё, что открыто поверх рабочего экрана. */
export const closeOverlays = () => {
  const s = useStore.getState()
  s.setDemo(null)
  s.setSimOpen(false)
  s.setCompareOpen(false)
  s.setSettingsOpen(false)
  s.setFeedOpen(false)
}

const open = (key: Section) => {
  const s = useStore.getState()
  if (key === 'settings') s.setSettingsOpen(true)
  else if (key !== 'plan' && key !== 'engineers') s.setDemo(key)
}

const MAIN: Item[] = [
  { key: 'plan', label: 'Заявки', title: 'Заявки дня: список, поиск, карточка', icon: <IconRoute /> },
  { key: 'engineers', label: 'Инженеры', title: 'Инженеры: ленты дня бригад, маршрут по адресам', icon: <IconUsers /> },
  { key: 'deficit', label: 'Нагрузка', title: 'Нагрузка бригад по окнам и районам: где спрос выше, чем могут закрыть бригады, и где они свободны', icon: <IconGauge />, needsPlan: true },
]

const LOWER: Item[] = [
  { key: 'compare', label: 'Живой день', title: 'Живой день: контрольное распределение и наш план на двух картах, с событиями дня', icon: <IconPlay />, needsPlan: true },
  { key: 'race', label: 'Имитация', title: 'Имитация: контроль, базовый и наш план на одних событиях — 20 прогонов дня на участок', icon: <IconFlask /> },
]

// Под чертой: отчёты о решении и настройки расчёта — то, что читают и задают, а не показывают.
const UPPER: Item[] = [
  // «О проекте», а не «Отчёты»: здесь описание решения — как оно устроено и почему, а не отчётность.
  { key: 'reports', label: 'О проекте', title: 'О проекте: как устроено решение, интерфейс, модели, нагрузка и безопасность', icon: <IconInfo /> },
  { key: 'settings', label: 'Настройки', title: 'Настройки расчёта: правила, тарифы, бригады, модель', icon: <IconSliders /> },
]

export default function Rail() {
  const store = useStore()
  const plan = activePlan(store)

  const active: Section | null = store.demo
    ?? (store.simOpen ? null
      : store.compareOpen ? 'reports'
        : store.settingsOpen ? 'settings'
          : store.feedOpen ? null
          : store.panelOpen ? 'engineers' : 'plan')

  const item = (i: Item) => {
    const on = active === i.key
    return (
      <button
        key={i.key}
        type="button"
        className={`b-rail-i${on ? ' on' : ''}`}
        aria-current={on ? 'page' : undefined}
        title={i.title}
        disabled={i.needsPlan && !plan}
        onClick={() => {
          closeOverlays()
          // Заявки и инженеры — содержимое левой панели: выбрать другое — показать его,
          // нажать на показанное — свернуть панель или развернуть обратно.
          if (i.key === 'plan' || i.key === 'engineers') {
            if (on) store.setSideOpen(!store.sideOpen)
            else {
              store.setPanelOpen(i.key === 'engineers')
              store.setSideOpen(true)
            }
          } else if (!on) open(i.key)
        }}
      >
        {i.icon}
        <span>{i.label}</span>
      </button>
    )
  }

  return (
    <nav className="b-rail" aria-label="Разделы">
      {/* Знак ведёт на главную — заявки дня: всё открытое поверх закрывается. */}
      <button
        type="button"
        className="b-rail-brand"
        title="билайн бизнес · Маршрут дня — к заявкам"
        aria-label="Маршрут дня: к заявкам"
        onClick={() => {
          closeOverlays()
          if (store.crewView) store.openCrew(null)
          store.setPanelOpen(false)
          store.setSideOpen(true)
        }}
      >
        <img src="/brand/beeline-logo.svg" alt="" width={24} height={24} />
      </button>
      {MAIN.map(item)}
      <span className="sp" />
      {LOWER.map(item)}
      <hr className="b-rail-hr" />
      {UPPER.map(item)}
    </nav>
  )
}

/** Нагрузка — вкладка «Диспетчера» на телефоне: ушли в другой раздел и вернулись — она снова открыта. */
let phoneDeficit = false

/**
 * Телефон: нижняя панель из пяти разделов. «Диспетчер» — карта со шторкой,
 * в шторке вкладки «Заявки», «Бригады», «Нагрузка» и «Итог дня»; остальные —
 * те же экраны, что в колонке компьютера. Панель не уезжает и не закрывается:
 * крестиков у разделов на телефоне нет, переход — нажатием сюда.
 */
export function PhoneNav() {
  const store = useStore()
  const plan = activePlan(store)
  const active: Section =
    store.demo && store.demo !== 'versions' && store.demo !== 'deficit' ? store.demo
      : store.settingsOpen ? 'settings' : 'plan'

  const go = (key: Section) => {
    if (key === active) return
    if (active === 'plan') phoneDeficit = store.demo === 'deficit'
    closeOverlays()
    if (key === 'plan') {
      if (phoneDeficit && plan) store.setDemo('deficit')
    } else open(key)
  }

  const items: Item[] = [
    { key: 'plan', label: 'Диспетчер', title: 'Заявки, бригады и нагрузка дня на карте', icon: <IconRoute /> },
    ...LOWER,
    ...UPPER,
  ]

  return (
    <nav className="b-pnav" aria-label="Разделы">
      {items.map((i) => {
        const on = active === i.key
        return (
          <button
            key={i.key}
            type="button"
            className={on ? 'on' : ''}
            aria-current={on ? 'page' : undefined}
            aria-label={i.label}
            disabled={i.needsPlan && !plan}
            onClick={() => go(i.key)}
          >
            {i.icon}
            <span>{i.short ?? i.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
