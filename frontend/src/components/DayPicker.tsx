/**
 * День плана — общий фильтр экрана: «пн, 17 августа» с календарём. На
 * компьютере стоит в заголовке левой колонки у правого края, а при свёрнутой
 * колонке — в шапке над картой; на телефоне — в шапке. Календарь листается
 * по месяцам; выбрать можно только дни, на которые есть данные, остальные
 * погашены. День — отдельный набор того же участка: `vostok` — 17 августа,
 * `vostok-2026-09-28` — 28 сентября; «Вся Москва» так же (`moskva-<дата>`).
 * Выбор дня переключает набор. Сегодняшний день обведён.
 */

import { useState } from 'react'
import { Popup } from '@gravity-ui/uikit'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import { loadDatasets } from '../data'
import { IconCalendar, IconChevron } from '../lib/icons'

/** Набор без дня: `yugo-vostok-2026-09-28` → `yugo-vostok`. */
const familyOf = (id: string) => id.replace(/-\d{4}-\d{2}-\d{2}$/, '')

const WEEK = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

const parse = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

const same = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

export default function DayPicker() {
  const date = useStore((s) => s.dataset?.date)
  const datasetId = useStore((s) => s.datasetId)
  const setDatasetId = useStore((s) => s.setDatasetId)
  const { data: datasets = [] } = useQuery({ queryKey: ['datasets'], queryFn: loadDatasets, staleTime: Infinity })
  // Дни открытого набора: дата → набор этого дня.
  const byDay = new Map(datasets.filter((d) => familyOf(d.id) === familyOf(datasetId)).map((d) => [d.date, d.id]))
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
  const isoOf = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

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
            {cells.map((cell, i) => {
              const target = cell ? byDay.get(isoOf(cell)) : undefined
              return cell ? (
                <button
                  key={i}
                  type="button"
                  className={`${same(cell, day) ? 'on' : ''}${same(cell, today) ? ' today' : ''}`}
                  disabled={!same(cell, day) && !target}
                  aria-current={same(cell, day) ? 'date' : undefined}
                  onClick={() => {
                    setOpen(false)
                    if (target && target !== datasetId) setDatasetId(target)
                  }}
                >
                  {cell.getDate()}
                </button>
              ) : (
                <span key={i} />
              )
            })}
          </div>
          {/* Дни с данными бывают в разных месяцах: они же строкой, чтобы не листать. */}
          {byDay.size > 1 ? (
            <div className="b-cal-days">
              {[...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([iso, id]) => (
                <button
                  key={id}
                  type="button"
                  className={id === datasetId ? 'on' : ''}
                  onClick={() => {
                    setOpen(false)
                    if (id !== datasetId) setDatasetId(id)
                  }}
                >
                  {parse(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }).replace('.', '')}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </Popup>
    </>
  )
}
