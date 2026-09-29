/**
 * Подходы помощника настроек. Помощник — демонстрация: он не считает план,
 * а узнаёт в словах диспетчера знакомую ситуацию и предлагает набор
 * переключателей, который под неё собран. Каждый подход — ключевые основы
 * слов, короткое объяснение и изменения полей схемы настроек.
 *
 * Значения берутся только из полей схемы (`GET /settings`): поле, которого
 * в схеме нет, помощник молча пропускает, а число за пределами границ поля
 * не предложит — границы проверяет `propose`.
 */

import type { SettingsField } from '../../types'

export interface Recipe {
  key: string
  title: string
  /** Основы слов, по которым узнаётся ситуация. */
  stems: string[]
  /** Одно-два предложения: почему так. */
  why: string
  changes: Record<string, unknown>
}

export const RECIPES: Recipe[] = [
  {
    key: 'accident',
    title: 'Аварии — первыми',
    stems: ['авари', 'узел', 'узл', 'обрыв', 'линк', 'сбой', 'массов'],
    why: 'Авария держит без связи целый дом, поэтому её ставим раньше плановых визитов, под неё держим резерв бригад, а цена аварии растёт с числом клиентов узла.',
    changes: {
      'options.emergency_first': true,
      'options.emergency_reaction_min': 60,
      'options.accident_lock_horizon_min': 30,
      'options.idle_call': 'accident',
      'options.reserve_pct': 15,
      'economy.emergency_scale.on': true,
    },
  },
  {
    key: 'on_time',
    title: 'Приезжать вовремя',
    stems: ['опозд', 'вовремя', 'жалоб', 'окн', 'срыв', 'недовол', 'клиент ждал', 'не успева'],
    why: 'Опоздания рождаются на впритык собранных маршрутах. Даём запас по окну, считаем риск срыва по каждому визиту и не сдвигаем обещанное время дальше чем на полчаса.',
    changes: {
      'options.objective_order': 'on_time_crews_rub',
      'options.reliability': 'medium',
      'options.risk': true,
      'options.max_shift_min': 30,
      'options.hourly_traffic': true,
    },
  },
  {
    key: 'economy',
    title: 'Экономить на дороге',
    stems: ['эконом', 'деньг', 'дорог', 'бензин', 'топлив', 'пробег', 'расход', 'рубл', 'дешев', 'затрат', 'бюджет'],
    why: 'Сначала вовремя, потом рубли, и только потом число бригад. Дальние бригады стартуют из дома, между визитами ждут у следующей заявки, а не катаются впустую.',
    changes: {
      'options.objective_order': 'on_time_rub_crews',
      'options.start': 'hybrid',
      'options.standby': true,
      'options.balance': false,
    },
  },
  {
    key: 'overload',
    title: 'Разгрузить бригады',
    stems: ['перегру', 'устал', 'сверх', 'выгора', 'нагрузк', 'равномер', 'переработ', 'увольн'],
    why: 'Нагрузку выравниваем между бригадами, работу сверх нормы не планируем, обед ставим всем. План может взять на одну бригаду больше — это видно в сводке.',
    changes: {
      'options.balance': true,
      'options.extra_load': false,
      'options.breaks': true,
    },
  },
  {
    key: 'traffic',
    title: 'Пятница и пробки',
    stems: ['пятниц', 'пробк', 'час пик', 'трафик', 'затор', 'вечер'],
    why: 'В пятницу вечером город стоит. Берём скорости по часу и дню недели, поправки 2ГИС и запас по окну, чтобы пробка не съела обещанное время.',
    changes: {
      'options.day_type': 'friday',
      'options.hourly_traffic': true,
      'options.traffic': true,
      'options.reliability': 'medium',
    },
  },
  {
    key: 'weather',
    title: 'Непогода',
    stems: ['дожд', 'ливен', 'ливн', 'снег', 'погод', 'гололё', 'гололе', 'метел', 'зим', 'мороз'],
    why: 'В снег и ливень всё едет медленнее: замедляем дорогу на 30 % и берём большой запас по окну.',
    changes: {
      'options.season_factor': 1.3,
      'options.reliability': 'high',
    },
  },
  {
    key: 'intraday',
    title: 'Много заявок день в день',
    stems: ['день в день', 'срочн', 'новые заявк', 'новых заявок', 'поток', 'внепланов', 'сыплют', 'прилета'],
    why: 'Когда заявки прилетают весь день, держим резерв ёмкости, копим события по десять минут и пересчитываем пачкой, а задержку бригады отрабатываем сами.',
    changes: {
      'options.reserve_pct': 20,
      'options.intraday_share_pct': 20,
      'options.batch_window_min': 10,
      'options.delay_auto_replan': true,
    },
  },
  {
    key: 'stable',
    title: 'Меньше перестановок',
    stems: ['дёрга', 'дерга', 'стабильн', 'перестав', 'перестраив', 'путают', 'меньше измен', 'спокойн'],
    why: 'Бригада не любит, когда маршрут меняют под руками. Ближайшие полтора часа не трогаем, визит двигаем не дальше чем на двадцать минут, после события сохраняем порядок.',
    changes: {
      'options.lock_horizon_min': 90,
      'options.max_shift_min': 20,
      'options.replan_mode': 'local',
    },
  },
]

