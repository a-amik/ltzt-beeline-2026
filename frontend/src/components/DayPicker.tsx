/**
 * День плана — общий фильтр экрана: «пн, 17 августа» с календарём. На
 * компьютере стоит в заголовке левой колонки у правого края, а при свёрнутой
 * колонке — в шапке над картой; на телефоне — в шапке. Календарь листается
 * по месяцам; выбрать можно только дни, на которые есть данные (сейчас набор
 * заказчика — один день), остальные погашены. Сегодняшний день обведён.
 */

import { useState } from 'react'
import { Popup } from '@gravity-ui/uikit'
import { useStore } from '../store'
import { IconCalendar, IconChevron } from '../lib/icons'

const WEEK = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

const parse = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

const same = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

export default function DayPicker() {
  const date = useStore((s) => s.dataset?.date)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null)
  // Показанный месяц: первое число; при открытии — месяц дня плана.
  const [shown, setShown] = useState<Date | null>(null)
  if (!date) return null
  const day = parse(date)
  const month = shown ?? new Date(day.getFullYear(), day.getMonth(), 1)
  const today = new Date()
  const label = day.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
  const title = month.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }).replace(' г.', '')

  // Сетка месяца с понедельника; пустые клетки до первого числа.
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const lead = (month.getDay() + 6) % 7
  const cells = [...Array.from({ length: lead }, () => null), ...Array.from({ length: days }, (_, i) => new Date(month.getFullYear(), month.getMonth(), i + 1))]
  const step = (delta: number) => setShown(new Date(month.getFullYear(), month.getMonth() + delta, 1))

  return (
    <>
      <button
        ref={setAnchor}
        type="button"
        className="b-day-btn"
        onClick={() => {
          setShown(null)
          setOpen(!open)
        }}
        aria-expanded={open}
        aria-label={`День плана: ${label}`}
      >
        <IconCalendar />
        <span>{label}</span>
        <IconChevron />
      </button>
      <Popup open={open} onOpenChange={setOpen} anchorElement={anchor} placement={['bottom-end', 'bottom-start', 'bottom']} offset={{ mainAxis: 6 }}>
        <div className="b-cal" role="grid" aria-label={title}>
          <div className="b-cal-m">
            <button type="button" className="prev" onClick={() => step(-1)} aria-label="Предыдущий месяц">
              <IconChevron />
            </button>
            <b>{title[0].toUpperCase() + title.slice(1)}</b>
            <button type="button" className="next" onClick={() => step(1)} aria-label="Следующий месяц">
              <IconChevron />
            </button>
          </div>
          <div className="b-cal-g">
            {WEEK.map((w) => (
              <i key={w}>{w}</i>
            ))}
            {cells.map((cell, i) =>
              cell ? (
                <button
                  key={i}
                  type="button"
                  className={`${same(cell, day) ? 'on' : ''}${same(cell, today) ? ' today' : ''}`}
                  disabled={!same(cell, day)}
                  onClick={() => setOpen(false)}
                >
                  {cell.getDate()}
                </button>
              ) : (
                <span key={i} />
              ),
            )}
          </div>
        </div>
      </Popup>
    </>
  )
}
