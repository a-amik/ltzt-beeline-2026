/**
 * Лента от бригад — одно место, где диспетчер видит всё, что бригады
 * сообщили: SOS, «проблема на заявке», «задерживаюсь», сообщения, звонки
 * клиентам и вопросы контроля по отметкам. Новое сверху; то, что требует
 * ответа, помечено цветом. Нажатие открывает детали бригады слева —
 * там же её маршрут, переписка и действия.
 *
 * Открывается колокольчиком в верхней полосе: число на нём — непрочитанное,
 * красное — если среди него SOS, проблема или задержка.
 */

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { crewApi, type FeedItem } from '../crew/crewApi'
import { useStore } from '../store'
import { IconBell } from '../lib/icons'
import { KIND_RU, useFeed } from './useFeed'
import './dispatch.css'

type Filter = 'all' | 'act' | 'flag'

export function FeedButton({ size = 'l' }: { size?: 'm' | 'l' }) {
  const feed = useFeed()
  const open = useStore((s) => s.feedOpen)
  const setOpen = useStore((s) => s.setFeedOpen)
  const unread = feed.data?.unread ?? 0
  const urgent = feed.data?.urgent ?? 0
  return (
    <Button
      view="flat"
      size={size}
      onClick={() => setOpen(!open)}
      title="Лента от бригад: сообщения, проблемы, задержки, контроль"
      aria-label={`Лента от бригад${unread ? `, новых ${unread}` : ''}`}
    >
      <span className="b-bell">
        <IconBell />
        {unread ? <b className={urgent ? 'hot' : ''}>{unread}</b> : null}
      </span>
    </Button>
  )
}

export default function FeedPanel() {
  const store = useStore()
  const client = useQueryClient()
  const feed = useFeed()
  const [filter, setFilter] = useState<Filter>('all')
  if (!store.feedOpen) return null
  const items = (feed.data?.items ?? []).filter((item) =>
    filter === 'all' ? true : filter === 'flag' ? item.kind === 'flag' : ['sos', 'problem', 'delay'].includes(item.kind),
  )
  const open = (item: FeedItem) => {
    store.openCrew(item.engineer_id)
    store.setFeedOpen(false)
    if (item.unread) {
      crewApi
        .read(store.datasetId, item.engineer_id, 'dispatcher')
        .then(() => client.invalidateQueries({ queryKey: ['feed', store.datasetId] }))
        .catch(() => undefined)
    }
  }
  return (
    <div className="b-feed-scrim" onClick={() => store.setFeedOpen(false)}>
      <aside className="b-feed" role="dialog" aria-label="Лента от бригад" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Лента от бригад</h2>
          <button type="button" onClick={() => store.setFeedOpen(false)} aria-label="Закрыть">
            ✕
          </button>
        </header>
        <div className="b-feed-filter" role="tablist">
          {(
            [
              ['all', 'Всё'],
              ['act', 'Требует ответа'],
              ['flag', 'Контроль'],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={filter === key} onClick={() => setFilter(key)}>
              {label}
            </button>
          ))}
        </div>
        <ol>
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" className={`${item.kind}${item.unread ? ' unread' : ''}`} onClick={() => open(item)}>
                <span className="k">{KIND_RU[item.kind] ?? item.kind}</span>
                <b>{item.engineer}</b>
                <time>{item.time}</time>
                <span className="t">
                  {item.author === 'dispatcher' ? 'Вы: ' : ''}
                  {item.text}
                  {item.request_id ? ` · заявка ${item.request_id}` : ''}
                </span>
              </button>
            </li>
          ))}
          {!items.length ? (
            <li className="empty">
              {feed.isError ? 'Сервер не ответил' : 'Бригады пока ничего не сообщали'}
            </li>
          ) : null}
        </ol>
      </aside>
    </div>
  )
}
