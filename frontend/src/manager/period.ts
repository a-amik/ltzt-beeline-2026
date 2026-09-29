/** Периоды сводки руководителя: диапазон дней, период сравнения, подпись «11–17 авг». */

// Сокращения в родительном падеже: «19 июл – 17 авг», а не «19 июль».
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

export interface Range {
  from: string
  to: string
}

export type CompareMode = 'prev' | 'year' | 'custom'

export interface Period {
  main: Range
  compare: Range | null
  mode: CompareMode | null
}

export const parse = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
export const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const shift = (s: string, days: number) => {
  const d = parse(s)
  d.setDate(d.getDate() + days)
  return iso(d)
}
export const length = (r: Range) => Math.round((parse(r.to).getTime() - parse(r.from).getTime()) / 86400000) + 1
export const inside = (day: string, r: Range | null) => Boolean(r && day >= r.from && day <= r.to)

/** Период сравнения по режиму: предыдущий той же длины или тот же год назад. */
export function compareOf(main: Range, mode: CompareMode, custom: Range | null): Range {
  if (mode === 'custom' && custom) return custom
  if (mode === 'year') {
    const back = (s: string) => {
      const d = parse(s)
      d.setFullYear(d.getFullYear() - 1)
      return iso(d)
    }
    return { from: back(main.from), to: back(main.to) }
  }
  const n = length(main)
  return { from: shift(main.from, -n), to: shift(main.from, -1) }
}

/** «17 авг», «11–17 авг», «28 июл – 3 авг», год — если он не тот, что у последнего дня данных. */
export function rangeLabel(r: Range, anchorYear?: number): string {
  const a = parse(r.from)
  const b = parse(r.to)
  const month = (d: Date) => MONTHS[d.getMonth()]
  const year = (d: Date) => (anchorYear && d.getFullYear() !== anchorYear ? ` ${d.getFullYear()}` : '')
  if (r.from === r.to) return `${a.getDate()} ${month(a)}${year(a)}`
  if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()) return `${a.getDate()}–${b.getDate()} ${month(b)}${year(b)}`
  if (a.getFullYear() === b.getFullYear()) return `${a.getDate()} ${month(a)} – ${b.getDate()} ${month(b)}${year(b)}`
  return `${a.getDate()} ${month(a)} ${a.getFullYear()} – ${b.getDate()} ${month(b)} ${b.getFullYear()}`
}

export function dayPeriod(anchor: string): Period {
  return { main: { from: anchor, to: anchor }, compare: null, mode: null }
}
