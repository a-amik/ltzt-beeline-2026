/**
 * Переписка с бригадой со стороны диспетчера: то, что бригада написала
 * в приложении, «проблема на заявке», SOS и отметки звонков клиентам.
 * Открытие окна помечает сообщения бригады прочитанными.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, TextInput } from '@gravity-ui/uikit'
import { IconClose } from '../lib/icons'
import { crewApi } from './crewApi'
import './crew.css'

export function useInbox(region: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['crew-inbox', region],
    queryFn: () => crewApi.inbox(region!),
    enabled: Boolean(region) && enabled,
    refetchInterval: 5000,
    retry: false,
  })
}

export default function DispatcherChat({ region, engineerId, name, onClose }: {
  region: string
  engineerId: string
  name: string
  onClose: () => void
}) {
  const client = useQueryClient()
  const [text, setText] = useState('')
  const messages = useQuery({
    queryKey: ['crew-chat', region, engineerId],
    queryFn: () => crewApi.messages(region, engineerId),
    refetchInterval: 4000,
  })
  const list = messages.data ?? []
  useEffect(() => {
    if ((messages.data ?? []).some((m) => m.author === 'crew' && !m.read)) {
      crewApi.read(region, engineerId, 'dispatcher').then(() => client.invalidateQueries({ queryKey: ['crew-inbox', region] }))
    }
  }, [messages.data, region, engineerId, client])
  const say = useMutation({
    mutationFn: () => crewApi.say(region, engineerId, { text: text.trim(), author: 'dispatcher' }),
    onSuccess: () => {
      setText('')
      void client.invalidateQueries({ queryKey: ['crew-chat', region, engineerId] })
    },
  })
  return (
    <section className="b-dchat" role="dialog" aria-label={`Переписка с бригадой ${name}`}>
      <header>
        <b>{name}</b>
        <span>переписка из приложения бригады</span>
        <button type="button" onClick={onClose} aria-label="Закрыть">
          <IconClose />
        </button>
      </header>
      <ol>
        {list.map((m) => (
          <li key={m.id} className={`${m.author} ${m.kind}`}>
            <span>
              {m.kind === 'sos' ? 'SOS · ' : m.kind === 'problem' ? 'Проблема · ' : ''}
              {m.text}
            </span>
            <time>
              {m.time}
              {m.request_id ? ` · заявка ${m.request_id}` : ''}
            </time>
          </li>
        ))}
        {!list.length ? <li className="empty">Бригада ещё не писала</li> : null}
      </ol>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim()) say.mutate()
        }}
      >
        <TextInput size="m" value={text} onUpdate={setText} placeholder="Ответ бригаде" />
        <Button type="submit" view="action" size="m" disabled={!text.trim() || say.isPending}>
          Ответить
        </Button>
      </form>
    </section>
  )
}
