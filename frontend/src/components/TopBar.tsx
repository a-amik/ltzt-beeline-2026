/**
 * Верхняя полоса стоит только над картой: левая колонка раздела поднята
 * во всю высоту, знак — в колонке разделов. У левого края полосы название
 * экрана с днём плана (`DayPicker`), за ним общий поиск (палитра ⌘K),
 * справа набор, «Спланировать» и «Новая заявка», у правого
 * края — колокольчик ленты от бригад и меню «…». Разделы диспетчера
 * и имитации — в колонке слева (`Rail`); в «…» — то, что диспетчеру
 * не нужно каждую минуту: версии дня, правила расчёта (их задаёт
 * супервайзер), приложения бригады и руководителя, тема. На телефоне
 * колонки нет, и в «…» уходят ещё разделы и «Спланировать заново».
 * «До события / После» живёт на карте — это вид карты и метрик, а не команда.
 *
 * Выпадающих окон своей руки на экране нет — DropdownMenu и Sheet берутся
 * у Gravity, и на телефоне они сами открываются листом снизу.
 */

import { useState } from 'react'
import { Button, DropdownMenu, Menu, Sheet } from '@gravity-ui/uikit'
import { FeedButton } from '../dispatch/FeedPanel'
import type { DatasetSummary } from '../types'
import { useStore, type DialogKind } from '../store'
import {
  IconBolt,
  IconChevron,
  IconCalendar,
  IconPin,
  IconPlay,
  IconPlus,
  IconSearch,
} from '../lib/icons'
import MoreMenu from './MoreMenu'
import DayPicker from './DayPicker'
import { PALETTE_KEY, usePalette } from '../lib/hotkeys'


interface Props {
  /** Список наборов: «…» берёт его из кэша запросов сам. */
  datasets?: DatasetSummary[]
  phone: boolean
  onPlan: () => void
  onEvent: (kind: DialogKind) => void
  onSimulate?: () => void
}

export default function TopBar({ phone, onPlan, onEvent, onSimulate }: Props) {
  const store = useStore()
  const hasPlan = Boolean(store.plan)
  const selectedId = store.selectedRequestId

  if (phone) {
    return (
      <header className="b-top">
        {/* Знак и имя бренда — как в приложении бригады и у руководителя: «билайн бизнес» строчными. */}
        <span className="b-brand" title="билайн бизнес · Маршрут дня">
          <img src="/brand/beeline-logo.svg" alt="" width={24} height={24} />
          <b>билайн бизнес</b>
        </span>
        {/* «Плюс» — пересчёт дня и новая заявка; день плана — календарём в строке вкладок шторки. */}
        <span className="ml-auto flex min-w-0 items-center gap-1">
          <EventMenu hasPlan={hasPlan} selectedId={selectedId} onEvent={onEvent} phone onPlan={onPlan} />
          <FeedButton size="m" />
          <MoreMenu phone onPlan={onPlan} onSimulate={onSimulate} />
        </span>
      </header>
    )
  }

  return (
    <header className="b-top">
      <div className="b-top-cell m">
        {/* День плана и общий поиск — первыми; набора в шапке нет: участок выбирают
            фильтром в колонке, свой файл — пунктом в «…». */}
        {store.sideOpen ? null : <DayPicker />}
        <button type="button" className="b-top-search" onClick={() => usePalette.getState().setOpen(true)} title={`Поиск по заявкам, инженерам, районам и командам (${PALETTE_KEY})`}>
          <IconSearch />
          <span>Поиск</span>
          <kbd>{PALETTE_KEY}</kbd>
        </button>
        <span className="flex-1" />
        <Button view="action" size="l" onClick={onPlan} disabled={store.planning}>
          {store.planning ? 'Считаем…' : 'Спланировать'}
        </Button>
        <EventMenu hasPlan={hasPlan} selectedId={selectedId} onEvent={onEvent} />
        <span className="b-top-tools">
          <FeedButton />
          <MoreMenu phone={false} onPlan={onPlan} onSimulate={onSimulate} />
        </span>
      </div>
    </header>
  )
}

