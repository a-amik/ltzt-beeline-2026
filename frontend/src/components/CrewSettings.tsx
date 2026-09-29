/**
 * Бригады: дом, набор транспорта и согласие на нагрузку сверх нормы — по каждой.
 * Заказчик профилей бригад не давал, набор в датасете синтетический; здесь
 * руководитель задаёт свой, и диспетчер видит, как меняется план. Адрес дома ищется
 * геокодером сервера (Nominatim с кэшем), координаты можно поправить руками.
 *
 * Правки живут в общих правилах дня (`settings.crews`): их задаёт руководитель
 * на своём экране, сервер хранит и ставит под расчёт (`PUT /rules`). Диспетчер
 * видит эту вкладку только для чтения.
 */

import { useState } from 'react'
import { Button, Checkbox, Switch, TextInput } from '@gravity-ui/uikit'
import { api } from '../api'
import type { Engineer, Settings, Transport } from '../types'

const MODES: { value: Transport; label: string }[] = [
  { value: 'car', label: 'Авто' },
  { value: 'foot', label: 'Пешком' },
  { value: 'bike', label: 'Вело' },
  { value: 'transit', label: 'Общественный' },
]

export interface CrewOverride {
  home?: { lat: number; lon: number; address?: string }
  transports?: Transport[]
  extra_load?: boolean
}

export type Crews = Record<string, CrewOverride>

export function crewsOf(settings: Settings): Crews {
  const raw = settings.crews
  return raw && typeof raw === 'object' ? (raw as Crews) : {}
}

interface Props {
  /** Без своей шапки — на экране «Настройки» её несёт карточка группы. */
  plain?: boolean
  engineers: Engineer[]
  crews: Crews
  onChange: (crews: Crews) => void
}

export default function CrewSettings({ plain = false, engineers, crews, onChange }: Props) {
  const update = (id: string, patch: Partial<CrewOverride> | null) => {
    const next = { ...crews }
    if (patch === null) delete next[id]
    else next[id] = { ...(next[id] ?? {}), ...patch }
    onChange(next)
  }
  if (plain) {
    return (
      <div className="b-st-crews">
        {engineers.map((engineer) => (
          <CrewRow key={engineer.id} engineer={engineer} own={crews[engineer.id] ?? {}} onChange={(patch) => update(engineer.id, patch)} />
        ))}
      </div>
    )
  }
  return (
    <section className="b-set-group">
      <h3>Бригады: дом, транспорт, нагрузка</h3>
      <p className="b-set-hint" style={{ marginBottom: 12 }}>
        Набор в датасете синтетический: 60 % бригад пешком и на общественном транспорте, 25 % на машине,
        15 % на велосипеде. Дом — ближайший дом к центру заявок бригады в контрольном распределении: адрес
        условный, заказчик домов не давал. Здесь можно задать свой.
      </p>
      {engineers.map((engineer) => (
        <CrewRow
          key={engineer.id}
          engineer={engineer}
          own={crews[engineer.id] ?? {}}
          onChange={(patch) => update(engineer.id, patch)}
        />
      ))}
    </section>
  )
}

function CrewRow({
  engineer,
  own,
  onChange,
}: {
  engineer: Engineer
  own: CrewOverride
  onChange: (patch: Partial<CrewOverride> | null) => void
}) {
  const transports = own.transports ?? engineer.transports ?? [engineer.transport]
  const home = own.home ?? (engineer.home ? { lat: engineer.home.lat, lon: engineer.home.lon } : undefined)
  const [address, setAddress] = useState(own.home?.address ?? engineer.home?.address ?? '')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const changed = Object.keys(own).length > 0

  const find = async () => {
    if (!address.trim()) return
    setBusy(true)
    setNote(null)
    try {
      const hit = await api.geocode(address.trim())
      onChange({ home: { lat: hit.lat, lon: hit.lon, address: address.trim() } })
      setNote(hit.quality === 'house' ? 'Найден дом' : hit.quality === 'street' ? 'Найдена улица, дом не найден' : 'Найден только район')
    } catch {
      setNote('Адрес не нашёлся: Москва и область, улица и дом')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (mode: Transport, on: boolean) => {
    const next = MODES.map((m) => m.value).filter((m) => (m === mode ? on : transports.includes(m)))
    if (next.length) onChange({ transports: next })
  }

  return (
    <div className="b-crew-row">
      <div className="b-crew-row-head">
        <b>{engineer.name}</b>
        <span className="b-set-hint">
          смена {engineer.shift_start}–{engineer.shift_end}
          {home && !address ? ` · дом ${home.lat.toFixed(4)}, ${home.lon.toFixed(4)}` : ''}
        </span>
        {changed ? (
          <button type="button" className="b-set-reset" onClick={() => onChange(null)} title="Вернуть набор датасета">
            вернуть
          </button>
        ) : null}
      </div>
      <div className="b-crew-row-home">
        <TextInput
          size="m"
          value={address}
          onUpdate={setAddress}
          placeholder="Адрес дома: город, улица, дом"
          hasClear
          onKeyDown={(event) => {
            if (event.key === 'Enter') void find()
          }}
        />
        <Button view="outlined" size="m" onClick={() => void find()} disabled={busy || !address.trim()} loading={busy}>
          Найти
        </Button>
      </div>
      {note ? <small className="b-set-hint">{note}</small> : null}
      <div className="b-crew-row-modes">
        {MODES.map((mode) => (
          <Checkbox
            key={mode.value}
            size="m"
            checked={transports.includes(mode.value)}
            content={mode.label}
            onUpdate={(on) => toggle(mode.value, on)}
          />
        ))}
        <Switch
          size="m"
          checked={own.extra_load ?? engineer.extra_load ?? true}
          onUpdate={(on) => onChange({ extra_load: on })}
          content="сверх нормы"
        />
      </div>
    </div>
  )
}
