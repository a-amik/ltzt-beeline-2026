/**
 * Детали бригады — раскрываются в панели инженеров под строкой бригады,
 * на телефоне — шторкой снизу; открывает их клик по бригаде или запись ленты.
 * Всё, что про неё известно, в одном месте: транспорт и откуда стартует,
 * визиты и норма, бонус и пробег, маршрут адресами по порядку визитов,
 * запас устройств, где ждать между визитами, вопросы контроля и переписка.
 *
 * Здесь же действия с бригадой: задержка и выбытие уходят событием в пачку,
 * «Написать» открывает переписку. Раньше они жили в шапке правой колонки,
 * где их никто не находил.
 */

import { useMemo, useState } from 'react'
import { Button, Label } from '@gravity-ui/uikit'
import { activePlan, useStore } from '../store'
import { colorIndex, colorVar } from '../lib/colors'
import { num } from '../lib/ui'
import { IconClock, IconClose, IconPhone, IconUserOff } from '../lib/icons'
import DispatcherChat from '../crew/DispatcherChat'
import { KIND_RU, useFeed } from './useFeed'
import './dispatch.css'

const MODE: Record<string, string> = { car: 'машина', foot: 'пешком', bike: 'велосипед', transit: 'транспорт' }
const cap = (text: string) => (text ? text[0].toUpperCase() + text.slice(1) : text)
const KIT: Record<string, string> = { router: 'роутер', tv_box: 'приставка', speaker: 'колонка' }