/**
 * Меню новой заявки. Здесь только то, что не привязано ни к чему на экране:
 * заявка по форме, срочная заявка и вброс тычком по карте. События, которые
 * случаются с выбранной заявкой или бригадой, — отмена, перенос окна, клиента
 * нет, задержка, выбытие, — стоят в карточке заявки и в шапке колонки бригад:
 * выбирать предмет в одном месте, а действие искать в другом неудобно.
 *
 * На телефоне меню открывается листом снизу: окно под пальцем у верхнего
 * края экрана не достать. Своего выпадающего окна при этом не заводится —
 * и лист, и меню в нём берутся у Gravity, потому что `DropdownMenu`
 * листом снизу не умеет, а `Sheet` с `Menu` внутри — ровно то же самое.
 */
interface EventItem {
  key: string
  text: string
  hint: string | null
  icon: React.ReactNode
  disabled: boolean
  danger: boolean
  title?: string
  act: () => void
}

export function EventMenu({
  hasPlan,
  onEvent,
  size = 'l',
  phone = false,
  onPlan,
}: {
  hasPlan: boolean
  selectedId?: string | null
  onEvent: (kind: DialogKind) => void
  size?: 'm' | 'l'
  phone?: boolean
  /** Телефон: пересчёт дня — первым пунктом того же листа, что и новая заявка. */
  onPlan?: () => void
}) {
  const [open, setOpen] = useState(false)
  const planning = useStore((s) => s.planning)

  const items: EventItem[] = [
    ...(phone && onPlan
      ? [{
          key: 'plan',
          text: planning ? 'Считаем…' : 'Спланировать заново',
          hint: null,
          icon: <IconPlay />,
          disabled: planning,
          danger: false,
          act: onPlan,
        }]
      : []),
    {
      key: 'new',
      text: 'Заявка день в день',
      hint: null,
      icon: <IconCalendar />,
      disabled: false,
      danger: false,
      act: () => onEvent('new_request'),
    },
    {
      key: 'urgent',
      text: 'Срочная заявка',
      hint: null,
      icon: <IconBolt />,
      disabled: false,
      danger: false,
      act: () => onEvent('urgent'),
    },
    {
      key: 'drop',
      text: 'Ткнуть на карте',
      hint: null,
      icon: <IconPin />,
      disabled: false,
      danger: false,
      title: 'Каждый тычок по карте — новая заявка в этой точке',
      act: () => useStore.getState().setDropping(true),
    },
  ]

  const hint = (text: string) => <span className="pl-4 text-[var(--b-text-3)]">{text}</span>

  const switcher = (props: object = {}) => (
    <Button {...props} view="outlined" size={size} disabled={!hasPlan}>
      <span className="flex items-center gap-1.5">
        <IconPlus className="b-ev-plus" />
        <span className="b-ev-text">Новая заявка</span>
        <IconChevron />
      </span>
    </Button>
  )

  if (phone) {
    const item = (entry: EventItem) => (
      <Menu.Item
        key={entry.key}
        iconStart={entry.icon}
        iconEnd={entry.hint ? hint(entry.hint) : null}
        disabled={entry.disabled || (entry.key !== 'plan' && !hasPlan)}
        theme={entry.danger ? 'danger' : 'normal'}
        title={entry.title}
        onClick={() => {
          setOpen(false)
          entry.act()
        }}
      >
        {entry.text}
      </Menu.Item>
    )
    return (
      <>
        {/* На телефоне — жёлтый «плюс» в шапке; пересчёт в листе доступен и без плана. */}
        <Button view="action" size="m" className="b-plus" onClick={() => setOpen(true)} disabled={!hasPlan && !onPlan}
          title="Спланировать заново или добавить заявку" aria-label="Спланировать заново или добавить заявку">
          <IconPlus />
        </Button>
        <Sheet visible={open} onClose={() => setOpen(false)} title="Добавить">
          <Menu size="xl">
            <Menu.Group>{items.map(item)}</Menu.Group>
          </Menu>
        </Sheet>
      </>
    )
  }

  return (
    <DropdownMenu
      size="l"
      renderSwitcher={switcher}
      items={items.map((entry) => ({
        action: entry.act,
        text: entry.text,
        iconStart: entry.icon,
        disabled: entry.disabled,
        title: entry.title,
      }))}
    />
  )
}
