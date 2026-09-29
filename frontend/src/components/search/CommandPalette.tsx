/**
 * Общий поиск и клавиши диспетчера. Палитра по ⌘K (Ctrl+K) ищет сразу по
 * заявкам, инженерам, участкам и районам и по командам экрана: выбрал —
 * и открыт нужный раздел, карточка, а карта наехала на объект. Поле в
 * колонке остаётся местным фильтром списка, палитра места на экране не
 * занимает — в шапке только кнопка-подсказка к ней.
 *
 * Клавиши экрана — `lib/hotkeys`.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { activePlan, useStore, type DialogKind } from '../../store'
import { assignmentIndex, knownRequests } from '../../lib/plan'
import { placeTree, usePlaces } from '../../lib/places'
import { goSection, usePalette } from '../../lib/hotkeys'
import { closeOverlays } from '../Rail'
import { IconSearch } from '../../lib/icons'
import './palette.css'

interface Hit {
  key: string
  group: string
  title: string
  hint?: string
  keys?: string
  run: () => void
}

const LIMIT = 6

export default function CommandPalette({ onPlan, onEvent }: { onPlan: () => void; onEvent: (kind: DialogKind) => void }) {
  const open = usePalette((s) => s.open)
  const setOpen = usePalette((s) => s.setOpen)
  if (!open) return null
  return <Palette onClose={() => setOpen(false)} onPlan={onPlan} onEvent={onEvent} />
}

function Palette({ onClose, onPlan, onEvent }: { onClose: () => void; onPlan: () => void; onEvent: (kind: DialogKind) => void }) {
  const store = useStore()
  const plan = activePlan(store)
  const [query, setQuery] = useState('')
  const [at, setAt] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  const requests = useMemo(() => knownRequests(store.dataset, store.plan), [store.dataset, store.plan])
  const assigned = useMemo(() => assignmentIndex(plan), [plan])
  const tree = useMemo(() => placeTree(store.dataset), [store.dataset])

  const commands: Hit[] = useMemo(
    () => [
      { key: 'go-plan', group: 'Разделы', title: 'Заявки', keys: '1', run: () => goSection('plan') },
      { key: 'go-eng', group: 'Разделы', title: 'Инженеры', keys: '2', run: () => goSection('engineers') },
      ...(plan ? [{ key: 'go-def', group: 'Разделы', title: 'Нагрузка', keys: '3', run: () => goSection('deficit') }] : []),
      { key: 'plan', group: 'Действия', title: store.planning ? 'Считаем…' : 'Спланировать', run: onPlan },
      ...(store.plan
        ? [
            { key: 'new', group: 'Действия', title: 'Новая заявка день в день', run: () => onEvent('new_request') },
            { key: 'urgent', group: 'Действия', title: 'Срочная заявка', run: () => onEvent('urgent') },
          ]
        : []),
      { key: 'col', group: 'Действия', title: 'Поиск в колонке', keys: '/', run: () => window.setTimeout(() => document.querySelector<HTMLInputElement>('.b-col.l [data-col-search]')?.focus(), 0) },
      {
        key: 'rules',
        group: 'Действия',
        title: 'Правила расчёта',
        run: () => {
          closeOverlays()
          useStore.getState().setSettingsOpen(true)
        },
      },
      { key: 'theme', group: 'Действия', title: store.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема', run: store.toggleTheme },
    ],
    [plan, store.plan, store.planning, store.theme, store.toggleTheme, onPlan, onEvent],
  )

  const needle = query.trim().toLowerCase()
  const hits: Hit[] = useMemo(() => {
    if (!needle) return commands
    const out: Hit[] = []
    const names = new Map((store.dataset?.engineers ?? []).map((e) => [e.id, e.name]))
    out.push(
      ...requests
        .filter((r) => r.id.toLowerCase().includes(needle) || r.address.toLowerCase().includes(needle) || r.type_bk.toLowerCase().includes(needle))
        .slice(0, LIMIT)
        .map((r) => ({
          key: `r-${r.id}`,
          group: 'Заявки',
          title: `${r.id} · ${r.type_bk}`,
          hint: `${r.address.replace(/^Москва,\s*/, '')}${assigned.get(r.id) ? ` · ${names.get(assigned.get(r.id)!.engineerId) ?? ''}` : ''}`,
          run: () => {
            const s = useStore.getState()
            goSection('plan')
            if (s.crewView) s.openCrew(null)
            s.setSearch('')
            s.selectRequest(r.id)
            s.selectEngineer(assigned.get(r.id)?.engineerId ?? null)
            s.focusRequest(r.id)
            window.setTimeout(() => document.querySelector(`.b-col.l [role="option"][aria-selected="true"]`)?.scrollIntoView({ block: 'center' }), 60)
          },
        })),
    )
    out.push(
      ...(store.dataset?.engineers ?? [])
        .filter((e) => e.name.toLowerCase().includes(needle) || e.id.toLowerCase().includes(needle))
        .slice(0, LIMIT)
        .map((e) => ({
          key: `e-${e.id}`,
          group: 'Инженеры',
          title: e.name,
          hint: `${plan?.routes.find((route) => route.engineer_id === e.id)?.stops.length ?? 0} визитов${e.sector ? ` · ${store.dataset?.sectors?.find((s) => s.id === e.sector)?.name ?? ''}` : ''}`,
          run: () => {
            closeOverlays()
            useStore.getState().openCrew(e.id)
          },
        })),
    )
    const places: Hit[] = []
    for (const s of tree) {
      if (s.id && s.name.toLowerCase().includes(needle)) {
        places.push({
          key: `s-${s.id}`,
          group: 'Места',
          title: s.name,
          hint: `участок · ${s.count} заявок`,
          run: () => {
            useStore.getState().setSector(s.id)
            usePlaces.getState().setDistricts([])
          },
        })
      }
      for (const d of s.districts) {
        if (!d.name.toLowerCase().includes(needle)) continue
        places.push({
          key: `d-${d.name}`,
          group: 'Места',
          title: d.name,
          hint: `район${s.id ? ` · ${s.name}` : ''} · ${d.count} заявок`,
          run: () => {
            useStore.getState().setSector(null)
            usePlaces.getState().setDistricts([d.name])
          },
        })
      }
    }
    out.push(...places.slice(0, LIMIT))
    out.push(...commands.filter((c) => c.title.toLowerCase().includes(needle)))
    return out
  }, [needle, commands, requests, assigned, store.dataset, plan, tree])

  useEffect(() => {
    listRef.current?.querySelector('.on')?.scrollIntoView({ block: 'nearest' })
  }, [at])

  const run = (hit: Hit | undefined) => {
    if (!hit) return
    onClose()
    hit.run()
  }

  let group = ''
  return (
    <div className="b-pal-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="b-pal" role="dialog" aria-label="Поиск по экрану">
        <label className="b-pal-q">
          <IconSearch />
          <input
            autoFocus
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setAt(0)
            }}
            placeholder="Заявка, адрес, инженер, район или команда"
            aria-label="Поиск"
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setAt(Math.min(hits.length - 1, at + 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setAt(Math.max(0, at - 1))
              } else if (event.key === 'Enter') {
                event.preventDefault()
                run(hits[at])
              } else if (event.key === 'Escape') {
                event.preventDefault()
                event.stopPropagation()
                onClose()
              }
            }}
          />
          <kbd>Esc</kbd>
        </label>
        <div className="b-pal-list b-scroll" ref={listRef} role="listbox">
          {hits.map((hit, i) => {
            const head = hit.group !== group ? hit.group : null
            group = hit.group
            return (
              <div key={hit.key}>
                {head ? <div className="b-pal-g">{head}</div> : null}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === at}
                  className={`b-pal-i${i === at ? ' on' : ''}`}
                  onMouseMove={() => i !== at && setAt(i)}
                  onClick={() => run(hit)}
                >
                  <span>{hit.title}</span>
                  {hit.hint ? <small>{hit.hint}</small> : null}
                  {hit.keys ? <kbd>{hit.keys}</kbd> : null}
                </button>
              </div>
            )
          })}
          {hits.length === 0 ? <p className="b-pal-none">Ничего не нашлось</p> : null}
        </div>
        <div className="b-pal-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> выбрать</span>
          <span><kbd>Enter</kbd> открыть</span>
          <span><kbd>/</kbd> поиск в колонке</span>
          <span><kbd>Esc</kbd> снять выбор</span>
        </div>
      </div>
    </div>
  )
}
