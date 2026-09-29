/** Время дня — строки «ЧЧ:ММ» и минуты от полуночи. День один, суток не переходим. */

/** Начало и конец ленты дня. */
export const DAY_START = 10 * 60
export const DAY_END = 22 * 60
export const DAY_SPAN = DAY_END - DAY_START

export function toMin(hhmm: string): number {
  const [h, m] = hhmm.split(':')
  return Number(h) * 60 + Number(m)
}

export function fromMin(min: number): string {
  const m = Math.max(0, Math.round(min))
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

/** «96 мин» → «1 ч 36 мин»: в метриках часы читаются, минуты — нет. */
export function humanMin(min: number): string {
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  return h ? `${h} ч ${m} мин` : `${m} мин`
}
