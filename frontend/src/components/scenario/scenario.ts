/**
 * Сценарий дня — общий язык «Живого дня» и «Имитации»: какой день и откуда
 * стартуют бригады. Варианты, подписи и подсказки одни на оба экрана, чтобы
 * один и тот же день назывался одинаково. Подписи короткие, пояснение —
 * в подсказке ⓘ.
 */

import type { CustomEvent } from '../../types'

export type DayType = 'normal' | 'hard'
/** Какой день: без событий, события набора участка или случайные события обычного и тяжёлого дня. */
export type DayKind = 'none' | 'data' | DayType
/** «Живой день» умеет ещё свои события: их считают на месте, в «Имитации» дни посчитаны заранее. */
export type LiveKind = 'custom' | DayKind
export type StartKind = 'office' | 'hybrid' | 'home'

export interface DayCounts {
  new_requests: number | null
  cancels: number
  no_shows: number
  reschedules: number
  delays: number
  engineer_off: number
}

/** Случайных наборов событий на участок и тип дня — столько же дней в «Имитации» (`race --seeds`). */
export const SEEDS = 20

/** Счётчики событий типа дня — те же, что в гонке (`bee_routing.race.MODES`). */
export const DAY_TYPES: Record<DayType, { label: string; counts: DayCounts; newShare: number }> = {
  normal: { label: 'Обычный день', newShare: 1, counts: { new_requests: null, cancels: 2, no_shows: 2, reschedules: 1, delays: 1, engineer_off: 0 } },
  hard: { label: 'Тяжёлый день', newShare: 2, counts: { new_requests: null, cancels: 4, no_shows: 3, reschedules: 2, delays: 3, engineer_off: 1 } },
}

export const DAY_KINDS: DayKind[] = ['none', 'data', 'normal', 'hard']

// В выборе дня: без событий, обычный, тяжёлый — и свои события последними.
// «События из набора» из выбора сняты: три заложенных события перекрывает любой из готовых дней.
export const LIVE_KINDS: LiveKind[] = ['none', 'normal', 'hard', 'custom']

export const DAY_LABELS: Record<LiveKind, string> = {
  custom: 'Свои события',
  none: 'Без событий',
  data: 'События из набора',
  normal: DAY_TYPES.normal.label,
  hard: DAY_TYPES.hard.label,
}

export const isRandom = (kind: LiveKind): kind is DayType => kind === 'normal' || kind === 'hard'

export function dayInfo(type: DayType, sharePct: number): string {
  const c = DAY_TYPES[type].counts
  const share = Math.round(sharePct * DAY_TYPES[type].newShare)
  const off = c.engineer_off ? `, выбывает бригад: ${c.engineer_off}` : ''
  return `Новых заявок днём — ${share} % набора; отмен — ${c.cancels}, «клиента нет» — ${c.no_shows}, `
    + `переносов окна — ${c.reschedules}, задержек бригад — ${c.delays}${off}.`
    + (type === 'normal' ? ' Так проходит обычный день по ответам Билайна: день в день приходит 10—15 % заявок.' : ' Вдвое больше событий, чем в обычный день.')
    + ` Что именно случится, решает номер набора: ${SEEDS} наборов, у каждого свои адреса и минуты.`
}

export function dayKindInfo(kind: LiveKind, sharePct: number): string {
  if (kind === 'custom') return 'События задаёте сами: что случится, во сколько и с какой бригадой или заявкой. Ничего случайного.'
  if (kind === 'none') return 'Утренние планы как есть: днём ничего не случается. Сравнивается только утреннее распределение.'
  if (kind === 'data') {
    return 'Три события, заложенные в набор участка: выбывает самая загруженная бригада, клиент отменяет заявку, '
      + 'приходит срочная авария. Время событий — в допущениях.'
  }
  return dayInfo(kind, sharePct)
}

export const STARTS: Record<StartKind, { label: string; options: Record<string, unknown> }> = {
  office: { label: 'Из офиса', options: { start: 'office', zone_start: false } },
  hybrid: { label: 'Гибрид', options: { start: 'hybrid', zone_start: false } },
  home: { label: 'Из дома', options: { start: 'home' } },
}

export function startInfo(kind: StartKind, hybridKm: number): string {
  const km = String(hybridKm).replace('.', ',')
  if (kind === 'office') return 'Все бригады начинают день в офисе участка — по регламенту.'
  if (kind === 'hybrid') {
    return `Часть из дома, часть из офиса: бригада, чей участок дальше ${km} км от офиса, выходит из дома, остальные — из офиса. `
      + 'На трёх участках заказчика из дома выходит 18 бригад из 35.'
  }
  return 'Все бригады выходят из дома. Адресов домов в данных заказчика нет: домом считаем центр заявок бригады в контрольный день 17 августа — там, где она работает.'
}

/** Подпись кнопки «Сценарий»: какой день, откуда старт и, если задан, номер набора. */
export function scenarioLabel(kind: LiveKind, start: StartKind, seed?: number): string {
  const set = seed !== undefined && isRandom(kind) ? ` · набор № ${seed}` : ''
  return `${DAY_LABELS[kind]} · ${STARTS[start].label.toLowerCase()}${set}`
}

/** Общая строка под выбором сценария — одна на оба экрана. */
export const SCENARIO_NOTE = 'Старт бригад и события у всех планов одни, минута в минуту. '
  + 'Контроль и базовый план отвечают на события правилом п. 2.3, наш план — перепланированием.'

/** Что выбрано в сайд-шите: какой день, старт, номер набора и свои события. */
export interface ScenarioDraft {
  kind: LiveKind
  start: StartKind
  seed: number
  custom: CustomEvent[]
}

/** По умолчанию на обоих экранах: обычный день, старт из офиса, набор № 1. */
export const DEFAULT_SCENARIO: ScenarioDraft = { kind: 'normal', start: 'office', seed: 1, custom: [] }
