/**
 * Краски маршрутов. Источник значений — CSS-переменные `--b-route-1…10`
 * в theme.css; здесь только порядковый номер краски и её чтение для карты,
 * которой переменную не подставить.
 */

export const ROUTE_COLOR_COUNT = 10

/** Запасные значения — если переменная почему-то не объявлена. */
const FALLBACK = [
  '#0b6bcb', '#d9480f', '#2f9e44', '#9c36b5', '#0ca678',
  '#c92a2a', '#5f3dc4', '#e67700', '#1098ad', '#a61e4d',
]

/** Номер краски у инженера — по его месту в наборе, по кругу. */
export function colorIndex(engineerId: string, order: string[]): number {
  const i = order.indexOf(engineerId)
  return (i < 0 ? 0 : i) % ROUTE_COLOR_COUNT
}

/** Ссылка на краску для разметки и стилей. */
export function colorVar(index: number): string {
  return `var(--b-route-${index + 1})`
}

/** Разрешённое значение краски — нужно карте: в MapLibre `var()` не передать. */
export function readRouteColors(): string[] {
  if (typeof window === 'undefined') return FALLBACK
  const style = getComputedStyle(document.documentElement)
  return FALLBACK.map((fallback, i) => {
    const value = style.getPropertyValue(`--b-route-${i + 1}`).trim()
    return value || fallback
  })
}

/** Значение произвольного токена темы — тем же способом. */
export function readToken(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}
