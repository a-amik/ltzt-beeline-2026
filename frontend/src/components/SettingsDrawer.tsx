/**
 * Настройки расчёта: что учитывать при построении, тарифы, норма и бонусы,
 * обед, время в пути. Форма не нарисована руками, а собрана по схеме
 * с сервера (`GET /settings`): подписи, единицы и диапазоны приходят
 * готовыми, второго списка настраиваемых чисел в клиенте нет.
 *
 * У изменённого поля справа стоит «вернуть» с числом модели — сброс по одному;
 * «Сбросить всё» возвращает допущения целиком. Применение пересчитывает план сразу: диспетчер
 * меняет число ради того, чтобы увидеть последствие, а не ради формы.
 *
 * Вкладок три: правила и тарифы, бригады, модель. Группы с пометкой `tech`
 * в схеме — поиск решателя, режим пересчёта, поправки к OSRM — уходят
 * на вкладку «Модель»: их крутит тот, кто считает модель, и при показе
 * экрана они на глаза не попадаются.
 *
 * Правила общие на день и задаёт их эксперт (`mode="edit"`): форма сохраняет
 * их на сервер (`PUT /rules`), и сервер ставит их под каждый расчёт. Режим
 * «только чтение» (`mode="read"`) запирает поля одним `<fieldset disabled>`.
 *
 * Вида два. `layout="screen"` — раздел колонки «Настройки»: слева колонка той
 * же ширины, что у «Заявок», — название, поиск и оглавление; посередине все
 * группы подряд, в шапке над ними — светлая и тёмная тема; справа помощник
 * (`settings/Helper`), который подбирает настройки по словам диспетчера.
 * `layout="drawer"` — прежнее окно сбоку (экран руководителя).
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Button,
  Checkbox,
  HelpMark,
  NumberInput,
  RadioGroup,
  SegmentedRadioGroup,
  Switch,
  TextInput,
} from '@gravity-ui/uikit'
import { loadSettingsForm } from '../data'
import type { Engineer, Settings, SettingsField, SettingsGroup } from '../types'
import { IconClose, IconSearch } from '../lib/icons'
import { usePhone } from '../lib/media'
import { useScrollEdge } from '../lib/scrollEdge'
import NavBurger from './NavBurger'
import MoreMenu from './MoreMenu'
import CrewSettings, { crewsOf } from './CrewSettings'
import ThemeSwitch from './ThemeSwitch'
import Helper from './settings/Helper'
import BeeMark from './settings/BeeMark'

const EMPTY: Settings = {}

function getPath(tree: Settings, path: string): unknown {
  let node: unknown = tree
  for (const part of path.split('.')) {
    if (!node || typeof node !== 'object' || !(part in (node as Record<string, unknown>))) return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return node
}

function setPath(tree: Settings, path: string, value: unknown): Settings {
  const out = structuredClone(tree) as Record<string, unknown>
  const parts = path.split('.')
  let node = out
  for (const part of parts.slice(0, -1)) {
    if (!node[part] || typeof node[part] !== 'object') node[part] = {}
    node = node[part] as Record<string, unknown>
  }
  if (value === undefined) delete node[parts[parts.length - 1]]
  else node[parts[parts.length - 1]] = value
  return out
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

interface Props {
  /** edit — руководитель правит правила; read — диспетчер их только видит. */
  mode: 'edit' | 'read'
  /** Действующие правила: переопределения поверх допущений модели. */
  initial: Settings
  engineers: Engineer[]
  onClose: () => void
  /** edit — сохранить правила; read — пересчитать план по действующим. */
  onSubmit: (draft: Settings) => void
  submitLabel: string
  busy?: boolean
  /** Строка под заголовком: кто задаёт правила и когда их меняли. */
  note?: string
  /** screen — отдельный экран эксперта; drawer — окно сбоку. */
  layout?: 'drawer' | 'screen'
}

