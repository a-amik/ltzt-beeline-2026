/**
 * Поле поиска колонки — одно на разделы «Заявки», «Инженеры», «Нагрузка».
 * Фильтр живёт в самом поле: воронка справа открывает дерево «участок →
 * районы» со строкой быстрого выбора, а выбранное встаёт метками слева,
 * перед текстом. Отдельных рядов кнопок над списком нет.
 *
 * Backspace в пустом поле снимает последнюю метку — как в почтовых адресатах.
 *
 * У «Заявок» в том же окне есть вторая вкладка — «Тип»: вид заявки (авария,
 * ремонт, подключение, дозаказ) и подтипы заказчика внутри («Нет линка»,
 * «Разрывы»…). Выбранное тоже встаёт метками в поле (`lib/kinds.ts`).
 */

import { useMemo, useState, type ReactNode } from 'react'
import { Popup, SegmentedRadioGroup, TextInput } from '@gravity-ui/uikit'
import { useStore } from '../../store'
import { placeTree, useHasPlaces, usePlaces, type PlaceSector } from '../../lib/places'
import { KIND_LABEL, kindKey, kindTree, pickedLabel, subKey, useKinds, type KindNode } from '../../lib/kinds'
import { IconChevron, IconFilter, IconSearch } from '../../lib/icons'
import './search.css'

interface Props {
  value: string
  onUpdate: (value: string) => void
  placeholder: string
  /** Метка перед местами — бригада, в маршруте которой ищут. */
  lead?: ReactNode
  /** Backspace в пустом поле при метке `lead`. */
  onDropLead?: () => void
  /** Вкладка «Тип» в окне фильтра — у «Заявок». */
  kinds?: boolean
}

export default function ColumnSearch({ value, onUpdate, placeholder, lead, onDropLead, kinds = false }: Props) {
  const dataset = useStore((s) => s.dataset)
  const sector = useStore((s) => s.sector)
  const setSector = useStore((s) => s.setSector)
  const districts = usePlaces((s) => s.districts)
  const setDistricts = usePlaces((s) => s.setDistricts)
  const hasPlaces = useHasPlaces()
  const picks = useKinds((s) => s.picked)
  const setPicks = useKinds((s) => s.set)
  const typePicks = kinds ? picks : []
  const [tab, setTab] = useState<'place' | 'type'>(hasPlaces ? 'place' : 'type')
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null)

  const sectorName = dataset?.sectors?.find((s) => s.id === sector)?.name
  const picked = Boolean(sector || districts.length || typePicks.length)

  const chips = (
    <>
      {lead}
      {sectorName ? (
        <button type="button" className="b-tagchip b-placechip" onClick={() => setSector(null)} title="Убрать участок из фильтра">
          <span>{sectorName}</span>
          <b>✕</b>
        </button>
      ) : null}
      {districts.length > 2 ? (
        <button type="button" className="b-tagchip b-placechip" onClick={() => setDistricts([])} title={districts.join(', ')}>
          <span>Районы · {districts.length}</span>
          <b>✕</b>
        </button>
      ) : (
        districts.map((name) => (
          <button
            key={name}
            type="button"
            className="b-tagchip b-placechip"
            onClick={() => setDistricts(districts.filter((d) => d !== name))}
            title="Убрать район из фильтра"
          >
            <span>{name}</span>
            <b>✕</b>
          </button>
        ))
      )}
      {typePicks.length > 2 ? (
        <button type="button" className="b-tagchip b-placechip" onClick={() => setPicks([])} title={typePicks.map(pickedLabel).join(', ')}>
          <span>Типы · {typePicks.length}</span>
          <b>✕</b>
        </button>
      ) : (
        typePicks.map((key) => (
          <button
            key={key}
            type="button"
            className="b-tagchip b-placechip"
            onClick={() => setPicks(typePicks.filter((k) => k !== key))}
            title="Убрать тип из фильтра"
          >
            <span>{pickedLabel(key)}</span>
            <b>✕</b>
          </button>
        ))
      )}
    </>
  )
  const hasChips = Boolean(lead || sectorName || districts.length || typePicks.length)

  return (
    <div className="b-csearch">
      <TextInput
        size="m"
        value={value}
        onUpdate={onUpdate}
        placeholder={sectorName || districts.length || typePicks.length ? 'уточнить' : placeholder}
        hasClear
        controlProps={{ 'data-col-search': '' } as never}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value) {
            event.stopPropagation()
            onUpdate('')
          }
          if (event.key !== 'Backspace' || value) return
          if (typePicks.length) setPicks(typePicks.slice(0, -1))
          else if (districts.length) setDistricts(districts.slice(0, -1))
          else if (sector) setSector(null)
          else onDropLead?.()
        }}
        startContent={
          <span className="b-csearch-chips">
            {hasChips ? null : <IconSearch className="ml-2 text-[var(--b-text-3)]" />}
            {chips}
          </span>
        }
        endContent={
          hasPlaces || kinds ? (
            <button
              ref={setAnchor}
              type="button"
              className={`b-csearch-f${picked ? ' on' : ''}${open ? ' open' : ''}`}
              onClick={() => setOpen(!open)}
              title={kinds ? 'Фильтр: место и тип заявки' : 'Фильтр: участок и район'}
              aria-label={kinds ? 'Фильтр: место и тип заявки' : 'Фильтр: участок и район'}
              aria-expanded={open}
            >
              <IconFilter />
            </button>
          ) : null
        }
      />
      <Popup open={open} onOpenChange={setOpen} anchorElement={anchor} placement={['bottom-end', 'bottom']} offset={{ mainAxis: 6 }}>
        {kinds ? (
          <div className="b-pf-tabs">
            <SegmentedRadioGroup
              size="m"
              width="max"
              value={tab}
              onUpdate={(next) => setTab(next as 'place' | 'type')}
              options={[
                ...(hasPlaces ? [{ value: 'place', content: 'Место' }] : []),
                { value: 'type', content: typePicks.length ? `Тип · ${typePicks.length}` : 'Тип' },
              ]}
            />
          </div>
        ) : null}
        {kinds && tab === 'type' ? (
          <KindFilter tree={kindTree(dataset)} onDone={() => setOpen(false)} />
        ) : (
          <PlaceFilter tree={placeTree(dataset)} onDone={() => setOpen(false)} />
        )}
      </Popup>
    </div>
  )
}

