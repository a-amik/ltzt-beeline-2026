/**
 * Вкладки приложения бригады кроме смены: BeeGPT — переписка
 * по смене с диспетчером, поданная как помощник, — и профиль — адреса старта, история смен, отзывы.
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, TextInput } from '@gravity-ui/uikit'
import { num, plural } from '../lib/ui'
import { IconClose, IconPlus, IconStar } from '../lib/icons'
import BeeMark from '../components/settings/BeeMark'
import { crewApi, type Address, type CrewProfile } from './crewApi'

const QUICK = ['Буду через 10 минут', 'Задерживаюсь на предыдущей заявке', 'Клиент перенёс время', 'Нужна помощь по заявке']

export function ChatTab({ region, engineerId, requestId }: { region: string; engineerId: string; requestId: string | null }) {
  const client = useQueryClient()
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const messages = useQuery({
    queryKey: ['crew-chat', region, engineerId],
    queryFn: () => crewApi.messages(region, engineerId),
    refetchInterval: 4000,
  })
  const say = useMutation({
    mutationFn: (body: { text: string; kind?: 'text' | 'sos' }) =>
      crewApi.say(region, engineerId, { ...body, request_id: requestId }),
    onSuccess: () => {
      setText('')
      void client.invalidateQueries({ queryKey: ['crew-chat', region, engineerId] })
    },
  })
  const list = messages.data ?? []
  useEffect(() => {
    const data = messages.data ?? []
    if (data.some((m) => m.author === 'dispatcher' && !m.read)) void crewApi.read(region, engineerId, 'crew')
    end.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.data, region, engineerId])
  return (
    <div className="b-crew-body b-chat">
      <header className="b-help-top b-chat-top">
        <BeeMark size={28} className="b-help-mark" />
        <div className="b-help-name">
          <b>BeeGPT</b>
        </div>
      </header>
      <p className="b-crew-muted">Вопросы по смене и заявкам. Звонки клиентам ложатся сюда же отметкой — без номеров.</p>
      <ol className="b-chat-list" aria-live="polite">
        {list.map((m) => (
          <li key={m.id} className={`${m.author} ${m.kind}`}>
            <span>{m.text}</span>
            <time>
              {m.time}
              {m.request_id ? ` · заявка ${m.request_id}` : ''}
            </time>
          </li>
        ))}
        {!list.length ? <li className="empty">Сообщений пока нет</li> : null}
      </ol>
      <div ref={end} />
      <div className="b-chat-quick">
        {QUICK.map((q) => (
          <button key={q} type="button" onClick={() => say.mutate({ text: q })}>
            {q}
          </button>
        ))}
      </div>
      <form
        className="b-chat-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim()) say.mutate({ text: text.trim() })
        }}
      >
        <TextInput size="l" value={text} onUpdate={setText} placeholder="Спросите BeeGPT" />
        <Button type="submit" view="action" size="l" disabled={!text.trim() || say.isPending}>
          Отправить
        </Button>
      </form>
    </div>
  )
}

export function ProfileTab({ region, engineerId, name, children }: {
  region: string
  engineerId: string
  name: string
  children?: React.ReactNode
}) {
  const client = useQueryClient()
  const profile = useQuery({ queryKey: ['crew-profile', region, engineerId], queryFn: () => crewApi.profile(region, engineerId) })
  const history = useQuery({ queryKey: ['crew-history', region, engineerId], queryFn: () => crewApi.history(region, engineerId), staleTime: Infinity })
  const save = useMutation({
    mutationFn: (next: CrewProfile) => crewApi.saveProfile(region, engineerId, next),
    onSuccess: (saved) => client.setQueryData(['crew-profile', region, engineerId], saved),
  })
  const data = profile.data
  const starting = data?.addresses.find((a) => a.id === data.start_id)
  const h = history.data
  const earned = h ? h.days.reduce((s, d) => s + d.earned_rub, 0) : 0
  return (
    <div className="b-crew-body">
      <section className="b-crew-card b-profile-head">
        <b>{name}</b>
        {h ? (
          <span>
            <IconStar className="b-i-fill" />
            {h.rating.toFixed(2).replace('.', ',')} · {h.reviews_count} {plural(h.reviews_count, 'отзыв', 'отзыва', 'отзывов')}
          </span>
        ) : null}
      </section>

      <section className="b-crew-card">
        <h3>Откуда начинаю день</h3>
        <p className="b-crew-muted">
          Адресов может быть несколько: дом, дача, в гостях. Выбранный войдёт в следующий план — сегодняшний маршрут не
          меняется.
        </p>
        {data ? (
          <ul className="b-addr" role="radiogroup" aria-label="Адрес старта">
            {data.addresses.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={a.id === data.start_id}
                  className={a.id === data.start_id ? 'on' : ''}
                  onClick={() => save.mutate({ ...data, start_id: a.id })}
                >
                  <b>{a.label}</b>
                  <em>{a.address}</em>
                </button>
                {a.id !== 'home' ? (
                  <button
                    type="button"
                    className="b-addr-x"
                    aria-label={`Удалить адрес ${a.label}`}
                    onClick={() => save.mutate({ ...data, addresses: data.addresses.filter((x) => x.id !== a.id) })}
                  >
                    <IconClose />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="b-crew-muted">Загружаем адреса…</p>
        )}
        {starting && data?.since ? (
          <p className="b-addr-note">
            Со следующего плана: старт «{starting.label}». Выбрано {data.since.slice(11, 16)}
            {data.since_plan ? `, план ${data.since_plan} идёт как шёл` : ''}.
          </p>
        ) : null}
        {data ? <AddAddress onAdd={(a) => save.mutate({ ...data, addresses: [...data.addresses, a] })} /> : null}
      </section>

      {h ? (
        <section className="b-crew-card">
          <h3>Две недели</h3>
          <p className="b-crew-muted">
            {h.days.length} {plural(h.days.length, 'смена', 'смены', 'смен')} · {num(earned)} ₽ · визитов вовремя{' '}
            {Math.round((100 * h.days.reduce((s, d) => s + d.on_time, 0)) / Math.max(1, h.days.reduce((s, d) => s + d.visits, 0)))} %
          </p>
          <ol className="b-history">
            {[...h.days].reverse().map((d) => (
              <li key={d.date}>
                <time>{new Date(`${d.date}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', weekday: 'short' })}</time>
                <span>
                  {d.visits} {plural(d.visits, 'визит', 'визита', 'визитов')} · {num(d.km, 0)} км
                </span>
                <b>{num(d.earned_rub)} ₽</b>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {h ? (
        <section className="b-crew-card">
          <h3>Отзывы клиентов</h3>
          <ul className="b-reviews">
            {h.reviews.map((r, i) => (
              <li key={i}>
                <span className="b-stars" role="img" aria-label={`${r.stars} из 5`}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <IconStar key={n} className={n <= r.stars ? 'b-i-fill' : 'off'} />
                  ))}
                </span>
                <p>{r.text}</p>
                <em>
                  {r.type_bk} · {new Date(`${r.date}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}
                </em>
              </li>
            ))}
          </ul>
          <p className="b-crew-muted">История и отзывы — синтетика для показа.</p>
        </section>
      ) : null}
      {children}
    </div>
  )
}

function AddAddress({ onAdd }: { onAdd: (address: Address) => void }) {
  // Поля появляются по кнопке: в карточке постоянно стоят сами адреса.
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      const found = await crewApi.geocode(text)
      onAdd({ id: `a${Date.now()}`, label: label.trim() || 'Адрес', address: text.trim(), lat: found.lat, lon: found.lon })
      setLabel('')
      setText('')
      setOpen(false)
    } catch (e) {
      setError(`Адрес не нашёлся: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }
  if (!open)
    return (
      <Button view="outlined" size="l" width="max" className="b-addr-open" onClick={() => setOpen(true)}>
        <IconPlus />
        Добавить адрес
      </Button>
    )
  return (
    <form
      className="b-addr-add"
      onSubmit={(event) => {
        event.preventDefault()
        if (text.trim()) void add()
      }}
    >
      <TextInput size="l" value={label} onUpdate={setLabel} placeholder="Название: дача, у мамы" autoFocus />
      <TextInput size="l" value={text} onUpdate={setText} placeholder="Адрес: город, улица, дом" />
      <div className="b-addr-add-acts">
        <Button
          view="flat"
          size="l"
          onClick={() => {
            setOpen(false)
            setError(null)
          }}
        >
          Отмена
        </Button>
        <Button type="submit" view="action" size="l" loading={busy} disabled={!text.trim()}>
          Сохранить
        </Button>
      </div>
      {error ? <p className="b-crew-muted">{error}</p> : null}
    </form>
  )
}