export default function SettingsDrawer({ mode, initial, engineers, onClose, onSubmit, submitLabel, busy, note, layout = 'drawer' }: Props) {
  const readOnly = mode === 'read'
  const phone = usePhone()
  const form = useQuery({ queryKey: ['settings-form'], queryFn: loadSettingsForm, staleTime: Infinity })
  const [draft, setDraft] = useState<Settings>(initial)
  const [tab, setTab] = useState<'rules' | 'crews' | 'model'>('rules')
  const crewsChanged = Object.keys(crewsOf(draft)).length

  const defaults = form.data?.defaults ?? EMPTY
  const changedCount = useMemo(() => {
    if (!form.data) return 0
    return form.data.schema
      .flatMap((group) => group.fields)
      .filter((field) => {
        const value = getPath(draft, field.path)
        return value !== undefined && !same(value, getPath(defaults, field.path))
      }).length
  }, [draft, form.data, defaults])

  const close = onClose
  const valueOf = (field: SettingsField) => {
    const own = getPath(draft, field.path)
    return own === undefined ? getPath(defaults, field.path) : own
  }
  const update = (field: SettingsField, value: unknown) => {
    const back = same(value, getPath(defaults, field.path)) ? undefined : value
    setDraft((current) => setPath(current, field.path, back))
  }
  const apply = () => onSubmit(draft)

  const groupSection = (group: NonNullable<typeof form.data>['schema'][number]) => (
    <section key={group.key} className="b-set-group">
      <h3>{group.title}</h3>
      {group.fields.map((field) => {
        const own = getPath(draft, field.path)
        const changed = own !== undefined && !same(own, getPath(defaults, field.path))
        const inline = field.type === 'bool'
        return (
          <div key={field.path} className={`b-set-row ${field.type}${inline ? ' inline' : ''}`}>
            {inline ? null : (
              <label className="b-set-label">
                {field.label}
                {changed && !readOnly ? (
                  <button
                    type="button"
                    className="b-set-reset"
                    onClick={() => update(field, getPath(defaults, field.path))}
                    title="Вернуть значение модели"
                  >
                    вернуть {String(getPath(defaults, field.path))}
                  </button>
                ) : null}
              </label>
            )}
            {control(field)}
            {field.hint ? <small className="b-set-hint">{field.hint}</small> : null}
          </div>
        )
      })}
    </section>
  )

  const crewsSection = (
    <CrewSettings
      plain={layout === 'screen'}
      engineers={engineers}
      crews={crewsOf(draft)}
      onChange={(crews) =>
        setDraft((current) => {
          const next = { ...current }
          if (Object.keys(crews).length) next.crews = crews
          else delete next.crews
          return next
        })
      }
    />
  )

  const control = (field: SettingsField, bare = false) => {
    const value = valueOf(field)
    switch (field.type) {
      case 'bool':
        return (
          <Switch
            size="m"
            checked={Boolean(value)}
            onUpdate={(checked) => update(field, checked)}
            content={bare ? undefined : field.label}
            aria-label={bare ? field.label : undefined}
          />
        )
      case 'choice': {
        const choices = (field.choices ?? []).map((choice) => ({ value: choice.value, content: choice.label }))
        // На телефоне сегмент с длинными подписями обрезал их до «Время → бриг…»:
        // такой выбор идёт списком в столбик, с подписью целиком. Короткие остаются сегментом.
        if (phone && choices.some((choice) => choice.content.length > 14)) {
          return (
            <RadioGroup
              size="m"
              direction="vertical"
              className="b-st-radio"
              value={String(value ?? '')}
              onUpdate={(next) => update(field, next)}
              options={choices}
            />
          )
        }
        return (
          <SegmentedRadioGroup
            size="m"
            width="max"
            value={String(value ?? '')}
            onUpdate={(next) => update(field, next)}
            options={choices}
          />
        )
      }
      case 'multi': {
        const list = Array.isArray(value) ? (value as string[]) : []
        return (
          <div className="b-set-multi">
            {(field.choices ?? []).map((choice) => (
              <Checkbox
                key={choice.value}
                size="m"
                checked={list.includes(choice.value)}
                content={choice.label}
                onUpdate={(checked) => {
                  const next = (field.choices ?? [])
                    .map((c) => c.value)
                    .filter((v) => (v === choice.value ? checked : list.includes(v)))
                  update(field, next.length ? next : list)
                }}
              />
            ))}
          </div>
        )
      }
      case 'time':
        return (
          <TextInput
            size="m"
            value={String(value ?? '')}
            placeholder="ЧЧ:ММ"
            controlProps={{ inputMode: 'numeric', pattern: '[0-2][0-9]:[0-5][0-9]' }}
            onUpdate={(next) => update(field, next)}
          />
        )
      default:
        return (
          <NumberInput
            size="m"
            value={typeof value === 'number' ? value : null}
            min={field.min}
            max={field.max}
            step={field.step}
            allowDecimal={!Number.isInteger(field.step ?? 1)}
            endContent={field.unit ? <span className="b-set-unit">{field.unit}</span> : undefined}
            onUpdate={(next) => {
              if (next !== null) update(field, next)
            }}
          />
        )
    }
  }

  const summary = changedCount || crewsChanged
    ? `Изменено полей: ${changedCount}${crewsChanged ? `, бригад: ${crewsChanged}` : ''}. Остальное — по допущениям модели.`
    : 'Все числа — по допущениям модели. Тарифы оценочные: заказчик их не давал.'

  // Строка экрана «Настройки»: слева название и ⓘ с пояснением, справа поле.
  // Длинный переключатель и множественный выбор — под названием, на всю ширину.
  const changedPaths = new Set(
    (form.data?.schema ?? []).flatMap((group) => group.fields).filter((field) => {
      const own = getPath(draft, field.path)
      return own !== undefined && !same(own, getPath(defaults, field.path))
    }).map((field) => field.path),
  )
  const screenRow = (field: SettingsField) => {
    const changed = changedPaths.has(field.path)
    const wide = (field.type === 'choice' && (field.choices?.length ?? 0) > 2) || field.type === 'multi'
    const back = getPath(defaults, field.path)
    return (
      <div key={field.path} className={`b-st-row${wide ? ' wide' : ''}${changed ? ' changed' : ''}`}>
        <div className="b-st-l">
          <span className="lb">{field.label}</span>
          {field.hint ? (
            <HelpMark aria-label={`Подробнее: ${field.label}`} popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
              <div className="b-st-hint">{field.hint}</div>
            </HelpMark>
          ) : null}
          {changed && !readOnly ? (
            <button type="button" className="b-st-reset" onClick={() => update(field, back)} title="Вернуть значение модели">
              вернуть {typeof back === 'boolean' ? (back ? 'вкл.' : 'выкл.') : Array.isArray(back) ? 'как было' : String(back)}
            </button>
          ) : null}
        </div>
        <div className="b-st-c">{control(field, true)}</div>
      </div>
    )
  }

  if (layout === 'screen') {
    return (
      <SettingsScreen
        note={note}
        groups={form.data?.schema ?? []}
        loading={form.isLoading}
        failed={!form.isLoading && !form.data}
        row={screenRow}
        crews={crewsSection}
        changedPaths={changedPaths}
        crewsChanged={crewsChanged}
        valueOf={valueOf}
        onApply={(values) => values.forEach(({ field, value }) => update(field, value))}
        readOnly={readOnly}
        busy={busy}
        submitLabel={submitLabel}
        onReset={() => setDraft({})}
        onSubmit={apply}
        onClose={close}
      />
    )
  }

  return (
    <div className="b-drawer fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={close} aria-hidden="true" />
      <aside
        role="dialog"
        aria-label={readOnly ? 'Правила расчёта' : 'Правила дня'}
        className="b-set relative flex w-[560px] max-w-[96vw] flex-col bg-[var(--b-float)]"
        style={{ boxShadow: 'var(--b-shadow-float)' }}
      >
        <div className="b-set-head">
          <div className="min-w-0 flex-1">
            <h2>{readOnly ? 'Правила расчёта' : 'Правила дня'}</h2>
            {note ? <p className="b-set-lock">{note}</p> : null}
            <p>{summary}</p>
            <div style={{ marginTop: 10 }}>
              <SegmentedRadioGroup
                size="m"
                value={tab}
                onUpdate={(value) => setTab(value as 'rules' | 'crews' | 'model')}
                options={[
                  { value: 'rules', content: 'Правила и тарифы' },
                  { value: 'crews', content: 'Бригады' },
                  { value: 'model', content: 'Модель' },
                ]}
              />
            </div>
          </div>
          <Button view="flat" size="m" onClick={close} title="Закрыть">
            <IconClose />
          </Button>
        </div>

        <fieldset className="b-set-body b-set-fieldset" disabled={readOnly}>
          {tab === 'crews' ? (
            crewsSection
          ) : form.isLoading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 10 }, (_, i) => (
                <div key={i} className="b-skeleton h-8 w-full" />
              ))}
            </div>
          ) : !form.data ? (
            <p className="text-[var(--b-text-2)]">
              Настройки считает сервер, а он сейчас не отвечает. Демо-план строится по допущениям.
            </p>
          ) : (
            form.data.schema.filter((group) => Boolean(group.tech) === (tab === 'model')).map(groupSection)
          )}
        </fieldset>

        <div className="b-set-foot">
          <Button view="action" size="l" onClick={apply} disabled={!form.data || busy}>
            {submitLabel}
          </Button>
          {readOnly ? null : (
            <Button view="outlined" size="l" onClick={() => setDraft({})} disabled={!changedCount && !crewsChanged}>
              Сбросить всё
            </Button>
          )}
        </div>
      </aside>
    </div>
  )
}