/** Дерево мест: участок раскрывается в районы; строка сверху ищет по обоим. */
function PlaceFilter({ tree, onDone }: { tree: PlaceSector[]; onDone: () => void }) {
  const sector = useStore((s) => s.sector)
  const setSector = useStore((s) => s.setSector)
  const districts = usePlaces((s) => s.districts)
  const toggleDistrict = usePlaces((s) => s.toggleDistrict)
  const setDistricts = usePlaces((s) => s.setDistricts)
  const [query, setQuery] = useState('')
  const flat = tree.length === 1 && tree[0].id === null
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(flat ? [''] : sector ? [sector] : []))

  const needle = query.trim().toLowerCase()
  const found = useMemo(() => {
    if (!needle) return null
    const out: { kind: 'sector' | 'district'; name: string; id: string | null; hint: string; count: number }[] = []
    for (const s of tree) {
      if (s.id && s.name.toLowerCase().includes(needle)) out.push({ kind: 'sector', name: s.name, id: s.id, hint: `${s.districts.length} районов`, count: s.count })
      for (const d of s.districts) {
        if (d.name.toLowerCase().includes(needle)) out.push({ kind: 'district', name: d.name, id: s.id, hint: s.id ? s.name : '', count: d.count })
      }
    }
    return out
  }, [needle, tree])

  const pickSector = (id: string | null) => {
    setSector(sector === id ? null : id)
    setDistricts([])
  }
  // Район из другого участка — участок снимается: иначе фильтр пустой.
  const pickDistrict = (name: string, owner: string | null) => {
    if (sector && owner !== sector) setSector(null)
    toggleDistrict(name)
  }

  const district = (name: string, count: number, owner: string | null, hint?: string) => (
    <button
      key={name}
      type="button"
      role="menuitemcheckbox"
      aria-checked={districts.includes(name)}
      className={`b-pf-row d${districts.includes(name) ? ' on' : ''}`}
      onClick={() => pickDistrict(name, owner)}
    >
      <i className="b-pf-box" />
      <span>{name}</span>
      {hint ? <small>{hint}</small> : null}
      <em>{count}</em>
    </button>
  )

  return (
    <div className="b-pf" role="menu" aria-label="Участок и район">
      <div className="b-pf-q">
        <TextInput
          size="m"
          value={query}
          onUpdate={setQuery}
          placeholder={flat ? 'Район' : 'Участок или район'}
          autoFocus
          hasClear
          onKeyDown={(event) => {
            if (event.key === 'Enter' && found?.length) {
              const first = found[0]
              if (first.kind === 'sector') pickSector(first.id)
              else pickDistrict(first.name, first.id)
              setQuery('')
            }
          }}
          startContent={<IconSearch className="ml-2 text-[var(--b-text-3)]" />}
        />
      </div>
      <div className="b-pf-list b-scroll">
        {found ? (
          found.length ? (
            found.map((item) =>
              item.kind === 'sector' ? (
                <button
                  key={`s-${item.id}`}
                  type="button"
                  role="menuitemradio"
                  aria-checked={sector === item.id}
                  className={`b-pf-row s${sector === item.id && !districts.length ? ' on' : ''}`}
                  onClick={() => pickSector(item.id)}
                >
                  <span>{item.name}</span>
                  <small>{item.hint}</small>
                  <em>{item.count}</em>
                </button>
              ) : (
                district(item.name, item.count, item.id, item.hint)
              ),
            )
          ) : (
            <p className="b-pf-none">Ничего не нашлось</p>
          )
        ) : (
          tree.map((s) => {
            const key = s.id ?? ''
            const open = expanded.has(key)
            return (
              <div key={key}>
                {flat ? null : (
                  <div className={`b-pf-row s${sector === s.id && !districts.length ? ' on' : ''}`}>
                    <button
                      type="button"
                      className="b-pf-tw"
                      aria-expanded={open}
                      aria-label={open ? `Свернуть ${s.name}` : `Районы участка ${s.name}`}
                      onClick={() => {
                        const next = new Set(expanded)
                        if (open) next.delete(key)
                        else next.add(key)
                        setExpanded(next)
                      }}
                    >
                      <IconChevron className={open ? '' : 'shut'} />
                    </button>
                    <button type="button" className="b-pf-lb" role="menuitemradio" aria-checked={sector === s.id} onClick={() => pickSector(s.id)}>
                      <span>{s.name}</span>
                      <em>{s.count}</em>
                    </button>
                  </div>
                )}
                {open ? <div className={flat ? '' : 'b-pf-sub'}>{s.districts.map((d) => district(d.name, d.count, s.id))}</div> : null}
              </div>
            )
          })
        )}
      </div>
      <div className="b-pf-foot">
        <button
          type="button"
          disabled={!sector && !districts.length}
          onClick={() => {
            setSector(null)
            setDistricts([])
          }}
        >
          Сбросить
        </button>
        <button type="button" className="ok" onClick={onDone}>
          Готово
        </button>
      </div>
    </div>
  )
}

