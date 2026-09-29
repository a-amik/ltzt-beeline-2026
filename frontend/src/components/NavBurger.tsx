/**
 * Бургер — навигация по страницам раздела на телефоне: в «О проекте» — страницы
 * и главы открытой, в «Настройках» — группы. Стоит в шапке раздела рядом с «…»:
 * колонки страниц на телефоне нет, а строка вкладок или выпадающий список
 * отнимали место у содержимого. Текущий пункт отмечен.
 */

import { Button, DropdownMenu } from '@gravity-ui/uikit'
import { IconMenu } from '../lib/icons'

export interface NavItem {
  text: string
  selected?: boolean
  action: () => void
}

export default function NavBurger({ label, groups }: { label: string; groups: NavItem[][] }) {
  return (
    <DropdownMenu
      size="l"
      popupProps={{ placement: ['bottom-end', 'bottom'] }}
      renderSwitcher={(props) => (
        <Button {...props} view="flat" size="m" title={label} aria-label={label}>
          <IconMenu />
        </Button>
      )}
      items={groups.filter((g) => g.length).map((group) => group.map((item) => ({
        text: item.text,
        selected: item.selected,
        action: item.action,
      })))}
    />
  )
}