export default function CrewCard({ engineerId, embedded = false }: { engineerId: string; embedded?: boolean }) {
  const store = useStore()
  const plan = activePlan(store)
  const dataset = store.dataset
  const feed = useFeed()
  const [chat, setChat] = useState(false)
  const engineer = dataset?.engineers.find((e) => e.id === engineerId)
  const route = plan?.routes.find((r) => r.engineer_id === engineerId) ?? null
  const order = useMemo(() => (dataset?.engineers ?? []).map((e) => e.id), [dataset])
  const byId = useMemo(() => new Map((dataset?.requests ?? []).map((r) => [r.id, r])), [dataset])
  if (!engineer || !dataset) return null

  const stops = route?.stops ?? []
  const late = stops.filter((s) => s.late_min > 0).length
  const options = ((plan?.settings as { options?: Record<string, unknown> } | undefined)?.options ?? {}) as Record<string, unknown>
  const zoned = Boolean(engineer.anchor_name) && options.zone_start !== false
  const start = zoned
    ? options.zone_start_point === 'home'
      ? `дом в районе «${engineer.anchor_name}»`
      : `опорная точка «${engineer.anchor_name}»`
    : plan?.start === 'home'
      ? engineer.home?.address ? `дом, ${engineer.home.address}` : 'дом'
      : 'офис'
  const stock = plan?.stock?.[engineerId] ?? {}
  const used: Record<string, number> = {}
  for (const s of stops) {
    if (s.status === 'no_show') continue
    for (const d of byId.get(s.request_id)?.equipment ?? []) used[d] = (used[d] ?? 0) + 1
  }
  const left = Object.entries(stock)
    .map(([d, n]) => [d, n - (used[d] ?? 0)] as const)
    .filter(([, n]) => n > 0)
  const waits = (plan?.standby ?? []).filter((w) => w.engineer_id === engineerId)
  const mine = (feed.data?.items ?? []).filter((i) => i.engineer_id === engineerId)
  const flags = mine.filter((i) => i.kind === 'flag')
  const talk = mine.filter((i) => i.kind !== 'flag').slice(0, 4)
  const color = colorVar(colorIndex(engineerId, order))

  return (
    <section className={`b-crewcard${embedded ? ' embedded' : ''}`} style={{ ['--c' as string]: color }} aria-label={`Бригада ${engineer.name}`}>
      {embedded ? null : (
        <header>
          <i />
          <h3>{engineer.name}</h3>
          <Button view="flat" size="s" onClick={() => store.openCrew(null)} title="Закрыть детали бригады">
            <IconClose />
          </Button>
        </header>
      )}
      <p className="b-crewcard-sub">
        {/* Каждая часть между точками начинается с прописной: строка читается перечнем, а не одной фразой. */}
        {cap((engineer.transports ?? [engineer.transport]).map((t) => MODE[t] ?? t).join(', '))} · Старт — {start} · Смена{' '}
        {engineer.shift_start}–{engineer.shift_end}
        {engineer.extra_load === false ? ' · Сверх нормы не берёт' : ''}
      </p>
      <dl className="b-crewcard-kpi">
        <div>
          <dt>Визитов</dt>
          <dd>{stops.length}</dd>
        </div>
        <div>
          <dt>Норма</dt>
          <dd>{route?.norm_min ?? 0} мин</dd>
        </div>
        <div className={late ? 'bad' : ''}>
          <dt>Пробег</dt>
          <dd>
            {num(route?.distance_km ?? 0, 1)} км{late ? ` · опозданий ${late}` : ''}
          </dd>
        </div>
      </dl>
      {stops.length ? (
        // Маршрут адресами по порядку визитов: диспетчер видит день бригады
        // целиком, не переключаясь на список заявок. Строка открывает заявку на карте.
        <ol className="b-crewroute" aria-label="Маршрут по адресам">
          {stops.map((stop, index) => {
            const request = byId.get(stop.request_id)
            const noShow = stop.status === 'no_show'
            const on = store.selectedRequestId === stop.request_id
            return (
              <li key={stop.request_id}>
                <button
                  type="button"
                  className={`${on ? 'on' : ''}${stop.late_min > 0 ? ' late' : ''}${noShow ? ' off' : ''}`}
                  aria-pressed={on}
                  onClick={() => {
                    store.selectRequest(on ? null : stop.request_id)
                    if (!on) store.focusRequest(stop.request_id)
                  }}
                >
                  <i>{index + 1}</i>
                  <time>{stop.start}</time>
                  <span className="a" title={request?.address}>
                    {request?.address ?? stop.request_id}
                  </span>
                  <span className="w">
                    {request ? `окно ${request.window_start}–${request.window_end}` : ''}
                    {noShow ? ' · клиента нет' : stop.late_min > 0 ? ` · опоздание ${stop.late_min} мин` : ''}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="b-crewcard-line muted">Визитов в плане нет.</p>
      )}
      {left.length ? (
        <p className="b-crewcard-line">
          Запас под заявки дня: {left.map(([d, n]) => `${KIT[d] ?? d} × ${n}`).join(', ')}
        </p>
      ) : null}
      {route?.break_start ? (
        <p className="b-crewcard-line">
          Обед {route.break_start}–{route.break_end}
        </p>
      ) : null}
      {waits.length ? (
        <ul className="b-crewcard-list">
          {waits.map((w) => (
            <li key={`${w.after_request_id}-${w.start}`}>
              <time>
                {w.start}–{w.end}
              </time>
              {w.text}
            </li>
          ))}
        </ul>
      ) : null}
      {flags.length ? (
        <ul className="b-crewcard-list warn">
          {flags.map((f) => (
            <li key={f.id}>{f.text}</li>
          ))}
        </ul>
      ) : null}
      {talk.length ? (
        <ul className="b-crewcard-list talk">
          {talk.map((m) => (
            <li key={m.id} className={`${m.kind}${m.unread ? ' unread' : ''}`}>
              <time>{m.time}</time>
              <Label size="xs" theme={m.kind === 'sos' || m.kind === 'problem' ? 'danger' : m.kind === 'delay' ? 'warning' : 'normal'}>
                {m.author === 'dispatcher' ? 'вы' : (KIND_RU[m.kind] ?? m.kind).toLowerCase()}
              </Label>
              {m.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="b-crewcard-line muted">Бригада пока ничего не писала.</p>
      )}
      {store.offline ? null : (
        <div className="b-crewcard-acts">
          <Button view="action" size="m" onClick={() => setChat(true)}>
            Написать
          </Button>
          {store.plan ? (
            <>
              <Button view="outlined" size="m" onClick={() => store.openDialog('delay')} title="Бригада задерживается">
                <span className="flex items-center gap-1">
                  <IconClock />
                  Задержка
                </span>
              </Button>
              <Button view="flat-danger" size="m" onClick={() => store.openDialog('engineer_off')} title="Бригада выбывает до конца дня">
                <span className="flex items-center gap-1">
                  <IconUserOff />
                  Выбыла
                </span>
              </Button>
            </>
          ) : null}
          <a className="b-crewcard-app" href={`#crew/${engineerId}`} target="_blank" rel="noreferrer" title="Приложение бригады">
            <IconPhone />
          </a>
        </div>
      )}
      {chat ? (
        <DispatcherChat region={dataset.id} engineerId={engineerId} name={engineer.name} onClose={() => setChat(false)} />
      ) : null}
    </section>
  )
}