/** Типы заявок: вид раскрывается в подтипы заказчика; строка сверху ищет по обоим. */
function KindFilter({ tree, onDone }: { tree: KindNode[]; onDone: () => void }) {
  const picked = useKinds((s) => s.picked)
  const toggle = useKinds((s) => s.toggle)
  const set = useKinds((s) => s.set)
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(tree.filter((n) => n.kind === 'repair').map((n) => n.kind)))
  const needle = query.trim().toLowerCase()

  const row = (key: string, name: string, count: number, cls: string, hint?: string) => (
    <button
      key={key}
      type="button"
      role="menuitemcheckbox"
      aria-checked={picked.includes(key)}
      className={`b-pf-row ${cls}${picked.includes(key) ? ' on' : ''}`}
      onClick={() => toggle(key)}
    >
      <i className="b-pf-box" />
      <span>{name}</span>
      {hint ? <small>{hint}</small> : null}
      <em>{count}</em>
    </button>
  )

  return (
    <div className="b-pf" role="menu" aria-label="Тип заявки">
      <div className="b-pf-q">
        <TextInput
          size="m"
          value={query}
          onUpdate={setQuery}
          placeholder="Тип или подтип: нет линка, разрывы…"
          autoFocus
          hasClear
          startContent={<IconSearch className="ml-2 text-[var(--b-text-3)]" />}
        />
      </div>
      <div className="b-pf-list b-scroll">
        {needle ? (
          (() => {
            const found = tree.flatMap((node) => [
              ...(KIND_LABEL[node.kind].toLowerCase().includes(needle)
                ? [row(kindKey(node.kind), KIND_LABEL[node.kind], node.count, 's')]
                : []),
              ...node.subs
                .filter((sub) => sub.name.toLowerCase().includes(needle))
                .map((sub) => row(subKey(node.kind, sub.name), sub.name, sub.count, 'd', KIND_LABEL[node.kind])),
            ])
            return found.length ? found : <p className="b-pf-none">Ничего не нашлось</p>
          })()
        ) : (
          tree.map((node) => {
            const open = expanded.has(node.kind)
            return (
              <div key={node.kind}>
                <div className={`b-pf-row s${picked.includes(kindKey(node.kind)) ? ' on' : ''}`}>
                  <button
                    type="button"
                    className="b-pf-tw"
                    aria-expanded={open}
                    aria-label={open ? `Свернуть ${KIND_LABEL[node.kind]}` : `Подтипы: ${KIND_LABEL[node.kind]}`}
                    onClick={() => {
                      const next = new Set(expanded)
                      if (open) next.delete(node.kind)
                      else next.add(node.kind)
                      setExpanded(next)
                    }}
                  >
                    <IconChevron className={open ? '' : 'shut'} />
                  </button>
                  <button
                    type="button"
                    className="b-pf-lb"
                    role="menuitemcheckbox"
                    aria-checked={picked.includes(kindKey(node.kind))}
                    onClick={() => toggle(kindKey(node.kind))}
                  >
                    <span>{KIND_LABEL[node.kind]}</span>
                    <em>{node.count}</em>
                  </button>
                </div>
                {open ? <div className="b-pf-sub">{node.subs.map((sub) => row(subKey(node.kind, sub.name), sub.name, sub.count, 'd'))}</div> : null}
              </div>
            )
          })
        )}
      </div>
      <div className="b-pf-foot">
        <button type="button" disabled={!picked.length} onClick={() => set([])}>
          Сбросить
        </button>
        <button type="button" className="ok" onClick={onDone}>
          Готово
        </button>
      </div>
    </div>
  )
}
