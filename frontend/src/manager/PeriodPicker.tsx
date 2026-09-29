/**
 * Период сводки руководителя и период сравнения — календарь «как в
 * аналитике»: слева готовые периоды, справа два месяца, выбор двумя
 * щелчками (начало и конец), ниже — «Сравнить с»: предыдущим периодом
 * той же длины, тем же периодом год назад или своим. Выбранное вступает
 * в силу кнопкой «Применить»: руководитель собирает оба периода, прежде
 * чем экран перестроится.
 *
 * Готовые периоды отсчитываются от последнего дня с данными, а не от
 * сегодняшнего числа: «Неделя» — семь дней, которыми он кончается. Дни
 * с данными помечены точкой; выбрать можно любые.
 */

import { useState } from 'react'
import { Button, Popup, SegmentedRadioGroup, Switch } from '@gravity-ui/uikit'
import { IconCalendar, IconChevron } from '../lib/icons'
import { compareOf, inside, iso, length, parse, rangeLabel, shift, type CompareMode, type Period, type Range } from './period'

const WEEK = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

const PRESETS = [
  { key: 'day', label: 'День', days: 1 },
  { key: 'week', label: 'Неделя', days: 7 },
  { key: 'month', label: 'Месяц', days: 30 },
  { key: 'quarter', label: 'Квартал', days: 91 },
  { key: 'year', label: 'Год', days: 365 },
] as const

const MODES: { value: CompareMode; content: string }[] = [
  { value: 'prev', content: 'Предыдущим' },
  { value: 'year', content: 'Год назад' },
  { value: 'custom', content: 'Своим' },
]

