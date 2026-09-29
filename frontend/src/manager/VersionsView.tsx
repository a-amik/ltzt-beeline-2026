/**
 * Версии дня: каждый план региона с событием, которое его породило,
 * от утреннего до действующего. Версии переживают перезапуск сервиса
 * (состояние дня пишется на диск при каждой версии). «Вернуть» делает
 * версию действующим планом — его увидят и бригады.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { num } from '../lib/ui'
import type { Plan } from '../types'
import { managerApi } from './managerApi'
import './manager.css'

export default function VersionsView({ region, onRestore, onClose }: {
  region: string
  onRestore: (plan: Plan) => void
  onClose: () => void
}) {
  const client = useQueryClient()
  const versions = useQuery({ queryKey: ['versions', region], queryFn: () => managerApi.versions(region), refetchInterval: 5000 })
  const restore = useMutation({
    mutationFn: (id: string) => managerApi.restore<Plan>(id),
    onSuccess: (plan) => {
      onRestore(plan)
      void client.invalidateQueries({ queryKey: ['versions', region] })
    },
  })
  const rows = [...(versions.data ?? [])].reverse()
  return (
    <div className="b-ver-scrim" onClick={onClose}>
      <aside className="b-ver" role="dialog" aria-label="Версии дня" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Версии дня</h2>
          <span>{rows.length}</span>
          <button type="button" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </header>
        <p>Состояние дня хранится на диске и переживает перезапуск сервиса. Бледные версии — варианты, которые не приняли.</p>
        <ol>
          {rows.map((v) => (
            <li key={v.id} className={`${v.current ? 'current' : ''}${v.on_line ? '' : ' off'}`}>
              <b>
                {v.id} · {v.what}
                {v.time ? `, ${v.time}` : ''}
              </b>
              <span>
                вовремя {v.on_time ?? '—'} · бригад {v.crews ?? '—'} · итог {v.net_rub != null ? `${num(v.net_rub)} ₽` : '—'} · не назначено{' '}
                {v.unassigned}
                {v.parent_id ? ` · из ${v.parent_id}` : ''}
              </span>
              <span className="act">
                {v.current ? (
                  'действует'
                ) : (
                  <Button view="outlined" size="s" loading={restore.isPending && restore.variables === v.id} onClick={() => restore.mutate(v.id)}>
                    Вернуть
                  </Button>
                )}
              </span>
            </li>
          ))}
          {!rows.length ? <li>Версий пока нет</li> : null}
        </ol>
      </aside>
    </div>
  )
}
