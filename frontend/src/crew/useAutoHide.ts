/**
 * Шапка приложения бригады уходит по скроллу вниз и возвращается движением
 * вверх. Экран телефона короткий, и шапка, занимающая его верх
 * всю смену, платы за себя не приносит.
 *
 * Пять условий: ход считается накоплением (вниз уходит от 8 px, вверх
 * возвращается от 40 px, смена направления обнуляет счёт); у верха
 * страницы шапка стоит всегда; прыжок — не жест чтения, большой скачок
 * за одно событие не считается; под открытой шторкой шапка не двигается;
 * прячет её скрипт через `transform`, а при «меньше движения» — без перехода
 * (это в стилях). Фокус внутри шапки возвращает её.
 */

import { useEffect, useRef, useState, type RefObject } from 'react'

const DOWN_PX = 8
const UP_PX = 40
const TOP_PX = 50
const JUMP_PX = 240

/**
 * `root` — если прокручивается не окно, а список внутри элемента (шторка экрана
 * диспетчера на телефоне): тогда слушается прокрутка его потомков.
 */
export function useAutoHide(
  frozen: boolean,
  header: RefObject<HTMLElement | null>,
  root?: RefObject<HTMLElement | null>,
): boolean {
  const [hidden, setHidden] = useState(false)
  const last = useRef(0)
  const run = useRef(0)
  const frozenRef = useRef(frozen)
  useEffect(() => {
    frozenRef.current = frozen
  }, [frozen])

  useEffect(() => {
    last.current = window.scrollY
    const seen = new WeakMap<EventTarget, number>()
    const onScroll = (event?: Event) => {
      const target = root?.current && event?.target instanceof HTMLElement ? event.target : null
      const y = target ? target.scrollTop : window.scrollY
      const before = target ? (seen.get(target) ?? y) : last.current
      const delta = y - before
      if (target) seen.set(target, y)
      else last.current = y
      if (frozenRef.current) return
      if (y < TOP_PX) {
        run.current = 0
        setHidden(false)
        return
      }
      if (Math.abs(delta) > JUMP_PX) {
        run.current = 0
        return
      }
      if (Math.sign(delta) !== Math.sign(run.current)) run.current = 0
      run.current += delta
      if (run.current > DOWN_PX) setHidden(true)
      else if (run.current < -UP_PX) setHidden(false)
    }
    const onFocus = (event: FocusEvent) => {
      if (header.current && event.target instanceof Node && header.current.contains(event.target)) setHidden(false)
    }
    const scroller: EventTarget = root?.current ?? window
    scroller.addEventListener('scroll', onScroll as EventListener, { passive: true, capture: Boolean(root?.current) })
    document.addEventListener('focusin', onFocus)
    return () => {
      scroller.removeEventListener('scroll', onScroll as EventListener, { capture: Boolean(root?.current) } as EventListenerOptions)
      document.removeEventListener('focusin', onFocus)
    }
  }, [header, root])

  return hidden && !frozen
}
