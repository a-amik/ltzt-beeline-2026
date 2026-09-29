/**
 * Подтверждение свайпом, как у приложений курьеров: ручку тянут вправо до
 * конца, и только тогда действие срабатывает. Случайное касание в кармане
 * отметку не поставит — на это приём и нужен.
 *
 * С клавиатуры действие подтверждают Enter или пробелом: свайп — жест
 * пальца, и без пальца он не должен запирать действие. Короткое касание
 * ничего не делает, а подсказывает, что тянуть.
 */

import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { IconArrowRight } from '../lib/icons'

const DONE_SHARE = 0.82

interface Props {
  label: string
  onConfirm: () => void
  disabled?: boolean
  tone?: 'action' | 'danger' | 'normal'
}

export default function SwipeButton({ label, onConfirm, disabled, tone = 'action' }: Props) {
  const track = useRef<HTMLDivElement>(null)
  const start = useRef<number | null>(null)
  const [shift, setShift] = useState(0)
  const [limit, setLimit] = useState(0)
  const [hint, setHint] = useState(false)

  const max = () => {
    const box = track.current?.getBoundingClientRect()
    return box ? Math.max(0, box.width - 56) : 0
  }
  const down = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    start.current = event.clientX - shift
    setLimit(max())
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (start.current === null) return
    setShift(Math.min(max(), Math.max(0, event.clientX - start.current)))
  }
  const up = () => {
    if (start.current === null) return
    start.current = null
    const limit = max()
    if (limit > 0 && shift >= limit * DONE_SHARE) {
      setShift(limit)
      onConfirm()
      window.setTimeout(() => setShift(0), 400)
      return
    }
    if (shift < 6) {
      setHint(true)
      window.setTimeout(() => setHint(false), 1600)
    }
    setShift(0)
  }
  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onConfirm()
    }
  }
  const share = limit ? shift / limit : 0

  return (
    <div
      ref={track}
      className={`b-swipe ${tone}${disabled ? ' off' : ''}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-disabled={disabled || undefined}
      onKeyDown={key}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
    >
      <span className="b-swipe-label" style={{ opacity: 1 - share }}>
        {hint ? 'Проведите вправо →' : label}
      </span>
      <span className="b-swipe-knob" style={{ transform: `translateX(${shift}px)` }} aria-hidden="true">
        <IconArrowRight />
      </span>
    </div>
  )
}