/** Подсказки под полем ввода: как можно сказать. */
export const EXAMPLES = [
  'Мало бригад, много аварий',
  'Клиенты жалуются на опоздания',
  'Хочу сэкономить на дороге',
  'Пятница, пробки',
  'Бригады перегружены',
  'Снег и гололёд',
]

export interface Change {
  field: SettingsField
  from: unknown
  to: unknown
}

export interface Proposal {
  recipes: Recipe[]
  changes: Change[]
}

/** Узнать подходы в словах диспетчера. Порядок — как в тексте. */
export function match(text: string): Recipe[] {
  const low = ` ${text.toLowerCase().replace(/ё/g, 'е')} `
  const found = RECIPES.map((recipe) => {
    const at = Math.min(...recipe.stems.map((stem) => {
      const i = low.indexOf(stem.replace(/ё/g, 'е'))
      return i < 0 ? Infinity : i
    }))
    return { recipe, at }
  }).filter((x) => x.at < Infinity)
  return found.sort((a, b) => a.at - b.at).map((x) => x.recipe)
}

/**
 * Собрать изменения: поля из схемы, в её границах, и только те, что правда
 * меняются. Где два подхода трогают одно поле, прав первый названный.
 */
export function propose(recipes: Recipe[], fields: SettingsField[], valueOf: (field: SettingsField) => unknown): Proposal {
  const byPath = new Map(fields.map((field) => [field.path, field]))
  const seen = new Set<string>()
  const changes: Change[] = []
  for (const recipe of recipes) {
    for (const [path, to] of Object.entries(recipe.changes)) {
      const field = byPath.get(path)
      if (!field || seen.has(path)) continue
      if (typeof to === 'number' && ((field.min !== undefined && to < field.min) || (field.max !== undefined && to > field.max))) continue
      if (field.type === 'choice' && !(field.choices ?? []).some((c) => c.value === to)) continue
      seen.add(path)
      const from = valueOf(field)
      if (JSON.stringify(from) !== JSON.stringify(to)) changes.push({ field, from, to })
    }
  }
  return { recipes, changes }
}

/** Значение поля словами: «вкл.», подпись варианта, число с единицей. */
export function show(field: SettingsField, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'вкл.' : 'выкл.'
  if (field.type === 'choice') return field.choices?.find((c) => c.value === value)?.label ?? String(value ?? '—')
  if (Array.isArray(value)) return value.map((v) => field.choices?.find((c) => c.value === v)?.label ?? v).join(', ')
  if (value === undefined || value === null) return '—'
  const num = typeof value === 'number' ? String(value).replace('.', ',') : String(value)
  return field.unit ? `${num} ${field.unit}` : num
}
