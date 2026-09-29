/** Числа по-русски. Классы узлов живут в `index.css`, а кнопки — в Gravity UI. */

export function num(value: number, digits = 0): string {
  return value.toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** 1 заявка, 2 заявки, 5 заявок. */
export function plural(n: number, one: string, few: string, many: string): string {
  const k = Math.abs(Math.trunc(n))
  if (k % 10 === 1 && k % 100 !== 11) return one
  if (k % 10 >= 2 && k % 10 <= 4 && !(k % 100 >= 12 && k % 100 <= 14)) return few
  return many
}