export default function PeriodPicker({ value, anchor, dataDays, onChange }: {
  value: Period
  /** Последний день с данными: от него считаются готовые периоды. */
  anchor: string
  dataDays: string[]
  onChange: (next: Period) => void
}) {
  const [open, setOpen] = useState(false)
  const [button, setButton] = useState<HTMLButtonElement | null>(null)
  const [draft, setDraft] = useState<Period>(value)
  // Что правят щелчки по календарю: сам период или свой период сравнения.
  const [target, setTarget] = useState<'main' | 'compare'>('main')
  // Первый щелчок ставит начало; до второго конец следует за курсором.
  const [start, setStart] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [shown, setShown] = useState<Date>(() => parse(anchor))
  const year = parse(anchor).getFullYear()

  const openPicker = () => {
    setDraft(value)
    setTarget('main')
    setStart(null)
    const end = parse(value.main.to)
    setShown(new Date(end.getFullYear(), end.getMonth() - 1, 1))
    setOpen(true)
  }

  const withMain = (main: Range) => (d: Period): Period => ({
    main,
    mode: d.mode,
    compare: d.mode ? compareOf(main, d.mode, d.mode === 'custom' ? d.compare : null) : null,
  })

  const pick = (day: string) => {
    if (!start) {
      setStart(day)
      return
    }
    const range = day < start ? { from: day, to: start } : { from: start, to: day }
    setStart(null)
    if (target === 'compare') setDraft((d) => ({ ...d, mode: 'custom', compare: range }))
    else setDraft(withMain(range))
  }

  // Растянутый выбор до второго щелчка — чтобы видеть, что получится.
  const pending: Range | null = start && hover ? (hover < start ? { from: hover, to: start } : { from: start, to: hover }) : start ? { from: start, to: start } : null
  const main = target === 'main' && pending ? pending : draft.main
  const compare = target === 'compare' && pending ? pending : draft.compare

  const preset = PRESETS.find((p) => draft.main.to === anchor && length(draft.main) === p.days)?.key

  const setMode = (mode: CompareMode | null) => {
    setStart(null)
    if (!mode) {
      setTarget('main')
      setDraft((d) => ({ ...d, mode: null, compare: null }))
      return
    }
    setTarget(mode === 'custom' ? 'compare' : 'main')
    setDraft((d) => ({ ...d, mode, compare: compareOf(d.main, mode, mode === 'custom' ? (d.compare ?? compareOf(d.main, 'prev', null)) : null) }))
  }

  const month = (first: Date) => {
    const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
    const lead = (first.getDay() + 6) % 7
    const title = first.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }).replace(' г.', '')
    return (
      <div className="b-pp-month">
        <b>{title[0].toUpperCase() + title.slice(1)}</b>
        <div className="b-pp-grid" role="grid" aria-label={title} onMouseLeave={() => setHover(null)}>
          {WEEK.map((w) => (
            <i key={w}>{w}</i>
          ))}
          {Array.from({ length: lead }, (_, i) => (
            <span key={`l${i}`} />
          ))}
          {Array.from({ length: days }, (_, i) => {
            const day = iso(new Date(first.getFullYear(), first.getMonth(), i + 1))
            const cls = [
              inside(day, main) ? 'in' : '',
              day === main.from ? 'from' : '',
              day === main.to ? 'to' : '',
              inside(day, compare) ? 'cmp' : '',
              compare && day === compare.from ? 'cfrom' : '',
              compare && day === compare.to ? 'cto' : '',
              dataDays.includes(day) ? 'data' : '',
            ].filter(Boolean).join(' ')
            return (
              <button key={day} type="button" className={cls} onClick={() => pick(day)} onMouseEnter={() => setHover(day)}>
                {i + 1}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  const second = new Date(shown.getFullYear(), shown.getMonth() + 1, 1)
  const step = (delta: number) => setShown(new Date(shown.getFullYear(), shown.getMonth() + delta, 1))

  return (
    <>
      <button ref={setButton} type="button" className="b-pp-btn" onClick={() => (open ? setOpen(false) : openPicker())} aria-expanded={open} aria-label={`Период: ${rangeLabel(value.main, year)}`}>
        <IconCalendar />
        <span>{rangeLabel(value.main, year)}</span>
        {value.compare ? <small>против {rangeLabel(value.compare, year)}</small> : null}
        <IconChevron />
      </button>
      <Popup open={open} onOpenChange={setOpen} anchorElement={button} placement={['bottom-end', 'bottom-start', 'bottom']} offset={{ mainAxis: 6 }}>
        <div className="b-pp">
          <nav className="b-pp-presets" aria-label="Готовые периоды">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={preset === p.key ? 'on' : ''}
                onClick={() => {
                  setStart(null)
                  setTarget('main')
                  setDraft(withMain({ from: shift(anchor, 1 - p.days), to: anchor }))
                  const end = parse(anchor)
                  setShown(new Date(end.getFullYear(), end.getMonth() - 1, 1))
                }}
              >
                {p.label}
              </button>
            ))}
          </nav>
          <div className="b-pp-main">
            <div className="b-pp-fields">
              <button type="button" className={`main${target === 'main' ? ' on' : ''}`} onClick={() => { setStart(null); setTarget('main') }}>
                <small>Период</small>
                {rangeLabel(main, year)}
              </button>
              {draft.mode ? (
                <button type="button" className={`cmp${target === 'compare' ? ' on' : ''}`} onClick={() => { setStart(null); setTarget('compare'); setDraft((d) => ({ ...d, mode: 'custom' })) }}>
                  <small>Сравнение</small>
                  {compare ? rangeLabel(compare, year) : '—'}
                </button>
              ) : null}
            </div>
            <div className="b-pp-months">
              <button type="button" className="prev" onClick={() => step(-1)} aria-label="Предыдущий месяц">
                <IconChevron />
              </button>
              {month(shown)}
              {month(second)}
              <button type="button" className="next" onClick={() => step(1)} aria-label="Следующий месяц">
                <IconChevron />
              </button>
            </div>
            <div className="b-pp-cmp">
              <Switch size="m" checked={Boolean(draft.mode)} onUpdate={(on) => setMode(on ? 'prev' : null)} content="Сравнить с" />
              {draft.mode ? <SegmentedRadioGroup size="s" value={draft.mode} onUpdate={(mode) => setMode(mode as CompareMode)} options={MODES} /> : null}
            </div>
            <footer className="b-pp-foot">
              <span className="b-pp-key">
                <i className="data" />
                есть данные
              </span>
              <Button view="flat" size="m" onClick={() => setOpen(false)}>
                Отмена
              </Button>
              <Button
                view="action"
                size="m"
                disabled={Boolean(start)}
                onClick={() => {
                  onChange(draft)
                  setOpen(false)
                }}
              >
                Применить
              </Button>
            </footer>
          </div>
        </div>
      </Popup>
    </>
  )
}
