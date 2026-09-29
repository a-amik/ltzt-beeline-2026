/**
 * Новая заявка и пересчёт на телефоне — кнопка «плюс» на карте с веером действий,
 * как speed dial в Material: нажали — над кнопкой встают действия с подписями, плюс
 * поворачивается в крестик; нажатие мимо или Esc закрывает. Шторка снизу
 * здесь лишняя: действий три, и палец уже в этом углу.
 */

import { useEffect, useState } from 'react'
import { useStore, type DialogKind } from '../store'
import { IconBolt, IconCalendar, IconPin, IconPlay, IconPlus } from '../lib/icons'
import './dispatch.css'

interface Props {
  disabled?: boolean
  onEvent: (kind: DialogKind) => void
  /** Действию нужна карта: шторка должна её открыть. */
  onNeedMap: () => void
  /** Пересчитать день — первым пунктом веера: отдельной кнопки на телефоне нет. */
  onPlan?: () => void
}

export default function SpeedDial({ disabled = false, onEvent, onNeedMap, onPlan }: Props) {
  const [open, setOpen] = useState(false)
  const planning = useStore((s) => s.planning)
  useEffect(() => {
    if (!open) return
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [open])

  const items = [
    ...(onPlan ? [{ key: 'plan', text: planning ? 'Считаем…' : 'Спланировать заново', icon: <IconPlay />, act: onPlan }] : []),
    { key: 'drop', text: 'Ткнуть на карте', icon: <IconPin />, act: () => { onNeedMap(); useStore.getState().setDropping(true) } },
    { key: 'urgent', text: 'Срочная заявка', icon: <IconBolt />, act: () => onEvent('urgent') },
    { key: 'new', text: 'Заявка день в день', icon: <IconCalendar />, act: () => onEvent('new_request') },
  ]

  return (
    <>
      {open ? <div className="b-dial-scrim" onClick={() => setOpen(false)} aria-hidden="true" /> : null}
      <div className={`b-dial${open ? ' open' : ''}`}>
        {open ? (
          <ul role="menu" aria-label="Новая заявка">
            {items.map((item, i) => (
              <li key={item.key} style={{ ['--i' as string]: items.length - 1 - i }}>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false)
                    item.act()
                  }}
                >
                  <span>{item.text}</span>
                  <i>{item.icon}</i>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <button
          type="button"
          className="b-dial-main"
          disabled={disabled}
          aria-expanded={open}
          aria-label={open ? 'Закрыть' : 'Новая заявка или пересчёт'}
          onClick={() => setOpen(!open)}
        >
          <IconPlus />
        </button>
      </div>
    </>
  )
}