/**
 * Экран «Настройки» — раздел колонки: шапка той же высоты, что у разделов,
 * с поиском по настройкам; слева оглавление групп (метка — в группе есть
 * изменения), справа группы карточками. Каждая настройка — строка: название
 * и ⓘ с пояснением и источником числа слева, поле справа. Панель «Сохранить»
 * появляется снизу, только когда что-то изменено.
 */
function SettingsScreen({
  note, groups, loading, failed, row, crews, changedPaths, crewsChanged, valueOf, onApply, readOnly, busy, submitLabel, onReset, onSubmit, onClose,
}: {
  note?: string
  groups: SettingsGroup[]
  loading: boolean
  failed: boolean
  row: (field: SettingsField) => React.ReactNode
  crews: React.ReactNode
  changedPaths: Set<string>
  crewsChanged: number
  valueOf: (field: SettingsField) => unknown
  onApply: (values: { field: SettingsField; value: unknown }[]) => void
  readOnly: boolean
  busy?: boolean
  submitLabel: string
  onReset: () => void
  onSubmit: () => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  // Телефон: поиск — значком в шапке раздела, поле встаёт по нажатию; группы — бургером.
  const phone = usePhone()
  const [searching, setSearching] = useState(false)
  // На узком экране оглавление — строка с прокруткой вбок; край затухает, пока есть что листать.
  const navRef = useRef<HTMLElement>(null)
  useScrollEdge(navRef)
  const [active, setActive] = useState(groups[0]?.key ?? '')
  // На узком экране помощник не помещается колонкой и открывается поверх по знаку.
  const [helper, setHelper] = useState(false)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const needle = query.trim().toLowerCase()
  const match = (field: SettingsField, groupTitle: string) =>
    !needle || `${field.label} ${field.hint ?? ''} ${groupTitle}`.toLowerCase().includes(needle)
  // «Бригады» стоят после «Затрат»: состав бригад — последнее, что эксперт правит в правилах.
  const plain = groups.filter((group) => !group.tech)
  const tech = groups.filter((group) => group.tech)
  const shown = (list: typeof groups) =>
    list.map((group) => ({ ...group, fields: group.fields.filter((field) => match(field, group.title)) })).filter((group) => group.fields.length)
  const showCrews = !needle || 'бригады дом транспорт адрес'.includes(needle) || needle.includes('бригад')
  const changed = changedPaths.size + crewsChanged
  const jump = (key: string) => {
    setActive(key)
    document.getElementById(`st-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const navItem = (key: string, title: string, dirty: boolean) => (
    <button key={key} type="button" className={active === key ? 'on' : ''} onClick={() => jump(key)}>
      <span>{title}</span>
      {dirty ? <i className="b-st-dot" title="Есть изменения" /> : null}
    </button>
  )
  const card = (group: (typeof groups)[number]) => (
    <section key={group.key} id={`st-${group.key}`} className="b-st-card">
      <header>
        <h2>{group.title}</h2>
        {group.note ? <p>{group.note}</p> : null}
      </header>
      {group.fields.map(row)}
    </section>
  )
  const plainShown = shown(plain)
  const techShown = shown(tech)

  const allFields = groups.flatMap((group) => group.fields)
  const helperApply = (values: { field: SettingsField; value: unknown }[], focus: SettingsField) => {
    setQuery('')
    onApply(values)
    const group = groups.find((g) => g.fields.some((f) => f.path === focus.path))
    if (group) window.setTimeout(() => jump(group.key), 60)
  }

  return (
    <div className={`b-demo b-st${helper ? ' helper' : ''}`} role="dialog" aria-label="Настройки">
      <aside className="b-st-side">
        <div className="b-ch">
          <b>Настройки</b>
          {note ? (
            <HelpMark aria-label="Кто задаёт настройки" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
              <div className="b-st-hint">{note}</div>
            </HelpMark>
          ) : null}
          <Button view="flat" size="m" onClick={onClose} title="Закрыть — Esc" className="b-st-close">
            <IconClose />
          </Button>
          {phone ? (
            <span className="b-st-acts">
              <Button view={searching || query ? 'normal' : 'flat'} size="m" title="Найти настройку" aria-label="Найти настройку"
                aria-expanded={searching || Boolean(query)}
                onClick={() => { if (searching && query) setQuery(''); setSearching(!searching) }}>
                <IconSearch />
              </Button>
              <NavBurger
                label="Группы настроек"
                groups={[
                  [...plainShown.map((g) => ({ text: g.title, selected: active === g.key, action: () => jump(g.key) })),
                    ...(showCrews ? [{ text: 'Бригады', selected: active === 'crews', action: () => jump('crews') }] : [])],
                  techShown.map((g) => ({ text: `Модель · ${g.title}`, selected: active === g.key, action: () => jump(g.key) })),
                ]}
              />
              <MoreMenu phone size="m" />
            </span>
          ) : null}
        </div>
        <div className={`b-csearch${phone && !searching && !query ? ' shut' : ''}`}>
          <TextInput
            size="m"
            autoFocus={phone && searching}
            value={query}
            onUpdate={setQuery}
            placeholder="Найти настройку"
            hasClear
            startContent={<IconSearch className="ml-2 text-[var(--b-text-3)]" />}
          />
        </div>
        <nav ref={navRef} className="b-st-nav b-scroll" aria-label="Группы настроек">
          {plainShown.map((group) => navItem(group.key, group.title, group.fields.some((f) => changedPaths.has(f.path))))}
          {showCrews ? navItem('crews', 'Бригады', crewsChanged > 0) : null}
          {techShown.length ? <small>Модель</small> : null}
          {techShown.map((group) => navItem(group.key, group.title, group.fields.some((f) => changedPaths.has(f.path))))}
        </nav>
      </aside>

      <div className="b-st-main">
        <header className="b-st-top">
          <ThemeSwitch />
        </header>
        <fieldset className="b-st-page b-scroll" disabled={readOnly}>
          {loading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="b-skeleton h-10 w-full" />
              ))}
            </div>
          ) : failed ? (
            <p className="b-st-empty">Настройки хранит сервер, а он сейчас не отвечает.</p>
          ) : (
            <>
              {plainShown.map(card)}
              {showCrews ? (
                <section id="st-crews" className="b-st-card crews">
                  <header>
                    <h2>Бригады</h2>
                    <p>Дом, транспорт и работа сверх нормы — по каждой бригаде</p>
                  </header>
                  {crews}
                </section>
              ) : null}
              {techShown.length ? <h2 className="b-st-part">Модель</h2> : null}
              {techShown.map(card)}
              {!plainShown.length && !techShown.length && !showCrews ? <p className="b-st-empty">Ничего не нашлось</p> : null}
            </>
          )}
        </fieldset>
      {changed && !readOnly ? (
        <div className="b-st-save" role="region" aria-label="Несохранённые изменения">
          <span>
            Изменено: {changed}
          </span>
          <Button view="outlined" size="l" onClick={onReset}>
            Сбросить всё
          </Button>
          <Button view="action" size="l" onClick={onSubmit} disabled={busy}>
            {submitLabel}
          </Button>
        </div>
      ) : null}
      </div>

      <Helper fields={allFields} valueOf={valueOf} onApply={helperApply} readOnly={readOnly} onClose={() => setHelper(false)} />
      {/* Узкий экран: помощник — по знаку в углу. */}
      <button type="button" className="b-help-fab" onClick={() => setHelper(true)} title="BeeGPT" aria-label="Открыть BeeGPT">
        <BeeMark size={26} idle />
      </button>
    </div>
  )
}
