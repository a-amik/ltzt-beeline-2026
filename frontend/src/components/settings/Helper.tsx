/**
 * Помощник настроек — колонка справа на экране «Настройки». Переключателей
 * на экране много, а диспетчер думает не переключателями, а своим днём:
 * «мало бригад, много аварий», «клиенты жалуются на опоздания». Помощник
 * узнаёт в этих словах ситуацию (`recipes.ts`), объясняет подход и показывает,
 * какие настройки поменяет: было → станет. Ничего не меняет без «Применить»;
 * применённое ложится в форму как обычная правка — с «вернуть» у поля
 * и панелью «Сохранить» внизу, — и его можно откатить одной кнопкой.
 *
 * Это демонстрация: подход подбирается по ключевым словам в браузере,
 * без сервера. Пока BeeGPT «думает», знак в ленте пишет строки и вспыхивает искрой;
 * знак в шапке стоит: движение одно, там, куда придёт ответ.
 */

import { useEffect, useRef, useState } from 'react'
import { Button, TextInput } from '@gravity-ui/uikit'
import type { SettingsField } from '../../types'
import { IconArrowRight, IconClose } from '../../lib/icons'
import BeeMark, { ANSWER_AT } from './BeeMark'
import { EXAMPLES, match, propose, show, type Change } from './recipes'

interface Message {
  id: number
  from: 'me' | 'bot'
  text: string
  changes?: Change[]
  /** Подсказки-примеры под ответом, когда ситуация не узнана. */
  examples?: boolean
  state?: 'offered' | 'applied' | 'undone' | 'declined'
}

interface Props {
  fields: SettingsField[]
  valueOf: (field: SettingsField) => unknown
  /** Поставить значения в форму; `focus` — поле, к которому прокрутить. */
  onApply: (values: { field: SettingsField; value: unknown }[], focus: SettingsField) => void
  readOnly?: boolean
  onClose?: () => void
}

const GREETING =
  'Расскажите своими словами, какой сегодня день: что мешает, что важнее всего. Подберу подход и покажу, какие настройки поменять. Без вашего «Применить» ничего не меняю.'

let seq = 0

export default function Helper({ fields, valueOf, onApply, readOnly, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([{ id: ++seq, from: 'bot', text: GREETING, examples: true }])
  const [text, setText] = useState('')
  const [thinking, setThinking] = useState(false)
  const [typed, setTyped] = useState<{ id: number; words: number } | null>(null)
  const list = useRef<HTMLDivElement>(null)
  // Ответ собирается в миг, когда кончилась «мысль»: к тому времени форма могла поменяться.
  const latest = useRef({ fields, valueOf })
  latest.current = { fields, valueOf }

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, thinking, typed?.words])

  // Ответ печатается по словам; карточка изменений встаёт, когда текст допечатан.
  useEffect(() => {
    if (!typed) return
    const message = messages.find((m) => m.id === typed.id)
    const total = message ? message.text.split(' ').length : 0
    if (typed.words >= total) {
      setTyped(null)
      return
    }
    const timer = window.setTimeout(() => setTyped({ id: typed.id, words: typed.words + 1 }), 26)
    return () => window.clearTimeout(timer)
  }, [typed, messages])

  const patch = (id: number, next: Partial<Message>) =>
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...next } : m)))

  const send = (raw: string) => {
    const ask = raw.trim()
    if (!ask || thinking) return
    setText('')
    setMessages((all) => [...all, { id: ++seq, from: 'me', text: ask }])
    setThinking(true)
    window.setTimeout(() => {
      const { fields: now, valueOf: read } = latest.current
      const recipes = match(ask)
      const { changes } = propose(recipes, now, read)
      const titles = recipes.map((r) => `«${r.title}»`).join(' и ')
      const reply: Message = !recipes.length
        ? { id: ++seq, from: 'bot', text: 'Не узнал ситуацию. Скажите проще: что мешает или что важнее всего сегодня. Например:', examples: true }
        : !changes.length
          ? { id: ++seq, from: 'bot', text: `Подход ${titles}: всё уже стоит так, менять нечего.` }
          : {
              id: ++seq,
              from: 'bot',
              text: `Подход ${titles}. ${recipes.map((r) => r.why).join(' ')}`,
              changes,
              state: readOnly ? undefined : 'offered',
            }
      setThinking(false)
      setMessages((all) => [...all, reply])
      setTyped({ id: reply.id, words: 0 })
    }, ANSWER_AT)
  }

  const apply = (message: Message, back = false) => {
    const changes = message.changes ?? []
    if (!changes.length) return
    onApply(changes.map((c) => ({ field: c.field, value: back ? c.from : c.to })), changes[0].field)
    patch(message.id, { state: back ? 'undone' : 'applied' })
  }

  return (
    <aside className="b-help" aria-label="BeeGPT: помощник настроек">
      <header className="b-help-top">
        <BeeMark size={28} idle className="b-help-mark" />
        <div className="b-help-name">
          <b>BeeGPT</b>
        </div>
        {onClose ? (
          <Button view="flat" size="m" onClick={onClose} className="b-help-close" title="Закрыть BeeGPT">
            <IconClose />
          </Button>
        ) : null}
      </header>

      <div className="b-help-list b-scroll" ref={list} role="log" aria-live="polite">
        {messages.map((m) => {
          const words = typed?.id === m.id ? typed.words : Infinity
          const text = Number.isFinite(words) ? m.text.split(' ').slice(0, words).join(' ') : m.text
          const done = !Number.isFinite(words)
          return m.from === 'me' ? (
            <p key={m.id} className="b-help-me">
              {m.text}
            </p>
          ) : (
            <div key={m.id} className="b-help-bot">
              <p>{text}</p>
              {done && m.examples ? (
                <div className="b-help-ex">
                  {EXAMPLES.map((ex) => (
                    <button key={ex} type="button" onClick={() => send(ex)} disabled={thinking}>
                      {ex}
                    </button>
                  ))}
                </div>
              ) : null}
              {done && m.changes?.length ? (
                <div className={`b-help-card${m.state === 'applied' ? ' on' : ''}`}>
                  <small>
                    {m.state === 'applied' ? 'Поставлено в форму' : `Поменяю: ${m.changes.length}`}
                  </small>
                  <ul>
                    {m.changes.map((c) => (
                      <li key={c.field.path}>
                        <span>{c.field.label}</span>
                        <em>
                          <s>{show(c.field, c.from)}</s> → <b>{show(c.field, c.to)}</b>
                        </em>
                      </li>
                    ))}
                  </ul>
                  {m.state === 'offered' || m.state === 'undone' ? (
                    <div className="b-help-acts">
                      <Button view="action" size="m" onClick={() => apply(m)}>
                        Применить
                      </Button>
                      {m.state === 'offered' ? (
                        <Button view="flat" size="m" onClick={() => patch(m.id, { state: 'declined' })}>
                          Не надо
                        </Button>
                      ) : null}
                    </div>
                  ) : m.state === 'applied' ? (
                    <div className="b-help-acts">
                      <span>Сохраните внизу — план пересчитается</span>
                      <Button view="flat" size="s" onClick={() => apply(m, true)}>
                        Вернуть
                      </Button>
                    </div>
                  ) : m.state === 'declined' ? (
                    <div className="b-help-acts">
                      <span>Оставил как есть</span>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )
        })}
        {thinking ? (
          <div className="b-help-bot thinking" role="status">
            <BeeMark busy size={26} className="b-help-mark" />
            <span>Подбираю подход…</span>
          </div>
        ) : null}
      </div>

      <form
        className="b-help-in"
        onSubmit={(event) => {
          event.preventDefault()
          send(text)
        }}
      >
        <TextInput size="l" value={text} onUpdate={setText} placeholder="Опишите свой день" disabled={thinking} />
        <Button type="submit" view="action" size="l" disabled={thinking || !text.trim()} title="Отправить">
          <IconArrowRight />
        </Button>
      </form>
    </aside>
  )
}
